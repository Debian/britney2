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
    version of a source or binary package (see RCBugPolicy.read_bugs).

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

import optparse
import os
import sys
import time
from collections import defaultdict, namedtuple
from functools import reduce
from itertools import product
from operator import attrgetter
from urllib.parse import quote

import apt_pkg

# Check the "check_field_name" reflection before removing an import here.
from britney2.consts import (SOURCE, SOURCEVER, ARCHITECTURE, CONFLICTS, DEPENDS, PROVIDES, MULTIARCH)
from britney2.excuse import Excuse
from britney2.hints import HintParser
from britney2.installability.builder import InstallabilityTesterBuilder
from britney2.migrationitem import MigrationItem
from britney2.policies.policy import AgePolicy, RCBugPolicy, PolicyVerdict
from britney2.utils import (old_libraries_format, undo_changes,
                            compute_reverse_tree, possibly_compressed,
                            read_nuninst, write_nuninst, write_heidi,
                            eval_uninst, newly_uninst, make_migrationitem,
                            write_excuses, write_heidi_delta, write_controlfiles,
                            old_libraries, is_nuninst_asgood_generous,
                            clone_nuninst, check_installability,
                            create_provides_map, read_release_file,
                            )

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


class SourcePackage(object):

    __slots__ = ['version', 'section', 'binaries', 'maintainer', 'is_fakesrc']

    def __init__(self, version, section, binaries, maintainer, is_fakesrc):
        self.version = version
        self.section = section
        self.binaries = binaries
        self.maintainer = maintainer
        self.is_fakesrc = is_fakesrc

    def __getitem__(self, item):
        return getattr(self, self.__slots__[item])

BinaryPackageId = namedtuple('BinaryPackageId', [
                               'package_name',
                               'version',
                               'architecture',
                           ])

BinaryPackage = namedtuple('BinaryPackage', [
                               'version',
                               'section',
                               'source',
                               'source_version',
                               'architecture',
                               'multi_arch',
                               'depends',
                               'conflicts',
                               'provides',
                               'is_essential',
                               'pkg_id',
                           ])

SuiteInfo = namedtuple('SuiteInfo', [
    'name',
    'path',
    'excuses_suffix',
])


class Britney(object):
    """Britney, the Debian testing updater script
    
    This is the script that updates the testing distribution. It is executed
    each day after the installation of the updated packages. It generates the 
    `Packages' files for the testing distribution, but it does so in an
    intelligent manner; it tries to avoid any inconsistency and to use only
    non-buggy packages.

    For more documentation on this script, please read the Developers Reference.
    """

    HINTS_HELPERS = ("easy", "hint", "remove", "block", "block-udeb", "unblock", "unblock-udeb", "approve", "remark")
    HINTS_STANDARD = ("urgent", "age-days") + HINTS_HELPERS
    # ALL = {"force", "force-hint", "block-all"} | HINTS_STANDARD | registered policy hints (not covered above)
    HINTS_ALL = ('ALL')

    def __init__(self):
        """Class constructor

        This method initializes and populates the data lists, which contain all
        the information needed by the other methods of the class.
        """

        # parse the command line arguments
        self.policies = []
        self._hint_parser = HintParser(self)
        self.suite_info = {}
        self.__parse_arguments()
        MigrationItem.set_architectures(self.options.architectures)

        # initialize the apt_pkg back-end
        apt_pkg.init()
        self.sources = {}
        self.binaries = {}
        self.all_selected = []
        self.excuses = {}

        try:
            self.read_hints(self.options.hintsdir)
        except AttributeError:
            self.read_hints(os.path.join(self.suite_info['unstable'].path, 'Hints'))

        if self.options.nuninst_cache:
            self.log("Not building the list of non-installable packages, as requested", type="I")
            if self.options.print_uninst:
                print('* summary')
                print('\n'.join('%4d %s' % (len(nuninst[x]), x) for x in self.options.architectures))
                return

        self.all_binaries = {}
        # read the source and binary packages for the involved distributions
        self.sources['testing'] = self.read_sources(self.suite_info['testing'].path)
        self.sources['unstable'] = self.read_sources(self.suite_info['unstable'].path)
        for suite in ('tpu', 'pu'):
            if hasattr(self.options, suite):
                self.sources[suite] = self.read_sources(getattr(self.options, suite))
            else:
                self.sources[suite] = {}

        self.binaries['testing'] = {}
        self.binaries['unstable'] = {}
        self.binaries['tpu'] = {}
        self.binaries['pu'] = {}

        self.binaries['unstable'] = self.read_binaries(self.suite_info['unstable'].path, "unstable", self.options.architectures)
        for suite in ('tpu', 'pu'):
            if suite in self.suite_info:
                self.binaries[suite] = self.read_binaries(self.suite_info[suite].path, suite, self.options.architectures)
            else:
                # _build_installability_tester relies on this being
                # properly initialised, so insert two empty dicts
                # here.
                for arch in self.options.architectures:
                    self.binaries[suite][arch] = ({}, {})
        # Load testing last as some live-data tests have more complete information in
        # unstable
        self.binaries['testing'] = self.read_binaries(self.suite_info['testing'].path, "testing", self.options.architectures)

        try:
            constraints_file = os.path.join(self.options.static_input_dir, 'constraints')
            faux_packages = os.path.join(self.options.static_input_dir, 'faux-packages')
        except AttributeError:
            self.log("The static_input_dir option is not set", type='I')
            constraints_file = None
            faux_packages = None
        if faux_packages is not None and os.path.exists(faux_packages):
            self.log("Loading faux packages from %s" % faux_packages, type='I')
            self._load_faux_packages(faux_packages)
        elif faux_packages is not None:
            self.log("No Faux packages as %s does not exist" % faux_packages, type='I')

        if constraints_file is not None and os.path.exists(constraints_file):
            self.log("Loading constraints from %s" % constraints_file, type='I')
            self.constraints = self._load_constraints(constraints_file)
        else:
            if constraints_file is not None:
                self.log("No constraints as %s does not exist" % constraints_file, type='I')
            self.constraints = {
                'keep-installable': [],
            }

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
                package, pkg_entry1.version, parch), type="E")
            for f, v1, v2 in bad:
                self.log(" ... %s %s != %s" % (check_field_name[f], v1, v2))
            raise ValueError("Invalid data set")

        # Merge ESSENTIAL if necessary
        assert pkg_entry1.is_essential or not pkg_entry2.is_essential

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

        for suite in ('testing', 'unstable', 'pu', 'tpu'):
            suffix = suite if suite in {'pu', 'tpu'} else ''
            if hasattr(self.options, suite):
                suite_path = getattr(self.options, suite)
                self.suite_info[suite] = SuiteInfo(name=suite, path=suite_path, excuses_suffix=suffix)
            else:
                if suite in {'testing', 'unstable'}:
                    self.log("Mandatory configuration %s is not set in the config" % suite.upper(), type='E')
                    sys.exit(1)
                self.log("Optional suite %s is not defined (config option: %s) " % (suite, suite.upper()))

        try:
            release_file = read_release_file(self.suite_info['testing'].path)
            self.log("Found a Release file in testing - using that for defaults")
        except FileNotFoundError:
            self.log("Testing does not have a Release file.")
            release_file = None

        if getattr(self.options, "components", None):
            self.options.components = [s.strip() for s in self.options.components.split(",")]
        elif release_file and not self.options.control_files:
            self.options.components = release_file['Components'].split()
            self.log("Using components listed in Release file: %s" % ' '.join(self.options.components))
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
        self.options.outofsync_arches = self.options.outofsync_arches.split()
        self.options.break_arches = self.options.break_arches.split()
        self.options.new_arches = self.options.new_arches.split()

        if getattr(self.options, "architectures", None):
            # Sort the architecture list
            allarches = sorted(self.options.architectures.split())
        else:
            if not release_file:
                self.log("No configured architectures and there is no release file for testing", type="E")
                self.log("Please check if there is a \"Release\" file in %s" % self.suite_info['testing'].path, type="E")
                self.log("or if the config file contains a non-empty \"ARCHITECTURES\" field", type="E")
                sys.exit(1)
            allarches = sorted(release_file['Architectures'].split())
            self.log("Using architectures listed in Release file: %s" % ' '.join(allarches))
        arches = [x for x in allarches if x in self.options.nobreakall_arches]
        arches += [x for x in allarches if x not in arches and x not in self.options.outofsync_arches]
        arches += [x for x in allarches if x not in arches and x not in self.options.break_arches]
        arches += [x for x in allarches if x not in arches and x not in self.options.new_arches]
        arches += [x for x in allarches if x not in arches]
        self.options.architectures = [sys.intern(arch) for arch in arches]
        self.options.smooth_updates = self.options.smooth_updates.split()

        if not hasattr(self.options, 'ignore_cruft') or \
            self.options.ignore_cruft == "0":
            self.options.ignore_cruft = False

        self.policies.append(AgePolicy(self.options, self.suite_info, MINDAYS))
        self.policies.append(RCBugPolicy(self.options, self.suite_info))

        for policy in self.policies:
            policy.register_hints(self._hint_parser)

    @property
    def hints(self):
        return self._hint_parser.hints

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

    def _load_faux_packages(self, faux_packages_file):
        """Loads fake packages

        In rare cases, it is useful to create a "fake" package that can be used to satisfy
        dependencies.  This is usually needed for packages that are not shipped directly
        on this mirror but is a prerequisite for using this mirror (e.g. some vendors provide
        non-distributable "setup" packages and contrib/non-free packages depend on these).

        :param faux_packages_file: Path to the file containing the fake package definitions
        """
        tag_file = apt_pkg.TagFile(faux_packages_file)
        get_field = tag_file.section.get
        step = tag_file.step
        no = 0

        while step():
            no += 1
            pkg_name = get_field('Package', None)
            if pkg_name is None:
                raise ValueError("Missing Package field in paragraph %d (file %s)" % (no, faux_packages_file))
            pkg_name = sys.intern(pkg_name)
            version = sys.intern(get_field('Version', '1.0-1'))
            provides_raw = get_field('Provides')
            archs_raw = get_field('Architecture', None)
            component = get_field('Component', 'non-free')
            if archs_raw:
                archs = archs_raw.split()
            else:
                archs = self.options.architectures
            faux_section = 'faux'
            if component != 'main':
                faux_section = "%s/faux" % component
            src_data = SourcePackage(version,
                        sys.intern(faux_section),
                        [],
                        None,
                        True,
                        )

            self.sources['testing'][pkg_name] = src_data
            self.sources['unstable'][pkg_name] = src_data

            for arch in archs:
                pkg_id = BinaryPackageId(pkg_name, version, arch)
                if provides_raw:
                    provides = self._parse_provides(pkg_id, provides_raw)
                else:
                    provides = []
                bin_data = BinaryPackage(version,
                                         faux_section,
                                         pkg_name,
                                         version,
                                         arch,
                                         get_field('Multi-Arch'),
                                         None,
                                         None,
                                         provides,
                                         False,
                                         pkg_id,
                                         )

                src_data.binaries.append(pkg_id)
                self.binaries['testing'][arch][0][pkg_name] = bin_data
                self.binaries['unstable'][arch][0][pkg_name] = bin_data
                self.all_binaries[pkg_id] = bin_data

    def _load_constraints(self, constraints_file):
        """Loads configurable constraints

        The constraints file can contain extra rules that Britney should attempt
        to satisfy.  Examples can be "keep package X in testing and ensure it is
        installable".

        :param constraints_file: Path to the file containing the constraints
        """
        tag_file = apt_pkg.TagFile(constraints_file)
        get_field = tag_file.section.get
        step = tag_file.step
        no = 0
        faux_version = sys.intern('1')
        faux_section = sys.intern('faux')
        keep_installable = []
        constraints = {
            'keep-installable': keep_installable
        }

        while step():
            no += 1
            pkg_name = get_field('Fake-Package-Name', None)
            if pkg_name is None:
                raise ValueError("Missing Fake-Package-Name field in paragraph %d (file %s)" % (no, constraints_file))
            pkg_name = sys.intern(pkg_name)

            def mandatory_field(x):
                v = get_field(x, None)
                if v is None:
                    raise ValueError("Missing %s field for %s (file %s)" % (x, pkg_name, constraints_file))
                return v

            constraint = mandatory_field('Constraint')
            if constraint not in {'present-and-installable'}:
                raise ValueError("Unsupported constraint %s for %s (file %s)" % (constraint, pkg_name, constraints_file))

            self.log(" - constraint %s" % pkg_name, type='I')

            pkg_list = [x.strip() for x in mandatory_field('Package-List').split("\n") if x.strip() != '' and not x.strip().startswith("#")]
            src_data = SourcePackage(faux_version,
                        faux_section,
                        [],
                        None,
                        True,
                        )
            self.sources['testing'][pkg_name] = src_data
            self.sources['unstable'][pkg_name] = src_data
            keep_installable.append(pkg_name)
            for arch in self.options.architectures:
                deps = []
                for pkg_spec in pkg_list:
                    s = pkg_spec.split(None, 1)
                    if len(s) == 1:
                        deps.append(s[0])
                    else:
                        pkg, arch_res = s
                        if not (arch_res.startswith('[') and arch_res.endswith(']')):
                            raise ValueError("Invalid arch-restriction on %s - should be [arch1 arch2] (for %s file %s)"
                                             % (pkg, pkg_name, constraints_file))
                        arch_res = arch_res[1:-1].split()
                        if not arch_res:
                            msg = "Empty arch-restriction for %s: Uses comma or negation (for %s file %s)"
                            raise ValueError(msg % (pkg, pkg_name, constraints_file))
                        for a in arch_res:
                            if a == arch:
                                deps.append(pkg)
                            elif ',' in a or '!' in a:
                                msg = "Invalid arch-restriction for %s: Uses comma or negation (for %s file %s)"
                                raise ValueError(msg % (pkg, pkg_name, constraints_file))
                pkg_id = BinaryPackageId(pkg_name, faux_version, arch)
                bin_data = BinaryPackage(faux_version,
                                         faux_section,
                                         pkg_name,
                                         faux_version,
                                         arch,
                                         'no',
                                         ', '.join(deps),
                                         None,
                                         [],
                                         False,
                                         pkg_id,
                                         )
                src_data.binaries.append(pkg_id)
                self.binaries['testing'][arch][0][pkg_name] = bin_data
                self.binaries['unstable'][arch][0][pkg_name] = bin_data
                self.all_binaries[pkg_id] = bin_data

        return constraints

    def _build_installability_tester(self, archs):
        """Create the installability tester"""

        solvers = self.get_dependency_solvers
        binaries = self.binaries
        builder = InstallabilityTesterBuilder()

        for (dist, arch) in product(binaries, archs):
            testing = (dist == 'testing')
            for pkgname in binaries[dist][arch][0]:
                pkgdata = binaries[dist][arch][0][pkgname]
                pkg_id = pkgdata.pkg_id
                if not builder.add_binary(pkg_id, essential=pkgdata.is_essential,
                                          in_testing=testing):
                    continue

                depends = []
                conflicts = []
                possible_dep_ranges = {}

                # We do not differentiate between depends and pre-depends
                if pkgdata.depends:
                    depends.extend(apt_pkg.parse_depends(pkgdata.depends, False))

                if pkgdata.conflicts:
                    conflicts = apt_pkg.parse_depends(pkgdata.conflicts, False)

                with builder.relation_builder(pkg_id) as relations:

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
                                    dep_pkg_id = pdata.pkg_id
                                    if dep:
                                        sat.add(dep_pkg_id)
                                    elif pkg_id != dep_pkg_id:
                                        # if t satisfies its own
                                        # conflicts relation, then it
                                        # is using §7.6.2
                                        relations.add_breaks(dep_pkg_id)
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
            maint = get_field('Maintainer')
            if maint:
                maint = intern(maint.strip())
            section = get_field('Section')
            if section:
                section = intern(section.strip())
            sources[intern(pkg)] = SourcePackage(intern(ver),
                            section,
                            [],
                            maint,
                            False,
                            )
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
                filename = possibly_compressed(filename)
                self._read_sources_file(filename, sources)
        else:
            filename = os.path.join(basedir, "Sources")
            sources = self._read_sources_file(filename)

        return sources

    def _parse_provides(self, pkg_id, provides_raw):
        parts = apt_pkg.parse_depends(provides_raw, False)
        nprov = []
        for or_clause in parts:
            if len(or_clause) != 1:
                msg = "Ignoring invalid provides in %s: Alternatives [%s]" % (str(pkg_id), str(or_clause))
                self.log(msg, type='W')
                continue
            for part in or_clause:
                provided, provided_version, op = part
                if op != '' and op != '=':
                    msg = "Ignoring invalid provides in %s: %s (%s %s)" % (str(pkg_id), provided, op, provided_version)
                    self.log(msg, type='W')
                    continue
                provided = sys.intern(provided)
                provided_version = sys.intern(provided_version)
                part = (provided, provided_version, sys.intern(op))
                nprov.append(part)
        return nprov

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
            pkg_id = BinaryPackageId(pkg, version, arch)

            if pkg in packages:
                old_pkg_data = packages[pkg]
                if apt_pkg.version_compare(old_pkg_data.version, version) > 0:
                    continue
                old_pkg_id = old_pkg_data.pkg_id
                old_src_binaries = srcdist[old_pkg_data[SOURCE]].binaries
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

            source = pkg
            source_version = version
            # retrieve the name and the version of the source package
            source_raw = get_field('Source')
            if source_raw:
                source = intern(source_raw.split(" ")[0])
                if "(" in source_raw:
                    source_version = intern(source_raw[source_raw.find("(")+1:source_raw.find(")")])

            provides_raw = get_field('Provides')
            if provides_raw:
                provides = self._parse_provides(pkg_id, provides_raw)
            else:
                provides = []

            dpkg = BinaryPackage(version,
                    intern(get_field('Section')),
                    source,
                    source_version,
                    intern(get_field('Architecture')),
                    get_field('Multi-Arch'),
                    deps,
                    ', '.join(final_conflicts_list) or None,
                    provides,
                    ess,
                    pkg_id,
                   )

            # if the source package is available in the distribution, then register this binary package
            if source in srcdist:
                # There may be multiple versions of any arch:all packages
                # (in unstable) if some architectures have out-of-date
                # binaries.  We only want to include the package in the
                # source -> binary mapping once. It doesn't matter which
                # of the versions we include as only the package name and
                # architecture are recorded.
                if pkg_id not in srcdist[source].binaries:
                    srcdist[source].binaries.append(pkg_id)
            # if the source package doesn't exist, create a fake one
            else:
                srcdist[source] = SourcePackage(source_version, 'faux', [pkg_id], None, True)

            # add the resulting dictionary to the package list
            packages[pkg] = dpkg
            if pkg_id in all_binaries:
                self.merge_pkg_entries(pkg, arch, all_binaries[pkg_id], dpkg)
            else:
                all_binaries[pkg_id] = dpkg

            # add the resulting dictionary to the package list
            packages[pkg] = dpkg

        return packages

    def read_binaries(self, basedir, distribution, architectures):
        """Read the list of binary packages from the specified directory

        This method reads all the binary packages for a given distribution,
        which is expected to be in the directory denoted by the "base_dir"
        parameter.

        If the "components" config parameter is set, the directory should
        be the "suite" directory of a local mirror (i.e. the one containing
        the "InRelease" file).  Otherwise, Britney will read the packages
        information from all the "Packages_${arch}" files referenced by
        the "architectures" parameter.

        Considering the
        large amount of memory needed, not all the fields are loaded
        in memory. The available fields are Version, Source, Multi-Arch,
        Depends, Conflicts, Provides and Architecture.

        The `Provides' field is used to populate the virtual packages list.

        The method returns a dict mapping an architecture name to a 2-element
        tuple.  The first element in the tuple is a map from binary package
        names to "BinaryPackage" objects; the second element is a dictionary
        which maps virtual packages to real packages that provide them.
        """
        arch2packages = {}

        if self.options.components:
            release_file = read_release_file(basedir)
            listed_archs = set(release_file['Architectures'].split())
            for arch in architectures:
                packages = {}
                if arch not in listed_archs:
                    self.log("Skipping arch %s for %s: It is not listed in the Release file" % (arch, distribution))
                    arch2packages[arch] = ({}, {})
                    continue
                for component in self.options.components:
                    binary_dir = "binary-%s" % arch
                    filename = os.path.join(basedir,
                                            component,
                                            binary_dir,
                                            'Packages')
                    filename = possibly_compressed(filename)
                    udeb_filename = os.path.join(basedir,
                                                 component,
                                                 "debian-installer",
                                                 binary_dir,
                                                 "Packages")
                    # We assume the udeb Packages file is present if the
                    # regular one is present
                    udeb_filename = possibly_compressed(udeb_filename)
                    self._read_packages_file(filename,
                                             arch,
                                             self.sources[distribution],
                                             packages)
                    self._read_packages_file(udeb_filename,
                                             arch,
                                             self.sources[distribution],
                                             packages)
                # create provides
                provides = create_provides_map(packages)
                arch2packages[arch] = (packages, provides)
        else:
            for arch in architectures:
                filename = os.path.join(basedir, "Packages_%s" % arch)
                packages = self._read_packages_file(filename,
                                                    arch,
                                                    self.sources[distribution])
                provides = create_provides_map(packages)
                arch2packages[arch] = (packages, provides)

        return arch2packages

    def read_hints(self, hintsdir):
        """Read the hint commands from the specified directory
        
        The hint commands are read from the files contained in the directory
        specified by the `hintsdir' parameter.
        The names of the files have to be the same as the authorized users
        for the hints.
        
        The file contains rows with the format:

        <command> <package-name>[/<version>]

        The method returns a dictionary where the key is the command, and
        the value is the list of affected packages.
        """

        for who in self.HINTS.keys():
            if who == 'command-line':
                lines = self.options.hints and self.options.hints.split(';') or ()
                filename = '<cmd-line>'
                self._hint_parser.parse_hints(who, self.HINTS[who], filename, lines)
            else:
                filename = os.path.join(hintsdir, who)
                if not os.path.isfile(filename):
                    self.log("Cannot read hints list from %s, no such file!" % filename, type="E")
                    continue
                self.log("Loading hints list from %s" % filename)
                with open(filename, encoding='utf-8') as f:
                    self._hint_parser.parse_hints(who, self.HINTS[who], filename, f)

        hints = self._hint_parser.hints

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
                if (op == '' and version == '') or apt_pkg.check_dep(package.version, op, version):
                    if archqual is None or (archqual == 'any' and package.multi_arch == 'allowed'):
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
        packages_s_a = self.binaries[suite][arch]
        packages_t_a = self.binaries['testing'][arch]
        binaries_s_a = packages_s_a[0]
        binary_u = binaries_s_a[pkg]

        # local copies for better performance
        parse_depends = apt_pkg.parse_depends
        get_dependency_solvers = self.get_dependency_solvers

        # analyze the dependency fields (if present)
        deps = binary_u.depends
        if not deps:
            return True
        is_all_ok = True


        # for every dependency block (formed as conjunction of disjunction)
        for block, block_txt in zip(parse_depends(deps, False), deps.split(',')):
            # if the block is satisfied in testing, then skip the block
            packages = get_dependency_solvers(block, packages_t_a)
            if packages:
                for p in packages:
                    if p not in binaries_s_a:
                        continue
                    excuse.add_sane_dep(binaries_s_a[p].source)
                continue

            # check if the block can be satisfied in the source suite, and list the solving packages
            packages = get_dependency_solvers(block, packages_s_a)
            packages = [packages_s_a[0][p].source for p in packages]

            # if the dependency can be satisfied by the same source package, skip the block:
            # obviously both binary packages will enter testing together
            if src in packages: continue

            # if no package can satisfy the dependency, add this information to the excuse
            if not packages:
                excuse.addhtml("%s/%s unsatisfiable Depends: %s" % (pkg, arch, block_txt.strip()))
                excuse.addreason("depends")
                if arch not in self.options.break_arches:
                    is_all_ok = False
                continue

            # for the solving packages, update the excuse to add the dependencies
            for p in packages:
                if arch not in self.options.break_arches:
                    if p in self.sources['testing'] and self.sources['testing'][p].version == self.sources[suite][p].version:
                        excuse.add_dep("%s/%s" % (p, arch), arch)
                    else:
                        excuse.add_dep(p, arch)
                else:
                    excuse.add_break_dep(p, arch)
        return is_all_ok

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
        excuse.set_vers(src.version, None)
        src.maintainer and excuse.set_maint(src.maintainer)
        src.section and excuse.set_section(src.section)

        # if the package is blocked, skip it
        for hint in self.hints.search('block', package=pkg, removal=True):
            excuse.addhtml("Not touching package, as requested by %s "
                "(check https://release.debian.org/testing/freeze_policy.html if update is needed)" % hint.user)
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
        suite_info = self.suite_info[suite]
        suffix = ''
        if suite_info.excuses_suffix:
            suffix = "_%s" % suite_info.excuses_suffix

        # build the common part of the excuse, which will be filled by the code below
        ref = "%s/%s%s" % (src, arch, suffix)
        excuse = Excuse(ref)
        excuse.set_vers(source_t.version, source_t.version)
        source_u.maintainer and excuse.set_maint(source_u.maintainer)
        source_u.section and excuse.set_section(source_u.section)
        
        # if there is a `remove' hint and the requested version is the same as the
        # version in testing, then stop here and return False
        # (as a side effect, a removal may generate such excuses for both the source
        # package and its binary packages on each architecture)
        for hint in self.hints.search('remove', package=src, version=source_t.version):
            excuse.add_hint(hint)
            excuse.addhtml("Removal request by %s" % (hint.user))
            excuse.addhtml("Trying to remove package, not update it")
            self.excuses[excuse.name] = excuse
            return False

        # the starting point is that there is nothing wrong and nothing worth doing
        anywrongver = False
        anyworthdoing = False

        packages_t_a = self.binaries['testing'][arch][0]
        packages_s_a = self.binaries[suite][arch][0]

        # for every binary package produced by this source in unstable for this architecture
        for pkg_id in sorted(x for x in source_u.binaries if x.architecture == arch):
            pkg_name = pkg_id.package_name

            # retrieve the testing (if present) and unstable corresponding binary packages
            binary_t = pkg_name in packages_t_a and packages_t_a[pkg_name] or None
            binary_u = packages_s_a[pkg_name]

            # this is the source version for the new binary package
            pkgsv = binary_u.source_version

            # if the new binary package is architecture-independent, then skip it
            if binary_u.architecture == 'all':
                if pkg_id not in source_t.binaries:
                    # only add a note if the arch:all does not match the expected version
                    excuse.addhtml("Ignoring %s %s (from %s) as it is arch: all" % (pkg_name, binary_u.version, pkgsv))
                continue

            # if the new binary package is not from the same source as the testing one, then skip it
            # this implies that this binary migration is part of a source migration
            if source_u.version == pkgsv and source_t.version != pkgsv:
                anywrongver = True
                excuse.addhtml("From wrong source: %s %s (%s not %s)" % (pkg_name, binary_u.version, pkgsv, source_t.version))
                continue

            # cruft in unstable
            if source_u.version != pkgsv and source_t.version != pkgsv:
                if self.options.ignore_cruft:
                    excuse.addhtml("Old cruft: %s %s (but ignoring cruft, so nevermind)" % (pkg_name, pkgsv))
                else:
                    anywrongver = True
                    excuse.addhtml("Old cruft: %s %s" % (pkg_name, pkgsv))
                continue

            # if the source package has been updated in unstable and this is a binary migration, skip it
            # (the binaries are now out-of-date)
            if source_t.version == pkgsv and source_t.version != source_u.version:
                anywrongver = True
                excuse.addhtml("From wrong source: %s %s (%s not %s)" % (pkg_name, binary_u.version, pkgsv, source_u.version))
                continue

            # find unsatisfied dependencies for the new binary package
            self.excuse_unsat_deps(pkg_name, src, arch, suite, excuse)

            # if the binary is not present in testing, then it is a new binary;
            # in this case, there is something worth doing
            if not binary_t:
                excuse.addhtml("New binary: %s (%s)" % (pkg_name, binary_u.version))
                anyworthdoing = True
                continue

            # at this point, the binary package is present in testing, so we can compare
            # the versions of the packages ...
            vcompare = apt_pkg.version_compare(binary_t.version, binary_u.version)

            # ... if updating would mean downgrading, then stop here: there is something wrong
            if vcompare > 0:
                anywrongver = True
                excuse.addhtml("Not downgrading: %s (%s to %s)" % (pkg_name, binary_t.version, binary_u.version))
                break
            # ... if updating would mean upgrading, then there is something worth doing
            elif vcompare < 0:
                excuse.addhtml("Updated binary: %s (%s to %s)" % (pkg_name, binary_t.version, binary_u.version))
                anyworthdoing = True

        # if there is nothing wrong and there is something worth doing or the source
        # package is not fake, then check what packages should be removed
        if not anywrongver and (anyworthdoing or not source_u.is_fakesrc):
            srcv = source_u.version
            ssrc = source_t.version == srcv
            # if this is a binary-only migration via *pu, we never want to try
            # removing binary packages
            if not (ssrc and suite != 'unstable'):
                # for every binary package produced by this source in testing for this architecture
                _, _, smoothbins = self._compute_groups(src,
                                                        "unstable",
                                                        arch,
                                                        False)

                for pkg_id in sorted(x for x in source_t.binaries if x.architecture == arch):
                    pkg = pkg_id.package_name
                    # if the package is architecture-independent, then ignore it
                    tpkg_data = packages_t_a[pkg]
                    if tpkg_data.version == 'all':
                        if pkg_id not in source_u.binaries:
                            # only add a note if the arch:all does not match the expected version
                            excuse.addhtml("Ignoring removal of %s as it is arch: all" % (pkg))
                        continue
                    # if the package is not produced by the new source package, then remove it from testing
                    if pkg not in packages_s_a:
                        excuse.addhtml("Removed binary: %s %s" % (pkg, tpkg_data.version))
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
            if apt_pkg.version_compare(source_t.version, source_u.version) == 0:
                return False
        else:
            source_t = None

        suite_info = self.suite_info[suite]
        suffix = ''
        if suite_info.excuses_suffix:
            suffix = "_%s" % suite_info.excuses_suffix

        # build the common part of the excuse, which will be filled by the code below
        ref = "%s%s" % (src, suffix)
        excuse = Excuse(ref)
        excuse.set_vers(source_t and source_t.version or None, source_u.version)
        source_u.maintainer and excuse.set_maint(source_u.maintainer)
        source_u.section and excuse.set_section(source_u.section)

        # the starting point is that we will update the candidate
        update_candidate = True
        
        # if the version in unstable is older, then stop here with a warning in the excuse and return False
        if source_t and apt_pkg.version_compare(source_u.version, source_t.version) < 0:
            excuse.addhtml("ALERT: %s is newer in testing (%s %s)" % (src, source_t.version, source_u.version))
            self.excuses[excuse.name] = excuse
            excuse.addreason("newerintesting")
            return False

        # check if the source package really exists or if it is a fake one
        if source_u.is_fakesrc:
            excuse.addhtml("%s source package doesn't exist" % (src))
            update_candidate = False

        # if there is a `remove' hint and the requested version is the same as the
        # version in testing, then stop here and return False
        for hint in self.hints.search('remove', package=src):
            if source_t and source_t.version == hint.version or \
               source_u.version == hint.version:
                excuse.add_hint(hint)
                excuse.addhtml("Removal request by %s" % (hint.user))
                excuse.addhtml("Trying to remove package, not update it")
                update_candidate = False

        # check if there is a `block' or `block-udeb' hint for this package, or a `block-all source' hint
        blocked = {}
        for hint in self.hints.search(package=src):
            if hint.type == 'block':
                blocked['block'] = hint
                excuse.add_hint(hint)
            if hint.type == 'block-udeb':
                blocked['block-udeb'] = hint
                excuse.add_hint(hint)
        if 'block' not in blocked:
            for hint in self.hints.search(type='block-all'):
                if hint.package == 'source' or (not source_t and hint.package == 'new-source'):
                    blocked['block'] = hint
                    excuse.add_hint(hint)
                    break
        if suite in ('pu', 'tpu'):
            blocked['block'] = '%s-block' % (suite)
            excuse.needs_approval = True

        # if the source is blocked, then look for an `unblock' hint; the unblock request
        # is processed only if the specified version is correct. If a package is blocked
        # by `block-udeb', then `unblock-udeb' must be present to cancel it.
        for block_cmd in blocked:
            unblock_cmd = "un" + block_cmd
            unblocks = self.hints.search(unblock_cmd, package=src)

            if unblocks and unblocks[0].version is not None and unblocks[0].version == source_u.version:
                excuse.add_hint(unblocks[0])
                if block_cmd == 'block-udeb' or not excuse.needs_approval:
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

        # at this point, we check the status of the builds on all the supported architectures
        # to catch the out-of-date ones
        pkgs = {src: ["source"]}
        all_binaries = self.all_binaries
        for arch in self.options.architectures:
            oodbins = {}
            uptodatebins = False
            # for every binary package produced by this source in the suite for this architecture
            for pkg_id in sorted(x for x in source_u.binaries if x.architecture == arch):
                pkg = pkg_id.package_name
                if pkg not in pkgs: pkgs[pkg] = []
                pkgs[pkg].append(arch)

                # retrieve the binary package and its source version
                binary_u = all_binaries[pkg_id]
                pkgsv = binary_u.source_version

                # if it wasn't built by the same source, it is out-of-date
                # if there is at least one binary on this arch which is
                # up-to-date, there is a build on this arch
                if source_u.version != pkgsv:
                    if pkgsv not in oodbins:
                        oodbins[pkgsv] = []
                    oodbins[pkgsv].append(pkg)
                    excuse.add_old_binary(pkg, pkgsv)
                    continue
                else:
                    # if the binary is arch all, it doesn't count as
                    # up-to-date for this arch
                    if binary_u.architecture == arch:
                        uptodatebins = True

                # if the package is architecture-dependent or the current arch is `nobreakall'
                # find unsatisfied dependencies for the binary package
                if binary_u.architecture != 'all' or arch in self.options.nobreakall_arches:
                    is_valid = self.excuse_unsat_deps(pkg, src, arch, suite, excuse)
                    inst_tester = self._inst_tester
                    if not is_valid and inst_tester.any_of_these_are_in_testing({binary_u.pkg_id}) \
                            and not inst_tester.is_installable(binary_u.pkg_id):
                        # Forgive uninstallable packages only when
                        # they are already broken in testing ideally
                        # we would not need to be forgiving at
                        # all. However, due to how arch:all packages
                        # are handled, we do run into occasionally.
                        update_candidate = False

            # if there are out-of-date packages, warn about them in the excuse and set update_candidate
            # to False to block the update; if the architecture where the package is out-of-date is
            # in the `outofsync_arches' list, then do not block the update
            if oodbins:
                oodtxt = ""
                for v in oodbins.keys():
                    if oodtxt: oodtxt = oodtxt + "; "
                    oodtxt = oodtxt + "%s (from <a href=\"https://buildd.debian.org/status/logs.php?" \
                        "arch=%s&pkg=%s&ver=%s\" target=\"_blank\">%s</a>)" % \
                        (", ".join(sorted(oodbins[v])), quote(arch), quote(src), quote(v), v)
                if uptodatebins:
                    text = "old binaries left on <a href=\"https://buildd.debian.org/status/logs.php?" \
                        "arch=%s&pkg=%s&ver=%s\" target=\"_blank\">%s</a>: %s" % \
                        (quote(arch), quote(src), quote(source_u.version), arch, oodtxt)
                else:
                    text = "missing build on <a href=\"https://buildd.debian.org/status/logs.php?" \
                        "arch=%s&pkg=%s&ver=%s\" target=\"_blank\">%s</a>: %s" % \
                        (quote(arch), quote(src), quote(source_u.version), arch, oodtxt)

                if arch in self.options.outofsync_arches:
                    text = text + " (but %s isn't keeping up, so nevermind)" % (arch)
                    if not uptodatebins:
                        excuse.missing_build_on_ood_arch(arch)
                else:
                    if uptodatebins:
                        if self.options.ignore_cruft:
                            text = text + " (but ignoring cruft, so nevermind)"
                        else:
                            update_candidate = False
                    else:
                        update_candidate = False
                        excuse.missing_build_on_arch(arch)

                excuse.addhtml(text)

        # if the source package has no binaries, set update_candidate to False to block the update
        if not source_u.binaries:
            excuse.addhtml("%s has no binaries on any arch" % src)
            excuse.addreason("no-binaries")
            update_candidate = False

        # if the suite is unstable, then we have to check the urgency and the minimum days of
        # permanence in unstable before updating testing; if the source package is too young,
        # the check fails and we set update_candidate to False to block the update; consider
        # the age-days hint, if specified for the package
        policy_info = excuse.policy_info
        policy_verdict = PolicyVerdict.PASS
        for policy in self.policies:
            if suite in policy.applicable_suites:
                v = policy.apply_policy(policy_info, suite, src, source_t, source_u, excuse)
                if v.value > policy_verdict.value:
                    policy_verdict = v

        if policy_verdict.is_rejected:
            update_candidate = False

        if suite in ('pu', 'tpu') and source_t:
            # o-o-d(ish) checks for (t-)p-u
            # This only makes sense if the package is actually in testing.
            for arch in self.options.architectures:
                # if the package in testing has no binaries on this
                # architecture, it can't be out-of-date
                if not any(x for x in source_t.binaries
                           if x.architecture == arch and all_binaries[x].architecture != 'all'):
                    continue

                # if the (t-)p-u package has produced any binaries on
                # this architecture then we assume it's ok. this allows for
                # uploads to (t-)p-u which intentionally drop binary
                # packages
                if any(x for x in self.binaries[suite][arch][0].values() \
                         if x.source == src and x.source_version == source_u.version and \
                             x.architecture != 'all'):
                    continue

                if suite == 'tpu':
                    base = 'testing'
                else:
                    base = 'stable'
                text = "Not yet built on <a href=\"https://buildd.debian.org/status/logs.php?arch=%s&pkg=%s&ver=%s&suite=%s\" target=\"_blank\">%s</a> (relative to testing)" % (quote(arch), quote(src), quote(source_u.version), base, arch)

                if arch in self.options.outofsync_arches:
                    text = text + " (but %s isn't keeping up, so never mind)" % (arch)
                    excuse.missing_build_on_ood_arch(arch)
                else:
                    update_candidate = False
                    excuse.missing_build_on_arch(arch)

                excuse.addhtml(text)

        # check if there is a `force' hint for this package, which allows it to go in even if it is not updateable
        forces = self.hints.search('force', package=src, version=source_u.version)
        if forces:
            excuse.dontinvalidate = True
        if not update_candidate and forces:
            excuse.addhtml("Should ignore, but forced by %s" % (forces[0].user))
            excuse.force()
            update_candidate = True

        # if the package can be updated, it is a valid candidate
        if update_candidate:
            excuse.is_valid = True

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

        unstable = sources['unstable']
        testing = sources['testing']

        # this list will contain the packages which are valid candidates;
        # if a package is going to be removed, it will have a "-" prefix
        upgrade_me = []
        upgrade_me_append = upgrade_me.append  # Every . in a loop slows it down

        excuses = self.excuses = {}

        # for every source package in testing, check if it should be removed
        for pkg in testing:
            if should_remove_source(pkg):
                upgrade_me_append("-" + pkg)

        # for every source package in unstable check if it should be upgraded
        for pkg in unstable:
            if unstable[pkg].is_fakesrc: continue
            # if the source package is already present in testing,
            # check if it should be upgraded for every binary package
            if pkg in testing and not testing[pkg].is_fakesrc:
                for arch in architectures:
                    if should_upgrade_srcarch(pkg, arch, 'unstable'):
                        upgrade_me_append("%s/%s" % (pkg, arch))

            # check if the source package should be upgraded
            if should_upgrade_src(pkg, 'unstable'):
                upgrade_me_append(pkg)

        # for every source package in *-proposed-updates, check if it should be upgraded
        for suite in ['pu', 'tpu']:
            for pkg in sources[suite]:
                # if the source package is already present in testing,
                # check if it should be upgraded for every binary package
                if pkg in testing:
                    for arch in architectures:
                        if should_upgrade_srcarch(pkg, arch, suite):
                            upgrade_me_append("%s/%s_%s" % (pkg, arch, suite))

                # check if the source package should be upgraded
                if should_upgrade_src(pkg, suite):
                    upgrade_me_append("%s_%s" % (pkg, suite))

        # process the `remove' hints, if the given package is not yet in upgrade_me
        for hint in self.hints['remove']:
            src = hint.package
            if src in upgrade_me: continue
            if ("-"+src) in upgrade_me: continue
            if src not in testing: continue

            # check if the version specified in the hint is the same as the considered package
            tsrcv = testing[src].version
            if tsrcv != hint.version:
                continue

            # add the removal of the package to upgrade_me and build a new excuse
            upgrade_me_append("-%s" % (src))
            excuse = Excuse("-%s" % (src))
            excuse.set_vers(tsrcv, None)
            excuse.addhtml("Removal request by %s" % (hint.user))
            excuse.addhtml("Package is broken, will try to remove")
            excuse.add_hint(hint)
            excuse.is_valid = True
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
                r = inst_tester.is_installable(pkgdata.pkg_id)
                if not r:
                    nuninst[arch].add(pkg_name)

            # if they are not required, remove architecture-independent packages
            nuninst[arch + "+all"] = nuninst[arch].copy()
            if not check_archall:
                for pkg in nuninst[arch + "+all"]:
                    bpkg = binaries[arch][0][pkg]
                    if bpkg.architecture == 'all':
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
                for pkg_id in source_data.binaries:
                    binary, _, parch = pkg_id
                    if (migration_architecture != 'source'
                        and parch != migration_architecture):
                        continue

                    # Work around #815995
                    if migration_architecture == 'source' and is_removal and binary not in binaries_t[parch][0]:
                        continue

                    # Do not include hijacked binaries
                    if binaries_t[parch][0][binary].source != source_name:
                        continue
                    bins.append(pkg_id)

                for pkg_id in bins:
                    binary, _, parch = pkg_id
                    # if a smooth update is possible for the package, skip it
                    if allow_smooth_updates and suite == 'unstable' and \
                       binary not in self.binaries[suite][parch][0] and \
                       ('ALL' in self.options.smooth_updates or \
                        binaries_t[parch][0][binary].section in self.options.smooth_updates):

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
                         binaries_t[parch][0][binary].architecture == 'all':
                        continue
                    else:
                        rms.add(pkg_id)

        # single binary removal; used for clearing up after smooth
        # updates but not supported as a manual hint
        elif source_name in binaries_t[migration_architecture][0]:
            version = binaries_t[migration_architecture][0][source_name].version
            rms.add((source_name, version, migration_architecture))

        # add the new binary packages (if we are not removing)
        if not is_removal:
            source_data = sources[suite][source_name]
            for pkg_id in source_data.binaries:
                binary, _, parch = pkg_id
                if migration_architecture not in ['source', parch]:
                    continue

                if self.binaries[suite][parch][0][binary].source != source_name:
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
                if (parch not in self.options.outofsync_arches and
                    source_data.version != self.binaries[suite][parch][0][binary].source_version and
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

        affected_pos = set()
        affected_remain = set()

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

                for rm_pkg_id in rms:
                    binary, _, parch = rm_pkg_id
                    key = (binary, parch)
                    eqv_table[key] = rm_pkg_id

                for new_pkg_id in updates:
                    binary, _, parch = new_pkg_id
                    key = (binary, parch)
                    old_pkg_id = eqv_table.get(key)
                    if old_pkg_id is not None:
                        if inst_tester.are_equivalent(new_pkg_id, old_pkg_id):
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
                        affected_pos.update(inst_tester.reverse_dependencies_of(rm_pkg_id))
                        affected_remain.update(inst_tester.negative_dependencies_of(rm_pkg_id))

                    # remove the provided virtual packages
                    for j, prov_version, _ in pkg_data.provides:
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
            pkg_id = binaries_t_a[item.package].pkg_id
            undo['binaries'][(item.package, item.architecture)] = pkg_id
            affected_pos.update(inst_tester.reverse_dependencies_of(pkg_id))
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
                if not equivalent_replacement:
                    affected_pos.add(updated_pkg_id)
                # if the binary already exists in testing, it is currently
                # built by another source package. we therefore remove the
                # version built by the other source package, after marking
                # all of its reverse dependencies as affected
                if binary in binaries_t_a:
                    old_pkg_data = binaries_t_a[binary]
                    old_pkg_id = old_pkg_data.pkg_id
                    # save the old binary package
                    undo['binaries'][key] = old_pkg_id
                    if not equivalent_replacement:
                        # all the reverse conflicts
                        affected_pos.update(inst_tester.reverse_dependencies_of(old_pkg_id))
                        affected_remain.update(inst_tester.negative_dependencies_of(old_pkg_id))
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
                            affected_pos.update(inst_tester.reverse_dependencies_of(tpkg_id))

                # add/update the binary package from the source suite
                new_pkg_data = packages_s[parch][0][binary]
                binaries_t_a[binary] = new_pkg_data
                inst_tester.add_testing_binary(updated_pkg_id)
                # register new provided packages
                for j, prov_version, _ in new_pkg_data.provides:
                    key = (j, parch)
                    if j not in provides_t_a:
                        undo['nvirtual'].append(key)
                        provides_t_a[j] = set()
                    elif key not in undo['virtual']:
                        undo['virtual'][key] = provides_t_a[j].copy()
                    provides_t_a[j].add((binary, prov_version))
                if not equivalent_replacement:
                    # all the reverse dependencies are affected by the change
                    affected_pos.add(updated_pkg_id)
                    affected_remain.update(inst_tester.negative_dependencies_of(updated_pkg_id))

            # add/update the source package
            if item.architecture == 'source':
                sources['testing'][item.package] = sources[item.suite][item.package]

        # Also include the transitive rdeps of the packages found so far
        compute_reverse_tree(inst_tester, affected_pos)
        compute_reverse_tree(inst_tester, affected_remain)
        # return the package name, the suite, the list of affected packages and the undo dictionary
        return (affected_pos, affected_remain, undo)

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
            affected_pos, affected_remain, undo = self.doop_source(item, hint_undo=lundo)
            undo_list = [(undo, item)]
            if item.architecture == 'source':
                affected_architectures = set(self.options.architectures)
            else:
                affected_architectures.add(item.architecture)
        else:
            undo_list = []
            removals = set()
            affected_pos = set()
            affected_remain = set()
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
                item_affected_pos, item_affected_remain, undo = self.doop_source(item,
                                                                                 hint_undo=lundo,
                                                                                 removals=removals)
                affected_pos.update(item_affected_pos)
                affected_remain.update(item_affected_remain)
                undo_list.append((undo, item))

        # Optimise the test if we may revert directly.
        # - The automatic-revert is needed since some callers (notably via hints) may
        #   accept the outcome of this migration and expect nuninst to be updated.
        #   (e.g. "force-hint" or "hint")
        if automatic_revert:
            affected_remain -= affected_pos
        else:
            affected_remain |= affected_pos
            affected_pos = set()

        # Copy nuninst_comp - we have to deep clone affected
        # architectures.

        # NB: We do this *after* updating testing as we have to filter out
        # removed binaries.  Otherwise, uninstallable binaries that were
        # removed by the item would still be counted.

        nuninst_after = clone_nuninst(nuninst_now, packages_t, affected_architectures)
        must_be_installable = self.constraints['keep-installable']

        # check the affected packages on all the architectures
        for arch in affected_architectures:
            check_archall = arch in nobreakall_arches

            check_installability(self._inst_tester, packages_t, arch, affected_pos, affected_remain,
                                 check_archall, nuninst_after)

            # if the uninstallability counter is worse than before, break the loop
            if automatic_revert:
                worse = False
                if len(nuninst_after[arch]) > len(nuninst_now[arch]):
                    worse = True
                else:
                    regression = nuninst_after[arch] - nuninst_now[arch]
                    if not regression.isdisjoint(must_be_installable):
                        worse = True
                # ... except for a few special cases
                if worse and ((item.architecture != 'source' and arch not in new_arches) or
                   (arch not in break_arches)):
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
        rescheduled_packages = packages
        maybe_rescheduled_packages = []

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
        while rescheduled_packages:
            groups = {group_info[x] for x in rescheduled_packages}
            worklist = self._inst_tester.solve_groups(groups)
            rescheduled_packages = []

            worklist.reverse()

            while worklist:
                comp = worklist.pop()
                comp_name = ' '.join(item.uvname for item in comp)
                self.output_write("trying: %s\n" % comp_name)
                accepted, nuninst_after, comp_undo, failed_arch = self.try_migration(comp, nuninst_last_accepted, lundo)
                if accepted:
                    selected.extend(comp)
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
                    rescheduled_packages.extend(maybe_rescheduled_packages)
                    maybe_rescheduled_packages.clear()
                else:
                    broken = sorted(b for b in nuninst_after[failed_arch]
                                    if b not in nuninst_last_accepted[failed_arch])
                    compare_nuninst = None
                    if any(item for item in comp if item.architecture != 'source'):
                        compare_nuninst = nuninst_last_accepted
                    # NB: try_migration already reverted this for us, so just print the results and move on
                    self.output_write("skipped: %s (%d, %d, %d)\n" % (comp_name, len(rescheduled_packages),
                                                                      len(maybe_rescheduled_packages), len(worklist)))
                    self.output_write("    got: %s\n" % (self.eval_nuninst(nuninst_after, compare_nuninst)))
                    self.output_write("    * %s: %s\n" % (failed_arch, ", ".join(broken)))

                    if len(comp) > 1:
                        self.output_write("    - splitting the component into single items and retrying them\n")
                        worklist.extend([item] for item in comp)
                    else:
                        maybe_rescheduled_packages.append(comp[0])

        self.output_write(" finish: [%s]\n" % ",".join( x.uvname for x in selected ))
        self.output_write("endloop: %s\n" % (self.eval_nuninst(self.nuninst_orig)))
        self.output_write("    now: %s\n" % (self.eval_nuninst(nuninst_last_accepted)))
        self.output_write(eval_uninst(self.options.architectures,
                                      newly_uninst(self.nuninst_orig, nuninst_last_accepted)))
        self.output_write("\n")

        return (nuninst_last_accepted, maybe_rescheduled_packages)


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
                                              newly_uninst(nuninst_start, nuninst_end)))

        if not force:
            break_arches = set(self.options.break_arches)
            if all(x.architecture in break_arches for x in selected):
                # If we only migrated items from break-arches, then we
                # do not allow any regressions on these architectures.
                # This usually only happens with hints
                break_arches = set()
            better = is_nuninst_asgood_generous(self.constraints,
                                                self.options.architectures,
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
                                              newly_uninst(nuninst_start, nuninst_end)))
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

        self.output_write("\n")

    def assert_nuninst_is_correct(self):
        self.log("> Update complete - Verifying non-installability counters", type="I")

        cached_nuninst = self.nuninst_orig
        self._inst_tester.compute_testing_installability()
        computed_nuninst = self.get_nuninst(build=True)
        if cached_nuninst != computed_nuninst:
            only_on_break_archs = True
            self.log("==================== NUNINST OUT OF SYNC =========================", type="E")
            for arch in self.options.architectures:
                expected_nuninst = set(cached_nuninst[arch])
                actual_nuninst = set(computed_nuninst[arch])
                false_negatives = actual_nuninst - expected_nuninst
                false_positives = expected_nuninst - actual_nuninst
                # Britney does not quite work correctly with
                # break/fucked arches, so ignore issues there for now.
                if (false_negatives or false_positives) and arch not in self.options.break_arches:
                    only_on_break_archs = False
                if false_negatives:
                    self.log(" %s - unnoticed nuninst: %s" % (arch, str(false_negatives)), type="E")
                if false_positives:
                    self.log(" %s - invalid nuninst: %s" % (arch, str(false_positives)), type="E")
                self.log(" %s - actual nuninst: %s" % (arch, str(actual_nuninst)), type="I")
                self.log("==================== NUNINST OUT OF SYNC =========================", type="E")
            if not only_on_break_archs:
                raise AssertionError("NUNINST OUT OF SYNC")
            else:
                self.log("Nuninst is out of sync on some break arches",
                         type="W")

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

        if getattr(self.options, "remove_obsolete", "yes") == "yes":
            # obsolete source packages
            # a package is obsolete if none of the binary packages in testing
            # are built by it
            self.log("> Removing obsolete source packages from testing", type="I")
            # local copies for performance
            sources = self.sources['testing']
            binaries = self.binaries['testing']
            used = set(binaries[arch][0][binary].source
                         for arch in binaries
                         for binary in binaries[arch][0]
                      )
            removals = [ MigrationItem("-%s/%s" % (source, sources[source].version))
                         for source in sources if source not in used
                       ]
            if removals:
                self.output_write("Removing obsolete source packages from testing (%d):\n" % (len(removals)))
                self.do_all(actions=removals)

        # smooth updates
        removals = old_libraries(self.sources, self.binaries, self.options.outofsync_arches)
        if self.options.smooth_updates:
            self.log("> Removing old packages left in testing from smooth updates", type="I")
            if removals:
                self.output_write("Removing packages left in testing for smooth updates (%d):\n%s" % \
                    (len(removals), old_libraries_format(removals)))
                self.do_all(actions=removals)
                removals = old_libraries(self.sources, self.binaries, self.options.outofsync_arches)
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
                         self.suite_info['testing'].path)
                write_controlfiles(self.sources, self.binaries,
                                   'testing', self.suite_info['testing'].path)

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
        from britney2.completer import Completer

        histfile = os.path.expanduser('~/.britney2_history')
        if os.path.exists(histfile):
            readline.read_history_file(histfile)

        readline.parse_and_bind('tab: complete')
        readline.set_completer(Completer(self).completer)
        # Package names can contain "-" and we use "/" in our presentation of them as well,
        # so ensure readline does not split on these characters.
        readline.set_completer_delims(readline.get_completer_delims().replace('-', '').replace('/', ''))

        known_hints = self._hint_parser.registered_hints

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
                # run a hint
            elif user_input and user_input[0] in ('easy', 'hint', 'force-hint'):
                try:
                    self.do_hint(user_input[0], 'hint-tester',
                                 [k.rsplit("/", 1) for k in user_input[1:] if "/" in k])
                    self.printuninstchange()
                except KeyboardInterrupt:
                    continue
            elif user_input and user_input[0] in known_hints:
                self._hint_parser.parse_hints('hint-tester', self.HINTS_ALL, '<stdin>', [' '.join(user_input)])
                self.write_excuses()

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
            rightversion = inunstable and (apt_pkg.version_compare(self.sources['unstable'][pkg.package].version, pkg.version) == 0)
            if pkg.suite == 'unstable' and not rightversion:
                for suite in ['pu', 'tpu']:
                    if pkg.package in self.sources[suite] and apt_pkg.version_compare(self.sources[suite][pkg.package].version, pkg.version) == 0:
                        pkg.suite = suite
                        _pkgvers[idx] = pkg
                        break

            # handle *-proposed-updates
            if pkg.suite in ['pu', 'tpu']:
                if pkg.package not in self.sources[pkg.suite]: continue
                if apt_pkg.version_compare(self.sources[pkg.suite][pkg.package].version, pkg.version) != 0:
                    self.output_write(" Version mismatch, %s %s != %s\n" % (pkg.package, pkg.version, self.sources[pkg.suite][pkg.package].version))
                    ok = False
            # does the package exist in unstable?
            elif not inunstable:
                self.output_write(" Source %s has no version in unstable\n" % pkg.package)
                ok = False
            elif not rightversion:
                self.output_write(" Version mismatch, %s %s != %s\n" % (pkg.package, pkg.version, self.sources['unstable'][pkg.package].version))
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
        self.log("> Processing hints from the auto hinter", type="I")

        sources_t = self.sources['testing']
        excuses = self.excuses

        # consider only excuses which are valid candidates and still relevant.
        valid_excuses = frozenset(y.uvname for y in self.upgrade_me
                                  if y not in sources_t or sources_t[y].version != excuses[y].ver[1])
        excuses_deps = {name: valid_excuses.intersection(excuse.deps)
                        for name, excuse in excuses.items() if name in valid_excuses}
        excuses_rdeps = defaultdict(set)
        for name, deps in excuses_deps.items():
            for dep in deps:
                excuses_rdeps[dep].add(name)

        def find_related(e, hint, circular_first=False):
            excuse = excuses[e]
            if not circular_first:
                hint[e] = excuse.ver[1]
            if not excuse.deps:
                return hint
            for p in excuses_deps[e]:
                if p in hint or p not in valid_excuses:
                    continue
                if not find_related(p, hint):
                    return False
            return hint

        # loop on them
        candidates = []
        mincands = []
        seen_hints = set()
        for e in valid_excuses:
            excuse = excuses[e]
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
                    new_items = set((x, excuses[x].ver[1]) for x in excuses_deps[item])
                    new_items.update((x, excuses[x].ver[1]) for x in excuses_rdeps[item])
                    new_items -= seen_items
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
            all[(pkg.source, pkg.source_version)].add(p)

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
