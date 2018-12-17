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
import logging
import optparse
import os
import sys
import time
from collections import defaultdict
from functools import reduce
from itertools import chain
from operator import attrgetter
from urllib.parse import quote

import apt_pkg

from britney2 import SourcePackage, BinaryPackageId, BinaryPackage
from britney2.excuse import Excuse
from britney2.hints import HintParser
from britney2.inputs.suiteloader import DebMirrorLikeSuiteContentLoader, MissingRequiredConfigurationError
from britney2.installability.builder import build_installability_tester
from britney2.installability.solver import InstallabilitySolver
from britney2.migrationitem import MigrationItem
from britney2.policies import PolicyVerdict
from britney2.policies.policy import AgePolicy, RCBugPolicy, PiupartsPolicy, BuildDependsPolicy
from britney2.policies.autopkgtest import AutopkgtestPolicy
from britney2.transaction import start_transaction
from britney2.utils import (log_and_format_old_libraries,
                            compute_reverse_tree, get_dependency_solvers,
                            read_nuninst, write_nuninst, write_heidi,
                            format_and_log_uninst, newly_uninst, make_migrationitem,
                            write_excuses, write_heidi_delta, write_controlfiles,
                            old_libraries, is_nuninst_asgood_generous,
                            clone_nuninst, check_installability,
                            invalidate_excuses, compile_nuninst,
                            find_smooth_updateable_binaries, parse_provides,
                            MigrationConstraintException,
                            )

__author__ = 'Fabio Tranchitella and the Debian Release Team'
__version__ = '2.0'


class Britney(object):
    """Britney, the Debian testing updater script
    
    This is the script that updates the testing distribution. It is executed
    each day after the installation of the updated packages. It generates the 
    `Packages' files for the testing distribution, but it does so in an
    intelligent manner; it tries to avoid any inconsistency and to use only
    non-buggy packages.

    For more documentation on this script, please read the Developers Reference.
    """

    HINTS_HELPERS = ("easy", "hint", "remove", "block", "block-udeb", "unblock", "unblock-udeb", "approve",
                     "remark", "ignore-piuparts", "ignore-rc-bugs", "force-skiptest", "force-badtest")
    HINTS_STANDARD = ("urgent", "age-days") + HINTS_HELPERS
    # ALL = {"force", "force-hint", "block-all"} | HINTS_STANDARD | registered policy hints (not covered above)
    HINTS_ALL = ('ALL')

    def __init__(self):
        """Class constructor

        This method initializes and populates the data lists, which contain all
        the information needed by the other methods of the class.
        """

        # setup logging - provide the "short level name" (i.e. INFO -> I) that
        # we used to use prior to using the logging module.

        old_factory = logging.getLogRecordFactory()
        short_level_mapping = {
            'CRITICAL': 'F',
            'INFO': 'I',
            'WARNING': 'W',
            'ERROR': 'E',
            'DEBUG': 'N',
        }

        def record_factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            try:
                record.shortlevelname = short_level_mapping[record.levelname]
            except KeyError:
                record.shortlevelname = record.levelname
            return record

        logging.setLogRecordFactory(record_factory)
        logging.basicConfig(format='{shortlevelname}: [{asctime}] - {message}',
                            style='{',
                            datefmt="%Y-%m-%dT%H:%M:%S%z",
                            stream=sys.stdout,
                            )

        self.logger = logging.getLogger()

        # Logger for "upgrade_output"; the file handler will be attached later when
        # we are ready to open the file.
        self.output_logger = logging.getLogger('britney2.output.upgrade_output')
        self.output_logger.setLevel(logging.INFO)

        # initialize the apt_pkg back-end
        apt_pkg.init()

        # parse the command line arguments
        self.policies = []
        self._hint_parser = HintParser()
        self.suite_info = None  # Initialized during __parse_arguments
        self.__parse_arguments()
        MigrationItem.set_architectures(self.options.architectures)
        MigrationItem.set_suites(self.suite_info)

        self.all_selected = []
        self.excuses = {}

        try:
            self.read_hints(self.options.hintsdir)
        except AttributeError:
            self.read_hints(os.path.join(self.suite_info['unstable'].path, 'Hints'))

        if self.options.nuninst_cache:
            self.logger.info("Not building the list of non-installable packages, as requested")
            if self.options.print_uninst:
                nuninst = read_nuninst(self.options.noninst_status,
                                       self.options.architectures)
                print('* summary')
                print('\n'.join('%4d %s' % (len(nuninst[x]), x) for x in self.options.architectures))
                return

        try:
            constraints_file = os.path.join(self.options.static_input_dir, 'constraints')
            faux_packages = os.path.join(self.options.static_input_dir, 'faux-packages')
        except AttributeError:
            self.logger.info("The static_input_dir option is not set")
            constraints_file = None
            faux_packages = None
        if faux_packages is not None and os.path.exists(faux_packages):
            self.logger.info("Loading faux packages from %s", faux_packages)
            self._load_faux_packages(faux_packages)
        elif faux_packages is not None:
            self.logger.info("No Faux packages as %s does not exist", faux_packages)

        if constraints_file is not None and os.path.exists(constraints_file):
            self.logger.info("Loading constraints from %s", constraints_file)
            self.constraints = self._load_constraints(constraints_file)
        else:
            if constraints_file is not None:
                self.logger.info("No constraints as %s does not exist", constraints_file)
            self.constraints = {
                'keep-installable': [],
            }

        self.logger.info("Compiling Installability tester")
        self.pkg_universe, self._inst_tester = build_installability_tester(self.suite_info, self.options.architectures)
        target_suite = self.suite_info.target_suite
        target_suite.inst_tester = self._inst_tester

        if not self.options.nuninst_cache:
            self.logger.info("Building the list of non-installable packages for the full archive")
            self._inst_tester.compute_installability()
            nuninst = compile_nuninst(target_suite,
                                      self.options.architectures,
                                      self.options.nobreakall_arches)
            self.nuninst_orig = nuninst
            for arch in self.options.architectures:
                self.logger.info("> Found %d non-installable packages", len(nuninst[arch]))
                if self.options.print_uninst:
                    self.nuninst_arch_report(nuninst, arch)

            if self.options.print_uninst:
                print('* summary')
                print('\n'.join(map(lambda x: '%4d %s' % (len(nuninst[x]), x), self.options.architectures)))
                return
            else:
                write_nuninst(self.options.noninst_status, nuninst)

            stats = self._inst_tester.compute_stats()
            self.logger.info("> Installability tester statistics (per architecture)")
            for arch in self.options.architectures:
                arch_stat = stats[arch]
                self.logger.info(">  %s", arch)
                for stat in arch_stat.stat_summary():
                    self.logger.info(">  - %s", stat)
        else:
            self.logger.info("Loading uninstallability counters from cache")
            self.nuninst_orig = read_nuninst(self.options.noninst_status,
                                             self.options.architectures)

        # nuninst_orig may get updated during the upgrade process
        self.nuninst_orig_save = clone_nuninst(self.nuninst_orig, architectures=self.options.architectures)

        for policy in self.policies:
            policy.hints = self.hints
            policy.initialise(self)

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
        parser.add_option("", "--compute-migrations", action="store_true", dest="compute_migrations", default=True,
                          help="Compute which packages can migrate (the default)")
        parser.add_option("", "--no-compute-migrations", action="store_false", dest="compute_migrations",
                          help="Do not compute which packages can migrate.")
        parser.add_option("", "--series", action="store", dest="series", default='testing',
                               help="set distribution series name")
        (self.options, self.args) = parser.parse_args()

        if self.options.verbose:
            self.logger.setLevel(logging.INFO)
        else:
            self.logger.setLevel(logging.WARNING)
        # TODO: Define a more obvious toggle for debug information
        try:  # pragma: no cover
            if int(os.environ.get('BRITNEY_DEBUG', '0')):
                self.logger.setLevel(logging.DEBUG)
        except ValueError:  # pragma: no cover
            pass

        # integrity checks
        if self.options.nuninst_cache and self.options.print_uninst:  # pragma: no cover
            self.logger.error("nuninst_cache and print_uninst are mutually exclusive!")
            sys.exit(1)
        # if the configuration file exists, then read it and set the additional options
        elif not os.path.isfile(self.options.config):  # pragma: no cover
            self.logger.error("Unable to read the configuration file (%s), exiting!", self.options.config)
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

        if hasattr(self.options, 'components'):
            self.logger.error("The COMPONENTS configuration has been removed.")
            self.logger.error("Britney will read the value from the Release file automatically")
            sys.exit(1)

        suite_loader = DebMirrorLikeSuiteContentLoader(self.options)

        try:
            self.suite_info = suite_loader.load_suites()
        except MissingRequiredConfigurationError as e:
            self.logger.error("Could not load the suite content due to missing configuration: %s", str(e))
            sys.exit(1)
        self.all_binaries = suite_loader.all_binaries()
        self.options.components = suite_loader.components
        self.options.architectures = suite_loader.architectures
        self.options.nobreakall_arches = suite_loader.nobreakall_arches
        self.options.outofsync_arches = suite_loader.outofsync_arches
        self.options.break_arches = suite_loader.break_arches
        self.options.new_arches = suite_loader.new_arches

        if self.options.control_files and self.options.components:  # pragma: no cover
            # We cannot regenerate the control files correctly when reading from an
            # actual mirror (we don't which package goes in what component etc.).
            self.logger.error("Cannot use --control-files with mirror-layout (components)!")
            sys.exit(1)

        if not hasattr(self.options, "heidi_delta_output"):
            self.options.heidi_delta_output = self.options.heidi_output + "Delta"

        self.options.smooth_updates = self.options.smooth_updates.split()

        if not hasattr(self.options, 'ignore_cruft') or \
            self.options.ignore_cruft == "0":
            self.options.ignore_cruft = False

        if not hasattr(self.options, 'adt_retry_url_mech'):
            self.options.adt_retry_url_mech = ''

        self.policies.append(RCBugPolicy(self.options, self.suite_info))
        self.policies.append(PiupartsPolicy(self.options, self.suite_info))
        if getattr(self.options, 'adt_enable') == 'yes':
            self.policies.append(AutopkgtestPolicy(self.options, self.suite_info))
        self.policies.append(AgePolicy(self.options, self.suite_info, MINDAYS))
        self.policies.append(BuildDependsPolicy(self.options, self.suite_info))

        for policy in self.policies:
            policy.register_hints(self._hint_parser)

    @property
    def hints(self):
        return self._hint_parser.hints

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
        pri_source_suite = self.suite_info.primary_source_suite
        target_suite = self.suite_info.target_suite

        while step():
            no += 1
            pkg_name = get_field('Package', None)
            if pkg_name is None:  # pragma: no cover
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
                                     None,
                                     None,
                                     [],
                                     [],
                                     )

            target_suite.sources[pkg_name] = src_data
            pri_source_suite.sources[pkg_name] = src_data

            for arch in archs:
                pkg_id = BinaryPackageId(pkg_name, version, arch)
                if provides_raw:
                    provides = parse_provides(provides_raw, pkg_id=pkg_id, logger=self.logger)
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
                target_suite.binaries[arch][pkg_name] = bin_data
                pri_source_suite.binaries[arch][pkg_name] = bin_data
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
        pri_source_suite = self.suite_info.primary_source_suite
        target_suite = self.suite_info.target_suite

        while step():
            no += 1
            pkg_name = get_field('Fake-Package-Name', None)
            if pkg_name is None:  # pragma: no cover
                raise ValueError("Missing Fake-Package-Name field in paragraph %d (file %s)" % (no, constraints_file))
            pkg_name = sys.intern(pkg_name)

            def mandatory_field(x):
                v = get_field(x, None)
                if v is None:  # pragma: no cover
                    raise ValueError("Missing %s field for %s (file %s)" % (x, pkg_name, constraints_file))
                return v

            constraint = mandatory_field('Constraint')
            if constraint not in {'present-and-installable'}:  # pragma: no cover
                raise ValueError("Unsupported constraint %s for %s (file %s)" % (constraint, pkg_name, constraints_file))

            self.logger.info(" - constraint %s", pkg_name)

            pkg_list = [x.strip() for x in mandatory_field('Package-List').split("\n") if x.strip() != '' and not x.strip().startswith("#")]
            src_data = SourcePackage(faux_version,
                                     faux_section,
                                     [],
                                     None,
                                     True,
                                     None,
                                     None,
                                     [],
                                     [],
                                     )
            target_suite.sources[pkg_name] = src_data
            pri_source_suite.sources[pkg_name] = src_data
            keep_installable.append(pkg_name)
            for arch in self.options.architectures:
                deps = []
                for pkg_spec in pkg_list:
                    s = pkg_spec.split(None, 1)
                    if len(s) == 1:
                        deps.append(s[0])
                    else:
                        pkg, arch_res = s
                        if not (arch_res.startswith('[') and arch_res.endswith(']')):  # pragma: no cover
                            raise ValueError("Invalid arch-restriction on %s - should be [arch1 arch2] (for %s file %s)"
                                             % (pkg, pkg_name, constraints_file))
                        arch_res = arch_res[1:-1].split()
                        if not arch_res:  # pragma: no cover
                            msg = "Empty arch-restriction for %s: Uses comma or negation (for %s file %s)"
                            raise ValueError(msg % (pkg, pkg_name, constraints_file))
                        for a in arch_res:
                            if a == arch:
                                deps.append(pkg)
                            elif ',' in a or '!' in a:  # pragma: no cover
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
                target_suite.binaries[arch][pkg_name] = bin_data
                pri_source_suite.binaries[arch][pkg_name] = bin_data
                self.all_binaries[pkg_id] = bin_data

        return constraints

    # Data reading/writing methods
    # ----------------------------

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
                    self.logger.error("Cannot read hints list from %s, no such file!", filename)
                    continue
                self.logger.info("Loading hints list from %s", filename)
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
                            self.logger.warning("Overriding %s[%s] = ('%s', '%s') with ('%s', '%s')",
                                                x, package, hint2.version, hint2.user, hint.version, hint.user)
                            hint2.set_active(False)
                        else:
                            # This hint is for an older version, so ignore it in favour of the new one
                            self.logger.warning("Ignoring %s[%s] = ('%s', '%s'), ('%s', '%s') is higher or equal",
                                                x, package, hint.version, hint.user, hint2.version, hint2.user)
                            hint.set_active(False)
                    else:
                        self.logger.warning("Overriding %s[%s] = ('%s', '%s') with ('%s', '%s')",
                                            x, package, hint2.user, hint2, hint.user, hint)
                        hint2.set_active(False)

                z[package] = key

        # Sanity check the hints hash
        if len(hints["block"]) == 0 and len(hints["block-udeb"]) == 0:
            self.logger.warning("WARNING: No block hints at all, not even udeb ones!")

    # Utility methods for package analysis
    # ------------------------------------

    def excuse_unsat_deps(self, pkg, src, arch, source_suite, excuse, get_dependency_solvers=get_dependency_solvers):
        """Find unsatisfied dependencies for a binary package

        This method analyzes the dependencies of the binary package specified
        by the parameter `pkg', built from the source package `src', for the
        architecture `arch' within the suite `suite'. If the dependency can't
        be satisfied in testing and/or unstable, it updates the excuse passed
        as parameter.
        """
        # retrieve the binary package from the specified suite and arch
        target_suite = self.suite_info.target_suite
        binaries_s_a = source_suite.binaries[arch]
        provides_s_a = source_suite.provides_table[arch]
        binaries_t_a = target_suite.binaries[arch]
        provides_t_a = target_suite.provides_table[arch]
        binary_u = binaries_s_a[pkg]

        source_s = source_suite.sources[binary_u.source]
        if (binary_u.source_version != source_s.version):
            # we don't want cruft to block packages, so if this is cruft, we
            # can simply ignore it; if the cruft would migrate to testing, the
            # installability check will catch missing deps
            return True

        # local copies for better performance
        parse_depends = apt_pkg.parse_depends

        # analyze the dependency fields (if present)
        deps = binary_u.depends
        if not deps:
            return True
        is_all_ok = True

        # for every dependency block (formed as conjunction of disjunction)
        for block, block_txt in zip(parse_depends(deps, False), deps.split(',')):
            # if the block is satisfied in testing, then skip the block
            packages = get_dependency_solvers(block, binaries_t_a, provides_t_a)
            if packages:
                for p in packages:
                    if p.pkg_id.package_name not in binaries_s_a:
                        continue
                    excuse.add_sane_dep(p.source)
                continue

            # check if the block can be satisfied in the source suite, and list the solving packages
            packages = get_dependency_solvers(block, binaries_s_a, provides_s_a)
            packages = [p.source for p in packages]

            # if the dependency can be satisfied by the same source package, skip the block:
            # obviously both binary packages will enter testing together
            if src in packages: continue

            # if no package can satisfy the dependency, add this information to the excuse
            if not packages:
                excuse.addhtml("%s/%s unsatisfiable Depends: %s" % (pkg, arch, block_txt.strip()))
                excuse.add_unsatisfiable_dep(block_txt.strip(), arch)
                excuse.addreason("depends")
                excuse.add_unsatisfiable_on_arch(arch)
                if arch not in self.options.break_arches:
                    is_all_ok = False
                continue

            # for the solving packages, update the excuse to add the dependencies
            if arch not in self.options.break_arches:
                sources_t = target_suite.sources
                sources_s = source_suite.sources
                for p in packages:
                    if p in sources_t and sources_t[p].version == sources_s[p].version:
                        excuse.add_dep("%s/%s" % (p, arch), arch)
                    else:
                        excuse.add_dep(p, arch)
            else:
                for p in packages:
                    excuse.add_break_dep(p, arch)

        return is_all_ok

    # Package analysis methods
    # ------------------------

    def should_remove_source(self, pkg):
        """Check if a source package should be removed from testing
        
        This method checks if a source package should be removed from the
        target suite; this happens if the source package is not
        present in the primary source suite anymore.

        It returns True if the package can be removed, False otherwise.
        In the former case, a new excuse is appended to the object
        attribute excuses.
        """
        # if the source package is available in unstable, then do nothing
        source_suite = self.suite_info.primary_source_suite
        if pkg in source_suite.sources:
            return False
        # otherwise, add a new excuse for its removal
        src = self.suite_info.target_suite.sources[pkg]
        excuse = Excuse("-" + pkg)
        excuse.addhtml("Package not in %s, will try to remove" % source_suite.name)
        excuse.set_vers(src.version, None)
        src.maintainer and excuse.set_maint(src.maintainer)
        src.section and excuse.set_section(src.section)

        # if the package is blocked, skip it
        for hint in self.hints.search('block', package=pkg, removal=True):
            excuse.addhtml("Not touching package, as requested by %s "
                "(contact debian-release if update is needed)" % hint.user)
            excuse.addreason("block")
            self.excuses[excuse.name] = excuse
            return False

        excuse.policy_verdict = PolicyVerdict.PASS
        self.excuses[excuse.name] = excuse
        return True

    def should_upgrade_srcarch(self, src, arch, suite_name):
        """Check if a set of binary packages should be upgraded

        This method checks if the binary packages produced by the source
        package on the given architecture should be upgraded; this can
        happen also if the migration is a binary-NMU for the given arch.
       
        It returns False if the given packages don't need to be upgraded,
        True otherwise. In the former case, a new excuse is appended to
        the object attribute excuses.
        """
        # retrieve the source packages for testing and suite

        source_suite = self.suite_info[suite_name]
        target_suite = self.suite_info.target_suite
        source_t = target_suite.sources[src]
        source_u = source_suite.sources[src]
        suffix = ''
        if source_suite.excuses_suffix:
            suffix = "_%s" % source_suite.excuses_suffix

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

        packages_t_a = target_suite.binaries[arch]
        packages_s_a = source_suite.binaries[arch]

        # for every binary package produced by this source in unstable for this architecture
        for pkg_id in sorted(x for x in source_u.binaries if x.architecture == arch):
            pkg_name = pkg_id.package_name

            # retrieve the testing (if present) and unstable corresponding binary packages
            binary_t = packages_t_a[pkg_name] if pkg_name in packages_t_a else None
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
            self.excuse_unsat_deps(pkg_name, src, arch, source_suite, excuse)

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

        srcv = source_u.version
        same_source = source_t.version == srcv
        primary_source_suite = self.suite_info.primary_source_suite
        is_primary_source = source_suite == primary_source_suite

        # if there is nothing wrong and there is something worth doing or the source
        # package is not fake, then check what packages should be removed
        if not anywrongver and (anyworthdoing or not source_u.is_fakesrc):
            # we want to remove binaries that are no longer produced by the
            # new source, but there are some special cases:
            # - if this is binary-only (same_source) and not from the primary
            #   source, we don't do any removals:
            #   binNMUs in *pu on some architectures would otherwise result in
            #   the removal of binaries on other architectures
            # - for the primary source, smooth binaries in the target suite
            #   are not considered for removal
            if not same_source or is_primary_source:
                smoothbins = set()
                if is_primary_source:
                    binaries_t = target_suite.binaries
                    possible_smooth_updates = [p for p in source_u.binaries if p.architecture == arch]
                    smoothbins = find_smooth_updateable_binaries(possible_smooth_updates,
                                                                 source_suite.sources[src],
                                                                 self.pkg_universe,
                                                                 target_suite,
                                                                 binaries_t,
                                                                 source_suite.binaries,
                                                                 frozenset(),
                                                                 self.options.smooth_updates)

                # for every binary package produced by this source in testing for this architecture
                for pkg_id in sorted(x for x in source_t.binaries if x.architecture == arch):
                    pkg = pkg_id.package_name
                    # if the package is architecture-independent, then ignore it
                    tpkg_data = packages_t_a[pkg]
                    if tpkg_data.architecture == 'all':
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
                        if same_source and pkg_id not in smoothbins:
                            # Special-case, if the binary is a candidate for a smooth update, we do not consider
                            # it "interesting" on its own.  This case happens quite often with smooth updatable
                            # packages, where the old binary "survives" a full run because it still has
                            # reverse dependencies.
                            anyworthdoing = True

        if anyworthdoing and same_source and not is_primary_source:
            # support for binNMUs from *pu is currently broken, so disable it
            # for now
            # see https://bugs.debian.org/916209 for more info
            excuse.addhtml("Ignoring binaries for %s from %s on %s (see https://bugs.debian.org/916209)" % (src, source_suite.name, arch))
            self.excuses[excuse.name] = excuse
            return False

        # if there is nothing wrong and there is something worth doing, this is a valid candidate
        if not anywrongver and anyworthdoing:
            excuse.policy_verdict = PolicyVerdict.PASS
            self.excuses[excuse.name] = excuse
            return True
        # else if there is something worth doing (but something wrong, too) this package won't be considered
        elif anyworthdoing:
            self.excuses[excuse.name] = excuse

        # otherwise, return False
        return False

    def should_upgrade_src(self, src, suite_name):
        """Check if source package should be upgraded

        This method checks if a source package should be upgraded. The analysis
        is performed for the source package specified by the `src' parameter, 
        for the distribution `suite_name'.
       
        It returns False if the given package doesn't need to be upgraded,
        True otherwise. In the former case, a new excuse is appended to
        the object attribute excuses.
        """

        source_suite = self.suite_info[suite_name]
        source_u = source_suite.sources[src]
        if source_u.is_fakesrc:
            # it is a fake package created to satisfy Britney implementation details; silently ignore it
            return False

        target_suite = self.suite_info.target_suite
        # retrieve the source packages for testing (if available) and suite
        if src in target_suite.sources:
            source_t = target_suite.sources[src]
            # if testing and unstable have the same version, then this is a candidate for binary-NMUs only
            if apt_pkg.version_compare(source_t.version, source_u.version) == 0:
                return False
        else:
            source_t = None

        suffix = ''
        if source_suite.excuses_suffix:
            suffix = "_%s" % source_suite.excuses_suffix

        # build the common part of the excuse, which will be filled by the code below
        ref = "%s%s" % (src, suffix)
        excuse = Excuse(ref)
        excuse.set_vers(source_t and source_t.version or None, source_u.version)
        source_u.maintainer and excuse.set_maint(source_u.maintainer)
        source_u.section and excuse.set_section(source_u.section)

        # if the version in unstable is older, then stop here with a warning in the excuse and return False
        if source_t and apt_pkg.version_compare(source_u.version, source_t.version) < 0:
            excuse.addhtml("ALERT: %s is newer in the target suite (%s %s)" % (src, source_t.version, source_u.version))
            self.excuses[excuse.name] = excuse
            excuse.addreason("newerintesting")
            return False

        # the starting point is that we will update the candidate
        excuse.policy_verdict = PolicyVerdict.PASS

        # if there is a `remove' hint and the requested version is the same as the
        # version in testing, then stop here and return False
        for hint in self.hints.search('remove', package=src):
            if source_t and source_t.version == hint.version or \
               source_u.version == hint.version:
                excuse.add_hint(hint)
                excuse.addhtml("Removal request by %s" % (hint.user))
                excuse.addhtml("Trying to remove package, not update it")
                excuse.policy_verdict = PolicyVerdict.REJECTED_PERMANENTLY
                break

        # check if there is a `block' or `block-udeb' hint for this package, or a `block-all source' hint
        blocked = {}
        for hint in self.hints.search(package=src):
            if hint.type in {'block', 'block-udeb'}:
                blocked[hint.type] = hint
                excuse.add_hint(hint)

        if 'block' not in blocked:
            for hint in self.hints.search(type='block-all'):
                if hint.package == 'source' or (not source_t and hint.package == 'new-source'):
                    blocked['block'] = hint
                    excuse.add_hint(hint)
                    break
        if source_suite.suite_class.is_additional_source:
            blocked['block'] = '%s-block' % (suite_name)
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
                if source_suite.suite_class.is_primary_source or block_cmd == 'block-udeb':
                    tooltip = "please contact debian-release if update is needed"
                    # redirect people to d-i RM for udeb things:
                    if block_cmd == 'block-udeb':
                        tooltip = "please contact the d-i release manager if an update is needed"
                    excuse.addhtml("Not touching package due to %s request by %s (%s)" %
                                   (block_cmd, blocked[block_cmd].user, tooltip))
                    excuse.addreason("block")
                else:
                    excuse.addhtml("NEEDS APPROVAL BY RM")
                    excuse.addreason("block")
                excuse.policy_verdict = PolicyVerdict.REJECTED_NEEDS_APPROVAL

        all_binaries = self.all_binaries
        for pkg_id in source_u.binaries:
            is_valid = self.excuse_unsat_deps(pkg_id.package_name, src, pkg_id.architecture, source_suite, excuse)
            if is_valid:
                continue

            binary_u = all_binaries[pkg_id]
            # There is an issue with the package.  If it is arch:any, then excuse_unsat_deps will have
            # handled everything for us correctly.  However, arch:all have some special-casing IRT
            # nobreakall that we deal with ourselves here.
            if binary_u.architecture == 'all' and pkg_id.architecture in self.options.nobreakall_arches:
                # We sometimes forgive uninstallable arch:all packages on nobreakall architectures
                # (e.g. we sometimes force-hint in arch:all packages that are only installable on
                #  on a subset of all nobreak architectures).
                # This forgivness is only done if the package is already in testing AND it is broken
                # in testing on this architecture already.  Anything else would be a regression
                if target_suite.is_pkg_in_the_suite(pkg_id) and not target_suite.is_installable(pkg_id):
                    # It is a regression.
                    excuse.policy_verdict = PolicyVerdict.REJECTED_PERMANENTLY

        # at this point, we check the status of the builds on all the supported architectures
        # to catch the out-of-date ones
        archs_to_consider = list(self.options.architectures)
        archs_to_consider.append('all')
        for arch in archs_to_consider:
            oodbins = {}
            uptodatebins = False
            # for every binary package produced by this source in the suite for this architecture
            if arch == 'all':
                consider_binaries = source_u.binaries
            else:
                # Will also include arch:all for the given architecture (they are filtered out
                # below)
                consider_binaries = sorted(x for x in source_u.binaries if x.architecture == arch)
            for pkg_id in consider_binaries:
                pkg = pkg_id.package_name

                # retrieve the binary package and its source version
                binary_u = all_binaries[pkg_id]
                pkgsv = binary_u.source_version

                # arch:all packages are treated separately from arch:arch
                if binary_u.architecture != arch:
                    continue

                # if it wasn't built by the same source, it is out-of-date
                # if there is at least one binary on this arch which is
                # up-to-date, there is a build on this arch
                if source_u.version != pkgsv:
                    if pkgsv not in oodbins:
                        oodbins[pkgsv] = set()
                    oodbins[pkgsv].add(pkg)
                    excuse.add_old_binary(pkg, pkgsv)
                    continue
                else:
                    uptodatebins = True

            # if there are out-of-date packages, warn about them in the excuse and set excuse.is_valid
            # to False to block the update; if the architecture where the package is out-of-date is
            # in the `outofsync_arches' list, then do not block the update
            if oodbins:
                oodtxt = ""
                for v in oodbins:
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
                            excuse.policy_verdict = PolicyVerdict.REJECTED_PERMANENTLY
                    else:
                        excuse.policy_verdict = PolicyVerdict.REJECTED_CANNOT_DETERMINE_IF_PERMANENT
                        excuse.missing_build_on_arch(arch)

                excuse.addhtml(text)

        # if the source package has no binaries, set is_valid to False to block the update
        if not source_u.binaries:
            excuse.addhtml("%s has no binaries on any arch" % src)
            excuse.addreason("no-binaries")
            excuse.policy_verdict = PolicyVerdict.REJECTED_PERMANENTLY

        policy_verdict = excuse.policy_verdict
        policy_info = excuse.policy_info
        suite_class = source_suite.suite_class
        for policy in self.policies:
            if suite_class in policy.applicable_suites:
                v = policy.apply_policy(policy_info, suite_name, src, source_t, source_u, excuse)
                if v.value > policy_verdict.value:
                    policy_verdict = v
        excuse.policy_verdict = policy_verdict

        if source_suite.suite_class.is_additional_source and source_t:
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
                if any(x for x in source_suite.binaries[arch].values()
                       if x.source == src and x.source_version == source_u.version and
                          x.architecture != 'all'):
                    continue

                # TODO: Find a way to avoid hardcoding pu/stable relation.
                if suite_name == 'pu':
                    base = 'stable'
                else:
                    base = target_suite.name
                text = "Not yet built on <a href=\"https://buildd.debian.org/status/logs.php?arch=%s&pkg=%s&ver=%s&suite=%s\" target=\"_blank\">%s</a> (relative to target suite)" % (quote(arch), quote(src), quote(source_u.version), base, arch)

                if arch in self.options.outofsync_arches:
                    text = text + " (but %s isn't keeping up, so never mind)" % (arch)
                    excuse.missing_build_on_ood_arch(arch)
                else:
                    excuse.policy_verdict = PolicyVerdict.REJECTED_CANNOT_DETERMINE_IF_PERMANENT
                    excuse.missing_build_on_arch(arch)

                excuse.addhtml(text)

        # check if there is a `force' hint for this package, which allows it to go in even if it is not updateable
        forces = self.hints.search('force', package=src, version=source_u.version)
        if forces:
            # force() updates the final verdict for us
            changed_state = excuse.force()
            if changed_state:
                excuse.addhtml("Should ignore, but forced by %s" % (forces[0].user))

        self.excuses[excuse.name] = excuse
        return excuse.is_valid
 
    def write_excuses(self):
        """Produce and write the update excuses

        This method handles the update excuses generation: the packages are
        looked at to determine whether they are valid candidates. For the details
        of this procedure, please refer to the module docstring.
        """

        self.logger.info("Update Excuses generation started")

        # list of local methods and variables (for better performance)
        suite_info = self.suite_info
        pri_source_suite = suite_info.primary_source_suite
        architectures = self.options.architectures
        should_remove_source = self.should_remove_source
        should_upgrade_srcarch = self.should_upgrade_srcarch
        should_upgrade_src = self.should_upgrade_src

        sources_s = pri_source_suite.sources
        sources_t = suite_info.target_suite.sources

        # this list will contain the packages which are valid candidates;
        # if a package is going to be removed, it will have a "-" prefix
        upgrade_me = set()
        upgrade_me_add = upgrade_me.add  # Every . in a loop slows it down

        excuses = self.excuses = {}

        # for every source package in testing, check if it should be removed
        for pkg in sources_t:
            if should_remove_source(pkg):
                upgrade_me_add("-" + pkg)

        # for every source package in unstable check if it should be upgraded
        for pkg in sources_s:
            if sources_s[pkg].is_fakesrc:
                continue
            # if the source package is already present in testing,
            # check if it should be upgraded for every binary package
            if pkg in sources_t and not sources_t[pkg].is_fakesrc:
                for arch in architectures:
                    if should_upgrade_srcarch(pkg, arch, pri_source_suite.name):
                        upgrade_me_add("%s/%s" % (pkg, arch))

            # check if the source package should be upgraded
            if should_upgrade_src(pkg, pri_source_suite.name):
                upgrade_me_add(pkg)

        # for every source package in the additional source suites, check if it should be upgraded
        for suite in self.suite_info.additional_source_suites:
            for pkg in suite.sources:
                # if the source package is already present in testing,
                # check if it should be upgraded for every binary package
                if pkg in sources_t:
                    for arch in architectures:
                        if should_upgrade_srcarch(pkg, arch, suite.name):
                            upgrade_me_add("%s/%s_%s" % (pkg, arch, suite.excuses_suffix))

                # check if the source package should be upgraded
                if should_upgrade_src(pkg, suite.name):
                    upgrade_me_add("%s_%s" % (pkg, suite.excuses_suffix))

        # process the `remove' hints, if the given package is not yet in upgrade_me
        for hint in self.hints['remove']:
            src = hint.package
            if src in upgrade_me: continue
            if ("-"+src) in upgrade_me: continue
            if src not in sources_t:
                continue

            # check if the version specified in the hint is the same as the considered package
            tsrcv = sources_t[src].version
            if tsrcv != hint.version:
                continue

            # add the removal of the package to upgrade_me and build a new excuse
            excuse = Excuse("-%s" % (src))
            excuse.set_vers(tsrcv, None)
            excuse.addhtml("Removal request by %s" % (hint.user))
            # if the removal of the package is blocked, skip it
            blocked = False
            for blockhint in self.hints.search('block', package=src, removal=True):
                excuse.addhtml("Not removing package, due to block hint by %s "
                    "(contact debian-release if update is needed)" % blockhint.user)
                excuse.addreason("block")
                blocked = True

            if blocked:
                excuses[excuse.name] = excuse
                continue

            upgrade_me_add("-%s" % (src))
            excuse.addhtml("Package is broken, will try to remove")
            excuse.add_hint(hint)
            # Using "PASS" here as "Created by a hint" != "accepted due to hint".  In a future
            # where there might be policy checks on removals, it would make sense to distinguish
            # those two states.  Not sure that future will ever be.
            excuse.policy_verdict = PolicyVerdict.PASS
            excuses[excuse.name] = excuse

        # extract the not considered packages, which are in the excuses but not in upgrade_me
        unconsidered = {ename for ename in excuses if ename not in upgrade_me}

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
        invalidate_excuses(excuses, upgrade_me, unconsidered)

        # sort the list of candidates
        self.upgrade_me = sorted(make_migrationitem(x, suite_info) for x in upgrade_me)

        # write excuses to the output file
        if not self.options.dry_run:
            self.logger.info("> Writing Excuses to %s", self.options.excuses_output)
            sorted_excuses = sorted(excuses.values(), key=lambda x: x.sortkey())
            write_excuses(sorted_excuses, self.options.excuses_output,
                          output_format="legacy-html")
            if hasattr(self.options, 'excuses_yaml_output'):
                self.logger.info("> Writing YAML Excuses to %s", self.options.excuses_yaml_output)
                write_excuses(sorted_excuses, self.options.excuses_yaml_output,
                              output_format="yaml")

        self.logger.info("Update Excuses generation completed")

    # Upgrade run
    # -----------

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

    def _compute_groups(self, source_name, source_suite, migration_architecture,
                        is_removal,
                        allow_smooth_updates=True,
                        removals=frozenset()):
        """Compute the groups of binaries being migrated by item

        This method will compute the binaries that will be added to,
        replaced in or removed from the target suite and which of
        the removals are smooth updatable.

        Parameters:
        * "source_name" is the name of the source package, whose
          binaries are migrating.
        * "suite" is the source suite from which the binaries are migrating.
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
        target_suite = self.suite_info.target_suite
        binaries_s = source_suite.binaries
        binaries_t = target_suite.binaries
        pkg_universe = self.pkg_universe

        adds = set()
        rms = set()
        smoothbins = set()

        # remove all binary packages (if the source already exists)
        if migration_architecture == 'source' or not is_removal:
            sources_t = target_suite.sources
            if source_name in sources_t:
                source_data = sources_t[source_name]

                bins = []
                # remove all the binaries

                # first, build a list of eligible binaries
                for pkg_id in source_data.binaries:
                    binary, _, parch = pkg_id
                    if migration_architecture != 'source' and parch != migration_architecture:
                        continue

                    # Work around #815995
                    if migration_architecture == 'source' and is_removal and binary not in binaries_t[parch]:
                        continue

                    # Do not include hijacked binaries
                    if binaries_t[parch][binary].source != source_name:
                        continue
                    bins.append(pkg_id)

                if allow_smooth_updates and source_suite.suite_class.is_primary_source:
                    smoothbins = find_smooth_updateable_binaries(bins,
                                                                 source_suite.sources[source_name],
                                                                 pkg_universe,
                                                                 target_suite,
                                                                 binaries_t,
                                                                 binaries_s,
                                                                 removals,
                                                                 self.options.smooth_updates)

                # remove all the binaries which aren't being smooth updated
                for pkg_id in (pkg_id for pkg_id in bins if pkg_id not in smoothbins):
                    binary, _, parch = pkg_id
                    # if this is a binary migration from *pu, only the arch:any
                    # packages will be present. ideally dak would also populate
                    # the arch-indep packages, but as that's not the case we
                    # must keep them around; they will not be re-added by the
                    # migration so will end up missing from testing
                    if migration_architecture != 'source' and \
                         source_suite.suite_class.is_additional_source and \
                         binaries_t[parch][binary].architecture == 'all':
                        continue
                    else:
                        rms.add(pkg_id)

        # single binary removal; used for clearing up after smooth
        # updates but not supported as a manual hint
        else:
            assert source_name in binaries_t[migration_architecture]
            pkg_id = binaries_t[migration_architecture][source_name].pkg_id
            rms.add(pkg_id)

        # add the new binary packages (if we are not removing)
        if not is_removal:
            source_data = source_suite.sources[source_name]
            source_ver_new = source_data.version
            if source_name in sources_t:
                source_data_old = sources_t[source_name]
                source_ver_old = source_data_old.version
                if apt_pkg.version_compare(source_ver_old,source_ver_new) > 0:
                    raise MigrationConstraintException("trying src:%s %s, while %s has %s"%(source_name,source_ver_new,target_suite.name,source_ver_old))

            for pkg_id in source_data.binaries:
                binary, ver, parch = pkg_id
                if migration_architecture not in ['source', parch]:
                    continue

                if binaries_s[parch][binary].source != source_name:
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

                # Don't add the binary if it is cruft; smooth updates will keep it if possible
                if (parch not in self.options.outofsync_arches and
                        source_data.version != binaries_s[parch][binary].source_version):
                    continue

                if binary in binaries_t[parch]:
                    oldver = binaries_t[parch][binary].version
                    if apt_pkg.version_compare(oldver,ver) > 0:
                        raise MigrationConstraintException("trying %s %s from src:%s %s, while %s has %s"
                            %(binary,ver,source_name,source_ver_new,target_suite.name,oldver))

                adds.add(pkg_id)

        return (adds, rms, smoothbins)

    def doop_source(self, item, transaction, removals=frozenset()):
        """Apply a change to the target suite as requested by `item`

        A transaction in which all changes will be recorded.  Can be None (e.g.
        during a "force-hint"), when the changes will not be rolled back.

        An optional set of binaries may be passed in "removals". Binaries listed
        in this set will be assumed to be removed at the same time as the "item"
        will migrate.  This may change what binaries will be smooth-updated.
        - Binaries in this set must be instances of BinaryPackageId.

        This method applies the changes required by the action `item` tracking
        them so it will be possible to revert them.

        The method returns a tuple containing a set of packages
        affected by the change (as (name, arch)-tuples) and the
        dictionary undo which can be used to rollback the changes.
        """
        undo = {'binaries': {}, 'sources': {}, 'virtual': {}, 'nvirtual': []}

        affected_direct = set()
        updated_binaries = set()

        # local copies for better performance
        source_suite = item.suite
        target_suite = self.suite_info.target_suite
        packages_t = target_suite.binaries
        provides_t = target_suite.provides_table
        pkg_universe = self.pkg_universe
        eqv_set = set()

        updates, rms, _ = self._compute_groups(item.package,
                                               source_suite,
                                               item.architecture,
                                               item.is_removal,
                                               removals=removals)

        # Handle the source package
        if item.architecture == 'source':
            sources_t = target_suite.sources
            if item.package in sources_t:
                source = sources_t[item.package]
                undo['sources'][item.package] = source
                del sources_t[item.package]
            else:
                # the package didn't exist, so we mark it as to-be-removed in case of undo
                undo['sources']['-' + item.package] = True

            # add/update the source package
            if not item.is_removal:
                sources_t[item.package] = source_suite.sources[item.package]

        # If we are removing *and* updating packages, then check for eqv. packages
        if rms and updates:
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
                    if pkg_universe.are_equivalent(new_pkg_id, old_pkg_id):
                        eqv_set.add(key)

        # remove all the binaries which aren't being smooth updated
        for rm_pkg_id in rms:
            binary, version, parch = rm_pkg_id
            pkey = (binary, parch)
            binaries_t_a = packages_t[parch]
            provides_t_a = provides_t[parch]

            pkg_data = binaries_t_a[binary]
            # save the old binary for undo
            undo['binaries'][pkey] = rm_pkg_id
            if pkey not in eqv_set:
                # all the reverse dependencies are affected by
                # the change
                affected_direct.update(pkg_universe.reverse_dependencies_of(rm_pkg_id))
                affected_direct.update(pkg_universe.negative_dependencies_of(rm_pkg_id))

            # remove the provided virtual packages
            for provided_pkg, prov_version, _ in pkg_data.provides:
                key = (provided_pkg, parch)
                if key not in undo['virtual']:
                    undo['virtual'][key] = provides_t_a[provided_pkg].copy()
                provides_t_a[provided_pkg].remove((binary, prov_version))
                if not provides_t_a[provided_pkg]:
                    del provides_t_a[provided_pkg]
            # finally, remove the binary package
            del binaries_t_a[binary]
            target_suite.remove_binary(rm_pkg_id)

        # Add/Update binary packages in testing
        if updates:
            packages_s = source_suite.binaries

            for updated_pkg_id in updates:
                binary, new_version, parch = updated_pkg_id
                key = (binary, parch)
                binaries_t_a = packages_t[parch]
                provides_t_a = provides_t[parch]
                equivalent_replacement = key in eqv_set

                # obviously, added/modified packages are affected
                if not equivalent_replacement:
                    affected_direct.add(updated_pkg_id)
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
                        affected_direct.update(pkg_universe.reverse_dependencies_of(old_pkg_id))
                    target_suite.remove_binary(old_pkg_id)
                elif transaction and transaction.parent_transaction:
                    # the binary isn't in the target suite, but it may have been at
                    # the start of the current hint and have been removed
                    # by an earlier migration. if that's the case then we
                    # will have a record of the older instance of the binary
                    # in the undo information. we can use that to ensure
                    # that the reverse dependencies of the older binary
                    # package are also checked.
                    # reverse dependencies built from this source can be
                    # ignored as their reverse trees are already handled
                    # by this function
                    for (tundo, tpkg) in transaction.parent_transaction.undo_items:
                        if key in tundo['binaries']:
                            tpkg_id = tundo['binaries'][key]
                            affected_direct.update(pkg_universe.reverse_dependencies_of(tpkg_id))

                # add/update the binary package from the source suite
                new_pkg_data = packages_s[parch][binary]
                binaries_t_a[binary] = new_pkg_data
                target_suite.add_binary(updated_pkg_id)
                updated_binaries.add(updated_pkg_id)
                # register new provided packages
                for provided_pkg, prov_version, _ in new_pkg_data.provides:
                    key = (provided_pkg, parch)
                    if provided_pkg not in provides_t_a:
                        undo['nvirtual'].append(key)
                        provides_t_a[provided_pkg] = set()
                    elif key not in undo['virtual']:
                        undo['virtual'][key] = provides_t_a[provided_pkg].copy()
                    provides_t_a[provided_pkg].add((binary, prov_version))
                if not equivalent_replacement:
                    # all the reverse dependencies are affected by the change
                    affected_direct.add(updated_pkg_id)
                    affected_direct.update(pkg_universe.negative_dependencies_of(updated_pkg_id))

        # Also include the transitive rdeps of the packages found so far
        affected_all = affected_direct.copy()
        compute_reverse_tree(pkg_universe, affected_all)
        if transaction:
            transaction.add_undo_item(undo, updated_binaries)
        # return the affected packages (direct and than all)
        return (affected_direct, affected_all)

    def try_migration(self, actions, nuninst_now, transaction, stop_on_first_regression=True):
        is_accepted = True
        affected_architectures = set()
        item = actions
        target_suite = self.suite_info.target_suite
        packages_t = target_suite.binaries

        nobreakall_arches = self.options.nobreakall_arches
        new_arches = self.options.new_arches
        break_arches = self.options.break_arches
        arch = None

        if len(actions) == 1:
            item = actions[0]
            # apply the changes
            affected_direct, affected_all = self.doop_source(item, transaction)
            if item.architecture == 'source':
                affected_architectures = set(self.options.architectures)
            else:
                affected_architectures.add(item.architecture)
        else:
            removals = set()
            affected_direct = set()
            affected_all = set()
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
                item_affected_direct, item_affected_all = self.doop_source(item,
                                                                           transaction,
                                                                           removals=removals)
                affected_direct.update(item_affected_direct)
                affected_all.update(item_affected_all)

        # Optimise the test if we may revert directly.
        # - The automatic-revert is needed since some callers (notably via hints) may
        #   accept the outcome of this migration and expect nuninst to be updated.
        #   (e.g. "force-hint" or "hint")
        if stop_on_first_regression:
            affected_all -= affected_direct
        else:
            affected_direct = set()

        # Copy nuninst_comp - we have to deep clone affected
        # architectures.

        # NB: We do this *after* updating testing as we have to filter out
        # removed binaries.  Otherwise, uninstallable binaries that were
        # removed by the item would still be counted.

        nuninst_after = clone_nuninst(nuninst_now, packages_s=packages_t, architectures=affected_architectures)
        must_be_installable = self.constraints['keep-installable']

        # check the affected packages on all the architectures
        for arch in affected_architectures:
            check_archall = arch in nobreakall_arches

            check_installability(target_suite, packages_t, arch, affected_direct, affected_all,
                                 check_archall, nuninst_after)

            # if the uninstallability counter is worse than before, break the loop
            if stop_on_first_regression:
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

        return (is_accepted, nuninst_after, arch)

    def iter_packages(self, packages, selected, nuninst=None, parent_transaction=None, try_removals=True):
        """Iter on the list of actions and apply them one-by-one

        This method applies the changes from `packages` to testing, checking the uninstallability
        counters for every action performed. If the action does not improve them, it is reverted.
        The method returns the new uninstallability counters and the remaining actions if the
        final result is successful, otherwise (None, []).
        """
        group_info = {}
        rescheduled_packages = packages
        maybe_rescheduled_packages = []
        output_logger = self.output_logger
        suite_info = self.suite_info
        all_binaries = self.all_binaries
        solver = InstallabilitySolver(self.pkg_universe, self._inst_tester)

        for y in sorted((y for y in packages), key=attrgetter('uvname')):
            try:
                updates, rms, _ = self._compute_groups(y.package, y.suite, y.architecture, y.is_removal)
                result = (y, frozenset(updates), frozenset(rms))
                group_info[y] = result
            except MigrationConstraintException as e:
                rescheduled_packages.remove(y)
                output_logger.info("not adding package to list: %s",(y.package))
                output_logger.info("    got exception: %s"%(repr(e)))

        if nuninst:
            nuninst_orig = nuninst
        else:
            nuninst_orig = self.nuninst_orig

        nuninst_last_accepted = nuninst_orig

        output_logger.info("recur: [] %s %d/0", ",".join(x.uvname for x in selected), len(packages))
        while rescheduled_packages:
            groups = {group_info[x] for x in rescheduled_packages}
            worklist = solver.solve_groups(groups)
            rescheduled_packages = []

            worklist.reverse()

            while worklist:
                comp = worklist.pop()
                comp_name = ' '.join(item.uvname for item in comp)
                output_logger.info("trying: %s" % comp_name)
                with start_transaction(suite_info, all_binaries, parent_transaction) as transaction:
                    accepted = False
                    try:
                        accepted, nuninst_after, failed_arch = self.try_migration(comp,
                                                                                  nuninst_last_accepted,
                                                                                  transaction)
                        if accepted:
                            selected.extend(comp)
                            transaction.commit()
                            output_logger.info("accepted: %s", comp_name)
                            output_logger.info("   ori: %s", self.eval_nuninst(nuninst_orig))
                            output_logger.info("   pre: %s", self.eval_nuninst(nuninst_last_accepted))
                            output_logger.info("   now: %s", self.eval_nuninst(nuninst_after))
                            if len(selected) <= 20:
                                output_logger.info("   all: %s", " ".join(x.uvname for x in selected))
                            else:
                                output_logger.info("  most: (%d) .. %s",
                                                   len(selected),
                                                   " ".join(x.uvname for x in selected[-20:]))
                            nuninst_last_accepted = nuninst_after
                            rescheduled_packages.extend(maybe_rescheduled_packages)
                            maybe_rescheduled_packages.clear()
                        else:
                            transaction.rollback()
                            broken = sorted(b for b in nuninst_after[failed_arch]
                                            if b not in nuninst_last_accepted[failed_arch])
                            compare_nuninst = None
                            if any(item for item in comp if item.architecture != 'source'):
                                compare_nuninst = nuninst_last_accepted
                            # NB: try_migration already reverted this for us, so just print the results and move on
                            output_logger.info("skipped: %s (%d, %d, %d)",
                                               comp_name,
                                               len(rescheduled_packages),
                                               len(maybe_rescheduled_packages),
                                               len(worklist)
                                               )
                            output_logger.info("    got: %s", self.eval_nuninst(nuninst_after, compare_nuninst))
                            output_logger.info("    * %s: %s", failed_arch, ", ".join(broken))

                    except MigrationConstraintException as e:
                        transaction.rollback()
                        output_logger.info("skipped: %s (%d, %d, %d)",
                                           comp_name,
                                           len(rescheduled_packages),
                                           len(maybe_rescheduled_packages),
                                           len(worklist)
                                           )
                        output_logger.info("    got exception: %s"%(repr(e)))

                    if not accepted:
                        if len(comp) > 1:
                            output_logger.info("    - splitting the component into single items and retrying them")
                            worklist.extend([item] for item in comp)
                        else:
                            maybe_rescheduled_packages.append(comp[0])

        if try_removals and self.options.smooth_updates:
            self.logger.info("> Removing old packages left in the target suite from smooth updates")
            removals = old_libraries(self.suite_info, self.options.outofsync_arches)
            if removals:
                output_logger.info("Removing packages left in the target suite for smooth updates (%d):", len(removals))
                log_and_format_old_libraries(self.output_logger, removals)
                (nuninst_last_accepted, extra) = self.iter_packages(removals,
                                                                    selected,
                                                                    nuninst=nuninst_last_accepted,
                                                                    parent_transaction=parent_transaction,
                                                                    try_removals=False)

        output_logger.info(" finish: [%s]", ",".join(x.uvname for x in selected))
        output_logger.info("endloop: %s", self.eval_nuninst(self.nuninst_orig))
        output_logger.info("    now: %s", self.eval_nuninst(nuninst_last_accepted))
        format_and_log_uninst(output_logger,
                              self.options.architectures,
                              newly_uninst(self.nuninst_orig, nuninst_last_accepted)
                              )
        output_logger.info("")

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
        output_logger = self.output_logger

        # these are special parameters for hints processing
        force = False
        recurse = True
        nuninst_end = None
        extra = []

        if hinttype == "easy" or hinttype == "force-hint":
            force = hinttype == "force-hint"
            recurse = False

        # if we have a list of initial packages, check them
        if init:
            for x in init:
                if x not in upgrade_me:
                    output_logger.warning("failed: %s is not a valid candidate (or it already migrated)", x.uvname)
                    return None
                selected.append(x)
                upgrade_me.remove(x)

        output_logger.info("start: %s", self.eval_nuninst(nuninst_start))
        output_logger.info("orig: %s", self.eval_nuninst(nuninst_start))

        with start_transaction(self.suite_info, self.all_binaries) as transaction:
            if not init or force:
                # Throw away the (outer) transaction as we will not be using it
                transaction.rollback()
                transaction = None

            if init:
                # init => a hint (e.g. "easy") - so do the hint run
                (_, nuninst_end, _) = self.try_migration(selected,
                                                         self.nuninst_orig,
                                                         transaction,
                                                         stop_on_first_regression=False)

                if recurse:
                    # Ensure upgrade_me and selected do not overlap, if we
                    # follow-up with a recurse ("hint"-hint).
                    upgrade_me = [x for x in upgrade_me if x not in set(selected)]

            if recurse:
                # Either the main run or the recursive run of a "hint"-hint.
                (nuninst_end, extra) = self.iter_packages(upgrade_me,
                                                          selected,
                                                          nuninst=nuninst_end,
                                                          parent_transaction=transaction)

            nuninst_end_str = self.eval_nuninst(nuninst_end)

            if not recurse:
                # easy or force-hint
                output_logger.info("easy: %s", nuninst_end_str)

                if not force:
                    format_and_log_uninst(self.output_logger,
                                          self.options.architectures,
                                          newly_uninst(nuninst_start, nuninst_end)
                                          )

            if force:
                # Force implies "unconditionally better"
                better = True
            else:
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
                output_logger.info("final: %s", ",".join(sorted(x.uvname for x in selected)))
                output_logger.info("start: %s", self.eval_nuninst(nuninst_start))
                output_logger.info(" orig: %s", self.eval_nuninst(self.nuninst_orig))
                output_logger.info("  end: %s", nuninst_end_str)
                if force:
                    broken = newly_uninst(nuninst_start, nuninst_end)
                    if broken:
                        output_logger.warning("force breaks:")
                        format_and_log_uninst(self.output_logger,
                                              self.options.architectures,
                                              broken,
                                              loglevel=logging.WARNING,
                                              )
                    else:
                        output_logger.info("force did not break any packages")
                output_logger.info("SUCCESS (%d/%d)", len(actions or self.upgrade_me), len(extra))
                self.nuninst_orig = nuninst_end
                self.all_selected += selected
                if transaction:
                    transaction.commit()
                if not actions:
                    if recurse:
                        self.upgrade_me = extra
                    else:
                        self.upgrade_me = [x for x in self.upgrade_me if x not in set(selected)]
            else:
                output_logger.info("FAILED\n")
                if not transaction:
                    return
                transaction.rollback()

        output_logger.info("")

    def assert_nuninst_is_correct(self):
        self.logger.info("> Update complete - Verifying non-installability counters")

        cached_nuninst = self.nuninst_orig
        self._inst_tester.compute_installability()
        computed_nuninst = compile_nuninst(self.suite_info.target_suite,
                                           self.options.architectures,
                                           self.options.nobreakall_arches)
        if cached_nuninst != computed_nuninst:  # pragma: no cover
            only_on_break_archs = True
            self.logger.error("==================== NUNINST OUT OF SYNC =========================")
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
                    self.logger.error(" %s - unnoticed nuninst: %s", arch, str(false_negatives))
                if false_positives:
                    self.logger.error(" %s - invalid nuninst: %s", arch, str(false_positives))
                self.logger.info(" %s - actual nuninst: %s", arch, str(actual_nuninst))
                self.logger.error("==================== NUNINST OUT OF SYNC =========================")
            if not only_on_break_archs:
                raise AssertionError("NUNINST OUT OF SYNC")
            else:
                self.logger.warning("Nuninst is out of sync on some break arches")

        self.logger.info("> All non-installability counters are ok")

    def upgrade_testing(self):
        """Upgrade testing using the packages from the source suites

        This method tries to upgrade testing using the packages from the
        source suites.
        Before running the do_all method, it tries the easy and force-hint
        commands.
        """

        output_logger = self.output_logger
        self.logger.info("Starting the upgrade test")
        output_logger.info("Generated on: %s", time.strftime("%Y.%m.%d %H:%M:%S %z", time.gmtime(time.time())))
        output_logger.info("Arch order is: %s", ", ".join(self.options.architectures))

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
        output_logger.info("info: main run")
        self.do_all()
        allpackages += self.upgrade_me
        for a in self.options.break_arches:
            backup = self.options.break_arches
            self.options.break_arches = " ".join(x for x in self.options.break_arches if x != a)
            self.upgrade_me = archpackages[a]
            output_logger.info("info: broken arch run for %s", a)
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
                output_logger.info("Skipping remaining hints...")
                break
            if self.do_hint("hint", x.user, x.packages):
                hintcnt += 1

        # run the auto hinter
        self.auto_hinter()

        if getattr(self.options, "remove_obsolete", "yes") == "yes":
            # obsolete source packages
            # a package is obsolete if none of the binary packages in testing
            # are built by it
            self.logger.info("> Removing obsolete source packages from the target suite")
            # local copies for performance
            target_suite = self.suite_info.target_suite
            sources_t = target_suite.sources
            binaries_t = target_suite.binaries
            used = set(binaries_t[arch][binary].source
                       for arch in binaries_t
                       for binary in binaries_t[arch]
                       )
            removals = [MigrationItem("-%s/%s" % (source, sources_t[source].version))
                        for source in sources_t if source not in used
                        ]
            if removals:
                output_logger.info("Removing obsolete source packages from the target suite (%d):", len(removals))
                self.do_all(actions=removals)

        # smooth updates
        removals = old_libraries(self.suite_info, self.options.outofsync_arches)
        if self.options.smooth_updates:
            self.logger.info("> Removing old packages left in the target suite from smooth updates")
            if removals:
                output_logger.info("Removing packages left in the target suite for smooth updates (%d):", len(removals))
                log_and_format_old_libraries(self.output_logger, removals)
                self.do_all(actions=removals)
                removals = old_libraries(self.suite_info, self.options.outofsync_arches)
        else:
            self.logger.info("> Not removing old packages left in the target suite from smooth updates"
                             " (smooth-updates disabled)")

        output_logger.info("List of old libraries in the target suite (%d):", len(removals))
        log_and_format_old_libraries(self.output_logger, removals)

        self.assert_nuninst_is_correct()

        # output files
        if not self.options.dry_run:
            target_suite = self.suite_info.target_suite
            # re-write control files
            if self.options.control_files:
                self.logger.info("Writing new control files for the target suite to %s",
                                 target_suite.path)
                write_controlfiles(target_suite)

            for policy in self.policies:
                policy.save_state(self)

            # write HeidiResult
            self.logger.info("Writing Heidi results to %s", self.options.heidi_output)
            write_heidi(self.options.heidi_output,
                        target_suite,
                        outofsync_arches=self.options.outofsync_arches)

            self.logger.info("Writing delta to %s", self.options.heidi_delta_output)
            write_heidi_delta(self.options.heidi_delta_output,
                              self.all_selected)


        self.printuninstchange()
        self.logger.info("Test completed!")

    def printuninstchange(self):
        self.logger.info("Checking for newly uninstallable packages")
        uninst = newly_uninst(self.nuninst_orig_save, self.nuninst_orig)

        if uninst:
            self.output_logger.warning("")
            self.output_logger.warning("Newly uninstallable packages in the target suite:")
            format_and_log_uninst(self.output_logger,
                                  self.options.architectures,
                                  uninst,
                                  loglevel=logging.WARNING,
                                  )

    def hint_tester(self):
        """Run a command line interface to test hints

        This method provides a command line interface for the release team to
        try hints and evaluate the results.
        """
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
                user_input = input('britney> ').split()
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
            self.logger.warning("Could not write %s: %s", histfile, e)

    def do_hint(self, hinttype, who, pkgvers):
        """Process hints

        This method process `easy`, `hint` and `force-hint` hints. If the
        requested version is not in the relevant source suite, then the hint
        is skipped.
        """

        output_logger = self.output_logger
        if isinstance(pkgvers[0], tuple) or isinstance(pkgvers[0], list):
            _pkgvers = [ MigrationItem('%s/%s' % (p, v)) for (p,v) in pkgvers ]
        else:
            _pkgvers = pkgvers

        suites = self.suite_info
        self.logger.info("> Processing '%s' hint from %s", hinttype, who)
        output_logger.info("Trying %s from %s: %s", hinttype, who,
                           " ".join("%s/%s" % (x.uvname, x.version) for x in _pkgvers)
                           )

        issues = []
        # loop on the requested packages and versions
        for idx in range(len(_pkgvers)):
            pkg = _pkgvers[idx]
            # skip removal requests
            if pkg.is_removal:
                continue

            suite = pkg.suite
            in_primary = pkg.package in suite.sources
            rightversion = in_primary and apt_pkg.version_compare(suite.sources[pkg.package].version, pkg.version) == 0
            if suite.suite_class.is_primary_source and not rightversion:
                for s in suites.additional_source_suites:
                    if pkg.package in s.sources and apt_pkg.version_compare(suite.sources[pkg.package].version,
                                                                            pkg.version) == 0:
                        suite = s
                        pkg.suite = s
                        _pkgvers[idx] = pkg
                        break

            if suite.suite_class.is_additional_source:
                if pkg.package not in suite.sources:
                    continue
                if apt_pkg.version_compare(suite.sources[pkg.package].version, pkg.version) != 0:
                    issues.append("Version mismatch, %s %s != %s" % (pkg.package, pkg.version,
                                                                     suite.sources[pkg.package].version))
            # does the package exist in the primary source suite?
            elif not in_primary:
                issues.append("Source %s has no version in %s" % (pkg.package, suite.name))
            elif not rightversion:
                issues.append("Version mismatch, %s %s != %s" % (pkg.package, pkg.version,
                                                                 suite.sources[pkg.package].version))
        if issues:
            output_logger.warning("%s: Not using hint", ", ".join(issues))
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
        self.logger.info("> Processing hints from the auto hinter")

        sources_t = self.suite_info.target_suite.sources
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
                    new_items = {(x, excuses[x].ver[1]) for x in chain(excuses_deps[item], excuses_rdeps[item])}
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
        binaries_t = self.suite_info.target_suite.binaries
        for p in nuninst[arch]:
            pkg = binaries_t[arch][p]
            all[(pkg.source, pkg.source_version)].add(p)

        print('* %s' % arch)

        for (src, ver), pkgs in sorted(all.items()):
            print('  %s (%s): %s' % (src, ver, ' '.join(sorted(pkgs))))

        print()

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

        if self.options.compute_migrations or self.options.hint_tester:
            if self.options.dry_run:
                self.logger.info("Upgrade output not (also) written to a separate file"
                                 " as this is a dry-run.")
            elif hasattr(self.options, 'upgrade_output'):
                upgrade_output = getattr(self.options, 'upgrade_output')
                file_handler = logging.FileHandler(upgrade_output, mode='w', encoding='utf-8')
                output_formatter = logging.Formatter('%(message)s')
                file_handler.setFormatter(output_formatter)
                self.output_logger.addHandler(file_handler)
                self.logger.info("Logging upgrade output to %s", upgrade_output)
            else:
                self.logger.info("Upgrade output not (also) written to a separate file"
                                 " as the UPGRADE_OUTPUT configuration is not provided.")

            # run the hint tester
            if self.options.hint_tester:
                self.hint_tester()
            # run the upgrade test
            else:
                self.upgrade_testing()

            self.logger.info('> Stats from the installability tester')
            for stat in self._inst_tester.stats.stats():
                self.logger.info('>   %s', stat)
        else:
            self.logger.info('Migration computation skipped as requested.')
        logging.shutdown()


if __name__ == '__main__':
    Britney().main()
