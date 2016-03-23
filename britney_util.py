# -*- coding: utf-8 -*-

# Refactored parts from britney.py, which is/was:
# Copyright (C) 2001-2008 Anthony Towns <ajt@debian.org>
#                         Andreas Barth <aba@debian.org>
#                         Fabio Tranchitella <kobold@debian.org>
# Copyright (C) 2010-2012 Adam D. Barratt <adsb@debian.org>
# Copyright (C) 2012 Niels Thykier <niels@thykier.net>
#
# New portions
# Copyright (C) 2013 Adam D. Barratt <adsb@debian.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.


import apt_pkg
from functools import partial
from datetime import datetime
from itertools import chain, repeat, filterfalse
import os
import time
import yaml

from migrationitem import MigrationItem, UnversionnedMigrationItem

from consts import (VERSION, BINARIES, PROVIDES, DEPENDS, CONFLICTS,
                    ARCHITECTURE, SECTION,
                    SOURCE, SOURCEVER, MAINTAINER, MULTIARCH,
                    ESSENTIAL)

def ifilter_except(container, iterable=None):
    """Filter out elements in container

    If given an iterable it returns a filtered iterator, otherwise it
    returns a function to generate filtered iterators.  The latter is
    useful if the same filter has to be (re-)used on multiple
    iterators that are not known on beforehand.
    """
    if iterable is not None:
        return filterfalse(container.__contains__, iterable)
    return partial(filterfalse, container.__contains__)


def ifilter_only(container, iterable=None):
    """Filter out elements in which are not in container

    If given an iterable it returns a filtered iterator, otherwise it
    returns a function to generate filtered iterators.  The latter is
    useful if the same filter has to be (re-)used on multiple
    iterators that are not known on beforehand.
    """
    if iterable is not None:
        return filter(container.__contains__, iterable)
    return partial(filter, container.__contains__)


# iter_except is from the "itertools" recipe
def iter_except(func, exception, first=None):
    """ Call a function repeatedly until an exception is raised.

    Converts a call-until-exception interface to an iterator interface.
    Like __builtin__.iter(func, sentinel) but uses an exception instead
    of a sentinel to end the loop.

    Examples:
        bsddbiter = iter_except(db.next, bsddb.error, db.first)
        heapiter = iter_except(functools.partial(heappop, h), IndexError)
        dictiter = iter_except(d.popitem, KeyError)
        dequeiter = iter_except(d.popleft, IndexError)
        queueiter = iter_except(q.get_nowait, Queue.Empty)
        setiter = iter_except(s.pop, KeyError)

    """
    try:
        if first is not None:
            yield first()
        while 1:
            yield func()
    except exception:
        pass


def undo_changes(lundo, inst_tester, sources, binaries, all_binary_packages,
                 BINARIES=BINARIES):
    """Undoes one or more changes to testing

    * lundo is a list of (undo, item)-tuples
    * inst_tester is an InstallabilityTester
    * sources is the table of all source packages for all suites
    * binaries is the table of all binary packages for all suites
      and architectures

    The "X=X" parameters are optimizations to avoid "load global"
    in loops.
    """

    # We do the undo process in "4 steps" and each step must be
    # fully completed for each undo-item before starting on the
    # next.
    #
    # see commit:ef71f0e33a7c3d8ef223ec9ad5e9843777e68133 and
    # #624716 for the issues we had when we did not do this.


    # STEP 1
    # undo all the changes for sources
    for (undo, item) in lundo:
        for k in undo['sources']:
            if k[0] == '-':
                del sources["testing"][k[1:]]
            else:
                sources["testing"][k] = undo['sources'][k]

    # STEP 2
    # undo all new binaries (consequence of the above)
    for (undo, item) in lundo:
        if not item.is_removal and item.package in sources[item.suite]:
            for p in sources[item.suite][item.package][BINARIES]:
                binary, arch = p.split("/")
                if item.architecture in ['source', arch]:
                    version = binaries["testing"][arch][0][binary][VERSION]
                    del binaries["testing"][arch][0][binary]
                    inst_tester.remove_testing_binary((binary, version, arch))


    # STEP 3
    # undo all other binary package changes (except virtual packages)
    for (undo, item) in lundo:
        for p in undo['binaries']:
            binary, arch = p.split("/")
            if binary[0] == "-":
                version = binaries["testing"][arch][0][binary][VERSION]
                del binaries['testing'][arch][0][binary[1:]]
                inst_tester.remove_testing_binary(binary, version, arch)
            else:
                binaries_t_a = binaries['testing'][arch][0]
                if p in binaries_t_a:
                    rmpkgdata = binaries_t_a[p]
                    inst_tester.remove_testing_binary((binary, rmpkgdata[VERSION], arch))
                pkgdata = all_binary_packages[undo['binaries'][p]]
                binaries_t_a[binary] = pkgdata
                inst_tester.add_testing_binary((binary, pkgdata[VERSION], arch))

    # STEP 4
    # undo all changes to virtual packages
    for (undo, item) in lundo:
        for p in undo['nvirtual']:
            j, arch = p.split("/")
            del binaries['testing'][arch][1][j]
        for p in undo['virtual']:
            j, arch = p.split("/")
            if j[0] == '-':
                del binaries['testing'][arch][1][j[1:]]
            else:
                binaries['testing'][arch][1][j] = undo['virtual'][p]


def old_libraries_format(libs):
    """Format old libraries in a smart table"""
    libraries = {}
    for i in libs:
        pkg = i.package
        if pkg in libraries:
            libraries[pkg].append(i.architecture)
        else:
            libraries[pkg] = [i.architecture]
    return "\n".join("  " + k + ": " + " ".join(libraries[k]) for k in libraries) + "\n"


def compute_reverse_tree(inst_tester, affected):
    """Calculate the full dependency tree for a set of packages

    This method returns the full dependency tree for a given set of
    packages.  The first argument is an instance of the InstallabilityTester
    and the second argument are a set of packages ids (as defined in
    the constructor of the InstallabilityTester).

    The set of affected packages will be updated in place and must
    therefore be mutable.
    """
    remain = list(affected)
    while remain:
        pkg_id = remain.pop()
        new_pkg_ids = inst_tester.reverse_dependencies_of(pkg_id) - affected
        affected.update(new_pkg_ids)
        remain.extend(new_pkg_ids)
    return None


def write_nuninst(filename, nuninst):
    """Write the non-installable report

    Write the non-installable report derived from "nuninst" to the
    file denoted by "filename".
    """
    with open(filename, 'w', encoding='utf-8') as f:
        # Having two fields with (almost) identical dates seems a bit
        # redundant.
        f.write("Built on: " + time.strftime("%Y.%m.%d %H:%M:%S %z", time.gmtime(time.time())) + "\n")
        f.write("Last update: " + time.strftime("%Y.%m.%d %H:%M:%S %z", time.gmtime(time.time())) + "\n\n")
        for k in nuninst:
            f.write("%s: %s\n" % (k, " ".join(nuninst[k])))


def read_nuninst(filename, architectures):
    """Read the non-installable report

    Read the non-installable report from the file denoted by
    "filename" and return it.  Only architectures in "architectures"
    will be included in the report.
    """
    nuninst = {}
    with open(filename, encoding='ascii') as f:
        for r in f:
            if ":" not in r: continue
            arch, packages = r.strip().split(":", 1)
            if arch.split("+", 1)[0] in architectures:
                nuninst[arch] = set(packages.split())
    return nuninst


def newly_uninst(nuold, nunew):
    """Return a nuninst statstic with only new uninstallable packages

    This method subtracts the uninstallable packages of the statistic
    "nunew" from the statistic "nuold".

    It returns a dictionary with the architectures as keys and the list
    of uninstallable packages as values.
    """
    res = {}
    for arch in ifilter_only(nunew, nuold):
        res[arch] = [x for x in nunew[arch] if x not in nuold[arch]]
    return res


def eval_uninst(architectures, nuninst):
    """Return a string which represents the uninstallable packages

    This method returns a string which represents the uninstallable
    packages reading the uninstallability statistics "nuninst".

    An example of the output string is:
      * i386: broken-pkg1, broken-pkg2
    """
    parts = []
    for arch in architectures:
        if arch in nuninst and nuninst[arch]:
            parts.append("    * %s: %s\n" % (arch,", ".join(sorted(nuninst[arch]))))
    return "".join(parts)


def write_heidi(filename, sources_t, packages_t,
                VERSION=VERSION, SECTION=SECTION,
                ARCHITECTURE=ARCHITECTURE, sorted=sorted):
    """Write the output HeidiResult

    This method write the output for Heidi, which contains all the
    binary packages and the source packages in the form:

    <pkg-name> <pkg-version> <pkg-architecture> <pkg-section>
    <src-name> <src-version> source <src-section>

    The file is written as "filename", it assumes all sources and
    packages in "sources_t" and "packages_t" to be the packages in
    "testing".

    The "X=X" parameters are optimizations to avoid "load global" in
    the loops.
    """
    with open(filename, 'w', encoding='ascii') as f:

        # write binary packages
        for arch in sorted(packages_t):
            binaries = packages_t[arch][0]
            for pkg_name in sorted(binaries):
                pkg = binaries[pkg_name]
                pkgv = pkg[VERSION]
                pkgarch = pkg[ARCHITECTURE] or 'all'
                pkgsec = pkg[SECTION] or 'faux'
                if pkg[SOURCEVER] and pkgarch == 'all' and \
                    pkg[SOURCEVER] != sources_t[pkg[SOURCE]][VERSION]:
                    # when architectures are marked as "fucked", their binary
                    # versions may be lower than those of the associated
                    # source package in testing. the binary package list for
                    # such architectures will include arch:all packages
                    # matching those older versions, but we only want the
                    # newer arch:all in testing
                    continue
                f.write('%s %s %s %s\n' % (pkg_name, pkgv, pkgarch, pkgsec))

        # write sources
        for src_name in sorted(sources_t):
            src = sources_t[src_name]
            srcv = src[VERSION]
            srcsec = src[SECTION] or 'unknown'
            f.write('%s %s source %s\n' % (src_name, srcv, srcsec))


def write_heidi_delta(filename, all_selected):
    """Write the output delta

    This method writes the packages to be upgraded, in the form:
    <src-name> <src-version>
    or (if the source is to be removed):
    -<src-name> <src-version>

    The order corresponds to that shown in update_output.
    """
    with open(filename, "w", encoding='ascii') as fd:

        fd.write("#HeidiDelta\n")

        for item in all_selected:
            prefix = ""

            if item.is_removal:
                prefix = "-"

            if item.architecture == 'source':
                fd.write('%s%s %s\n' % (prefix, item.package, item.version))
            else:
                fd.write('%s%s %s %s\n' % (prefix, item.package,
                                           item.version, item.architecture))


def make_migrationitem(package, sources, VERSION=VERSION):
    """Convert a textual package specification to a MigrationItem
    
    sources is a list of source packages in each suite, used to determine
    the version which should be used for the MigrationItem.
    """
    
    item = UnversionnedMigrationItem(package)
    return MigrationItem("%s/%s" % (item.uvname, sources[item.suite][item.package][VERSION]))


def write_excuses(excuses, dest_file, output_format="yaml"):
    """Write the excuses to dest_file

    Writes a list of excuses in a specified output_format to the
    path denoted by dest_file.  The output_format can either be "yaml"
    or "legacy-html".
    """
    if output_format == "yaml":
        with open(dest_file, 'w', encoding='utf-8') as f:
            excuselist = []
            for e in excuses:
                excuselist.append(e.excusedata())
            excusesdata = {}
            excusesdata["sources"] = excuselist
            excusesdata["generated-date"] = datetime.utcnow()
            f.write(yaml.dump(excusesdata, default_flow_style=False, allow_unicode=True))
    elif output_format == "legacy-html":
        with open(dest_file, 'w', encoding='utf-8') as f:
            f.write("<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.01//EN\" \"http://www.w3.org/TR/REC-html40/strict.dtd\">\n")
            f.write("<html><head><title>excuses...</title>")
            f.write("<meta http-equiv=\"Content-Type\" content=\"text/html;charset=utf-8\"></head><body>\n")
            f.write("<p>Generated: " + time.strftime("%Y.%m.%d %H:%M:%S %z", time.gmtime(time.time())) + "</p>\n")
            f.write("<ul>\n")
            for e in excuses:
                f.write("<li>%s" % e.html())
            f.write("</ul></body></html>\n")
    else:
        raise ValueError('Output format must be either "yaml or "legacy-html"')


def write_sources(sources_s, filename):
    """Write a sources file from Britney's state for a given suite

    Britney discards fields she does not care about, so the resulting
    file omits a lot of regular fields.
    """

    key_pairs = ((VERSION, 'Version'), (SECTION, 'Section'),
                 (MAINTAINER, 'Maintainer'))

    with open(filename, 'w', encoding='utf-8') as f:
        for src in sources_s:
           src_data = sources_s[src]
           output = "Package: %s\n" % src
           output += "\n".join(k + ": "+ src_data[key]
                               for key, k in key_pairs if src_data[key])
           f.write(output + "\n\n")


def relation_atom_to_string(atom):
    """Take a parsed dependency and turn it into a string
    """
    pkg, version, rel_op = atom
    if rel_op != '':
        if rel_op in ('<', '>'):
            # APT translate "<<" and ">>" into "<" and ">".  We have
            # deparse those into the original form.
            rel_op += rel_op
        return "%s (%s %s)" % (pkg, rel_op, version)
    return pkg


def write_controlfiles(sources, packages, suite, basedir):
    """Write the control files

    This method writes the control files for the binary packages of all
    the architectures and for the source packages.  Note that Britney
    discards a lot of fields that she does not care about.  Therefore,
    these files may omit a lot of regular fields.
    """

    sources_s = sources[suite]
    packages_s = packages[suite]

    key_pairs = ((SECTION, 'Section'), (ARCHITECTURE, 'Architecture'),
                 (MULTIARCH, 'Multi-Arch'), (SOURCE, 'Source'),
                 (VERSION, 'Version'), (DEPENDS, 'Depends'),
                 (PROVIDES, 'Provides'), (CONFLICTS, 'Conflicts'),
                 (ESSENTIAL, 'Essential'))

    for arch in packages_s:
        filename = os.path.join(basedir, 'Packages_%s' % arch)
        binaries = packages_s[arch][0]
        with open(filename, 'w', encoding='utf-8') as f:
            for pkg in binaries:
                output = "Package: %s\n" % pkg
                bin_data = binaries[pkg]
                for key, k in key_pairs:
                    if not bin_data[key]: continue
                    if key == SOURCE:
                        src = bin_data[SOURCE]
                        if sources_s[src][MAINTAINER]:
                            output += ("Maintainer: " + sources_s[src][MAINTAINER] + "\n")

                        if bin_data[SOURCE] == pkg:
                            if bin_data[SOURCEVER] != bin_data[VERSION]:
                                source = src + " (" + bin_data[SOURCEVER] + ")"
                            else: continue
                        else:
                            if bin_data[SOURCEVER] != bin_data[VERSION]:
                                source = src + " (" + bin_data[SOURCEVER] + ")"
                            else:
                                source = src
                        output += (k + ": " + source + "\n")
                    elif key == PROVIDES:
                        if bin_data[key]:
                            output += (k + ": " + ", ".join(relation_atom_to_string(p) for p in bin_data[key]) + "\n")
                    elif key == ESSENTIAL:
                        if bin_data[key]:
                            output += (k + ": " + " yes\n")
                    else:
                        output += (k + ": " + bin_data[key] + "\n")
                f.write(output + "\n")

    write_sources(sources_s, os.path.join(basedir, 'Sources'))


def old_libraries(sources, packages, fucked_arches=frozenset()):
    """Detect old libraries left in testing for smooth transitions

    This method detects old libraries which are in testing but no
    longer built from the source package: they are still there because
    other packages still depend on them, but they should be removed as
    soon as possible.

    For "fucked" architectures, outdated binaries are allowed to be in
    testing, so they are only added to the removal list if they are no longer
    in unstable.
    """
    sources_t = sources['testing']
    testing = packages['testing']
    unstable = packages['unstable']
    removals = []
    for arch in testing:
        for pkg_name in testing[arch][0]:
            pkg = testing[arch][0][pkg_name]
            if sources_t[pkg[SOURCE]][VERSION] != pkg[SOURCEVER] and \
                (arch not in fucked_arches or pkg_name not in unstable[arch][0]):
                migration = "-" + "/".join((pkg_name, arch, pkg[SOURCEVER]))
                removals.append(MigrationItem(migration))
    return removals


def is_nuninst_asgood_generous(architectures, old, new, break_arches=frozenset()):
    """Compares the nuninst counters to see if they improved

    Given a list of architecters, the previous and the current nuninst
    counters, this function determines if the current nuninst counter
    is better than the previous one.  Optionally it also accepts a set
    of "break_arches", the nuninst counter for any architecture listed
    in this set are completely ignored.

    Returns True if the new nuninst counter is better than the
    previous.  Returns False otherwise.

    """
    diff = 0
    for arch in architectures:
        if arch in break_arches:
            continue
        diff = diff + (len(new[arch]) - len(old[arch]))
    return diff <= 0


def clone_nuninst(nuninst, packages_s, architectures):
    """Selectively deep clone nuninst

    Given nuninst table, the package table for a given suite and
    a list of architectures, this function will clone the nuninst
    table.  Only the listed architectures will be deep cloned -
    the rest will only be shallow cloned.
    """
    clone = nuninst.copy()
    for arch in architectures:
        clone[arch] = set(x for x in nuninst[arch] if x in packages_s[arch][0])
        clone[arch + "+all"] = set(x for x in nuninst[arch + "+all"] if x in packages_s[arch][0])
    return clone
