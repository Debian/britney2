#!/usr/bin/python3 -u
# -*- coding: utf-8 -*-

# Copyright (C) 2001-2008 Anthony Towns <ajt@debian.org>
#                         Andreas Barth <aba@debian.org>
#                         Fabio Tranchitella <kobold@debian.org>
# Copyright (C) 2010-2013 Adam D. Barratt <adsb@debian.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

"""
= Introduction =

This is the Debian testing updater script, also known as "Britney".

Packages are usually installed into the `testing' distribution after
they have undergone some degree of testing in unstable. The goal of
this software is to do this task in a smart way, allowing testing
to always be fully installable and close to being a release candidate.

Britney's source code is split between two different but related tasks:
the first one is the generation of the update excuses, while the
second tries to update testing with the valid candidates; first 
each package alone, then larger and even larger sets of packages
together. Each try is accepted if testing is not more uninstallable
after the update than before.

= Data Loading =

In order to analyze the entire Debian distribution, Britney needs to
load in memory the whole archive: this means more than 10.000 packages
for twelve architectures, as well as the dependency interconnections
between them. For this reason, the memory requirements for running this
software are quite high and at least 1 gigabyte of RAM should be available.

Britney loads the source packages from the `Sources' file and the binary
packages from the `Packages_${arch}' files, where ${arch} is substituted
with the supported architectures. While loading the data, the software
analyzes the dependencies and builds a directed weighted graph in memory
with all the interconnections between the packages (see Britney.read_sources
and Britney.read_binaries).

Other than source and binary packages, Britney loads the following data:

  * BugsV, which contains the list of release-critical bugs for a given
    version of a source or binary package (see Britney.read_bugs).

  * Dates, which contains the date of the upload of a given version 
    of a source package (see Britney.read_dates).

  * Urgencies, which contains the urgency of the upload of a given
    version of a source package (see AgePolicy._read_urgencies).

  * Hints, which contains lists of commands which modify the standard behaviour
    of Britney (see Britney.read_hints).

For a more detailed explanation about the format of these files, please read
the documentation of the related methods. The exact meaning of them will be
instead explained in the chapter "Excuses Generation".

= Excuses =

An excuse is a detailed explanation of why a package can or cannot
be updated in the testing distribution from a newer package in 
another distribution (like for example unstable). The main purpose
of the excuses is to be written in an HTML file which will be 
published over HTTP. The maintainers will be able to parse it manually
or automatically to find the explanation of why their packages have
been updated or not.

== Excuses generation ==

These are the steps (with references to method names) that Britney
does for the generation of the update excuses.

 * If a source package is available in testing but it is not
   present in unstable and no binary packages in unstable are
   built from it, then it is marked for removal.

 * Every source package in unstable and testing-proposed-updates,
   if already present in testing, is checked for binary-NMUs, new
   or dropped binary packages in all the supported architectures
   (see Britney.should_upgrade_srcarch). The steps to detect if an
   upgrade is needed are:

    1. If there is a `remove' hint for the source package, the package
       is ignored: it will be removed and not updated.

    2. For every binary package built from the new source, it checks
       for unsatisfied dependencies, new binary packages and updated
       binary packages (binNMU), excluding the architecture-independent
       ones, and packages not built from the same source.

    3. For every binary package built from the old source, it checks
       if it is still built from the new source; if this is not true
       and the package is not architecture-independent, the script
       removes it from testing.

    4. Finally, if there is something worth doing (eg. a new or updated
       binary package) and nothing wrong it marks the source package
       as "Valid candidate", or "Not considered" if there is something
       wrong which prevented the update.

 * Every source package in unstable and testing-proposed-updates is
   checked for upgrade (see Britney.should_upgrade_src). The steps
   to detect if an upgrade is needed are:

    1. If the source package in testing is more recent the new one
       is ignored.

    2. If the source package doesn't exist (is fake), which means that
       a binary package refers to it but it is not present in the
       `Sources' file, the new one is ignored.

    3. If the package doesn't exist in testing, the urgency of the
       upload is ignored and set to the default (actually `low').

    4. If there is a `remove' hint for the source package, the package
       is ignored: it will be removed and not updated.

    5. If there is a `block' hint for the source package without an
       `unblock` hint or a `block-all source`, the package is ignored.

    6. If there is a `block-udeb' hint for the source package, it will
       have the same effect as `block', but may only be cancelled by
       a subsequent `unblock-udeb' hint.

    7. If the suite is unstable, the update can go ahead only if the
       upload happened more than the minimum days specified by the
       urgency of the upload; if this is not true, the package is
       ignored as `too-young'. Note that the urgency is sticky, meaning
       that the highest urgency uploaded since the previous testing
       transition is taken into account.

    8. If the suite is unstable, all the architecture-dependent binary
       packages and the architecture-independent ones for the `nobreakall'
       architectures have to be built from the source we are considering.
       If this is not true, then these are called `out-of-date'
       architectures and the package is ignored.

    9. The source package must have at least one binary package, otherwise
       it is ignored.

   10. If the suite is unstable, the new source package must have no
       release critical bugs which do not also apply to the testing
       one. If this is not true, the package is ignored as `buggy'.

   11. If there is a `force' hint for the source package, then it is
       updated even if it is marked as ignored from the previous steps.

   12. If the suite is {testing-,}proposed-updates, the source package can
       be updated only if there is an explicit approval for it.  Unless
       a `force' hint exists, the new package must also be available
       on all of the architectures for which it has binary packages in
       testing.

   13. If the package will be ignored, mark it as "Valid candidate",
       otherwise mark it as "Not considered".

 * The list of `remove' hints is processed: if the requested source
   package is not already being updated or removed and the version
   actually in testing is the same specified with the `remove' hint,
   it is marked for removal.

 * The excuses are sorted by the number of days from the last upload
   (days-old) and by name.

 * A list of unconsidered excuses (for which the package is not upgraded)
   is built. Using this list, all of the excuses depending on them are
   marked as invalid "impossible dependencies".

 * The excuses are written in an HTML file.
"""
from __future__ import print_function

import os
import sys
import time
import optparse

import apt_pkg

from collections import defaultdict
from functools import reduce
from itertools import chain, product
from operator import attrgetter

from urllib.parse import quote

from installability.builder import InstallabilityTesterBuilder
from excuse import Excuse
from migrationitem import MigrationItem
from hints import HintParser
from britney_util import (old_libraries_format, undo_changes,
                          compute_reverse_tree,
                          read_nuninst, write_nuninst, write_heidi,
                          eval_uninst, newly_uninst, make_migrationitem,
                          write_excuses, write_heidi_delta, write_controlfiles,
                          old_libraries, is_nuninst_asgood_generous,
                          clone_nuninst, check_installability)
from policies.policy import AgePolicy, PolicyVerdict
from consts import (VERSION, SECTION, BINARIES, MAINTAINER, FAKESRC,
                   SOURCE, SOURCEVER, ARCHITECTURE, DEPENDS, CONFLICTS,
                   PROVIDES, MULTIARCH, ESSENTIAL)

__author__ = 'Fabio Tranchitella and the Debian Release Team'
__version__ = '2.0'

# NB: ESSENTIAL deliberately skipped as the 2011 and 2012
# parts of the live-data tests require it (britney merges
# this field correctly from the unstable version where
# available)
check_field_name = dict((globals()[fn], fn) for fn in
                         (
                          "SOURCE SOURCEVER ARCHITECTURE MULTIARCH" +
                          " DEPENDS CONFLICTS PROVIDES"
                         ).split()
                        )

check_fields = sorted(check_field_name)

class Britney(object):
    """Britney, the Debian testing updater script
    
    This is the script that updates the testing distribution. It is executed
    each day after the installation of the updated packages. It generates the 
    `Packages' files for the testing distribution, but it does so in an
    intelligent manner; it tries to avoid any inconsistency and to use only
    non-buggy packages.

    For more documentation on this script, please read the Developers Reference.
    """

    HINTS_HELPERS = ("easy", "hint", "remove", "block", "block-udeb", "unblock", "unblock-udeb", "approve")
    HINTS_STANDARD = ("urgent", "age-days") + HINTS_HELPERS
    HINTS_ALL = ("force", "force-hint", "block-all") + HINTS_STANDARD

    def __init__(self):
        """Class constructor

        This method initializes and populates the data lists, which contain all
        the information needed by the other methods of the class.
        """

        # parse the command line arguments
        self.policies = []
        self.__parse_arguments()
        MigrationItem.set_architectures(self.options.architectures)

        # initialize the apt_pkg back-end
        apt_pkg.init()
        self.sources = {}
        self.binaries = {}
        self.all_selected = []
        self.excuses = {}

        try:
            self.hints = self.read_hints(self.options.hintsdir)
        except AttributeError:
            self.hints = self.read_hints(self.options.unstable)

        if self.options.nuninst_cache:
            self.log("Not building the list of non-installable packages, as requested", type="I")
            if self.options.print_uninst:
                print('* summary')
                print('\n'.join('%4d %s' % (len(nuninst[x]), x) for x in self.options.architectures))
                return

        self.all_binaries = {}
        # read the source and binary packages for the involved distributions
        self.sources['testing'] = self.read_sources(self.options.testing)
        self.sources['unstable'] = self.read_sources(self.options.unstable)
        self.sources['tpu'] = self.read_sources(self.options.tpu)

        if hasattr(self.options, 'pu'):
            self.sources['pu'] = self.read_sources(self.options.pu)
        else:
            self.sources['pu'] = {}

        self.binaries['testing'] = {}
        self.binaries['unstable'] = {}
        self.binaries['tpu'] = {}
        self.binaries['pu'] = {}

        for arch in self.options.architectures:
            self.binaries['testing'][arch] = self.read_binaries(self.options.testing, "testing", arch)
            self.binaries['unstable'][arch] = self.read_binaries(self.options.unstable, "unstable", arch)
            self.binaries['tpu'][arch] = self.read_binaries(self.options.tpu, "tpu", arch)
            if hasattr(self.options, 'pu'):
                self.binaries['pu'][arch] = self.read_binaries(self.options.pu, "pu", arch)
            else:
                # _build_installability_tester relies on it being
                # properly initialised, so insert two empty dicts
                # here.
                self.binaries['pu'][arch] = ({}, {})

        self.log("Compiling Installability tester", type="I")
        self._build_installability_tester(self.options.architectures)

        if not self.options.nuninst_cache:
            self.log("Building the list of non-installable packages for the full archive", type="I")
            nuninst = {}
            self._inst_tester.compute_testing_installability()
            for arch in self.options.architectures:
                self.log("> Checking for non-installable packages for architecture %s" % arch, type="I")
                result = self.get_nuninst(arch, build=True)
                nuninst.update(result)
                self.log("> Found %d non-installable packages" % len(nuninst[arch]), type="I")
                if self.options.print_uninst:
                    self.nuninst_arch_report(nuninst, arch)

            if self.options.print_uninst:
                print('* summary')
                print('\n'.join(map(lambda x: '%4d %s' % (len(nuninst[x]), x), self.options.architectures)))
                return
            else:
                write_nuninst(self.options.noninst_status, nuninst)

            stats = self._inst_tester.compute_stats()
            self.log("> Installability tester statistics (per architecture)", type="I")
            for arch in self.options.architectures:
                arch_stat = stats[arch]
                self.log(">  %s" % arch, type="I")
                for stat in arch_stat.stat_summary():
                    self.log(">  - %s" % stat, type="I")

        # read the release-critical bug summaries for testing and unstable
        self.bugs = {'unstable': self.read_bugs(self.options.unstable),
                     'testing': self.read_bugs(self.options.testing),}
        self.normalize_bugs()
        for policy in self.policies:
            policy.hints = self.hints
            policy.initialise(self)

    def merge_pkg_entries(self, package, parch, pkg_entry1, pkg_entry2,
                          check_fields=check_fields, check_field_name=check_field_name):
        bad = []
        for f in check_fields:
            if pkg_entry1[f] != pkg_entry2[f]:
                bad.append((f, pkg_entry1[f], pkg_entry2[f]))

        if bad:
            self.log("Mismatch found %s %s %s differs" % (
                package, pkg_entry1[VERSION], parch), type="E")
            for f, v1, v2 in bad:
                self.log(" ... %s %s != %s" % (check_field_name[f], v1, v2))
            raise ValueError("Invalid data set")

        # Merge ESSENTIAL if necessary
        if pkg_entry2[ESSENTIAL]:
            pkg_entry1[ESSENTIAL] = True

    def __parse_arguments(self):
        """Parse the command line arguments

        This method parses and initializes the command line arguments.
        While doing so, it preprocesses some of the options to be converted
        in a suitable form for the other methods of the class.
        """
        # initialize the parser
        parser = optparse.OptionParser(version="%prog")
        parser.add_option("-v", "", action="count", dest="verbose", help="enable verbose output")
        parser.add_option("-c", "--config", action="store", dest="config", default="/etc/britney.conf",
                               help="path for the configuration file")
        parser.add_option("", "--architectures", action="store", dest="architectures", default=None,
                               help="override architectures from configuration file")
        parser.add_option("", "--actions", action="store", dest="actions", default=None,
                               help="override the list of actions to be performed")
        parser.add_option("", "--hints", action="store", dest="hints", default=None,
                               help="additional hints, separated by semicolons")
        parser.add_option("", "--hint-tester", action="store_true", dest="hint_tester", default=None,
                               help="provide a command line interface to test hints")
        parser.add_option("", "--dry-run", action="store_true", dest="dry_run", default=False,
                               help="disable all outputs to the testing directory")
        parser.add_option("", "--control-files", action="store_true", dest="control_files", default=False,
                               help="enable control files generation")
        parser.add_option("", "--nuninst-cache", action="store_true", dest="nuninst_cache", default=False,
                               help="do not build the non-installability status, use the cache from file")
        parser.add_option("", "--print-uninst", action="store_true", dest="print_uninst", default=False,
                               help="just print a summary of uninstallable packages")
        parser.add_option("", "--components", action="store", dest="components",
                               help="Sources/Packages are laid out by components listed (, sep)")
        (self.options, self.args) = parser.parse_args()
        
        # integrity checks
        if self.options.nuninst_cache and self.options.print_uninst:
            self.log("nuninst_cache and print_uninst are mutually exclusive!", type="E")
            sys.exit(1)
        # if the configuration file exists, then read it and set the additional options
        elif not os.path.isfile(self.options.config):
            self.log("Unable to read the configuration file (%s), exiting!" % self.options.config, type="E")
            sys.exit(1)

        # minimum days for unstable-testing transition and the list of hints
        # are handled as an ad-hoc case
        MINDAYS = {}
        self.HINTS = {'command-line': self.HINTS_ALL}
        with open(self.options.config, encoding='utf-8') as config:
            for line in config:
                if '=' in line and not line.strip().startswith('#'):
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip()
                    if k.startswith("MINDAYS_"):
                        MINDAYS[k.split("_")[1].lower()] = int(v)
                    elif k.startswith("HINTS_"):
                        self.HINTS[k.split("_")[1].lower()] = \
                            reduce(lambda x,y: x+y, [hasattr(self, "HINTS_" + i) and getattr(self, "HINTS_" + i) or (i,) for i in v.split()])
                    elif not hasattr(self.options, k.lower()) or \
                         not getattr(self.options, k.lower()):
                        setattr(self.options, k.lower(), v)

        if getattr(self.options, "components", None):
            self.options.components = [s.strip() for s in self.options.components.split(",")]
        else:
            self.options.components = None

        if self.options.control_files and self.options.components:
            # We cannot regenerate the control files correctly when reading from an
            # actual mirror (we don't which package goes in what component etc.).
            self.log("Cannot use --control-files with mirror-layout (components)!", type="E")
            sys.exit(1)

        if not hasattr(self.options, "heidi_delta_output"):
            self.options.heidi_delta_output = self.options.heidi_output + "Delta"

        self.options.nobreakall_arches = self.options.nobreakall_arches.split()
        self.options.fucked_arches = self.options.fucked_arches.split()
        self.options.break_arches = self.options.break_arches.split()
        self.options.new_arches = self.options.new_arches.split()

        # Sort the architecture list
        allarches = sorted(self.options.architectures.split())
        arches = [x for x in allarches if x in self.options.nobreakall_arches]
        arches += [x for x in allarches if x not in arches and x not in self.options.fucked_arches]
        arches += [x for x in allarches if x not in arches and x not in self.options.break_arches]
        arches += [x for x in allarches if x not in arches and x not in self.options.new_arches]
        arches += [x for x in allarches if x not in arches]
        self.options.architectures = [sys.intern(arch) for arch in arches]
        self.options.smooth_updates = self.options.smooth_updates.split()

        if not hasattr(self.options, 'ignore_cruft') or \
            self.options.ignore_cruft == "0":
            self.options.ignore_cruft = False

        self.policies.append(AgePolicy(self.options, MINDAYS))

    def log(self, msg, type="I"):
        """Print info messages according to verbosity level
        
        An easy-and-simple log method which prints messages to the standard
        output. The type parameter controls the urgency of the message, and
        can be equal to `I' for `Information', `W' for `Warning' and `E' for
        `Error'. Warnings and errors are always printed, and information is
        printed only if verbose logging is enabled.
        """
        if self.options.verbose or type in ("E", "W"):
            print("%s: [%s] - %s" % (type, time.asctime(), msg))

    def _build_installability_tester(self, archs):
        """Create the installability tester"""

        solvers = self.get_dependency_solvers
        binaries = self.binaries
        builder = InstallabilityTesterBuilder()

        for (dist, arch) in product(binaries, archs):
            testing = (dist == 'testing')
            for pkgname in binaries[dist][arch][0]:
                pkgdata = binaries[dist][arch][0][pkgname]
                version = pkgdata[VERSION]
                t = (pkgname, version, arch)
                essential = pkgdata[ESSENTIAL]
                if not builder.add_binary(t, essential=essential,
                                          in_testing=testing):
                    continue

                depends = []
                conflicts = []
                possible_dep_ranges = {}

                # We do not differentiate between depends and pre-depends
                if pkgdata[DEPENDS]:
                    depends.extend(apt_pkg.parse_depends(pkgdata[DEPENDS], False))

                if pkgdata[CONFLICTS]:
                    conflicts = apt_pkg.parse_depends(pkgdata[CONFLICTS], False)

                with builder.relation_builder(t) as relations:

                    for (al, dep) in [(depends, True), \
                                      (conflicts, False)]:

                        for block in al:
                            sat = set()

                            for dep_dist in binaries:
                                dep_packages_s_a = binaries[dep_dist][arch]
                                pkgs = solvers(block, dep_packages_s_a)
                                for p in pkgs:
                                    # version and arch is already interned, but solvers use
                                    # the package name extracted from the field and it is therefore
                                    # not interned.
                                    pdata = dep_packages_s_a[0][p]
                                    pt = (sys.intern(p), pdata[VERSION], arch)
                                    if dep:
                                        sat.add(pt)
                                    elif t != pt:
                                        # if t satisfies its own
                                        # conflicts relation, then it
                                        # is using §7.6.2
                                        relations.add_breaks(pt)
                            if dep:
                                if len(block) != 1:
                                    relations.add_dependency_clause(sat)
                                else:
                                    # This dependency might be a part
                                    # of a version-range a la:
                                    #
                                    #   Depends: pkg-a (>= 1),
                                    #            pkg-a (<< 2~)
                                    #
                                    # In such a case we want to reduce
                                    # that to a single clause for
                                    # efficiency.
                                    #
                                    # In theory, it could also happen
                                    # with "non-minimal" dependencies
                                    # a la:
                                    #
                                    #   Depends: pkg-a, pkg-a (>= 1)
                                    #
                                    # But dpkg is known to fix that up
                                    # at build time, so we will
                                    # probably only see "ranges" here.
                                    key = block[0][0]
                                    if key in possible_dep_ranges:
                                        possible_dep_ranges[key] &= sat
                                    else:
                                        possible_dep_ranges[key] = sat

                        if dep:
                            for clause in possible_dep_ranges.values():
                                relations.add_dependency_clause(clause)

        self._inst_tester = builder.build()


    # Data reading/writing methods
    # ----------------------------

    def _read_sources_file(self, filename, sources=None, intern=sys.intern):
        if sources is None:
            sources = {}

        self.log("Loading source packages from %s" % filename)

        Packages = apt_pkg.TagFile(filename)
        get_field = Packages.section.get
        step = Packages.step

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
            sources[intern(pkg)] = [intern(ver),
                            intern(get_field('Section')),
                            [],
                            get_field('Maintainer'),
                            False,
                           ]
        return sources

    def read_sources(self, basedir):
        """Read the list of source packages from the specified directory

        The source packages are read from the `Sources' file within the
        directory specified as `basedir' parameter. Considering the
        large amount of memory needed, not all the fields are loaded
        in memory. The available fields are Version, Maintainer and Section.

        The method returns a list where every item represents a source
        package as a dictionary.
        """

        if self.options.components:
            sources = {}
            for component in self.options.components:
                filename = os.path.join(basedir, component, "source", "Sources")
                self._read_sources_file(filename, sources)
        else:
            filename = os.path.join(basedir, "Sources")
            sources = self._read_sources_file(filename)

        return sources

    def _read_packages_file(self, filename, arch, srcdist, packages=None, intern=sys.intern):
        self.log("Loading binary packages from %s" % filename)

        if packages is None:
            packages = {}

        all_binaries = self.all_binaries

        Packages = apt_pkg.TagFile(filename)
        get_field = Packages.section.get
        step = Packages.step

        while step():
            pkg = get_field('Package')
            version = get_field('Version')

            # There may be multiple versions of any arch:all packages
            # (in unstable) if some architectures have out-of-date
            # binaries.  We only ever consider the package with the
            # largest version for migration.
            pkg = intern(pkg)
            version = intern(version)
            pkg_id = (pkg, version, arch)

            if pkg in packages:
                old_pkg_data = packages[pkg]
                if apt_pkg.version_compare(old_pkg_data[VERSION], version) > 0:
                    continue
                old_pkg_id = (pkg, old_pkg_data[VERSION], arch)
                old_src_binaries = srcdist[old_pkg_data[SOURCE]][BINARIES]
                old_src_binaries.remove(old_pkg_id)
                # This may seem weird at first glance, but the current code rely
                # on this behaviour to avoid issues like #709460.  Admittedly it
                # is a special case, but Britney will attempt to remove the
                # arch:all packages without this.  Even then, this particular
                # stop-gap relies on the packages files being sorted by name
                # and the version, so it is not particularly resilient.
                if pkg_id not in old_src_binaries:
                    old_src_binaries.append(pkg_id)

            # Merge Pre-Depends with Depends and Conflicts with
            # Breaks. Britney is not interested in the "finer
            # semantic differences" of these fields anyway.
            pdeps = get_field('Pre-Depends')
            deps = get_field('Depends')
            if deps and pdeps:
                deps = pdeps + ', ' + deps
            elif pdeps:
                deps = pdeps

            ess = False
            if get_field('Essential', 'no') == 'yes':
                ess = True

            final_conflicts_list = []
            conflicts = get_field('Conflicts')
            if conflicts:
                final_conflicts_list.append(conflicts)
            breaks = get_field('Breaks')
            if breaks:
                final_conflicts_list.append(breaks)
            dpkg = [version,
                    intern(get_field('Section')),
                    pkg,
                    version,
                    intern(get_field('Architecture')),
                    get_field('Multi-Arch'),
                    deps,
                    ', '.join(final_conflicts_list) or None,
                    get_field('Provides'),
                    ess,
                   ]

            # retrieve the name and the version of the source package
            source = get_field('Source')
            if source:
                dpkg[SOURCE] = intern(source.split(" ")[0])
                if "(" in source:
                    dpkg[SOURCEVER] = intern(source[source.find("(")+1:source.find(")")])

            # if the source package is available in the distribution, then register this binary package
            if dpkg[SOURCE] in srcdist:
                # There may be multiple versions of any arch:all packages
                # (in unstable) if some architectures have out-of-date
                # binaries.  We only want to include the package in the
                # source -> binary mapping once. It doesn't matter which
                # of the versions we include as only the package name and
                # architecture are recorded.
                if pkg_id not in srcdist[dpkg[SOURCE]][BINARIES]:
                    srcdist[dpkg[SOURCE]][BINARIES].append(pkg_id)
            # if the source package doesn't exist, create a fake one
            else:
                srcdist[dpkg[SOURCE]] = [dpkg[SOURCEVER], 'faux', [pkg_id], None, True]

            if dpkg[PROVIDES]:
                parts = apt_pkg.parse_depends(dpkg[PROVIDES], False)
                nprov = []
                for or_clause in parts:
                    if len(or_clause) != 1:
                        msg = "Ignoring invalid provides in %s: Alternatives [%s]" % (str(pkg_id), str(or_clause))
                        self.log(msg, type='W')
                        continue
                    for part in or_clause:
                        provided, provided_version, op = part
                        if op != '' and op != '=':
                            msg = "Ignoring invalid provides in %s: %s (%s %s)" % (str(pkg_id), provided, op, version)
                            self.log(msg, type='W')
                            continue
                        provided = intern(provided)
                        provided_version = intern(provided_version)
                        part = (provided, provided_version, intern(op))
                        nprov.append(part)
                dpkg[PROVIDES] = nprov
            else:
                dpkg[PROVIDES] = []

            # add the resulting dictionary to the package list
            packages[pkg] = dpkg
            if pkg_id in all_binaries:
                self.merge_pkg_entries(pkg, arch, all_binaries[pkg_id], dpkg)
            else:
                all_binaries[pkg_id] = dpkg

            # add the resulting dictionary to the package list
            packages[pkg] = dpkg

        return packages

    def read_binaries(self, basedir, distribution, arch):
        """Read the list of binary packages from the specified directory

        The binary packages are read from the `Packages' files for `arch'.

        If components are specified, the files
        for each component are loaded according to the usual Debian mirror
        layout.

        If no components are specified, a single file named
        `Packages_${arch}' is expected to be within the directory
        specified as `basedir' parameter, replacing ${arch} with the
        value of the arch parameter.

        Considering the
        large amount of memory needed, not all the fields are loaded
        in memory. The available fields are Version, Source, Multi-Arch,
        Depends, Conflicts, Provides and Architecture.

        After reading the packages, reverse dependencies are computed
        and saved in the `rdepends' keys, and the `Provides' field is
        used to populate the virtual packages list.

        The dependencies are parsed with the apt_pkg.parse_depends method,
        and they are stored both as the format of its return value and
        text.

        The method returns a tuple. The first element is a list where
        every item represents a binary package as a dictionary; the second
        element is a dictionary which maps virtual packages to real
        packages that provide them.
        """

        if self.options.components:
            packages = {}
            for component in self.options.components:
                filename = os.path.join(basedir,
                             component, "binary-%s" % arch, "Packages")
                self._read_packages_file(filename, arch,
                      self.sources[distribution], packages)
        else:
            filename = os.path.join(basedir, "Packages_%s" % arch)
            packages = self._read_packages_file(filename, arch,
                             self.sources[distribution])

        # create provides
        provides = defaultdict(set)

        for pkg, dpkg in packages.items():
            # register virtual packages and real packages that provide
            # them
            for provided_pkg, provided_version, _ in dpkg[PROVIDES]:
                provides[provided_pkg].add((pkg, provided_version))


        # return a tuple with the list of real and virtual packages
        return (packages, provides)

    def read_bugs(self, basedir):
        """Read the release critical bug summary from the specified directory
        
        The RC bug summaries are read from the `BugsV' file within the
        directory specified in the `basedir' parameter. The file contains
        rows with the format:

        <package-name> <bug number>[,<bug number>...]

        The method returns a dictionary where the key is the binary package
        name and the value is the list of open RC bugs for it.
        """
        bugs = defaultdict(list)
        filename = os.path.join(basedir, "BugsV")
        self.log("Loading RC bugs data from %s" % filename)
        for line in open(filename, encoding='ascii'):
            l = line.split()
            if len(l) != 2:
                self.log("Malformed line found in line %s" % (line), type='W')
                continue
            pkg = l[0]
            bugs[pkg] += l[1].split(",")
        return bugs

    def __maxver(self, pkg, dist):
        """Return the maximum version for a given package name
        
        This method returns None if the specified source package
        is not available in the `dist' distribution. If the package
        exists, then it returns the maximum version between the
        source package and its binary packages.
        """
        maxver = None
        if pkg in self.sources[dist]:
            maxver = self.sources[dist][pkg][VERSION]
        for arch in self.options.architectures:
            if pkg not in self.binaries[dist][arch][0]: continue
            pkgv = self.binaries[dist][arch][0][pkg][VERSION]
            if maxver is None or apt_pkg.version_compare(pkgv, maxver) > 0:
                maxver = pkgv
        return maxver

    def normalize_bugs(self):
        """Normalize the release critical bug summaries for testing and unstable
        
        The method doesn't return any value: it directly modifies the
        object attribute `bugs'.
        """
        # loop on all the package names from testing and unstable bug summaries
        for pkg in set(chain(self.bugs['testing'], self.bugs['unstable'])):

            # make sure that the key is present in both dictionaries
            if pkg not in self.bugs['testing']:
                self.bugs['testing'][pkg] = []
            elif pkg not in self.bugs['unstable']:
                self.bugs['unstable'][pkg] = []

            if pkg.startswith("src:"):
                pkg = pkg[4:]

            # retrieve the maximum version of the package in testing:
            maxvert = self.__maxver(pkg, 'testing')

            # if the package is not available in testing, then reset
            # the list of RC bugs
            if maxvert is None:
                self.bugs['testing'][pkg] = []

    def read_hints(self, basedir):
        """Read the hint commands from the specified directory
        
        The hint commands are read from the files contained in the `Hints'
        directory within the directory specified as `basedir' parameter. 
        The names of the files have to be the same as the authorized users
        for the hints.
        
        The file contains rows with the format:

        <command> <package-name>[/<version>]

        The method returns a dictionary where the key is the command, and
        the value is the list of affected packages.
        """
        hint_parser = HintParser(self)

        for who in self.HINTS.keys():
            if who == 'command-line':
                lines = self.options.hints and self.options.hints.split(';') or ()
                filename = '<cmd-line>'
                hint_parser.parse_hints(who, self.HINTS[who], filename, lines)
            else:
                filename = os.path.join(basedir, "Hints", who)
                if not os.path.isfile(filename):
                    self.log("Cannot read hints list from %s, no such file!" % filename, type="E")
                    continue
                self.log("Loading hints list from %s" % filename)
                with open(filename, encoding='utf-8') as f:
                    hint_parser.parse_hints(who, self.HINTS[who], filename, f)

        hints = hint_parser.hints

        for x in ["block", "block-all", "block-udeb", "unblock", "unblock-udeb", "force", "urgent", "remove", "age-days"]:
            z = {}
            for hint in hints[x]:
                package = hint.package
                key = (hint, hint.user)
                if package in z and z[package] != key:
                    hint2 = z[package][0]
                    if x in ['unblock', 'unblock-udeb']:
                        if apt_pkg.version_compare(hint2.version, hint.version) < 0:
                            # This hint is for a newer version, so discard the old one
                            self.log("Overriding %s[%s] = ('%s', '%s') with ('%s', '%s')" %
                               (x, package, hint2.version, hint2.user, hint.version, hint.user), type="W")
                            hint2.set_active(False)
                        else:
                            # This hint is for an older version, so ignore it in favour of the new one
                            self.log("Ignoring %s[%s] = ('%s', '%s'), ('%s', '%s') is higher or equal" %
                               (x, package, hint.version, hint.user, hint2.version, hint2.user), type="W")
                            hint.set_active(False)
                    else:
                        self.log("Overriding %s[%s] = ('%s', '%s', '%s') with ('%s', '%s', '%s')" %
                           (x, package, hint2.version, hint2.user, hint2.days,
                            hint.version, hint.user, hint.days), type="W")
                        hint2.set_active(False)

                z[package] = key

        # Sanity check the hints hash
        if len(hints["block"]) == 0 and len(hints["block-udeb"]) == 0:
            self.log("WARNING: No block hints at all, not even udeb ones!", type="W")

        return hints


    # Utility methods for package analysis
    # ------------------------------------

    def get_dependency_solvers(self, block, packages_s_a, empty_set=frozenset()):
        """Find the packages which satisfy a dependency block

        This method returns the list of packages which satisfy a dependency
        block (as returned by apt_pkg.parse_depends) in a package table
        for a given suite and architecture (a la self.binaries[suite][arch])

        It returns a tuple with two items: the first is a boolean which is
        True if the dependency is satisfied, the second is the list of the
        solving packages.
        """
        packages = []
        binaries_s_a, provides_s_a = packages_s_a

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
                if (op == '' and version == '') or apt_pkg.check_dep(package[VERSION], op, version):
                    if archqual is None or (archqual == 'any' and package[MULTIARCH] == 'allowed'):
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


    def excuse_unsat_deps(self, pkg, src, arch, suite, excuse):
        """Find unsatisfied dependencies for a binary package

        This method analyzes the dependencies of the binary package specified
        by the parameter `pkg', built from the source package `src', for the
        architecture `arch' within the suite `suite'. If the dependency can't
        be satisfied in testing and/or unstable, it updates the excuse passed
        as parameter.
        """
        # retrieve the binary package from the specified suite and arch
        package_s_a = self.binaries[suite][arch]
        package_t_a = self.binaries['testing'][arch]
        binary_u = package_s_a[0][pkg]

        # local copies for better performance
        parse_depends = apt_pkg.parse_depends
        get_dependency_solvers = self.get_dependency_solvers

        # analyze the dependency fields (if present)
        if not binary_u[DEPENDS]:
            return
        deps = binary_u[DEPENDS]

        # for every dependency block (formed as conjunction of disjunction)
        for block, block_txt in zip(parse_depends(deps, False), deps.split(',')):
            # if the block is satisfied in testing, then skip the block
            packages = get_dependency_solvers(block, package_t_a)
            if packages:
                for p in packages:
                    if p not in package_s_a[0]:
                        continue
                    excuse.add_sane_dep(package_s_a[0][p][SOURCE])
                continue

            # check if the block can be satisfied in the source suite, and list the solving packages
            packages = get_dependency_solvers(block, package_s_a)
            packages = [package_s_a[0][p][SOURCE] for p in packages]

            # if the dependency can be satisfied by the same source package, skip the block:
            # obviously both binary packages will enter testing together
            if src in packages: continue

            # if no package can satisfy the dependency, add this information to the excuse
            if not packages:
                excuse.addhtml("%s/%s unsatisfiable Depends: %s" % (pkg, arch, block_txt.strip()))
                excuse.addreason("depends")
                continue

            # for the solving packages, update the excuse to add the dependencies
            for p in packages:
                if arch not in self.options.break_arches:
                    if p in self.sources['testing'] and self.sources['testing'][p][VERSION] == self.sources[suite][p][VERSION]:
                        excuse.add_dep("%s/%s" % (p, arch), arch)
                    else:
                        excuse.add_dep(p, arch)
                else:
                    excuse.add_break_dep(p, arch)

    # Package analysis methods
    # ------------------------

    def should_remove_source(self, pkg):
        """Check if a source package should be removed from testing
        
        This method checks if a source package should be removed from the
        testing distribution; this happens if the source package is not
        present in the unstable distribution anymore.

        It returns True if the package can be removed, False otherwise.
        In the former case, a new excuse is appended to the object
        attribute excuses.
        """
        # if the source package is available in unstable, then do nothing
        if pkg in self.sources['unstable']:
            return False
        # otherwise, add a new excuse for its removal
        src = self.sources['testing'][pkg]
        excuse = Excuse("-" + pkg)
        excuse.addhtml("Package not in unstable, will try to remove")
        excuse.addreason("remove")
        excuse.set_vers(src[VERSION], None)
        src[MAINTAINER] and excuse.set_maint(src[MAINTAINER].strip())
        src[SECTION] and excuse.set_section(src[SECTION].strip())

        # if the package is blocked, skip it
        for hint in self.hints.search('block', package=pkg, removal=True):
            excuse.addhtml("Not touching package, as requested by %s "
                "(check https://release.debian.org/testing/freeze_policy.html if update is needed)" % hint.user)
            excuse.addhtml("Not considered")
            excuse.addreason("block")
            self.excuses[excuse.name] = excuse
            return False

        excuse.is_valid = True
        self.excuses[excuse.name] = excuse
        return True

    def should_upgrade_srcarch(self, src, arch, suite):
        """Check if a set of binary packages should be upgraded

        This method checks if the binary packages produced by the source
        package on the given architecture should be upgraded; this can
        happen also if the migration is a binary-NMU for the given arch.
       
        It returns False if the given packages don't need to be upgraded,
        True otherwise. In the former case, a new excuse is appended to
        the object attribute excuses.
        """
        # retrieve the source packages for testing and suite
        source_t = self.sources['testing'][src]
        source_u = self.sources[suite][src]

        # build the common part of the excuse, which will be filled by the code below
        ref = "%s/%s%s" % (src, arch, suite != 'unstable' and "_" + suite or "")
        excuse = Excuse(ref)
        excuse.set_vers(source_t[VERSION], source_t[VERSION])
        source_u[MAINTAINER] and excuse.set_maint(source_u[MAINTAINER].strip())
        source_u[SECTION] and excuse.set_section(source_u[SECTION].strip())
        
        # if there is a `remove' hint and the requested version is the same as the
        # version in testing, then stop here and return False
        # (as a side effect, a removal may generate such excuses for both the source
        # package and its binary packages on each architecture)
        for hint in [x for x in self.hints.search('remove', package=src) if source_t[VERSION] == x.version]:
            excuse.addhtml("Removal request by %s" % (hint.user))
            excuse.addhtml("Trying to remove package, not update it")
            excuse.addhtml("Not considered")
            excuse.addreason("remove")
            self.excuses[excuse.name] = excuse
            return False

        # the starting point is that there is nothing wrong and nothing worth doing
        anywrongver = False
        anyworthdoing = False

        packages_t_a = self.binaries['testing'][arch][0]
        packages_s_a = self.binaries[suite][arch][0]

        # for every binary package produced by this source in unstable for this architecture
        for pkg_id in sorted(x for x in source_u[BINARIES] if x[2] == arch):
            pkg_name = pkg_id[0]

            # retrieve the testing (if present) and unstable corresponding binary packages
            binary_t = pkg_name in packages_t_a and packages_t_a[pkg_name] or None
            binary_u = packages_s_a[pkg_name]

            # this is the source version for the new binary package
            pkgsv = binary_u[SOURCEVER]

            # if the new binary package is architecture-independent, then skip it
            if binary_u[ARCHITECTURE] == 'all':
                excuse.addhtml("Ignoring %s %s (from %s) as it is arch: all" % (pkg_name, binary_u[VERSION], pkgsv))
                continue

            # if the new binary package is not from the same source as the testing one, then skip it
            # this implies that this binary migration is part of a source migration
            if source_u[VERSION] == pkgsv and source_t[VERSION] != pkgsv:
                anywrongver = True
                excuse.addhtml("From wrong source: %s %s (%s not %s)" % (pkg_name, binary_u[VERSION], pkgsv, source_t[VERSION]))
                continue

            # cruft in unstable
            if source_u[VERSION] != pkgsv and source_t[VERSION] != pkgsv:
                if self.options.ignore_cruft:
                    excuse.addhtml("Old cruft: %s %s (but ignoring cruft, so nevermind)" % (pkg_name, pkgsv))
                else:
                    anywrongver = True
                    excuse.addhtml("Old cruft: %s %s" % (pkg_name, pkgsv))
                continue

            # if the source package has been updated in unstable and this is a binary migration, skip it
            # (the binaries are now out-of-date)
            if source_t[VERSION] == pkgsv and source_t[VERSION] != source_u[VERSION]:
                anywrongver = True
                excuse.addhtml("From wrong source: %s %s (%s not %s)" % (pkg_name, binary_u[VERSION], pkgsv, source_u[VERSION]))
                continue

            # find unsatisfied dependencies for the new binary package
            self.excuse_unsat_deps(pkg_name, src, arch, suite, excuse)

            # if the binary is not present in testing, then it is a new binary;
            # in this case, there is something worth doing
            if not binary_t:
                excuse.addhtml("New binary: %s (%s)" % (pkg_name, binary_u[VERSION]))
                anyworthdoing = True
                continue

            # at this point, the binary package is present in testing, so we can compare
            # the versions of the packages ...
            vcompare = apt_pkg.version_compare(binary_t[VERSION], binary_u[VERSION])

            # ... if updating would mean downgrading, then stop here: there is something wrong
            if vcompare > 0:
                anywrongver = True
                excuse.addhtml("Not downgrading: %s (%s to %s)" % (pkg_name, binary_t[VERSION], binary_u[VERSION]))
                break
            # ... if updating would mean upgrading, then there is something worth doing
            elif vcompare < 0:
                excuse.addhtml("Updated binary: %s (%s to %s)" % (pkg_name, binary_t[VERSION], binary_u[VERSION]))
                anyworthdoing = True

        # if there is nothing wrong and there is something worth doing or the source
        # package is not fake, then check what packages should be removed
        if not anywrongver and (anyworthdoing or not source_u[FAKESRC]):
            srcv = source_u[VERSION]
            ssrc = source_t[VERSION] == srcv
            # if this is a binary-only migration via *pu, we never want to try
            # removing binary packages
            if not (ssrc and suite != 'unstable'):
                # for every binary package produced by this source in testing for this architecture
                _, _, smoothbins = self._compute_groups(src,
                                                        "unstable",
                                                        arch,
                                                        False)

                for pkg_id in sorted(x for x in source_t[BINARIES] if x[2] == arch):
                    pkg = pkg_id[0]
                    # if the package is architecture-independent, then ignore it
                    tpkg_data = packages_t_a[pkg]
                    if tpkg_data[ARCHITECTURE] == 'all':
                        excuse.addhtml("Ignoring removal of %s as it is arch: all" % (pkg))
                        continue
                    # if the package is not produced by the new source package, then remove it from testing
                    if pkg not in packages_s_a:
                        excuse.addhtml("Removed binary: %s %s" % (pkg, tpkg_data[VERSION]))
                        # the removed binary is only interesting if this is a binary-only migration,
                        # as otherwise the updated source will already cause the binary packages
                        # to be updated
                        if ssrc:
                            # Special-case, if the binary is a candidate for a smooth update, we do not consider
                            # it "interesting" on its own.  This case happens quite often with smooth updatable
                            # packages, where the old binary "survives" a full run because it still has
                            # reverse dependencies.
                            if pkg_id not in smoothbins:
                                anyworthdoing = True

        # if there is nothing wrong and there is something worth doing, this is a valid candidate
        if not anywrongver and anyworthdoing:
            excuse.is_valid = True
            self.excuses[excuse.name] = excuse
            return True
        # else if there is something worth doing (but something wrong, too) this package won't be considered
        elif anyworthdoing:
            excuse.addhtml("Not considered")
            self.excuses[excuse.name] = excuse

        # otherwise, return False
        return False

    def should_upgrade_src(self, src, suite):
        """Check if source package should be upgraded

        This method checks if a source package should be upgraded. The analysis
        is performed for the source package specified by the `src' parameter, 
        for the distribution `suite'.
       
        It returns False if the given package doesn't need to be upgraded,
        True otherwise. In the former case, a new excuse is appended to
        the object attribute excuses.
        """

        # retrieve the source packages for testing (if available) and suite
        source_u = self.sources[suite][src]
        if src in self.sources['testing']:
            source_t = self.sources['testing'][src]
            # if testing and unstable have the same version, then this is a candidate for binary-NMUs only
            if apt_pkg.version_compare(source_t[VERSION], source_u[VERSION]) == 0:
                return False
        else:
            source_t = None

        # build the common part of the excuse, which will be filled by the code below
        ref = "%s%s" % (src, suite != 'unstable' and "_" + suite or "")
        excuse = Excuse(ref)
        excuse.set_vers(source_t and source_t[VERSION] or None, source_u[VERSION])
        source_u[MAINTAINER] and excuse.set_maint(source_u[MAINTAINER].strip())
        source_u[SECTION] and excuse.set_section(source_u[SECTION].strip())

        # the starting point is that we will update the candidate
        update_candidate = True
        
        # if the version in unstable is older, then stop here with a warning in the excuse and return False
        if source_t and apt_pkg.version_compare(source_u[VERSION], source_t[VERSION]) < 0:
            excuse.addhtml("ALERT: %s is newer in testing (%s %s)" % (src, source_t[VERSION], source_u[VERSION]))
            self.excuses[excuse.name] = excuse
            excuse.addreason("newerintesting")
            return False

        # check if the source package really exists or if it is a fake one
        if source_u[FAKESRC]:
            excuse.addhtml("%s source package doesn't exist" % (src))
            update_candidate = False

        # if there is a `remove' hint and the requested version is the same as the
        # version in testing, then stop here and return False
        for item in self.hints.search('remove', package=src):
            if source_t and source_t[VERSION] == item.version or \
               source_u[VERSION] == item.version:
                excuse.addhtml("Removal request by %s" % (item.user))
                excuse.addhtml("Trying to remove package, not update it")
                excuse.addreason("remove")
                update_candidate = False

        # check if there is a `block' or `block-udeb' hint for this package, or a `block-all source' hint
        blocked = {}
        for hint in self.hints.search(package=src):
            if hint.type == 'block':
                blocked['block'] = hint
            if hint.type == 'block-udeb':
                blocked['block-udeb'] = hint
        for hint in self.hints.search(type='block-all', package='source'):
            blocked.setdefault('block', hint)
        if suite in ['pu', 'tpu']:
            blocked['block'] = '%s-block' % (suite)

        # if the source is blocked, then look for an `unblock' hint; the unblock request
        # is processed only if the specified version is correct. If a package is blocked
        # by `block-udeb', then `unblock-udeb' must be present to cancel it.
        for block_cmd in blocked:
            unblock_cmd = "un" + block_cmd
            unblocks = self.hints.search(unblock_cmd, package=src)

            if unblocks and unblocks[0].version is not None and unblocks[0].version == source_u[VERSION]:
                if suite == 'unstable' or block_cmd == 'block-udeb':
                    excuse.addhtml("Ignoring %s request by %s, due to %s request by %s" %
                                   (block_cmd, blocked[block_cmd].user, unblock_cmd, unblocks[0].user))
                else:
                    excuse.addhtml("Approved by %s" % (unblocks[0].user))
            else:
                if unblocks:
                    if unblocks[0].version is None:
                        excuse.addhtml("%s request by %s ignored due to missing version" %
                                       (unblock_cmd.capitalize(), unblocks[0].user))
                    else:
                        excuse.addhtml("%s request by %s ignored due to version mismatch: %s" %
                                       (unblock_cmd.capitalize(), unblocks[0].user, unblocks[0].version))
                if suite == 'unstable' or block_cmd == 'block-udeb':
                    tooltip = "check https://release.debian.org/testing/freeze_policy.html if update is needed"
                    # redirect people to d-i RM for udeb things:
                    if block_cmd == 'block-udeb':
                        tooltip = "please contact the d-i release manager if an update is needed"
                    excuse.addhtml("Not touching package due to %s request by %s (%s)" %
                                   (block_cmd, blocked[block_cmd].user, tooltip))
                    excuse.addreason("block")
                else:
                    excuse.addhtml("NEEDS APPROVAL BY RM")
                    excuse.addreason("block")
                update_candidate = False

        # if the suite is unstable, then we have to check the urgency and the minimum days of
        # permanence in unstable before updating testing; if the source package is too young,
        # the check fails and we set update_candidate to False to block the update; consider
        # the age-days hint, if specified for the package
        policy_info = excuse.policy_info
        policy_verdict = PolicyVerdict.PASS
        for policy in self.policies:
            if suite in policy.applicable_suites:
                v = policy.apply_policy(policy_info, suite, src, source_t, source_u)
                if v.value > policy_verdict.value:
                    policy_verdict = v

        if policy_verdict.is_rejected:
            update_candidate = False

        # Joggle some things into excuses
        # - remove once the YAML is the canonical source for this information
        if 'age' in policy_info:
            age_info = policy_info['age']
            age_hint = age_info.get('age-requirement-reduced', None)
            age_min_req = age_info['age-requirement']
            if age_hint:
                new_req = age_hint['new-requirement']
                who = age_hint['changed-by']
                if new_req:
                    excuse.addhtml("Overriding age needed from %d days to %d by %s" % (
                        age_min_req, new_req, who))
                else:
                    excuse.addhtml("Too young, but urgency pushed by %s" % who)
            excuse.setdaysold(age_info['current-age'], age_min_req)

        all_binaries = self.all_binaries

        if suite in ('pu', 'tpu') and source_t:
            # o-o-d(ish) checks for (t-)p-u
            # This only makes sense if the package is actually in testing.
            for arch in self.options.architectures:
                # if the package in testing has no binaries on this
                # architecture, it can't be out-of-date
                if not any(x for x in source_t[BINARIES]
                           if x[2] == arch and all_binaries[x][ARCHITECTURE] != 'all'):
                    continue
                    
                # if the (t-)p-u package has produced any binaries on
                # this architecture then we assume it's ok. this allows for
                # uploads to (t-)p-u which intentionally drop binary
                # packages
                if any(x for x in self.binaries[suite][arch][0].values() \
                          if x[SOURCE] == src and x[SOURCEVER] == source_u[VERSION] and \
                             x[ARCHITECTURE] != 'all'):
                    continue

                if suite == 'tpu':
                    base = 'testing'
                else:
                    base = 'stable'
                text = "Not yet built on <a href=\"http://buildd.debian.org/status/logs.php?arch=%s&pkg=%s&ver=%s&suite=%s\" target=\"_blank\">%s</a> (relative to testing)" % (quote(arch), quote(src), quote(source_u[VERSION]), base, arch)

                if arch in self.options.fucked_arches:
                    text = text + " (but %s isn't keeping up, so never mind)" % (arch)
                else:
                    update_candidate = False
                    excuse.addreason("arch")
                    excuse.addreason("arch-%s" % arch)
                    excuse.addreason("build-arch")
                    excuse.addreason("build-arch-%s" % arch)

                excuse.addhtml(text)

        # at this point, we check the status of the builds on all the supported architectures
        # to catch the out-of-date ones
        pkgs = {src: ["source"]}
        for arch in self.options.architectures:
            oodbins = {}
            uptodatebins = False
            # for every binary package produced by this source in the suite for this architecture
            for pkg_id in sorted(x for x in source_u[BINARIES] if x[2] == arch):
                pkg = pkg_id[0]
                if pkg not in pkgs: pkgs[pkg] = []
                pkgs[pkg].append(arch)

                # retrieve the binary package and its source version
                binary_u = all_binaries[pkg_id]
                pkgsv = binary_u[SOURCEVER]

                # if it wasn't built by the same source, it is out-of-date
                # if there is at least one binary on this arch which is
                # up-to-date, there is a build on this arch
                if source_u[VERSION] != pkgsv:
                    if pkgsv not in oodbins:
                        oodbins[pkgsv] = []
                    oodbins[pkgsv].append(pkg)
                    continue
                else:
                    # if the binary is arch all, it doesn't count as
                    # up-to-date for this arch
                    if binary_u[ARCHITECTURE] == arch:
                        uptodatebins = True

                # if the package is architecture-dependent or the current arch is `nobreakall'
                # find unsatisfied dependencies for the binary package
                if binary_u[ARCHITECTURE] != 'all' or arch in self.options.nobreakall_arches:
                    self.excuse_unsat_deps(pkg, src, arch, suite, excuse)

            # if there are out-of-date packages, warn about them in the excuse and set update_candidate
            # to False to block the update; if the architecture where the package is out-of-date is
            # in the `fucked_arches' list, then do not block the update
            if oodbins:
                oodtxt = ""
                for v in oodbins.keys():
                    if oodtxt: oodtxt = oodtxt + "; "
                    oodtxt = oodtxt + "%s (from <a href=\"http://buildd.debian.org/status/logs.php?" \
                        "arch=%s&pkg=%s&ver=%s\" target=\"_blank\">%s</a>)" % \
                        (", ".join(sorted(oodbins[v])), quote(arch), quote(src), quote(v), v)
                if uptodatebins:
                    text = "old binaries left on <a href=\"http://buildd.debian.org/status/logs.php?" \
                        "arch=%s&pkg=%s&ver=%s\" target=\"_blank\">%s</a>: %s" % \
                        (quote(arch), quote(src), quote(source_u[VERSION]), arch, oodtxt)
                else:
                    text = "missing build on <a href=\"http://buildd.debian.org/status/logs.php?" \
                        "arch=%s&pkg=%s&ver=%s\" target=\"_blank\">%s</a>: %s" % \
                        (quote(arch), quote(src), quote(source_u[VERSION]), arch, oodtxt)

                if arch in self.options.fucked_arches:
                    text = text + " (but %s isn't keeping up, so nevermind)" % (arch)
                else:
                    if uptodatebins:
                        excuse.addreason("cruft-arch")
                        excuse.addreason("cruft-arch-%s" % arch)
                        if self.options.ignore_cruft:
                            text = text + " (but ignoring cruft, so nevermind)"
                        else:
                            update_candidate = False
                            excuse.addreason("arch")
                            excuse.addreason("arch-%s" % arch)
                    else:
                        update_candidate = False
                        excuse.addreason("arch")
                        excuse.addreason("arch-%s" % arch)
                        excuse.addreason("build-arch")
                        excuse.addreason("build-arch-%s" % arch)

                if 'age' in policy_info and policy_info['age']['current-age']:
                    excuse.addhtml(text)

        # if the source package has no binaries, set update_candidate to False to block the update
        if not source_u[BINARIES]:
            excuse.addhtml("%s has no binaries on any arch" % src)
            excuse.addreason("no-binaries")
            update_candidate = False

        # if the suite is unstable, then we have to check the release-critical bug lists before
        # updating testing; if the unstable package has RC bugs that do not apply to the testing
        # one, the check fails and we set update_candidate to False to block the update
        if suite == 'unstable':
            for pkg in pkgs:
                bugs_t = []
                bugs_u = []
                if pkg in self.bugs['testing']:
                    bugs_t.extend(self.bugs['testing'][pkg])
                if pkg in self.bugs['unstable']:
                    bugs_u.extend(self.bugs['unstable'][pkg])
                if 'source' in pkgs[pkg]:
                    spkg = "src:%s" % (pkg)
                    if spkg in self.bugs['testing']:
                        bugs_t.extend(self.bugs['testing'][spkg])
                    if spkg in self.bugs['unstable']:
                        bugs_u.extend(self.bugs['unstable'][spkg])
 
                new_bugs = sorted(set(bugs_u).difference(bugs_t))
                old_bugs = sorted(set(bugs_t).difference(bugs_u))

                excuse.setbugs(old_bugs,new_bugs)

                if len(new_bugs) > 0:
                    excuse.addhtml("%s (%s) <a href=\"http://bugs.debian.org/cgi-bin/pkgreport.cgi?" \
                        "which=pkg&data=%s&sev-inc=critical&sev-inc=grave&sev-inc=serious\" " \
                        "target=\"_blank\">has new bugs</a>!" % (pkg, ", ".join(pkgs[pkg]), quote(pkg)))
                    excuse.addhtml("Updating %s introduces new bugs: %s" % (pkg, ", ".join(
                        ["<a href=\"http://bugs.debian.org/%s\">#%s</a>" % (quote(a), a) for a in new_bugs])))
                    update_candidate = False
                    excuse.addreason("buggy")

                if len(old_bugs) > 0:
                    excuse.addhtml("Updating %s fixes old bugs: %s" % (pkg, ", ".join(
                        ["<a href=\"http://bugs.debian.org/%s\">#%s</a>" % (quote(a), a) for a in old_bugs])))
                if len(old_bugs) > len(new_bugs) and len(new_bugs) > 0:
                    excuse.addhtml("%s introduces new bugs, so still ignored (even "
                        "though it fixes more than it introduces, whine at debian-release)" % pkg)

        # check if there is a `force' hint for this package, which allows it to go in even if it is not updateable
        forces = [x for x in self.hints.search('force', package=src) if source_u[VERSION] == x.version]
        if forces:
            excuse.dontinvalidate = True
        if not update_candidate and forces:
            excuse.addhtml("Should ignore, but forced by %s" % (forces[0].user))
            excuse.force()
            update_candidate = True

        # if the package can be updated, it is a valid candidate
        if update_candidate:
            excuse.is_valid = True
        # else it won't be considered
        else:
            # TODO
            excuse.addhtml("Not considered")

        self.excuses[excuse.name] = excuse
        return update_candidate

    def reversed_exc_deps(self):
        """Reverse the excuses dependencies

        This method returns a dictionary where the keys are the package names
        and the values are the excuse names which depend on it.
        """
        res = defaultdict(list)
        for exc in self.excuses.values():
            for d in exc.deps:
                res[d].append(exc.name)
        return res

    def invalidate_excuses(self, valid, invalid):
        """Invalidate impossible excuses

        This method invalidates the impossible excuses, which depend
        on invalid excuses. The two parameters contains the list of
        `valid' and `invalid' excuses.
        """
        excuses = self.excuses

        # build the reverse dependencies
        revdeps = self.reversed_exc_deps()

        # loop on the invalid excuses
        i = 0
        while i < len(invalid):
            # if there is no reverse dependency, skip the item
            if invalid[i] not in revdeps:
                i += 1
                continue
            # if the dependency can be satisfied by a testing-proposed-updates excuse, skip the item
            if (invalid[i] + "_tpu") in valid:
                i += 1
                continue
            # loop on the reverse dependencies
            for x in revdeps[invalid[i]]:
                # if the item is valid and it is marked as `dontinvalidate', skip the item
                if x in valid and excuses[x].dontinvalidate:
                    continue

                # otherwise, invalidate the dependency and mark as invalidated and
                # remove the depending excuses
                excuses[x].invalidate_dep(invalid[i])
                if x in valid:
                    p = valid.index(x)
                    invalid.append(valid.pop(p))
                    excuses[x].addhtml("Invalidated by dependency")
                    excuses[x].addhtml("Not considered")
                    excuses[x].addreason("depends")
                    excuses[x].is_valid = False
            i = i + 1
 
    def write_excuses(self):
        """Produce and write the update excuses

        This method handles the update excuses generation: the packages are
        looked at to determine whether they are valid candidates. For the details
        of this procedure, please refer to the module docstring.
        """

        self.log("Update Excuses generation started", type="I")

        # list of local methods and variables (for better performance)
        sources = self.sources
        architectures = self.options.architectures
        should_remove_source = self.should_remove_source
        should_upgrade_srcarch = self.should_upgrade_srcarch
        should_upgrade_src = self.should_upgrade_src

        # this list will contain the packages which are valid candidates;
        # if a package is going to be removed, it will have a "-" prefix
        upgrade_me = []

        excuses = self.excuses = {}

        # for every source package in testing, check if it should be removed
        for pkg in sources['testing']:
            if should_remove_source(pkg):
                upgrade_me.append("-" + pkg)

        # for every source package in unstable check if it should be upgraded
        for pkg in sources['unstable']:
            if sources['unstable'][pkg][FAKESRC]: continue
            # if the source package is already present in testing,
            # check if it should be upgraded for every binary package
            if pkg in sources['testing'] and not sources['testing'][pkg][FAKESRC]:
                for arch in architectures:
                    if should_upgrade_srcarch(pkg, arch, 'unstable'):
                        upgrade_me.append("%s/%s" % (pkg, arch))

            # check if the source package should be upgraded
            if should_upgrade_src(pkg, 'unstable'):
                upgrade_me.append(pkg)

        # for every source package in *-proposed-updates, check if it should be upgraded
        for suite in ['pu', 'tpu']:
            for pkg in sources[suite]:
                # if the source package is already present in testing,
                # check if it should be upgraded for every binary package
                if pkg in sources['testing']:
                    for arch in architectures:
                        if should_upgrade_srcarch(pkg, arch, suite):
                            upgrade_me.append("%s/%s_%s" % (pkg, arch, suite))

                # check if the source package should be upgraded
                if should_upgrade_src(pkg, suite):
                    upgrade_me.append("%s_%s" % (pkg, suite))

        # process the `remove' hints, if the given package is not yet in upgrade_me
        for item in self.hints['remove']:
            src = item.package
            if src in upgrade_me: continue
            if ("-"+src) in upgrade_me: continue
            if src not in sources['testing']: continue

            # check if the version specified in the hint is the same as the considered package
            tsrcv = sources['testing'][src][VERSION]
            if tsrcv != item.version:
                continue

            # add the removal of the package to upgrade_me and build a new excuse
            upgrade_me.append("-%s" % (src))
            excuse = Excuse("-%s" % (src))
            excuse.set_vers(tsrcv, None)
            excuse.addhtml("Removal request by %s" % (item.user))
            excuse.addhtml("Package is broken, will try to remove")
            excuse.addreason("remove")
            excuses[excuse.name] = excuse

        # extract the not considered packages, which are in the excuses but not in upgrade_me
        unconsidered = [ename for ename in excuses if ename not in upgrade_me]

        # invalidate impossible excuses
        for e in excuses.values():
            # parts[0] == package name
            # parts[1] == optional architecture
            parts = e.name.split('/')
            for d in e.deps:
                ok = False
                # source -> source dependency; both packages must have
                # valid excuses
                if d in upgrade_me or d in unconsidered:
                    ok = True
                # if the excuse is for a binNMU, also consider d/$arch as a
                # valid excuse
                elif len(parts) == 2:
                    bd = '%s/%s' % (d, parts[1])
                    if bd in upgrade_me or bd in unconsidered:
                        ok = True
                # if the excuse is for a source package, check each of the
                # architectures on which the excuse lists a dependency on d,
                # and consider the excuse valid if it is possible on each
                # architecture
                else:
                    arch_ok = True
                    for arch in e.deps[d]:
                        bd = '%s/%s' % (d, arch)
                        if bd not in upgrade_me and bd not in unconsidered:
                            arch_ok = False
                            break
                    if arch_ok:
                        ok = True
                if not ok:
                    e.addhtml("Impossible dependency: %s -> %s" % (e.name, d))
                    e.addreason("depends")
        self.invalidate_excuses(upgrade_me, unconsidered)

        # sort the list of candidates
        self.upgrade_me = sorted( make_migrationitem(x, self.sources) for x in upgrade_me )

        # write excuses to the output file
        if not self.options.dry_run:
            self.log("> Writing Excuses to %s" % self.options.excuses_output, type="I")
            sorted_excuses = sorted(excuses.values(), key=lambda x: x.sortkey())
            write_excuses(sorted_excuses, self.options.excuses_output,
                          output_format="legacy-html")
            if hasattr(self.options, 'excuses_yaml_output'):
                self.log("> Writing YAML Excuses to %s" % self.options.excuses_yaml_output, type="I")
                write_excuses(sorted_excuses, self.options.excuses_yaml_output,
                              output_format="yaml")

        self.log("Update Excuses generation completed", type="I")

    # Upgrade run
    # -----------


    def get_nuninst(self, requested_arch=None, build=False):
        """Return the uninstallability statistic for all the architectures

        To calculate the uninstallability counters, the method checks the
        installability of all the packages for all the architectures, and
        tracks dependencies in a recursive way. The architecture
        independent packages are checked only for the `nobreakall`
        architectures.

        It returns a dictionary with the architectures as keys and the list
        of uninstallable packages as values.

        NB: If build is False, requested_arch is ignored.
        """
        # if we are not asked to build the nuninst, read it from the cache
        if not build:
            return read_nuninst(self.options.noninst_status,
                                self.options.architectures)

        nuninst = {}

        # local copies for better performance
        binaries = self.binaries['testing']
        inst_tester = self._inst_tester

        # for all the architectures
        for arch in self.options.architectures:
            if requested_arch and arch != requested_arch: continue
            # if it is in the nobreakall ones, check arch-independent packages too
            check_archall = arch in self.options.nobreakall_arches

            # check all the packages for this architecture
            nuninst[arch] = set()
            for pkg_name in binaries[arch][0]:
                pkgdata = binaries[arch][0][pkg_name]
                pkg_id = (pkg_name, pkgdata[VERSION], arch)
                r = inst_tester.is_installable(pkg_id)
                if not r:
                    nuninst[arch].add(pkg_name)

            # if they are not required, remove architecture-independent packages
            nuninst[arch + "+all"] = nuninst[arch].copy()
            if not check_archall:
                for pkg in nuninst[arch + "+all"]:
                    bpkg = binaries[arch][0][pkg]
                    if bpkg[ARCHITECTURE] == 'all':
                        nuninst[arch].remove(pkg)

        # return the dictionary with the results
        return nuninst

    def eval_nuninst(self, nuninst, original=None):
        """Return a string which represents the uninstallability counters

        This method returns a string which represents the uninstallability
        counters reading the uninstallability statistics `nuninst` and, if
        present, merging the results with the `original` one.

        An example of the output string is:
        1+2: i-0:a-0:a-0:h-0:i-1:m-0:m-0:p-0:a-0:m-0:s-2:s-0

        where the first part is the number of broken packages in non-break
        architectures + the total number of broken packages for all the
        architectures.
        """
        res = []
        total = 0
        totalbreak = 0
        for arch in self.options.architectures:
            if arch in nuninst:
                n = len(nuninst[arch])
            elif original and arch in original:
                n = len(original[arch])
            else: continue
            if arch in self.options.break_arches:
                totalbreak = totalbreak + n
            else:
                total = total + n
            res.append("%s-%d" % (arch[0], n))
        return "%d+%d: %s" % (total, totalbreak, ":".join(res))


    def _compute_groups(self, source_name, suite, migration_architecture,
                        is_removal,
                        allow_smooth_updates=True,
                        removals=frozenset()):
        """Compute the groups of binaries being migrated by item

        This method will compute the binaries that will be added,
        replaced in testing and which of them are smooth updatable.

        Parameters:
        * "source_name" is the name of the source package, whose
          binaries are migrating.
        * "suite" is the suite from which the binaries are migrating.
          [Same as item.suite, where available]
        * "migration_architecture" is the architecture determines
          architecture of the migrating binaries (can be "source" for
          a "source"-migration, meaning all binaries regardless of
          architecture).  [Same as item.architecture, where available]
        * "is_removal" is a boolean determining if this is a removal
           or not [Same as item.is_removal, where available]
        * "allow_smooth_updates" is a boolean determing whether smooth-
          updates are permitted in this migration.  When set to False,
          the "smoothbins" return value will always be the empty set.
          Any value that would have been there will now be in "rms"
          instead. (defaults: True)
        * "removals" is a set of binaries that is assumed to be
          removed at the same time as this migration (e.g. in the same
          "easy"-hint).  This may affect what if some binaries are
          smooth updated or not. (defaults: empty-set)
          - Binaries must be given as ("package-name", "version",
            "architecture") tuples.

        Returns a tuple (adds, rms, smoothbins).  "adds" is a set of
        binaries that will updated in or appear after the migration.
        "rms" is a set of binaries that are not smooth-updatable (or
        binaries that could be, but there is no reason to let them be
        smooth updated).  "smoothbins" is set of binaries that are to
        be smooth-updated.

        Each "binary" in "adds", "rms" and "smoothbins" will be a
        tuple of ("package-name", "version", "architecture") and are
        thus tuples suitable for passing on to the
        InstallabilityTester.


        Unlike doop_source, this will not modify any data structure.
        """
        # local copies for better performances
        sources = self.sources
        binaries_t = self.binaries['testing']
        inst_tester = self._inst_tester

        adds = set()
        rms = set()
        smoothbins = set()

        # remove all binary packages (if the source already exists)
        if migration_architecture == 'source' or not is_removal:
            if source_name in sources['testing']:
                source_data = sources['testing'][source_name]

                bins = []
                check = set()
                # remove all the binaries

                # first, build a list of eligible binaries
                for pkg_id in source_data[BINARIES]:
                    binary, _, parch = pkg_id
                    if (migration_architecture != 'source'
                        and parch != migration_architecture):
                        continue

                    # Work around #815995
                    if migration_architecture == 'source' and is_removal and binary not in binaries_t[parch][0]:
                        continue

                    # Do not include hijacked binaries
                    if binaries_t[parch][0][binary][SOURCE] != source_name:
                        continue
                    bins.append(pkg_id)

                for pkg_id in bins:
                    binary, _, parch = pkg_id
                    # if a smooth update is possible for the package, skip it
                    if allow_smooth_updates and suite == 'unstable' and \
                       binary not in self.binaries[suite][parch][0] and \
                       ('ALL' in self.options.smooth_updates or \
                        binaries_t[parch][0][binary][SECTION] in self.options.smooth_updates):

                        # if the package has reverse-dependencies which are
                        # built from other sources, it's a valid candidate for
                        # a smooth update.  if not, it may still be a valid
                        # candidate if one if its r-deps is itself a candidate,
                        # so note it for checking later
                        rdeps = set(inst_tester.reverse_dependencies_of(pkg_id))
                        # We ignore all binaries listed in "removals" as we
                        # assume they will leave at the same time as the
                        # given package.
                        rdeps.difference_update(removals, bins)

                        smooth_update_it = False
                        if inst_tester.any_of_these_are_in_testing(rdeps):
                            combined = set(smoothbins)
                            combined.add(pkg_id)
                            for rdep in rdeps:
                                for dep_clause in inst_tester.dependencies_of(rdep):
                                    if dep_clause <= combined:
                                        smooth_update_it = True
                                        break

                        if smooth_update_it:
                            smoothbins = combined
                        else:
                            check.add(pkg_id)

                # check whether we should perform a smooth update for
                # packages which are candidates but do not have r-deps
                # outside of the current source
                while 1:
                    found_any = False
                    for pkg_id in check:
                        rdeps = inst_tester.reverse_dependencies_of(pkg_id)
                        if not rdeps.isdisjoint(smoothbins):
                            smoothbins.add(pkg_id)
                            found_any = True
                    if not found_any:
                        break
                    check = [x for x in check if x not in smoothbins]

                # remove all the binaries which aren't being smooth updated
                for pkg_id in (pkg_id for pkg_id in bins if pkg_id not in smoothbins):
                    binary, version, parch = pkg_id
                    # if this is a binary migration from *pu, only the arch:any
                    # packages will be present. ideally dak would also populate
                    # the arch-indep packages, but as that's not the case we
                    # must keep them around; they will not be re-added by the
                    # migration so will end up missing from testing
                    if migration_architecture != 'source' and \
                         suite != 'unstable' and \
                         binaries_t[parch][0][binary][ARCHITECTURE] == 'all':
                        continue
                    else:
                        rms.add(pkg_id)

        # single binary removal; used for clearing up after smooth
        # updates but not supported as a manual hint
        elif source_name in binaries_t[migration_architecture][0]:
            version = binaries_t[migration_architecture][0][source_name][VERSION]
            rms.add((source_name, version, migration_architecture))

        # add the new binary packages (if we are not removing)
        if not is_removal:
            source_data = sources[suite][source_name]
            for pkg_id in source_data[BINARIES]:
                binary, _, parch = pkg_id
                if migration_architecture not in ['source', parch]:
                    continue

                if self.binaries[suite][parch][0][binary][SOURCE] != source_name:
                    # This binary package has been hijacked by some other source.
                    # So don't add it as part of this update.
                    #
                    # Also, if this isn't a source update, don't remove
                    # the package that's been hijacked if it's present.
                    if migration_architecture != 'source':
                        for rm_b, rm_v, rm_p in list(rms):
                            if (rm_b, rm_p) == (binary, parch):
                                rms.remove((rm_b, rm_v, rm_p))
                    continue

                # Don't add the binary if it is old cruft that is no longer in testing
                if (parch not in self.options.fucked_arches and
                    source_data[VERSION] != self.binaries[suite][parch][0][binary][SOURCEVER] and
                    binary not in binaries_t[parch][0]):
                    continue

                adds.add(pkg_id)

        return (adds, rms, smoothbins)

    def doop_source(self, item, hint_undo=None, removals=frozenset()):
        """Apply a change to the testing distribution as requested by `pkg`

        An optional list of undo actions related to packages processed earlier
        in a hint may be passed in `hint_undo`.

        An optional set of binaries may be passed in "removals". Binaries listed
        in this set will be assumed to be removed at the same time as the "item"
        will migrate.  This may change what binaries will be smooth-updated.
        - Binaries in this set must be ("package-name", "version", "architecture")
          tuples.

        This method applies the changes required by the action `item` tracking
        them so it will be possible to revert them.

        The method returns a tuple containing a set of packages
        affected by the change (as (name, arch)-tuples) and the
        dictionary undo which can be used to rollback the changes.
        """
        undo = {'binaries': {}, 'sources': {}, 'virtual': {}, 'nvirtual': []}

        affected = set()

        # local copies for better performance
        sources = self.sources
        packages_t = self.binaries['testing']
        inst_tester = self._inst_tester
        eqv_set = set()

        updates, rms, _ = self._compute_groups(item.package,
                                               item.suite,
                                               item.architecture,
                                               item.is_removal,
                                               removals=removals)

        # remove all binary packages (if the source already exists)
        if item.architecture == 'source' or not item.is_removal:
            if item.package in sources['testing']:
                source = sources['testing'][item.package]


                eqv_table = {}

                for binary, version, parch in rms:
                    key = (binary, parch)
                    eqv_table[key] = version

                for p1 in updates:
                    binary, _, parch = p1
                    key = (binary, parch)
                    old_version = eqv_table.get(key)
                    if old_version is not None:
                        p2 = (binary, old_version, parch)
                        if inst_tester.are_equivalent(p1, p2):
                            eqv_set.add(key)

                # remove all the binaries which aren't being smooth updated
                for rm_pkg_id in rms:
                    binary, version, parch = rm_pkg_id
                    p = (binary, parch)
                    binaries_t_a, provides_t_a = packages_t[parch]
                    pkey = (binary, parch)

                    pkg_data = binaries_t_a[binary]
                    # save the old binary for undo
                    undo['binaries'][p] = rm_pkg_id
                    if pkey not in eqv_set:
                        # all the reverse dependencies are affected by
                        # the change
                        affected.update(inst_tester.reverse_dependencies_of(rm_pkg_id))
                        affected.update(inst_tester.negative_dependencies_of(rm_pkg_id))

                    # remove the provided virtual packages
                    for j, prov_version, _ in pkg_data[PROVIDES]:
                        key = (j, parch)
                        if key not in undo['virtual']:
                            undo['virtual'][key] = provides_t_a[j].copy()
                        provides_t_a[j].remove((binary, prov_version))
                        if not provides_t_a[j]:
                            del provides_t_a[j]
                    # finally, remove the binary package
                    del binaries_t_a[binary]
                    inst_tester.remove_testing_binary(rm_pkg_id)
                # remove the source package
                if item.architecture == 'source':
                    undo['sources'][item.package] = source
                    del sources['testing'][item.package]
            else:
                # the package didn't exist, so we mark it as to-be-removed in case of undo
                undo['sources']['-' + item.package] = True

        # single binary removal; used for clearing up after smooth
        # updates but not supported as a manual hint
        elif item.package in packages_t[item.architecture][0]:
            binaries_t_a = packages_t[item.architecture][0]
            version = binaries_t_a[item.package][VERSION]
            pkg_id = (item.package, version, item.architecture)
            undo['binaries'][(item.package, item.architecture)] = pkg_id
            affected.update(inst_tester.reverse_dependencies_of(pkg_id))
            del binaries_t_a[item.package]
            inst_tester.remove_testing_binary(pkg_id)

        # add the new binary packages (if we are not removing)
        if not item.is_removal:
            packages_s = self.binaries[item.suite]

            for updated_pkg_id in updates:
                binary, new_version, parch = updated_pkg_id
                key = (binary, parch)
                binaries_t_a, provides_t_a = packages_t[parch]
                equivalent_replacement = key in eqv_set

                # obviously, added/modified packages are affected
                if not equivalent_replacement and updated_pkg_id not in affected:
                    affected.add(updated_pkg_id)
                # if the binary already exists in testing, it is currently
                # built by another source package. we therefore remove the
                # version built by the other source package, after marking
                # all of its reverse dependencies as affected
                if binary in binaries_t_a:
                    old_pkg_data = binaries_t_a[binary]
                    old_version = old_pkg_data[VERSION]
                    old_pkg_id = (binary, old_version, parch)
                    # save the old binary package
                    undo['binaries'][key] = old_pkg_id
                    if not equivalent_replacement:
                        # all the reverse conflicts
                        affected.update(inst_tester.reverse_dependencies_of(old_pkg_id))
                        affected.update(inst_tester.negative_dependencies_of(old_pkg_id))
                    inst_tester.remove_testing_binary(old_pkg_id)
                elif hint_undo:
                    # the binary isn't in testing, but it may have been at
                    # the start of the current hint and have been removed
                    # by an earlier migration. if that's the case then we
                    # will have a record of the older instance of the binary
                    # in the undo information. we can use that to ensure
                    # that the reverse dependencies of the older binary
                    # package are also checked.
                    # reverse dependencies built from this source can be
                    # ignored as their reverse trees are already handled
                    # by this function
                    for (tundo, tpkg) in hint_undo:
                        if key in tundo['binaries']:
                            tpkg_id = tundo['binaries'][key]
                            affected.update(inst_tester.reverse_dependencies_of(tpkg_id))

                # add/update the binary package from the source suite
                new_pkg_data = packages_s[parch][0][binary]
                binaries_t_a[binary] = new_pkg_data
                inst_tester.add_testing_binary(updated_pkg_id)
                # register new provided packages
                for j, prov_version, _ in new_pkg_data[PROVIDES]:
                    key = (j, parch)
                    if j not in provides_t_a:
                        undo['nvirtual'].append(key)
                        provides_t_a[j] = set()
                    elif key not in undo['virtual']:
                        undo['virtual'][key] = provides_t_a[j].copy()
                    provides_t_a[j].add((binary, prov_version))
                if not equivalent_replacement:
                    # all the reverse dependencies are affected by the change
                    affected.add(updated_pkg_id)
                    affected.update(inst_tester.negative_dependencies_of(updated_pkg_id))

            # add/update the source package
            if item.architecture == 'source':
                sources['testing'][item.package] = sources[item.suite][item.package]

        # Also include the transitive rdeps of the packages found so far
        compute_reverse_tree(inst_tester, affected)
        # return the package name, the suite, the list of affected packages and the undo dictionary
        return (affected, undo)

    def try_migration(self, actions, nuninst_now, lundo=None, automatic_revert=True):
        is_accepted = True
        affected_architectures = set()
        item = actions
        packages_t = self.binaries['testing']

        nobreakall_arches = self.options.nobreakall_arches
        new_arches = self.options.new_arches
        break_arches = self.options.break_arches
        arch = None

        if len(actions) == 1:
            item = actions[0]
            # apply the changes
            affected, undo = self.doop_source(item, hint_undo=lundo)
            undo_list = [(undo, item)]
            if item.architecture == 'source':
                affected_architectures = set(self.options.architectures)
            else:
                affected_architectures.add(item.architecture)
        else:
            undo_list = []
            removals = set()
            affected = set()
            for item in actions:
                _, rms, _ = self._compute_groups(item.package, item.suite,
                                                 item.architecture,
                                                 item.is_removal,
                                                 allow_smooth_updates=False)
                removals.update(rms)
                affected_architectures.add(item.architecture)

            if 'source' in affected_architectures:
                affected_architectures = set(self.options.architectures)

            for item in actions:
                item_affected, undo = self.doop_source(item,
                                                       hint_undo=lundo,
                                                       removals=removals)
                affected.update(item_affected)
                undo_list.append((undo, item))

        # Copy nuninst_comp - we have to deep clone affected
        # architectures.

        # NB: We do this *after* updating testing as we have to filter out
        # removed binaries.  Otherwise, uninstallable binaries that were
        # removed by the item would still be counted.

        nuninst_after = clone_nuninst(nuninst_now, packages_t, affected_architectures)

        # check the affected packages on all the architectures
        for arch in affected_architectures:
            check_archall = arch in nobreakall_arches

            check_installability(self._inst_tester, packages_t, arch, affected, check_archall, nuninst_after)

            # if the uninstallability counter is worse than before, break the loop
            if automatic_revert and len(nuninst_after[arch]) > len(nuninst_now[arch]):
                # ... except for a few special cases
                if (item.architecture != 'source' and arch not in new_arches) or \
                   (arch not in break_arches):
                    is_accepted = False
                    break

        # check if the action improved the uninstallability counters
        if not is_accepted and automatic_revert:
            undo_copy = list(reversed(undo_list))
            undo_changes(undo_copy, self._inst_tester, self.sources, self.binaries, self.all_binaries)

        return (is_accepted, nuninst_after, undo_list, arch)

    def iter_packages(self, packages, selected, nuninst=None, lundo=None):
        """Iter on the list of actions and apply them one-by-one

        This method applies the changes from `packages` to testing, checking the uninstallability
        counters for every action performed. If the action does not improve them, it is reverted.
        The method returns the new uninstallability counters and the remaining actions if the
        final result is successful, otherwise (None, []).
        """
        group_info = {}
        maybe_rescheduled = packages
        changed = True

        for y in sorted((y for y in packages), key=attrgetter('uvname')):
            updates, rms, _ = self._compute_groups(y.package, y.suite, y.architecture, y.is_removal)
            result = (y, frozenset(updates), frozenset(rms))
            group_info[y] = result

        if selected is None:
            selected = []
        if nuninst:
            nuninst_orig = nuninst
        else:
            nuninst_orig = self.nuninst_orig

        nuninst_last_accepted = nuninst_orig

        self.output_write("recur: [] %s %d/0\n" % (",".join(x.uvname for x in selected), len(packages)))
        while changed:
            changed = False
            groups = {group_info[x] for x in maybe_rescheduled}
            worklist = self._inst_tester.solve_groups(groups)
            maybe_rescheduled = []

            worklist.reverse()

            while worklist:
                comp = worklist.pop()
                comp_name = ' '.join(item.uvname for item in comp)
                self.output_write("trying: %s\n" % comp_name)
                accepted, nuninst_after, comp_undo, failed_arch = self.try_migration(comp, nuninst_last_accepted, lundo)
                if accepted:
                    selected.extend(comp)
                    changed = True
                    if lundo is not None:
                        lundo.extend(comp_undo)
                    self.output_write("accepted: %s\n" % comp_name)
                    self.output_write("   ori: %s\n" % (self.eval_nuninst(nuninst_orig)))
                    self.output_write("   pre: %s\n" % (self.eval_nuninst(nuninst_last_accepted)))
                    self.output_write("   now: %s\n" % (self.eval_nuninst(nuninst_after)))
                    if len(selected) <= 20:
                        self.output_write("   all: %s\n" % (" ".join(x.uvname for x in selected)))
                    else:
                        self.output_write("  most: (%d) .. %s\n" % (len(selected), " ".join(x.uvname for x in selected[-20:])))
                    nuninst_last_accepted = nuninst_after
                else:
                    broken = sorted(b for b in nuninst_after[failed_arch]
                                    if b not in nuninst_last_accepted[failed_arch])
                    compare_nuninst = None
                    if any(item for item in comp if item.architecture != 'source'):
                        compare_nuninst = nuninst_last_accepted
                    # NB: try_migration already reverted this for us, so just print the results and move on
                    self.output_write("skipped: %s (%d, %d)\n" % (comp_name, len(maybe_rescheduled), len(worklist)))
                    self.output_write("    got: %s\n" % (self.eval_nuninst(nuninst_after, compare_nuninst)))
                    self.output_write("    * %s: %s\n" % (failed_arch, ", ".join(broken)))

                    if len(comp) > 1:
                        self.output_write("    - splitting the component into single items and retrying them\n")
                        worklist.extend([item] for item in comp)
                    else:
                        maybe_rescheduled.append(comp[0])

        self.output_write(" finish: [%s]\n" % ",".join( x.uvname for x in selected ))
        self.output_write("endloop: %s\n" % (self.eval_nuninst(self.nuninst_orig)))
        self.output_write("    now: %s\n" % (self.eval_nuninst(nuninst_last_accepted)))
        self.output_write(eval_uninst(self.options.architectures,
                                      newly_uninst(self.nuninst_orig, nuninst_last_accepted)))
        self.output_write("\n")

        return (nuninst_last_accepted, maybe_rescheduled)


    def do_all(self, hinttype=None, init=None, actions=None):
        """Testing update runner

        This method tries to update testing checking the uninstallability
        counters before and after the actions to decide if the update was
        successful or not.
        """
        selected = []
        if actions:
            upgrade_me = actions[:]
        else:
            upgrade_me = self.upgrade_me[:]
        nuninst_start = self.nuninst_orig

        # these are special parameters for hints processing
        force = False
        recurse = True
        lundo = None
        nuninst_end = None
        better = True
        extra = []

        if hinttype == "easy" or hinttype == "force-hint":
            force = hinttype == "force-hint"
            recurse = False

        # if we have a list of initial packages, check them
        if init:
            if not force:
                lundo = []
            for x in init:
                if x not in upgrade_me:
                    self.output_write("failed: %s is not a valid candidate (or it already migrated)\n" % (x.uvname))
                    return None
                selected.append(x)
                upgrade_me.remove(x)
        
        self.output_write("start: %s\n" % self.eval_nuninst(nuninst_start))
        if not force:
            self.output_write("orig: %s\n" % self.eval_nuninst(nuninst_start))


        if init:
            # init => a hint (e.g. "easy") - so do the hint run
            (better, nuninst_end, undo_list, _) = self.try_migration(selected,
                                                                     self.nuninst_orig,
                                                                     lundo=lundo,
                                                                     automatic_revert=False)
            if force:
                # Force implies "unconditionally better"
                better = True

            if lundo is not None:
                lundo.extend(undo_list)

            if recurse:
                # Ensure upgrade_me and selected do not overlap, if we
                # follow-up with a recurse ("hint"-hint).
                upgrade_me = [x for x in upgrade_me if x not in set(selected)]

        if recurse:
            # Either the main run or the recursive run of a "hint"-hint.
            (nuninst_end, extra) = self.iter_packages(upgrade_me, selected, nuninst=nuninst_end, lundo=lundo)

        nuninst_end_str = self.eval_nuninst(nuninst_end)

        if not recurse:
            # easy or force-hint
            if force:
                self.output_write("orig: %s\n" %  nuninst_end_str)
            self.output_write("easy: %s\n" %  nuninst_end_str)

            if not force:
                self.output_write(eval_uninst(self.options.architectures,
                                              newly_uninst(nuninst_start, nuninst_end)) + "\n")

        if not force:
            break_arches = set(self.options.break_arches)
            if all(x.architecture in break_arches for x in selected):
                # If we only migrated items from break-arches, then we
                # do not allow any regressions on these architectures.
                # This usually only happens with hints
                break_arches = set()
            better = is_nuninst_asgood_generous(self.options.architectures,
                                                self.nuninst_orig,
                                                nuninst_end,
                                                break_arches)

        if better:
            # Result accepted either by force or by being better than the original result.
            if recurse:
                self.output_write("Apparently successful\n")
            self.output_write("final: %s\n" % ",".join(sorted( x.uvname for x in selected )))
            self.output_write("start: %s\n" % self.eval_nuninst(nuninst_start))
            if not force:
                self.output_write(" orig: %s\n" % self.eval_nuninst(self.nuninst_orig))
            else:
                self.output_write(" orig: %s\n" % nuninst_end_str)
            self.output_write("  end: %s\n" % nuninst_end_str)
            if force:
                self.output_write("force breaks:\n")
                self.output_write(eval_uninst(self.options.architectures,
                                              newly_uninst(nuninst_start, nuninst_end)) + "\n")
            self.output_write("SUCCESS (%d/%d)\n" % (len(actions or self.upgrade_me), len(extra)))
            self.nuninst_orig = nuninst_end
            self.all_selected += selected
            if not actions:
                if recurse:
                    self.upgrade_me = extra
                else:
                    self.upgrade_me = [x for x in self.upgrade_me if x not in set(selected)]
        else:
            self.output_write("FAILED\n")
            if not lundo: return
            lundo.reverse()

            undo_changes(lundo, self._inst_tester, self.sources, self.binaries, self.all_binaries)


    def assert_nuninst_is_correct(self):
        self.log("> Update complete - Verifying non-installability counters", type="I")

        cached_nuninst = self.nuninst_orig
        self._inst_tester.compute_testing_installability()
        computed_nuninst = self.get_nuninst(build=True)
        if cached_nuninst != computed_nuninst:
            self.log("==================== NUNINST OUT OF SYNC =========================", type="E")
            for arch in self.options.architectures:
                expected_nuninst = set(cached_nuninst[arch])
                actual_nuninst = set(computed_nuninst[arch])
                false_negatives = actual_nuninst - expected_nuninst
                false_positives = expected_nuninst - actual_nuninst
                if false_negatives:
                    self.log(" %s - unnoticed nuninst: %s" % (arch, str(false_negatives)), type="E")
                if false_positives:
                    self.log(" %s - invalid nuninst: %s" % (arch, str(false_positives)), type="E")
                self.log(" %s - actual nuninst: %s" % (arch, str(actual_nuninst)), type="I")
                self.log("==================== NUNINST OUT OF SYNC =========================", type="E")
            raise AssertionError("NUNINST OUT OF SYNC")

        self.log("> All non-installability counters are ok", type="I")


    def upgrade_testing(self):
        """Upgrade testing using the unstable packages

        This method tries to upgrade testing using the packages from unstable.
        Before running the do_all method, it tries the easy and force-hint
        commands.
        """

        self.log("Starting the upgrade test", type="I")
        self.output_write("Generated on: %s\n" % (time.strftime("%Y.%m.%d %H:%M:%S %z", time.gmtime(time.time()))))
        self.output_write("Arch order is: %s\n" % ", ".join(self.options.architectures))

        self.log("> Calculating current uninstallability counters", type="I")
        self.nuninst_orig = self.get_nuninst()
        # nuninst_orig may get updated during the upgrade process
        self.nuninst_orig_save = self.get_nuninst()

        if not self.options.actions:
            # process `easy' hints
            for x in self.hints['easy']:
                self.do_hint("easy", x.user, x.packages)

            # process `force-hint' hints
            for x in self.hints["force-hint"]:
                self.do_hint("force-hint", x.user, x.packages)

        # run the first round of the upgrade
        # - do separate runs for break arches
        allpackages = []
        normpackages = self.upgrade_me[:]
        archpackages = {}
        for a in self.options.break_arches:
            archpackages[a] = [p for p in normpackages if p.architecture == a]
            normpackages = [p for p in normpackages if p not in archpackages[a]]
        self.upgrade_me = normpackages
        self.output_write("info: main run\n")
        self.do_all()
        allpackages += self.upgrade_me
        for a in self.options.break_arches:
            backup = self.options.break_arches
            self.options.break_arches = " ".join(x for x in self.options.break_arches if x != a)
            self.upgrade_me = archpackages[a]
            self.output_write("info: broken arch run for %s\n" % (a))
            self.do_all()
            allpackages += self.upgrade_me
            self.options.break_arches = backup
        self.upgrade_me = allpackages

        if self.options.actions:
            self.printuninstchange()
            return

        # process `hint' hints
        hintcnt = 0
        for x in self.hints["hint"][:50]:
            if hintcnt > 50:
                self.output_write("Skipping remaining hints...")
                break
            if self.do_hint("hint", x.user, x.packages):
                hintcnt += 1

        # run the auto hinter
        self.auto_hinter()

        # obsolete source packages
        # a package is obsolete if none of the binary packages in testing
        # are built by it
        self.log("> Removing obsolete source packages from testing", type="I")
        # local copies for performance
        sources = self.sources['testing']
        binaries = self.binaries['testing']
        used = set(binaries[arch][0][binary][SOURCE]
                     for arch in binaries
                     for binary in binaries[arch][0]
                  )
        removals = [ MigrationItem("-%s/%s" % (source, sources[source][VERSION]))
                     for source in sources if source not in used
                   ]
        if len(removals) > 0:
            self.output_write("Removing obsolete source packages from testing (%d):\n" % (len(removals)))
            self.do_all(actions=removals)

        # smooth updates
        removals = old_libraries(self.sources, self.binaries, self.options.fucked_arches)
        if self.options.smooth_updates:
            self.log("> Removing old packages left in testing from smooth updates", type="I")
            if removals:
                self.output_write("Removing packages left in testing for smooth updates (%d):\n%s" % \
                    (len(removals), old_libraries_format(removals)))
                self.do_all(actions=removals)
                removals = old_libraries(self.sources, self.binaries, self.options.fucked_arches)
        else:
            self.log("> Not removing old packages left in testing from smooth updates (smooth-updates disabled)",
                     type="I")

        self.output_write("List of old libraries in testing (%d):\n%s" % \
             (len(removals), old_libraries_format(removals)))

        self.assert_nuninst_is_correct()

        # output files
        if not self.options.dry_run:
            # re-write control files
            if self.options.control_files:
                self.log("Writing new testing control files to %s" %
                           self.options.testing)
                write_controlfiles(self.sources, self.binaries,
                                   'testing', self.options.testing)

            for policy in self.policies:
                policy.save_state(self)

            # write HeidiResult
            self.log("Writing Heidi results to %s" % self.options.heidi_output)
            write_heidi(self.options.heidi_output, self.sources["testing"],
                        self.binaries["testing"])

            self.log("Writing delta to %s" % self.options.heidi_delta_output)
            write_heidi_delta(self.options.heidi_delta_output,
                              self.all_selected)


        self.printuninstchange()
        self.log("Test completed!", type="I")

    def printuninstchange(self):
        self.log("Checking for newly uninstallable packages", type="I")
        text = eval_uninst(self.options.architectures, newly_uninst(
                        self.nuninst_orig_save, self.nuninst_orig))

        if text != '':
            self.output_write("\nNewly uninstallable packages in testing:\n%s" % \
                (text))

    def hint_tester(self):
        """Run a command line interface to test hints

        This method provides a command line interface for the release team to
        try hints and evaluate the results.
        """
        self.log("> Calculating current uninstallability counters", type="I")
        self.nuninst_orig = self.get_nuninst()
        self.nuninst_orig_save = self.get_nuninst()

        import readline
        from completer import Completer

        histfile = os.path.expanduser('~/.britney2_history')
        if os.path.exists(histfile):
            readline.read_history_file(histfile)

        readline.parse_and_bind('tab: complete')
        readline.set_completer(Completer(self).completer)
        # Package names can contain "-" and we use "/" in our presentation of them as well,
        # so ensure readline does not split on these characters.
        readline.set_completer_delims(readline.get_completer_delims().replace('-', '').replace('/', ''))

        while True:
            # read the command from the command line
            try:
                user_input = input('britney> ').lower().split()
            except EOFError:
                print("")
                break
            except KeyboardInterrupt:
                print("")
                continue
            # quit the hint tester
            if user_input and user_input[0] in ('quit', 'exit'):
                break
            elif user_input and user_input[0] in ('remove', 'approve', 'urgent', 'age-days',
                                        'block', 'block-udeb', 'unblock', 'unblock-udeb',
                                        'block-all', 'force'):
                self.hints.add_hint(' '.join(user_input), 'hint-tester')
                self.write_excuses()
            # run a hint
            elif user_input and user_input[0] in ('easy', 'hint', 'force-hint'):
                try:
                    self.do_hint(user_input[0], 'hint-tester',
                        [k.rsplit("/", 1) for k in user_input[1:] if "/" in k])
                    self.printuninstchange()
                except KeyboardInterrupt:
                    continue
        try:
            readline.write_history_file(histfile)
        except IOError as e:
            self.log("Could not write %s: %s" % (histfile, e), type="W")

    def do_hint(self, hinttype, who, pkgvers):
        """Process hints

        This method process `easy`, `hint` and `force-hint` hints. If the
        requested version is not in unstable, then the hint is skipped.
        """

        if isinstance(pkgvers[0], tuple) or isinstance(pkgvers[0], list):
            _pkgvers = [ MigrationItem('%s/%s' % (p, v)) for (p,v) in pkgvers ]
        else:
            _pkgvers = pkgvers

        self.log("> Processing '%s' hint from %s" % (hinttype, who), type="I")
        self.output_write("Trying %s from %s: %s\n" % (hinttype, who, " ".join("%s/%s" % (x.uvname, x.version) for x in _pkgvers)))

        ok = True
        # loop on the requested packages and versions
        for idx in range(len(_pkgvers)):
            pkg = _pkgvers[idx]
            # skip removal requests
            if pkg.is_removal:
                continue

            inunstable = pkg.package in self.sources['unstable']
            rightversion = inunstable and (apt_pkg.version_compare(self.sources['unstable'][pkg.package][VERSION], pkg.version) == 0)
            if pkg.suite == 'unstable' and not rightversion:
                for suite in ['pu', 'tpu']:
                    if pkg.package in self.sources[suite] and apt_pkg.version_compare(self.sources[suite][pkg.package][VERSION], pkg.version) == 0:
                        pkg.suite = suite
                        _pkgvers[idx] = pkg
                        break

            # handle *-proposed-updates
            if pkg.suite in ['pu', 'tpu']:
                if pkg.package not in self.sources[pkg.suite]: continue
                if apt_pkg.version_compare(self.sources[pkg.suite][pkg.package][VERSION], pkg.version) != 0:
                    self.output_write(" Version mismatch, %s %s != %s\n" % (pkg.package, pkg.version, self.sources[pkg.suite][pkg.package][VERSION]))
                    ok = False
            # does the package exist in unstable?
            elif not inunstable:
                self.output_write(" Source %s has no version in unstable\n" % pkg.package)
                ok = False
            elif not rightversion:
                self.output_write(" Version mismatch, %s %s != %s\n" % (pkg.package, pkg.version, self.sources['unstable'][pkg.package][VERSION]))
                ok = False
        if not ok:
            self.output_write("Not using hint\n")
            return False

        self.do_all(hinttype, _pkgvers)
        return True

    def auto_hinter(self):
        """Auto-generate "easy" hints.

        This method attempts to generate "easy" hints for sets of packages which
        must migrate together. Beginning with a package which does not depend on
        any other package (in terms of excuses), a list of dependencies and
        reverse dependencies is recursively created.

        Once all such lists have been generated, any which are subsets of other
        lists are ignored in favour of the larger lists. The remaining lists are
        then attempted in turn as "easy" hints.

        We also try to auto hint circular dependencies analyzing the update
        excuses relationships. If they build a circular dependency, which we already
        know as not-working with the standard do_all algorithm, try to `easy` them.
        """
        self.log("> Processing hints from the auto hinter",
                   type="I")

        # consider only excuses which are valid candidates
        valid_excuses = frozenset(y.uvname for y in self.upgrade_me)
        excuses = self.excuses
        excuses_deps = dict((name, set(excuse.deps)) for name, excuse in excuses.items() if name in valid_excuses)
        sources_t = self.sources['testing']

        def find_related(e, hint, circular_first=False):
            if e not in valid_excuses:
                return False
            excuse = excuses[e]
            if e in sources_t and sources_t[e][VERSION] == excuse.ver[1]:
                return True
            if not circular_first:
                hint[e] = excuse.ver[1]
            if not excuse.deps:
                return hint
            for p in excuse.deps:
                if p in hint: continue
                if not find_related(p, hint):
                    return False
            return hint

        # loop on them
        candidates = []
        mincands = []
        seen_hints = set()
        for e in valid_excuses:
            excuse = excuses[e]
            if e in sources_t and sources_t[e][VERSION] == excuse.ver[1]:
                continue
            if excuse.deps:
                hint = find_related(e, {}, True)
                if isinstance(hint, dict) and e in hint:
                    h = frozenset(hint.items())
                    if h not in seen_hints:
                        candidates.append(h)
                        seen_hints.add(h)
            else:
                items = [(e, excuse.ver[1])]
                orig_size = 1
                looped = False
                seen_items = set()
                seen_items.update(items)

                for item, ver in items:
                    # excuses which depend on "item" or are depended on by it
                    new_items = [(x, excuses[x].ver[1]) for x in valid_excuses if \
                       (item in excuses_deps[x] or x in excuses_deps[item]) \
                       and (x, excuses[x].ver[1]) not in seen_items]
                    items.extend(new_items)
                    seen_items.update(new_items)

                    if not looped and len(items) > 1:
                        orig_size = len(items)
                        h = frozenset(seen_items)
                        if h not in seen_hints:
                            mincands.append(h)
                            seen_hints.add(h)
                    looped = True
                if len(items) != orig_size:
                    h = frozenset(seen_items)
                    if h != mincands[-1] and h not in seen_hints:
                        candidates.append(h)
                        seen_hints.add(h)

        for l in [ candidates, mincands ]:
            for hint in l:
                self.do_hint("easy", "autohinter", [ MigrationItem("%s/%s" % (x[0], x[1])) for x in sorted(hint) ])

    def nuninst_arch_report(self, nuninst, arch):
        """Print a report of uninstallable packages for one architecture."""
        all = defaultdict(set)
        for p in nuninst[arch]:
            pkg = self.binaries['testing'][arch][0][p]
            all[(pkg[SOURCE], pkg[SOURCEVER])].add(p)

        print('* %s' % arch)

        for (src, ver), pkgs in sorted(all.items()):
            print('  %s (%s): %s' % (src, ver, ' '.join(sorted(pkgs))))

        print()

    def output_write(self, msg):
        """Simple wrapper for output writing"""
        print(msg, end='')
        self.__output.write(msg)

    def main(self):
        """Main method
        
        This is the entry point for the class: it includes the list of calls
        for the member methods which will produce the output files.
        """
        # if running in --print-uninst mode, quit
        if self.options.print_uninst:
            return
        # if no actions are provided, build the excuses and sort them
        elif not self.options.actions:
            self.write_excuses()
        # otherwise, use the actions provided by the command line
        else:
            self.upgrade_me = self.options.actions.split()

        with open(self.options.upgrade_output, 'w', encoding='utf-8') as f:
            self.__output = f

            # run the hint tester
            if self.options.hint_tester:
                self.hint_tester()
            # run the upgrade test
            else:
                self.upgrade_testing()

            self.log('> Stats from the installability tester', type="I")
            for stat in self._inst_tester.stats.stats():
                self.log('>   %s' % stat, type="I")


if __name__ == '__main__':
    Britney().main()
