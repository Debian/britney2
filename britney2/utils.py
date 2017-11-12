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
import errno
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from functools import partial
from itertools import filterfalse

import yaml

from britney2 import SourcePackage
from britney2.consts import (VERSION, PROVIDES, DEPENDS, CONFLICTS,
                             ARCHITECTURE, SECTION,
                             SOURCE, MAINTAINER, MULTIARCH,
                             ESSENTIAL)
from britney2.migrationitem import MigrationItem, UnversionnedMigrationItem
from britney2.policies import PolicyVerdict


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


def undo_changes(lundo, inst_tester, sources, binaries, all_binary_packages):
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
            source_data = sources[item.suite][item.package]
            for pkg_id in source_data.binaries:
                binary, _, arch = pkg_id
                if item.architecture in ['source', arch]:
                    try:
                        del binaries["testing"][arch][0][binary]
                    except KeyError:
                        # If this happens, pkg_id must be a cruft item that
                        # was *not* migrated.
                        assert source_data.version != all_binary_packages[pkg_id].version
                        assert not inst_tester.any_of_these_are_in_testing((pkg_id,))
                    inst_tester.remove_testing_binary(pkg_id)


    # STEP 3
    # undo all other binary package changes (except virtual packages)
    for (undo, item) in lundo:
        for p in undo['binaries']:
            binary, arch = p
            binaries_t_a = binaries['testing'][arch][0]
            assert binary not in binaries_t_a
            pkgdata = all_binary_packages[undo['binaries'][p]]
            binaries_t_a[binary] = pkgdata
            inst_tester.add_testing_binary(pkgdata.pkg_id)

    # STEP 4
    # undo all changes to virtual packages
    for (undo, item) in lundo:
        for provided_pkg, arch in undo['nvirtual']:
            del binaries['testing'][arch][1][provided_pkg]
        for p in undo['virtual']:
            provided_pkg, arch = p
            binaries['testing'][arch][1][provided_pkg] = undo['virtual'][p]


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


def write_heidi(filename, sources_t, packages_t, sorted=sorted):
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
                pkgv = pkg.version
                pkgarch = pkg.architecture or 'all'
                pkgsec = pkg.section or 'faux'
                if pkgsec == 'faux' or pkgsec.endswith('/faux'):
                    # Faux package; not really a part of testing
                    continue
                if pkg.source_version and pkgarch == 'all' and \
                    pkg.source_version != sources_t[pkg.source].version:
                    # when architectures are marked as "outofsync", their binary
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
            srcv = src.version
            srcsec = src.section or 'unknown'
            if srcsec == 'faux' or srcsec.endswith('/faux'):
                # Faux package; not really a part of testing
                continue
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


def make_migrationitem(package, sources):
    """Convert a textual package specification to a MigrationItem
    
    sources is a list of source packages in each suite, used to determine
    the version which should be used for the MigrationItem.
    """
    
    item = UnversionnedMigrationItem(package)
    return MigrationItem("%s/%s" % (item.uvname, sources[item.suite][item.package].version))


def write_excuses(excuselist, dest_file, output_format="yaml"):
    """Write the excuses to dest_file

    Writes a list of excuses in a specified output_format to the
    path denoted by dest_file.  The output_format can either be "yaml"
    or "legacy-html".
    """
    if output_format == "yaml":
        with open(dest_file, 'w', encoding='utf-8') as f:
            edatalist = [e.excusedata() for e in excuselist]
            excusesdata = {
                'sources': edatalist,
                'generated-date': datetime.utcnow(),
            }
            f.write(yaml.dump(excusesdata, default_flow_style=False, allow_unicode=True))
    elif output_format == "legacy-html":
        with open(dest_file, 'w', encoding='utf-8') as f:
            f.write("<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.01//EN\" \"http://www.w3.org/TR/REC-html40/strict.dtd\">\n")
            f.write("<html><head><title>excuses...</title>")
            f.write("<meta http-equiv=\"Content-Type\" content=\"text/html;charset=utf-8\"></head><body>\n")
            f.write("<p>Generated: " + time.strftime("%Y.%m.%d %H:%M:%S %z", time.gmtime(time.time())) + "</p>\n")
            f.write("<ul>\n")
            for e in excuselist:
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
                    if not bin_data[key]:
                        continue
                    if key == SOURCE:
                        src = bin_data.source
                        if sources_s[src].maintainer:
                            output += ("Maintainer: " + sources_s[src].maintainer + "\n")

                        if src == pkg:
                            if bin_data.source_version != bin_data.version:
                                source = src + " (" + bin_data.source_version + ")"
                            else: continue
                        else:
                            if bin_data.source_version != bin_data.version:
                                source = src + " (" + bin_data.source_version + ")"
                            else:
                                source = src
                        output += (k + ": " + source + "\n")
                    elif key == PROVIDES:
                        output += (k + ": " + ", ".join(relation_atom_to_string(p) for p in bin_data[key]) + "\n")
                    elif key == ESSENTIAL:
                        output += (k + ": " + " yes\n")
                    else:
                        output += (k + ": " + bin_data[key] + "\n")
                f.write(output + "\n")

    write_sources(sources_s, os.path.join(basedir, 'Sources'))


def old_libraries(sources, packages, outofsync_arches=frozenset()):
    """Detect old libraries left in testing for smooth transitions

    This method detects old libraries which are in testing but no
    longer built from the source package: they are still there because
    other packages still depend on them, but they should be removed as
    soon as possible.

    For "outofsync" architectures, outdated binaries are allowed to be in
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
            if sources_t[pkg.source].version != pkg.source_version and \
                (arch not in outofsync_arches or pkg_name not in unstable[arch][0]):
                migration = "-" + "/".join((pkg_name, arch, pkg.source_version))
                removals.append(MigrationItem(migration))
    return removals


def is_nuninst_asgood_generous(constraints, architectures, old, new, break_arches=frozenset()):
    """Compares the nuninst counters and constraints to see if they improved

    Given a list of architectures, the previous and the current nuninst
    counters, this function determines if the current nuninst counter
    is better than the previous one.  Optionally it also accepts a set
    of "break_arches", the nuninst counter for any architecture listed
    in this set are completely ignored.

    If the nuninst counters are equal or better, then the constraints
    are checked for regressions (ignoring break_arches).

    Returns True if the new nuninst counter is better than the
    previous and there are no constraint regressions (ignoring Break-archs).
    Returns False otherwise.

    """
    diff = 0
    for arch in architectures:
        if arch in break_arches:
            continue
        diff = diff + (len(new[arch]) - len(old[arch]))
    if diff > 0:
        return False
    must_be_installable = constraints['keep-installable']
    for arch in architectures:
        if arch in break_arches:
            continue
        regression = new[arch] - old[arch]
        if not regression.isdisjoint(must_be_installable):
            return False
    return True


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


def test_installability(inst_tester, pkg_name, pkg_id, broken, nuninst_arch):
    """Test for installability of a package on an architecture

    (pkg_name, pkg_version, pkg_arch) is the package to check.

    broken is the set of broken packages.  If p changes
    installability (e.g. goes from uninstallable to installable),
    broken will be updated accordingly.

    If nuninst_arch is not None then it also updated in the same
    way as broken is.
    """
    c = 0
    r = inst_tester.is_installable(pkg_id)
    if not r:
        # not installable
        if pkg_name not in broken:
            # regression
            broken.add(pkg_name)
            c = -1
        if nuninst_arch is not None and pkg_name not in nuninst_arch:
            nuninst_arch.add(pkg_name)
    else:
        if pkg_name in broken:
            # Improvement
            broken.remove(pkg_name)
            c = 1
        if nuninst_arch is not None and pkg_name in nuninst_arch:
            nuninst_arch.remove(pkg_name)
    return c


def check_installability(inst_tester, binaries, arch, updates, affected, check_archall, nuninst):
    broken = nuninst[arch + "+all"]
    packages_t_a = binaries[arch][0]
    improvement = 0

    # broken packages (first round)
    for pkg_id in (x for x in updates if x.architecture == arch):
        name, version, parch = pkg_id
        if name not in packages_t_a:
            continue
        pkgdata = packages_t_a[name]
        if version != pkgdata.version:
            # Not the version in testing right now, ignore
            continue
        actual_arch = pkgdata.architecture
        nuninst_arch = None
        # only check arch:all packages if requested
        if check_archall or actual_arch != 'all':
            nuninst_arch = nuninst[parch]
        else:
            nuninst[parch].discard(name)
        result = test_installability(inst_tester, name, pkg_id, broken, nuninst_arch)
        if improvement > 0 or not result:
            # Any improvement could in theory fix all of its rdeps, so
            # stop updating "improvement" after that.
            continue
        if result > 0:
            # Any improvement (even in arch:all packages) could fix any
            # number of rdeps
            improvement = 1
            continue
        if check_archall or actual_arch != 'all':
            # We cannot count arch:all breakage (except on no-break-arch-all arches)
            # because the nuninst check do not consider them regressions.
            improvement += result

    if improvement < 0:
        # The early round is sufficient to disprove the situation
        return

    for pkg_id in (x for x in affected if x.architecture == arch):
        name, version, parch = pkg_id
        if name not in packages_t_a:
            continue
        pkgdata = packages_t_a[name]
        if version != pkgdata.version:
            # Not the version in testing right now, ignore
            continue
        actual_arch = pkgdata.architecture
        nuninst_arch = None
        # only check arch:all packages if requested
        if check_archall or actual_arch != 'all':
            nuninst_arch = nuninst[parch]
        elif actual_arch == 'all':
            nuninst[parch].discard(name)
        test_installability(inst_tester, name, pkg_id, broken, nuninst_arch)


def possibly_compressed(path, permitted_compressesion=None):
    """Find and select a (possibly compressed) variant of a path

    If the given path exists, it will be returned

    :param path The base path.
    :param permitted_compressesion An optional list of alternative extensions to look for.
      Defaults to "gz" and "xz".
    :returns The path given possibly with one of the permitted extensions.  Will raise a
     FileNotFoundError
    """
    if os.path.exists(path):
        return path
    if permitted_compressesion is None:
        permitted_compressesion = ['gz', 'xz']
    for ext in permitted_compressesion:
        cpath = "%s.%s" % (path, ext)
        if os.path.exists(cpath):
            return cpath
    raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)


def create_provides_map(packages):
    """Create a provides map from a map binary package names and thier BinaryPackage objects

    :param packages: A dict mapping binary package names to their BinaryPackage object
    :return: A provides map
    """
    # create provides
    provides = defaultdict(set)

    for pkg, dpkg in packages.items():
        # register virtual packages and real packages that provide
        # them
        for provided_pkg, provided_version, _ in dpkg.provides:
            provides[provided_pkg].add((pkg, provided_version))

    return provides


def read_release_file(suite_dir):
    """Parses a given "Release" file

    :param suite_dir: The directory to the suite
    :return: A dict of the first (and only) paragraph in an Release file
    """
    release_file = os.path.join(suite_dir, 'Release')
    with open(release_file) as fd:
        tag_file = iter(apt_pkg.TagFile(fd))
        result = next(tag_file)
        if next(tag_file, None) is not None:  # pragma: no cover
            raise TypeError("%s has more than one paragraph" % release_file)
    return result


def read_sources_file(filename, sources=None, intern=sys.intern):
    """Parse a single Sources file into a hash

    Parse a single Sources file into a dict mapping a source package
    name to a SourcePackage object.  If there are multiple source
    packages with the same version, then highest versioned source
    package (that is not marked as "Extra-Source-Only") is the
    version kept in the dict.

    :param filename: Path to the Sources file.  Can be compressed by any algorithm supported by apt_pkg.TagFile
    :param sources: Optional dict to add the packages to.  If given, this is also the value returned.
    :param intern: Internal optimisation / implementation detail to avoid python's "LOAD_GLOBAL" instruction in a loop
    :return a dict mapping a name to a source package
    """
    if sources is None:
        sources = {}

    tag_file = apt_pkg.TagFile(filename)
    get_field = tag_file.section.get
    step = tag_file.step

    while step():
        if get_field('Extra-Source-Only', 'no') == 'yes':
            # Ignore sources only referenced by Built-Using
            continue
        pkg = get_field('Package')
        ver = get_field('Version')
        # There may be multiple versions of the source package
        # (in unstable) if some architectures have out-of-date
        # binaries.  We only ever consider the source with the
        # largest version for migration.
        if pkg in sources and apt_pkg.version_compare(sources[pkg][0], ver) > 0:
            continue
        maint = get_field('Maintainer')
        if maint:
            maint = intern(maint.strip())
        section = get_field('Section')
        if section:
            section = intern(section.strip())
        build_deps_arch = ", ".join(x for x in (get_field('Build-Depends'), get_field('Build-Depends-Arch'))
                                    if x is not None)
        if build_deps_arch != '':
            build_deps_arch = sys.intern(build_deps_arch)
        else:
            build_deps_arch = None
        sources[intern(pkg)] = SourcePackage(intern(ver),
                                             section,
                                             [],
                                             maint,
                                             False,
                                             build_deps_arch,
                                             )
    return sources


def get_dependency_solvers(block, binaries_s_a, provides_s_a, *, build_depends=False, empty_set=frozenset()):
    """Find the packages which satisfy a dependency block

    This method returns the list of packages which satisfy a dependency
    block (as returned by apt_pkg.parse_depends) in a package table
    for a given suite and architecture (a la self.binaries[suite][arch])

    It can also handle build-dependency relations if the named parameter
    "build_depends" is set to True.  In this case, block should be based
    on the return value from apt_pkg.parse_src_depends.

    :param block: The dependency block as parsed by apt_pkg.parse_depends (or apt_pkg.parse_src_depends
      if the "build_depends" is True)
    :param binaries_s_a: A dict mapping package names to the relevant BinaryPackage
    :param provides_s_a: A dict mapping package names to their providers (as generated by parse_provides)
    :param build_depends: If True, treat the "block" parameter as a build-dependency relation rather than
      a regular dependency relation.
    :param empty_set: Internal implementation detail / optimisation
    :return a list of package names solving the relation
    """
    packages = []

    # for every package, version and operation in the block
    for name, version, op in block:
        if ":" in name:
            name, archqual = name.split(":", 1)
        else:
            archqual = None

        # look for the package in unstable
        if name in binaries_s_a:
            package = binaries_s_a[name]
            # check the versioned dependency and architecture qualifier
            # (if present)
            if (op == '' and version == '') or apt_pkg.check_dep(package.version, op, version):
                if archqual is None:
                    packages.append(name)
                elif build_depends:
                    # Multi-arch handling for build-dependencies
                    # - :native is ok iff the target is arch:any
                    if archqual == 'native' and package.architecture != 'all':
                        packages.append(name)
                else:
                    # Multi-arch handling for regular dependencies
                    # - :any is ok iff the target has "M-A: allowed"
                    if archqual == 'any' and package.multi_arch == 'allowed':
                        packages.append(name)

        # look for the package in the virtual packages list and loop on them
        for prov, prov_version in provides_s_a.get(name, empty_set):
            assert prov in binaries_s_a
            # A provides only satisfies:
            # - an unversioned dependency (per Policy Manual §7.5)
            # - a dependency without an architecture qualifier
            #   (per analysis of apt code)
            if archqual is not None:
                # Punt on this case - these days, APT and dpkg might actually agree on
                # this.
                continue
            if (op == '' and version == '') or \
                    (prov_version != '' and apt_pkg.check_dep(prov_version, op, version)):
                packages.append(prov)

    return packages


def invalidate_excuses(excuses, valid, invalid):
    """Invalidate impossible excuses

    This method invalidates the impossible excuses, which depend
    on invalid excuses. The two parameters contains the sets of
    `valid' and `invalid' excuses.
    """

    # build the reverse dependencies
    revdeps = defaultdict(list)
    revbuilddeps = defaultdict(list)
    for exc in excuses.values():
        for d in exc.deps:
            revdeps[d].append(exc.name)
        for d in exc.arch_build_deps:
            revbuilddeps[d].append(exc.name)

    # loop on the invalid excuses
    for ename in iter_except(invalid.pop, KeyError):
        # if there is no reverse dependency, skip the item
        if ename not in revdeps and ename not in revbuilddeps:
            continue
        # if the dependency can be satisfied by a testing-proposed-updates excuse, skip the item
        if (ename + "_tpu") in valid:
            continue

        rdep_verdict = PolicyVerdict.REJECTED_WAITING_FOR_ANOTHER_ITEM
        if excuses[ename].policy_verdict.is_blocked:
            rdep_verdict = PolicyVerdict.REJECTED_BLOCKED_BY_ANOTHER_ITEM

        # loop on the reverse dependencies
        if ename in revdeps:
            for x in revdeps[ename]:
                # if the item is valid and it is not marked as `forced', then we invalidate it
                if x in valid and not excuses[x].forced:

                    # otherwise, invalidate the dependency and mark as invalidated and
                    # remove the depending excuses
                    excuses[x].invalidate_dep(ename)
                    valid.discard(x)
                    invalid.add(x)
                    excuses[x].addhtml("Invalidated by dependency")
                    excuses[x].addreason("depends")
                    if excuses[x].policy_verdict.value < rdep_verdict.value:
                        excuses[x].policy_verdict = rdep_verdict

        if ename in revbuilddeps:
            for x in revbuilddeps[ename]:
                # if the item is valid and it is not marked as `forced', then we invalidate it
                if x in valid and not excuses[x].forced:

                    # otherwise, invalidate the dependency and mark as invalidated and
                    # remove the depending excuses
                    excuses[x].invalidate_build_dep(ename)
                    valid.discard(x)
                    invalid.add(x)
                    excuses[x].addhtml("Invalidated by build-dependency")
                    if excuses[x].policy_verdict.value < rdep_verdict.value:
                        excuses[x].policy_verdict = rdep_verdict


def compile_nuninst(binaries_t, inst_tester, architectures, nobreakall_arches):
    """Compile a nuninst dict from the current testing

    :param binaries_t: Britney's binaries data structure for testing
    :param inst_tester: Britney's installability tester
    :param architectures: List of architectures
    :param nobreakall_arches: List of architectures where arch:all packages must be installable
    """
    nuninst = {}

    # for all the architectures
    for arch in architectures:
        # if it is in the nobreakall ones, check arch-independent packages too
        check_archall = arch in nobreakall_arches

        # check all the packages for this architecture
        nuninst[arch] = set()
        packages_t_a = binaries_t[arch][0]
        for pkg_name, pkg_data in packages_t_a.items():
            r = inst_tester.is_installable(pkg_data.pkg_id)
            if not r:
                nuninst[arch].add(pkg_name)

        # if they are not required, remove architecture-independent packages
        nuninst[arch + "+all"] = nuninst[arch].copy()
        if not check_archall:
            for pkg_name in nuninst[arch + "+all"]:
                pkg_data = packages_t_a[pkg_name]
                if pkg_data.architecture == 'all':
                    nuninst[arch].remove(pkg_name)

    return nuninst
