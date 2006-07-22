#!/usr/bin/env python2.4
# -*- coding: utf-8 -*-

# Copyright (C) 2001-2004 Anthony Towns <ajt@debian.org>
#                         Andreas Barth <aba@debian.org>
#                         Fabio Tranchitella <kobold@debian.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

"""
= Introdution =

This is the Debian testing updater script, also known as "Britney".

Packages are usually installed into the `testing' distribution after
they have undergone some degree of testing in unstable. The goal of
this software is to do this task in a smart way, allowing testing
to be always fully installable and close to being a release candidate.

Britney source code is splitted in two different but related tasks:
the first one is the generation of the update excuses, while the
second tries to update testing with the valid candidates; first 
each package alone, then larger and even larger sets of packages
together. Each try is accepted if testing is not more uninstallable
after the update than before.

= Data Loading =

In order to analyze the entire Debian distribution, Britney needs to
load in memory the whole archive: this means more than 10.000 packages
for twelve architectures, as well as the dependency interconnection
between them. For this reason, the memory requirement for running this
software are quite high and at least 1 gigabyte of RAM should be available.

Britney loads the source packages from the `Sources' file and the binary
packages from the `Packages_${arch}' files, where ${arch} is substituted
with the supported architectures. While loading the data, the software
analyze the dependencies and build a directed weighted graph in memory
with all the interconnections between the packages (see Britney.read_sources
and Britney.read_binaries).

Other than source and binary packages, Britney loads the following data:

  * Bugs, which contains the count of release-critical bugs for a given
    version of a source package (see Britney.read_bugs).

  * Dates, which contains the date of the upload of a given version 
    of a source package (see Britney.read_dates).

  * Urgencies, which contains the urgency of the upload of a given
    version of a source package (see Britney.read_urgencies).

  * Approvals, which contains the list of approved testing-proposed-updates
    packages (see Britney.read_approvals).

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

    2. For every binary package build from the new source, it checks
       for unsatisfied dependencies, new binary package and updated
       binary package (binNMU) excluding the architecture-independent
       ones and the packages not built from the same source.

    3. For every binary package build from the old source, it checks
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

    7. If the suite is unstable, the update can go ahead only if the
       upload happend more then the minimum days specified by the
       urgency of the upload; if this is not true, the package is
       ignored as `too-young'. Note that the urgency is sticky, meaning
       that the highest urgency uploaded since the previous testing
       transition is taken into account.

    8. All the architecture-dependent binary packages and the
       architecture-independent ones for the `nobreakall' architectures
       have to be built from the source we are considering. If this is
       not true, then these are called `out-of-date' architectures and
       the package is ignored.

    9. The source package must have at least a binary package, otherwise
       it is ignored.

   10. If the suite is unstable, the count of release critical bugs for
       the new source package must be less then the count for the testing
       one. If this is not true, the package is ignored as `buggy'.

   11. If there is a `force' hint for the source package, then it is
       updated even if it is marked as ignored from the previous steps.

   12. If the suite is testing-proposed-updates, the source package can
       be updated only if there is an explicit approval for it.

   13. If the package will be ignored, mark it as "Valid candidate",
       otherwise mark it as "Not considered".

 * The list of `remove' hints is processed: if the requested source
   package is not already being updated or removed and the version
   actually in testing is the same specified with the `remove' hint,
   it is marked for removal.

 * The excuses are sorted by the number of days from the last upload
   (days-old) and by name.

 * A list of unconsidered excuses (for which the package is not upgraded)
   is built. Using this list, all the excuses depending on them is marked
   as invalid for "unpossible dependency".

 * The excuses are written in an HTML file.
"""

import os
import re
import sys
import string
import time
import copy
import optparse
import operator

import apt_pkg

from excuse import Excuse
from upgrade import UpgradeRun

__author__ = 'Fabio Tranchitella'
__version__ = '2.0.alpha1'


class Britney:
    """Britney, the debian testing updater script
    
    This is the script that updates the testing_ distribution. It is executed
    each day after the installation of the updated packages. It generates the 
    `Packages' files for the testing distribution, but it does so in an
    intelligent manner; it try to avoid any inconsistency and to use only
    non-buggy packages.

    For more documentation on this script, please read the Developers Reference.
    """

    HINTS_STANDARD = ("easy", "hint", "remove", "block", "unblock", "urgent", "approve")
    HINTS_ALL = ("force", "force-hint", "block-all") + HINTS_STANDARD

    def __init__(self):
        """Class constructor

        This method initializes and populates the data lists, which contain all
        the information needed by the other methods of the class.
        """
        self.date_now = int(((time.time() / (60*60)) - 15) / 24)

        # parse the command line arguments
        self.__parse_arguments()

        # initialize the apt_pkg back-end
        apt_pkg.init()

        # read the source and binary packages for the involved distributions
        self.sources = {'testing': self.read_sources(self.options.testing),
                        'unstable': self.read_sources(self.options.unstable),
                        'tpu': self.read_sources(self.options.tpu),}
        self.binaries = {'testing': {}, 'unstable': {}, 'tpu': {}}
        for arch in self.options.architectures:
            self.binaries['testing'][arch] = self.read_binaries(self.options.testing, "testing", arch)
            self.binaries['unstable'][arch] = self.read_binaries(self.options.unstable, "unstable", arch)
            self.binaries['tpu'][arch] = self.read_binaries(self.options.tpu, "tpu", arch)

        # read the release-critical bug summaries for testing and unstable
        self.bugs = {'unstable': self.read_bugs(self.options.unstable),
                     'testing': self.read_bugs(self.options.testing),}
        self.normalize_bugs()

        # read additional data
        self.dates = self.read_dates(self.options.testing)
        self.urgencies = self.read_urgencies(self.options.testing)
        self.approvals = self.read_approvals(self.options.tpu)
        self.hints = self.read_hints(self.options.unstable)
        self.excuses = []

    def __parse_arguments(self):
        """Parse the command line arguments

        This method parses and initializes the command line arguments.
        While doing so, it preprocesses some of the options to be converted
        in a suitable form for the other methods of the class.
        """
        # initialize the parser
        self.parser = optparse.OptionParser(version="%prog")
        self.parser.add_option("-v", "", action="count", dest="verbose", help="enable verbose output")
        self.parser.add_option("-c", "--config", action="store", dest="config",
                          default="/etc/britney.conf", help="path for the configuration file")
        (self.options, self.args) = self.parser.parse_args()

        # if the configuration file exists, than read it and set the additional options
        if not os.path.isfile(self.options.config):
            self.__log("Unable to read the configuration file (%s), exiting!" % self.options.config, type="E")
            sys.exit(1)

        # minimum days for unstable-testing transition and the list of hints
        # are handled as an ad-hoc case
        self.MINDAYS = {}
        self.HINTS = {}
        for k, v in [map(string.strip,r.split('=', 1)) for r in file(self.options.config) if '=' in r and not r.strip().startswith('#')]:
            if k.startswith("MINDAYS_"):
                self.MINDAYS[k.split("_")[1].lower()] = int(v)
            elif k.startswith("HINTS_"):
                self.HINTS[k.split("_")[1].lower()] = \
                    reduce(lambda x,y: x+y, [hasattr(self, "HINTS_" + i) and getattr(self, "HINTS_" + i) or (i,) for i in v.split()])
            else:
                setattr(self.options, k.lower(), v)

        # Sort the architecture list
        allarches = sorted(self.options.architectures.split())
        arches = [x for x in allarches if x in self.options.nobreakall_arches]
        arches += [x for x in allarches if x not in arches and x not in self.options.fucked_arches]
        arches += [x for x in allarches if x not in arches and x not in self.options.break_arches]
        arches += [x for x in allarches if x not in arches]
        self.options.architectures = arches

    def __log(self, msg, type="I"):
        """Print info messages according to verbosity level
        
        An easy-and-simple log method which prints messages to the standard
        output. The type parameter controls the urgency of the message, and
        can be equal to `I' for `Information', `W' for `Warning' and `E' for
        `Error'. Warnings and errors are always printed, and information are
        printed only if the verbose logging is enabled.
        """
        if self.options.verbose or type in ("E", "W"):
            print "%s: [%s] - %s" % (type, time.asctime(), msg)

    # Data reading/writing methods
    # ----------------------------

    def read_sources(self, basedir):
        """Read the list of source packages from the specified directory
        
        The source packages are read from the `Sources' file within the
        directory specified as `basedir' parameter. Considering the
        large amount of memory needed, not all the fields are loaded
        in memory. The available fields are Version, Maintainer and Section.

        The method returns a list where every item represents a source
        package as a dictionary.
        """
        sources = {}
        package = None
        filename = os.path.join(basedir, "Sources")
        self.__log("Loading source packages from %s" % filename)
        packages = apt_pkg.ParseTagFile(open(filename))
        while packages.Step():
            pkg = packages.Section.get('Package')
            sources[pkg] = {'binaries': [],
                            'version': packages.Section.get('Version'),
                            'maintainer': packages.Section.get('Maintainer'),
                            'section': packages.Section.get('Section'),
                            }
        return sources

    def read_binaries(self, basedir, distribution, arch):
        """Read the list of binary packages from the specified directory
        
        The binary packages are read from the `Packages_${arch}' files
        within the directory specified as `basedir' parameter, replacing
        ${arch} with the value of the arch parameter. Considering the
        large amount of memory needed, not all the fields are loaded
        in memory. The available fields are Version, Source, Pre-Depends,
        Depends, Conflicts, Provides and Architecture.
        
        After reading the packages, reverse dependencies are computed
        and saved in the `rdepends' keys, and the `Provides' field is
        used to populate the virtual packages list.

        The dependencies are parsed with the apt.pkg.ParseDepends method,
        and they are stored both as the format of its return value and
        text.

        The method returns a tuple. The first element is a list where
        every item represents a binary package as a dictionary; the second
        element is a dictionary which maps virtual packages to real
        packages that provide it.
        """

        packages = {}
        provides = {}
        package = None
        filename = os.path.join(basedir, "Packages_%s" % arch)
        self.__log("Loading binary packages from %s" % filename)
        Packages = apt_pkg.ParseTagFile(open(filename))
        while Packages.Step():
            pkg = Packages.Section.get('Package')
            version = Packages.Section.get('Version')
            dpkg = {'version': version,
                    'source': pkg, 
                    'source-ver': version,
                    'architecture': Packages.Section.get('Architecture'),
                    'rdepends': [],
                    }
            for k in ('Pre-Depends', 'Depends', 'Provides', 'Conflicts'):
                v = Packages.Section.get(k)
                if v: dpkg[k.lower()] = v

            # retrieve the name and the version of the source package
            source = Packages.Section.get('Source')
            if source:
                dpkg['source'] = source.split(" ")[0]
                if "(" in source:
                    dpkg['source-ver'] = source.split("(")[1].split(")")[0]

            # if the source package is available in the distribution, then register this binary package
            if dpkg['source'] in self.sources[distribution]:
                self.sources[distribution][dpkg['source']]['binaries'].append(pkg + "/" + arch)
            # if the source package doesn't exist, create a fake one
            else:
                self.sources[distribution][dpkg['source']] = {'binaries': [pkg + "/" + arch],
                    'version': dpkg['source-ver'], 'maintainer': None, 'section': None, 'fake': True}

            # register virtual packages and real packages that provide them
            if dpkg.has_key('provides'):
                parts = map(string.strip, dpkg['provides'].split(","))
                for p in parts:
                    try:
                        provides[p].append(pkg)
                    except KeyError:
                        provides[p] = [pkg]
                del dpkg['provides']

            # append the resulting dictionary to the package list
            packages[pkg] = dpkg

        # loop again on the list of packages to register reverse dependencies
        # this is not needed for the moment, so it is disabled
        for pkg in packages:
            dependencies = []
            if packages[pkg].has_key('depends'):
                dependencies.extend(apt_pkg.ParseDepends(packages[pkg]['depends']))
            if packages[pkg].has_key('pre-depends'):
                dependencies.extend(apt_pkg.ParseDepends(packages[pkg]['pre-depends']))
            # register the list of the dependencies for the depending packages
            for p in dependencies:
                for a in p:
                    if a[0] in packages:
                        packages[a[0]]['rdepends'].append((pkg, a[1], a[2]))
                    elif a[0] in provides:
                        for i in provides[a[0]]:
                            packages[i]['rdepends'].append((pkg, a[1], a[2]))
            del dependencies

        # return a tuple with the list of real and virtual packages
        return (packages, provides)

    def read_bugs(self, basedir):
        """Read the release critial bug summary from the specified directory
        
        The RC bug summaries are read from the `Bugs' file within the
        directory specified as `basedir' parameter. The file contains
        rows with the format:

        <package-name> <count-of-rc-bugs>

        The method returns a dictionary where the key is the binary package
        name and the value is the number of open RC bugs for it.
        """
        bugs = {}
        filename = os.path.join(basedir, "Bugs")
        self.__log("Loading RC bugs count from %s" % filename)
        for line in open(filename):
            l = line.strip().split()
            if len(l) != 2: continue
            try:
                bugs[l[0]] = int(l[1])
            except ValueError:
                self.__log("Bugs, unable to parse \"%s\"" % line, type="E")
        return bugs

    def __maxver(self, pkg, dist):
        """Return the maximum version for a given package name
        
        This method returns None if the specified source package
        is not available in the `dist' distribution. If the package
        exists, then it returns the maximum version between the
        source package and its binary packages.
        """
        maxver = None
        if self.sources[dist].has_key(pkg):
            maxver = self.sources[dist][pkg]['version']
        for arch in self.options.architectures:
            if not self.binaries[dist][arch][0].has_key(pkg): continue
            pkgv = self.binaries[dist][arch][0][pkg]['version']
            if maxver == None or apt_pkg.VersionCompare(pkgv, maxver) > 0:
                maxver = pkgv
        return maxver

    def normalize_bugs(self):
        """Normalize the release critical bug summaries for testing and unstable
        
        The method doesn't return any value: it directly modifies the
        object attribute `bugs'.
        """
        # loop on all the package names from testing and unstable bug summaries
        for pkg in set(self.bugs['testing'].keys() + self.bugs['unstable'].keys()):

            # make sure that the key is present in both dictionaries
            if not self.bugs['testing'].has_key(pkg):
                self.bugs['testing'][pkg] = 0
            elif not self.bugs['unstable'].has_key(pkg):
                self.bugs['unstable'][pkg] = 0

            # retrieve the maximum version of the package in testing:
            maxvert = self.__maxver(pkg, 'testing')

            # if the package is not available in testing or it has the
            # same RC bug count, then do nothing
            if maxvert == None or \
               self.bugs['testing'][pkg] == self.bugs['unstable'][pkg]:
                continue

            # retrieve the maximum version of the package in testing:
            maxveru = self.__maxver(pkg, 'unstable')

            # if the package is not available in unstable, then do nothing
            if maxveru == None:
                continue
            # else if the testing package is more recent, then use the
            # unstable RC bug count for testing, too
            elif apt_pkg.VersionCompare(maxvert, maxveru) >= 0:
                self.bugs['testing'][pkg] = self.bugs['unstable'][pkg]

    def read_dates(self, basedir):
        """Read the upload date for the packages from the specified directory
        
        The upload dates are read from the `Date' file within the directory
        specified as `basedir' parameter. The file contains rows with the
        format:

        <package-name> <version> <date-of-upload>

        The dates are expressed as days starting from the 1970-01-01.

        The method returns a dictionary where the key is the binary package
        name and the value is tuple with two items, the version and the date.
        """
        dates = {}
        filename = os.path.join(basedir, "Dates")
        self.__log("Loading upload data from %s" % filename)
        for line in open(filename):
            l = line.strip().split()
            if len(l) != 3: continue
            try:
                dates[l[0]] = (l[1], int(l[2]))
            except ValueError:
                self.__log("Dates, unable to parse \"%s\"" % line, type="E")
        return dates

    def read_urgencies(self, basedir):
        """Read the upload urgency of the packages from the specified directory
        
        The upload urgencies are read from the `Urgency' file within the
        directory specified as `basedir' parameter. The file contains rows
        with the format:

        <package-name> <version> <urgency>

        The method returns a dictionary where the key is the binary package
        name and the value is the greatest urgency from the versions of the
        package that are higher then the testing one.
        """

        urgencies = {}
        filename = os.path.join(basedir, "Urgency")
        self.__log("Loading upload urgencies from %s" % filename)
        for line in open(filename):
            l = line.strip().split()
            if len(l) != 3: continue

            # read the minimum days associated to the urgencies
            urgency_old = urgencies.get(l[0], self.options.default_urgency)
            mindays_old = self.MINDAYS.get(urgency_old, self.MINDAYS[self.options.default_urgency])
            mindays_new = self.MINDAYS.get(l[2], self.MINDAYS[self.options.default_urgency])

            # if the new urgency is lower (so the min days are higher), do nothing
            if mindays_old <= mindays_new:
                continue

            # if the package exists in testing and it is more recent, do nothing
            tsrcv = self.sources['testing'].get(l[0], None)
            if tsrcv and apt_pkg.VersionCompare(tsrcv['version'], l[1]) >= 0:
                continue

            # if the package doesn't exist in unstable or it is older, do nothing
            usrcv = self.sources['unstable'].get(l[0], None)
            if not usrcv or apt_pkg.VersionCompare(usrcv['version'], l[1]) < 0:
                continue

            # update the urgency for the package
            urgencies[l[0]] = l[2]

        return urgencies

    def read_approvals(self, basedir):
        """Read the approval commands from the specified directory
        
        The approval commands are read from the files contained by the 
        `Approved' directory within the directory specified as `basedir'
        parameter. The name of the files has to be the same of the
        authorized users for the approvals.
        
        The file contains rows with the format:

        <package-name> <version>

        The method returns a dictionary where the key is the binary package
        name followed by an underscore and the version number, and the value
        is the user who submitted the command.
        """
        approvals = {}
        for approver in self.options.approvers.split():
            filename = os.path.join(basedir, "Approved", approver)
            self.__log("Loading approvals list from %s" % filename)
            for line in open(filename):
                l = line.strip().split()
                if len(l) != 2: continue
                approvals["%s_%s" % (l[0], l[1])] = approver
        return approvals

    def read_hints(self, basedir):
        """Read the hint commands from the specified directory
        
        The hint commands are read from the files contained by the `Hints'
        directory within the directory specified as `basedir' parameter. 
        The name of the files has to be the same of the authorized users
        for the hints.
        
        The file contains rows with the format:

        <command> <package-name>[/<version>]

        The method returns a dictionary where the key is the command, and
        the value is the list of affected packages.
        """
        hints = dict([(k,[]) for k in self.HINTS_ALL])

        for who in self.HINTS.keys():
            filename = os.path.join(basedir, "Hints", who)
            self.__log("Loading hints list from %s" % filename)
            for line in open(filename):
                line = line.strip()
                if line == "": continue
                l = line.split()
                if l[0] == 'finished':
                    break
                elif l[0] not in self.HINTS[who]:
                    continue
                elif l[0] in ["easy", "hint", "force-hint"]:
                    hints[l[0]].append((who, [k.split("/") for k in l if "/" in k]))
                elif l[0] in ["block-all"]:
                    hints[l[0]].extend([(y, who) for y in l[1:]])
                elif l[0] in ["block"]:
                    hints[l[0]].extend([(y, who) for y in l[1:]])
                elif l[0] in ["remove", "approve", "unblock", "force", "urgent"]:
                    hints[l[0]].extend([(k.split("/")[0], (k.split("/")[1],who) ) for k in l if "/" in k])

        for x in ["block", "block-all", "unblock", "force", "urgent", "remove"]:
            z = {}
            for a, b in hints[x]:
                if z.has_key(a):
                    self.__log("Overriding %s[%s] = %s with %s" % (x, a, z[a], b), type="W")
                z[a] = b
            hints[x] = z

        return hints

    # Utility methods for package analisys
    # ------------------------------------

    def same_source(self, sv1, sv2):
        """Check if two version numbers are built from the same source

        This method returns a boolean value which is true if the two
        version numbers specified as parameters are built from the same
        source. The main use of this code is to detect binary-NMU.
        """
        if sv1 == sv2:
            return 1

        m = re.match(r'^(.*)\+b\d+$', sv1)
        if m: sv1 = m.group(1)
        m = re.match(r'^(.*)\+b\d+$', sv2)
        if m: sv2 = m.group(1)

        if sv1 == sv2:
            return 1

        if re.search("-", sv1) or re.search("-", sv2):
            m = re.match(r'^(.*-[^.]+)\.0\.\d+$', sv1)
            if m: sv1 = m.group(1)
            m = re.match(r'^(.*-[^.]+\.[^.]+)\.\d+$', sv1)
            if m: sv1 = m.group(1)

            m = re.match(r'^(.*-[^.]+)\.0\.\d+$', sv2)
            if m: sv2 = m.group(1)
            m = re.match(r'^(.*-[^.]+\.[^.]+)\.\d+$', sv2)
            if m: sv2 = m.group(1)

            return (sv1 == sv2)
        else:
            m = re.match(r'^([^-]+)\.0\.\d+$', sv1)
            if m and sv2 == m.group(1): return 1

            m = re.match(r'^([^-]+)\.0\.\d+$', sv2)
            if m and sv1 == m.group(1): return 1

            return 0

    def get_dependency_solvers(self, block, arch, distribution, excluded=[]):
        """Find the packages which satisfy a dependency block

        This method returns the list of packages which satisfy a dependency
        block (as returned by apt_pkg.ParseDepends) for the given architecture
        and distribution.

        It returns a tuple with two items: the first is a boolean which is
        True if the dependency is satisfied, the second is the list of the
        solving packages.
        """

        packages = []

        # for every package, version and operation in the block
        for name, version, op in block:
            # look for the package in unstable
            if name in self.binaries[distribution][arch][0] and name not in excluded:
                package = self.binaries[distribution][arch][0][name]
                # check the versioned dependency (if present)
                if op == '' and version == '' or apt_pkg.CheckDep(package['version'], op, version):
                    packages.append(name)

            # look for the package in the virtual packages list
            if name in self.binaries[distribution][arch][1]:
                # loop on the list of packages which provides it
                for prov in self.binaries[distribution][arch][1][name]:
                    if prov in excluded or \
                       not self.binaries[distribution][arch][0].has_key(prov): continue
                    package = self.binaries[distribution][arch][0][prov]
                    # check the versioned dependency (if present)
                    # TODO: this is forbidden by the debian policy, which says that versioned
                    #       dependencies on virtual packages are never satisfied. The old britney
                    #       does it and we have to go with it, but at least a warning should be raised.
                    if op == '' and version == '' or apt_pkg.CheckDep(package['version'], op, version):
                        packages.append(prov)
                        break

        return (len(packages) > 0, packages)

    def excuse_unsat_deps(self, pkg, src, arch, suite, excuse=None, excluded=[], conflicts=False):
        """Find unsatisfied dependencies for a binary package

        This method analyzes the dependencies of the binary package specified
        by the parameter `pkg', built from the source package `src', for the
        architecture `arch' within the suite `suite'. If the dependency can't
        be satisfied in testing and/or unstable, it updates the excuse passed
        as parameter.

        The dependency fields checked are Pre-Depends and Depends.
        """
        # retrieve the binary package from the specified suite and arch
        binary_u = self.binaries[suite][arch][0][pkg]

        # analyze the dependency fields (if present)
        for type in ('Pre-Depends', 'Depends'):
            type_key = type.lower()
            if not binary_u.has_key(type_key):
                continue

            # for every block of dependency (which is formed as conjunction of disconjunction)
            for block, block_txt in zip(apt_pkg.ParseDepends(binary_u[type_key]), binary_u[type_key].split(',')):
                # if the block is satisfied in testing, then skip the block
                solved, packages = self.get_dependency_solvers(block, arch, 'testing', excluded)
                if solved: continue
                elif excuse == None:
                    return False

                # check if the block can be satisfied in unstable, and list the solving packages
                solved, packages = self.get_dependency_solvers(block, arch, suite)
                packages = [self.binaries[suite][arch][0][p]['source'] for p in packages]

                # if the dependency can be satisfied by the same source package, skip the block:
                # obviously both binary packages will enter testing togheter
                if src in packages: continue

                # if no package can satisfy the dependency, add this information to the excuse
                if len(packages) == 0:
                    excuse.addhtml("%s/%s unsatisfiable %s: %s" % (pkg, arch, type, block_txt.strip()))

                # for the solving packages, update the excuse to add the dependencies
                for p in packages:
                    if arch not in self.options.break_arches.split():
                        excuse.add_dep(p)
                    else:
                        excuse.add_break_dep(p, arch)

        # otherwise, the package is installable (not considering conflicts)
        # if we have been called inside UpgradeRun, then check conflicts before
        # saying that the package is really installable
        if not excuse and conflicts:
            return self.check_conflicts(pkg, arch, [], {})

        return True

    def check_conflicts(self, pkg, arch, system, conflicts):
        # if we are talking about a virtual package, skip it
        if not self.binaries['testing'][arch][0].has_key(pkg):
            return True

        binary_u = self.binaries['testing'][arch][0][pkg]

        # check the conflicts
        if conflicts.has_key(pkg):
            name, version, op = conflicts[pkg]
            if op == '' and version == '' or apt_pkg.CheckDep(binary_u['version'], op, version):
                return False

        # add the package
        lconflicts = conflicts
        system.append(pkg)

        # register conflicts
        if binary_u.has_key('conflicts'):
            for block in map(operator.itemgetter(0), apt_pkg.ParseDepends(binary_u['conflicts'])):
                if block[0] != pkg and block[0] in system:
                    name, version, op = block
                    binary_c = self.binaries['testing'][arch][0][block[0]]
                    if op == '' and version == '' or apt_pkg.CheckDep(binary_c['version'], op, version):
                        return False
                lconflicts[block[0]] = block

        # dependencies
        dependencies = []
        for type in ('Pre-Depends', 'Depends'):
            type_key = type.lower()
            if not binary_u.has_key(type_key): continue
            dependencies.extend(apt_pkg.ParseDepends(binary_u[type_key]))

        # go through them
        for block in dependencies:
            valid = False
            for name, version, op in block:
                if name in system or self.check_conflicts(name, arch, system, lconflicts):
                    valid = True
                    break
            if not valid:
                return False
        
        conflicts.update(lconflicts)
        return True

    # Package analisys methods
    # ------------------------

    def should_remove_source(self, pkg):
        """Check if a source package should be removed from testing
        
        This method checks if a source package should be removed from the
        testing distribution; this happen if the source package is not
        present in the unstable distribution anymore.

        It returns True if the package can be removed, False otherwise.
        In the former case, a new excuse is appended to the the object
        attribute excuses.
        """
        # if the soruce package is available in unstable, then do nothing
        if self.sources['unstable'].has_key(pkg):
            return False
        # otherwise, add a new excuse for its removal and return True
        src = self.sources['testing'][pkg]
        excuse = Excuse("-" + pkg)
        excuse.set_vers(src['version'], None)
        src['maintainer'] and excuse.set_maint(src['maintainer'].strip())
        src['section'] and excuse.set_section(src['section'].strip())
        excuse.addhtml("Valid candidate")
        self.excuses.append(excuse)
        return True

    def should_upgrade_srcarch(self, src, arch, suite):
        """Check if binary package should be upgraded

        This method checks if a binary package should be upgraded; this can
        happen also if the binary package is a binary-NMU for the given arch.
        The analisys is performed for the source package specified by the
        `src' parameter, checking the architecture `arch' for the distribution
        `suite'.
       
        It returns False if the given package doesn't need to be upgraded,
        True otherwise. In the former case, a new excuse is appended to
        the the object attribute excuses.
        """
        # retrieve the source packages for testing and suite
        source_t = self.sources['testing'][src]
        source_u = self.sources[suite][src]

        # build the common part of the excuse, which will be filled by the code below
        ref = "%s/%s%s" % (src, arch, suite != 'unstable' and "_" + suite or "")
        excuse = Excuse(ref)
        excuse.set_vers(source_t['version'], source_t['version'])
        source_u['maintainer'] and excuse.set_maint(source_u['maintainer'].strip())
        source_u['section'] and excuse.set_section(source_u['section'].strip())
        
        # if there is a `remove' hint and the requested version is the same of the
        # version in testing, then stop here and return False
        if self.hints["remove"].has_key(src) and \
           self.same_source(source_t['version'], self.hints["remove"][src][0]):
            excuse.addhtml("Removal request by %s" % (self.hints["remove"][src][1]))
            excuse.addhtml("Trying to remove package, not update it")
            excuse.addhtml("Not considered")
            self.excuses.append(excuse)
            return False

        # the starting point is that there is nothing wrong and nothing worth doing
        anywrongver = False
        anyworthdoing = False

        # for every binary package produced by this source in unstable for this architecture
        for pkg in sorted(filter(lambda x: x.endswith("/" + arch), source_u['binaries'])):
            pkg_name = pkg.split("/")[0]

            # retrieve the testing (if present) and unstable corresponding binary packages
            binary_t = pkg in source_t['binaries'] and self.binaries['testing'][arch][0][pkg_name] or None
            binary_u = self.binaries[suite][arch][0][pkg_name]

            # this is the source version for the new binary package
            pkgsv = self.binaries[suite][arch][0][pkg_name]['source-ver']

            # if the new binary package is architecture-independent, then skip it
            if binary_u['architecture'] == 'all':
                excuse.addhtml("Ignoring %s %s (from %s) as it is arch: all" % (pkg_name, binary_u['version'], pkgsv))
                continue

            # if the new binary package is not from the same source as the testing one, then skip it
            if not self.same_source(source_t['version'], pkgsv):
                anywrongver = True
                excuse.addhtml("From wrong source: %s %s (%s not %s)" % (pkg_name, binary_u['version'], pkgsv, source_t['version']))
                break

            # find unsatisfied dependencies for the new binary package
            self.excuse_unsat_deps(pkg_name, src, arch, suite, excuse)

            # if the binary is not present in testing, then it is a new binary;
            # in this case, there is something worth doing
            if not binary_t:
                excuse.addhtml("New binary: %s (%s)" % (pkg_name, binary_u['version']))
                anyworthdoing = True
                continue

            # at this point, the binary package is present in testing, so we can compare
            # the versions of the packages ...
            vcompare = apt_pkg.VersionCompare(binary_t['version'], binary_u['version'])

            # ... if updating would mean downgrading, then stop here: there is something wrong
            if vcompare > 0:
                anywrongver = True
                excuse.addhtml("Not downgrading: %s (%s to %s)" % (pkg_name, binary_t['version'], binary_u['version']))
                break
            # ... if updating would mean upgrading, then there is something worth doing
            elif vcompare < 0:
                excuse.addhtml("Updated binary: %s (%s to %s)" % (pkg_name, binary_t['version'], binary_u['version']))
                anyworthdoing = True

        # if there is nothing wrong and there is something worth doing or the source
        # package is not fake, then check what packages shuold be removed
        if not anywrongver and (anyworthdoing or self.sources[suite][src].has_key('fake')):
            srcv = self.sources[suite][src]['version']
            ssrc = self.same_source(source_t['version'], srcv)
            # for every binary package produced by this source in testing for this architecture
            for pkg in sorted([x.split("/")[0] for x in self.sources['testing'][src]['binaries'] if x.endswith("/"+arch)]):
                # if the package is architecture-independent, then ignore it
                if self.binaries['testing'][arch][0][pkg]['architecture'] == 'all':
                    excuse.addhtml("Ignoring removal of %s as it is arch: all" % (pkg))
                    continue
                # if the package is not produced by the new source package, then remove it from testing
                if not self.binaries[suite][arch][0].has_key(pkg):
                    tpkgv = self.binaries['testing'][arch][0][pkg]['version']
                    excuse.addhtml("Removed binary: %s %s" % (pkg, tpkgv))
                    if ssrc: anyworthdoing = True

        # if there is nothing wrong and there is something worth doing, this is valid candidate
        if not anywrongver and anyworthdoing:
            excuse.addhtml("Valid candidate")
            self.excuses.append(excuse)
            return True
        # else if there is something worth doing (but something wrong, too) this package won't be considered
        elif anyworthdoing:
            excuse.addhtml("Not considered")
            self.excuses.append(excuse)

        # otherwise, return False
        return False

    def should_upgrade_src(self, src, suite):
        """Check if source package should be upgraded

        This method checks if a source package should be upgraded. The analisys
        is performed for the source package specified by the `src' parameter, 
        checking the architecture `arch' for the distribution `suite'.
       
        It returns False if the given package doesn't need to be upgraded,
        True otherwise. In the former case, a new excuse is appended to
        the the object attribute excuses.
        """

        # retrieve the source packages for testing (if available) and suite
        source_u = self.sources[suite][src]
        if src in self.sources['testing']:
            source_t = self.sources['testing'][src]
            # if testing and unstable have the same version, then this is a candidate for binary-NMUs only
            if apt_pkg.VersionCompare(source_t['version'], source_u['version']) == 0:
                return False
        else:
            source_t = None

        # build the common part of the excuse, which will be filled by the code below
        ref = "%s%s" % (src, suite != 'unstable' and "_" + suite or "")
        excuse = Excuse(ref)
        excuse.set_vers(source_t and source_t['version'] or None, source_u['version'])
        source_u['maintainer'] and excuse.set_maint(source_u['maintainer'].strip())
        source_u['section'] and excuse.set_section(source_u['section'].strip())

        # the starting point is that we will update the candidate
        update_candidate = True
        
        # if the version in unstable is older, then stop here with a warning in the excuse and return False
        if source_t and apt_pkg.VersionCompare(source_u['version'], source_t['version']) < 0:
            excuse.addhtml("ALERT: %s is newer in testing (%s %s)" % (src, source_t['version'], source_u['version']))
            self.excuses.append(excuse)
            return False

        # check if the source package really exists or if it is a fake one
        if source_u.has_key('fake'):
            excuse.addhtml("%s source package doesn't exist" % (src))
            update_candidate = False

        # retrieve the urgency for the upload, ignoring it if this is a NEW package (not present in testing)
        urgency = self.urgencies.get(src, self.options.default_urgency)
        if not source_t and urgency != self.options.default_urgency:
            excuse.addhtml("Ignoring %s urgency setting for NEW package" % (urgency))
            urgency = self.options.default_urgency

        # if there is a `remove' hint and the requested version is the same of the
        # version in testing, then stop here and return False
        if self.hints["remove"].has_key(src):
            if source_t and self.same_source(source_t['version'], self.hints['remove'][src][0]) or \
               self.same_source(source_u['version'], self.hints['remove'][src][0]):
                excuse.addhtml("Removal request by %s" % (self.hints["remove"][src][1]))
                excuse.addhtml("Trying to remove package, not update it")
                update_candidate = False

        # check if there is a `block' hint for this package or a `block-all source' hint
        blocked = None
        if self.hints["block"].has_key(src):
            blocked = self.hints["block"][src]
        elif self.hints["block-all"].has_key("source"):
            blocked = self.hints["block-all"]["source"]

        # if the source is blocked, then look for an `unblock' hint; the unblock request
        # is processed only if the specified version is correct
        if blocked:
            unblock = self.hints["unblock"].get(src,(None,None))
            if unblock[0] != None:
                if self.same_source(unblock[0], source_u['version']):
                    excuse.addhtml("Ignoring request to block package by %s, due to unblock request by %s" % (blocked, unblock[1]))
                else:
                    excuse.addhtml("Unblock request by %s ignored due to version mismatch: %s" % (unblock[1], unblock[0]))
            else:
                excuse.addhtml("Not touching package, as requested by %s (contact debian-release if update is needed)" % (blocked))
                update_candidate = False

        # if the suite is unstable, then we have to check the urgency and the minimum days of
        # permanence in unstable before updating testing; if the source package is too young,
        # the check fails and we set update_candidate to False to block the update
        if suite == 'unstable':
            if not self.dates.has_key(src):
                self.dates[src] = (source_u['version'], self.date_now)
            elif not self.same_source(self.dates[src][0], source_u['version']):
                self.dates[src] = (source_u['version'], self.date_now)

            days_old = self.date_now - self.dates[src][1]
            min_days = self.MINDAYS[urgency]
            excuse.setdaysold(days_old, min_days)
            if days_old < min_days:
                if self.hints["urgent"].has_key(src) and self.same_source(source_u['version'], self.hints["urgent"][src][0]):
                    excuse.addhtml("Too young, but urgency pushed by %s" % (self.hints["urgent"][src][1]))
                else:
                    update_candidate = False

        # at this point, we check what is the status of the builds on all the supported architectures
        # to catch the out-of-date ones
        pkgs = {src: ["source"]}
        for arch in self.options.architectures:
            oodbins = {}
            # for every binary package produced by this source in the suite for this architecture
            for pkg in sorted([x.split("/")[0] for x in self.sources[suite][src]['binaries'] if x.endswith("/"+arch)]):
                if not pkgs.has_key(pkg): pkgs[pkg] = []
                pkgs[pkg].append(arch)

                # retrieve the binary package and its source version
                binary_u = self.binaries[suite][arch][0][pkg]
                pkgsv = binary_u['source-ver']

                # if it wasn't builded by the same source, it is out-of-date
                if not self.same_source(source_u['version'], pkgsv):
                    if not oodbins.has_key(pkgsv):
                        oodbins[pkgsv] = []
                    oodbins[pkgsv].append(pkg)
                    continue

                # if the package is architecture-dependent or the current arch is `nobreakall'
                # find unsatisfied dependencies for the binary package
                if binary_u['architecture'] != 'all' or arch in self.options.nobreakall_arches:
                    self.excuse_unsat_deps(pkg, src, arch, suite, excuse)

            # if there are out-of-date packages, warn about them in the excuse and set update_candidate
            # to False to block the update; if the architecture where the package is out-of-date is
            # in the `fucked_arches' list, then do not block the update
            if oodbins:
                oodtxt = ""
                for v in oodbins.keys():
                    if oodtxt: oodtxt = oodtxt + "; "
                    oodtxt = oodtxt + "%s (from <a href=\"http://buildd.debian.org/build.php?" \
                        "arch=%s&pkg=%s&ver=%s\" target=\"_blank\">%s</a>)" % \
                        (", ".join(sorted(oodbins[v])), arch, src, v, v)
                text = "out of date on <a href=\"http://buildd.debian.org/build.php?" \
                    "arch=%s&pkg=%s&ver=%s\" target=\"_blank\">%s</a>: %s" % \
                    (arch, src, source_u['version'], arch, oodtxt)

                if arch in self.options.fucked_arches:
                    text = text + " (but %s isn't keeping up, so nevermind)" % (arch)
                else:
                    update_candidate = False

                if self.date_now != self.dates[src][1]:
                    excuse.addhtml(text)

        # if the source package has no binaries, set update_candidate to False to block the update
        if len(self.sources[suite][src]['binaries']) == 0:
            excuse.addhtml("%s has no binaries on any arch" % src)
            update_candidate = False

        # if the suite is unstable, then we have to check the release-critical bug counts before
        # updating testing; if the unstable package have a RC bug count greater than the testing
        # one,  the check fails and we set update_candidate to False to block the update
        if suite == 'unstable':
            for pkg in pkgs.keys():
                if not self.bugs['testing'].has_key(pkg):
                    self.bugs['testing'][pkg] = 0
                if not self.bugs['unstable'].has_key(pkg):
                    self.bugs['unstable'][pkg] = 0

                if self.bugs['unstable'][pkg] > self.bugs['testing'][pkg]:
                    excuse.addhtml("%s (%s) is <a href=\"http://bugs.debian.org/cgi-bin/pkgreport.cgi?" \
                                   "which=pkg&data=%s&sev-inc=critical&sev-inc=grave&sev-inc=serious\" " \
                                   "target=\"_blank\">buggy</a>! (%d > %d)" % \
                                   (pkg, ", ".join(pkgs[pkg]), pkg, self.bugs['unstable'][pkg], self.bugs['testing'][pkg]))
                    update_candidate = False
                elif self.bugs['unstable'][pkg] > 0:
                    excuse.addhtml("%s (%s) is (less) <a href=\"http://bugs.debian.org/cgi-bin/pkgreport.cgi?" \
                                   "which=pkg&data=%s&sev-inc=critical&sev-inc=grave&sev-inc=serious\" " \
                                   "target=\"_blank\">buggy</a>! (%d <= %d)" % \
                                   (pkg, ", ".join(pkgs[pkg]), pkg, self.bugs['unstable'][pkg], self.bugs['testing'][pkg]))

        # check if there is a `force' hint for this package, which allows it to go in even if it is not updateable
        if not update_candidate and self.hints["force"].has_key(src) and \
           self.same_source(source_u['version'], self.hints["force"][src][0]):
            excuse.dontinvalidate = 1
            excuse.addhtml("Should ignore, but forced by %s" % (self.hints["force"][src][1]))
            update_candidate = True

        # if the suite is testing-proposed-updates, the package needs an explicit approval in order to go in
        if suite == "tpu":
            if self.approvals.has_key("%s_%s" % (src, source_u['version'])):
                excuse.addhtml("Approved by %s" % approvals["%s_%s" % (src, source_u['version'])])
            else:
                excuse.addhtml("NEEDS APPROVAL BY RM")
                update_candidate = False

        # if the package can be updated, it is a valid candidate
        if update_candidate:
            excuse.addhtml("Valid candidate")
        # else it won't be considered
        else:
            excuse.addhtml("Not considered")

        self.excuses.append(excuse)
        return update_candidate

    def reversed_exc_deps(self):
        """Reverse the excuses dependencies

        This method returns a dictionary where the keys are the package names
        and the values are the excuse names which depend on it.
        """
        res = {}
        for exc in self.excuses:
            for d in exc.deps:
                if not res.has_key(d): res[d] = []
                res[d].append(exc.name)
        return res

    def invalidate_excuses(self, valid, invalid):
        """Invalidate impossible excuses

        This method invalidates the impossible excuses, which depend
        on invalid excuses. The two parameters contains the list of
        `valid' and `invalid' excuses.
        """
        # build a lookup-by-name map
        exclookup = {}
        for e in self.excuses:
            exclookup[e.name] = e

        # build the reverse dependencies
        revdeps = self.reversed_exc_deps()

        # loop on the invalid excuses
        i = 0
        while i < len(invalid):
            # if there is no reverse dependency, skip the item
            if not revdeps.has_key(invalid[i]):
                i += 1
                continue
            # if there dependency can be satisfied by a testing-proposed-updates excuse, skip the item
            if (invalid[i] + "_tpu") in valid:
                i += 1
                continue
            # loop on the reverse dependencies
            for x in revdeps[invalid[i]]:
                # if the item is valid and it is marked as `dontinvalidate', skip the item
                if x in valid and exclookup[x].dontinvalidate:
                    continue

                # otherwise, invalidate the dependency and mark as invalidated and
                # remove the depending excuses
                exclookup[x].invalidate_dep(invalid[i])
                if x in valid:
                    p = valid.index(x)
                    invalid.append(valid.pop(p))
                    exclookup[x].addhtml("Invalidated by dependency")
                    exclookup[x].addhtml("Not considered")
            i = i + 1
 
    def write_excuses(self):
        """Produce and write the update excuses

        This method handles the update excuses generation: the packages are
        looked to determine whether they are valid candidates. For the details
        of this procedure, please refer to the module docstring.
        """

        self.__log("Update Excuses generation started", type="I")

        # this list will contain the packages which are valid candidates;
        # if a package is going to be removed, it will have a "-" prefix
        upgrade_me = []

        # for every source package in testing, check if it should be removed
        for pkg in self.sources['testing']:
            if self.should_remove_source(pkg):
                upgrade_me.append("-" + pkg)

        # for every source package in unstable check if it should be upgraded
        for pkg in self.sources['unstable']:
            # if the source package is already present in testing,
            # check if it should be upgraded for every binary package
            if self.sources['testing'].has_key(pkg):
                for arch in self.options.architectures:
                    if self.should_upgrade_srcarch(pkg, arch, 'unstable'):
                        upgrade_me.append("%s/%s" % (pkg, arch))

            # check if the source package should be upgraded
            if self.should_upgrade_src(pkg, 'unstable'):
                upgrade_me.append(pkg)

        # for every source package in testing-proposed-updates, check if it should be upgraded
        for pkg in self.sources['tpu']:
            # if the source package is already present in testing,
            # check if it should be upgraded for every binary package
            if self.sources['testing'].has_key(pkg):
                for arch in self.options.architectures:
                    if self.should_upgrade_srcarch(pkg, arch, 'tpu'):
                        upgrade_me.append("%s/%s_tpu" % (pkg, arch))

            # check if the source package should be upgraded
            if self.should_upgrade_src(pkg, 'tpu'):
                upgrade_me.append("%s_tpu" % pkg)

        # process the `remove' hints, if the given package is not yet in upgrade_me
        for src in self.hints["remove"].keys():
            if src in upgrade_me: continue
            if ("-"+src) in upgrade_me: continue
            if not self.sources['testing'].has_key(src): continue

            # check if the version specified in the hint is the same of the considered package
            tsrcv = self.sources['testing'][src]['version']
            if not self.same_source(tsrcv, self.hints["remove"][src][0]): continue

            # add the removal of the package to upgrade_me and build a new excuse
            upgrade_me.append("-%s" % (src))
            excuse = Excuse("-%s" % (src))
            excuse.set_vers(tsrcv, None)
            excuse.addhtml("Removal request by %s" % (self.hints["remove"][src][1]))
            excuse.addhtml("Package is broken, will try to remove")
            self.excuses.append(excuse)

        # sort the excuses by daysold and name
        self.excuses.sort(lambda x, y: cmp(x.daysold, y.daysold) or cmp(x.name, y.name))

        # extract the not considered packages, which are in the excuses but not in upgrade_me
        unconsidered = [e.name for e in self.excuses if e.name not in upgrade_me]

        # invalidate impossible excuses
        for e in self.excuses:
            for d in e.deps:
                if d not in upgrade_me and d not in unconsidered:
                    e.addhtml("Unpossible dep: %s -> %s" % (e.name, d))
        self.invalidate_excuses(upgrade_me, unconsidered)

        self.upgrade_me = sorted(upgrade_me)

        # write excuses to the output file
        self.__log("Writing Excuses to %s" % self.options.excuses_output, type="I")

        f = open(self.options.excuses_output, 'w')
        f.write("<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.01//EN\" \"http://www.w3.org/TR/REC-html40/strict.dtd\">\n")
        f.write("<html><head><title>excuses...</title>")
        f.write("<meta http-equiv=\"Content-Type\" content=\"text/html;charset=utf-8\"></head><body>\n")
        f.write("<p>Generated: " + time.strftime("%Y.%m.%d %H:%M:%S %z", time.gmtime(time.time())) + "</p>\n")
        f.write("<ul>\n")
        for e in self.excuses:
            f.write("<li>%s" % e.html())
        f.write("</ul></body></html>\n")
        f.close()

        self.__log("Update Excuses generation completed", type="I")

    # Upgrade run
    # -----------

    def get_nuninst(self):
        nuninst = {}

        def add_nuninst(pkg, arch):
            if pkg not in nuninst[arch]:
                nuninst[arch].append(pkg)
                for p in self.binaries['testing'][arch][0][pkg]['rdepends']:
                    tpkg = self.binaries['testing'][arch][0][p[0]]
                    if skip_archall and tpkg['architecture'] == 'all':
                        continue
                    r = self.excuse_unsat_deps(p[0], tpkg['source'], arch, 'testing', None, excluded=nuninst[arch])
                    if not r:
                        add_nuninst(p[0], arch)

        for arch in self.options.architectures:
            if arch not in self.options.nobreakall_arches:
                skip_archall = True
            else: skip_archall = False

            nuninst[arch] = []
            for pkg_name in self.binaries['testing'][arch][0]:
                pkg = self.binaries['testing'][arch][0][pkg_name]
                if skip_archall and pkg['architecture'] == 'all':
                    continue
                r = self.excuse_unsat_deps(pkg_name, pkg['source'], arch, 'testing', None, excluded=nuninst[arch])
                if not r:
                    add_nuninst(pkg_name, arch)

        return nuninst

    def eval_nuninst(self, nuninst, original=None):
        res = []
        total = 0
        totalbreak = 0
        for arch in self.options.architectures:
            if nuninst.has_key(arch):
                n = len(nuninst[arch]) + (original and len(original[arch]) or 0)
                if arch in self.options.break_arches:
                    totalbreak = totalbreak + n
                else:
                    total = total + n
                res.append("%s-%d" % (arch[0], n))
        return "%d+%d: %s" % (total, totalbreak, ":".join(res))

    def eval_uninst(self, nuninst):
        res = ""
        for arch in self.arches:
            if nuninst.has_key(arch) and nuninst[arch] != []:
                res = res + "    * %s: %s\n" % (arch,
                    ", ".join(nuninst[arch]))
        return res

    def doop_source(self, pkg):

        undo = {'binaries': {}, 'sources': {}}

        affected = []
        arch = None

        # arch = "<source>/<arch>",
        if "/" in pkg:
            pkg_name, arch = pkg.split("/")
            suite = "unstable"
        # removals = "-<source>",
        elif pkg[0] == "-":
            pkg_name = pkg[1:]
            suite = "testing"
        # testing-proposed-updates = "<source>_tpu"
        elif pkg[0].endswith("_tpu"):
            pkg_name = pkg[:-4]
            suite = "tpu"
        # normal = "<source>"
        else:
            pkg_name = pkg
            suite = "unstable"

        # remove all binary packages (if the source already exists)
        if not arch:
            if pkg_name in self.sources['testing']:
                source = self.sources['testing'][pkg_name]
                for p in source['binaries']:
                    binary, arch = p.split("/")
                    undo['binaries'][p] = self.binaries['testing'][arch][0][binary]
                    for j in self.binaries['testing'][arch][0][binary]['rdepends']:
                        if j not in affected: affected.append((j[0], j[1], j[2], arch))
                    del self.binaries['testing'][arch][0][binary]
                undo['sources'][pkg_name] = source
                del self.sources['testing'][pkg_name]
            else:
                undo['sources']['-' + pkg_name] = True

        # single architecture update (eg. binNMU)
        else:
            if self.binaries['testing'][arch][0].has_key(pkg_name):
                for j in self.binaries['testing'][arch][0][pkg_name]['rdepends']:
                    if j not in affected: affected.append((j[0], j[1], j[2], arch))
            source = {'binaries': [pkg]}

        # add the new binary packages (if we are not removing)
        if pkg[0] != "-":
            source = self.sources[suite][pkg_name]
            for p in source['binaries']:
                binary, arch = p.split("/")
                if p not in affected:
                    affected.append((binary, None, None, arch))
                if binary in self.binaries['testing'][arch][0]:
                    undo['binaries'][p] = self.binaries['testing'][arch][0][binary]
                    for j in self.binaries['testing'][arch][0][binary]['rdepends']:
                        if j not in affected: affected.append((j[0], j[1], j[2], arch))
                self.binaries['testing'][arch][0][binary] = self.binaries[suite][arch][0][binary]
                for j in self.binaries['testing'][arch][0][binary]['rdepends']:
                    if j not in affected: affected.append((j[0], j[1], j[2], arch))
            self.sources['testing'][pkg_name] = self.sources[suite][pkg_name]

        return (pkg_name, suite, affected, undo)

    def iter_packages(self, packages, output):
        extra = []
        nuninst_comp = self.get_nuninst()

        while packages:
            pkg = packages.pop(0)
            output.write("trying: %s\n" % (pkg))

            better = True
            nuninst = {}

            pkg_name, suite, affected, undo = self.doop_source(pkg)
            broken = []

            for arch in self.options.architectures:
                if arch not in self.options.nobreakall_arches:
                    skip_archall = True
                else: skip_archall = False

                l = -1
                while len(broken) > l and not (l == 0 and l == len(broken)):
                    l = len(broken)
                    for p in filter(lambda x: x[3] == arch, affected):
                        if not self.binaries['testing'][arch][0].has_key(p[0]) or \
                           skip_archall and self.binaries['testing'][arch][0][p[0]]['architecture'] == 'all': continue
                        r = self.excuse_unsat_deps(p[0], None, arch, 'testing', None, excluded=broken, conflicts=True)
                        if not r and p[0] not in broken: broken.append(p[0])

                l = 0
                while l < len(broken):
                    l = len(broken)
                    for j in broken:
                        for p in self.binaries['testing'][arch][0][j]['rdepends']:
                            if not self.binaries['testing'][arch][0].has_key(p[0]) or \
                               skip_archall and self.binaries['testing'][arch][0][p[0]]['architecture'] == 'all': continue
                            r = self.excuse_unsat_deps(p[0], None, arch, 'testing', None, excluded=broken, conflicts=True)
                            if not r and p[0] not in broken: broken.append(p[0])
                    
                nuninst[arch] = sorted(broken)
                if len(nuninst[arch]) > 0:
                    better = False
                    break

            if better:
                self.selected.append(pkg)
                packages.extend(extra)
                extra = []
                nuninst_new = nuninst_comp # FIXME!
                output.write("accepted: %s\n" % (pkg))
                output.write("   ori: %s\n" % (self.eval_nuninst(self.nuninst_orig)))
                output.write("   pre: %s\n" % (self.eval_nuninst(nuninst_comp)))
                output.write("   now: %s\n" % (self.eval_nuninst(nuninst_new)))
                if len(self.selected) <= 20:
                    output.write("   all: %s\n" % (" ".join(self.selected)))
                else:
                    output.write("  most: (%d) .. %s\n" % (len(self.selected), " ".join(self.selected[-20:])))
                nuninst_comp = nuninst_new
            else:
                output.write("skipped: %s (%d <- %d)\n" % (pkg, len(extra), len(packages)))
                output.write("    got: %s\n" % self.eval_nuninst(nuninst, self.nuninst_orig))
                output.write("    * %s: %s\n" % (arch, ", ".join(nuninst[arch])))
                extra.append(pkg)

                # undo the changes (source)
                for k in undo['sources'].keys():
                    if k[0] == '-':
                        del self.sources['testing'][k[1:]]
                    else: self.sources['testing'][k] = undo['sources'][k]

                # undo the changes (new binaries)
                if pkg in self.sources[suite]:
                    for p in self.sources[suite][pkg]['binaries']:
                        binary, arch = p.split("/")
                        del self.binaries['testing'][arch][0][binary]

                # undo the changes (binaries)
                for p in undo['binaries'].keys():
                    binary, arch = p.split("/")
                    self.binaries['testing'][arch][0][binary] = undo['binaries'][p]
 
    def do_all(self, output):
        nuninst_start = self.get_nuninst()
        output.write("start: %s\n" % self.eval_nuninst(nuninst_start))
        output.write("orig: %s\n" % self.eval_nuninst(nuninst_start))
        self.selected = []
        self.nuninst_orig = nuninst_start
        self.iter_packages(self.upgrade_me, output)

    def upgrade_testing(self):
        """Upgrade testing using the unstable packages

        This method tries to upgrade testing using the packages from unstable.
        """

        self.__log("Starting the upgrade test", type="I")
        output = open(self.options.upgrade_output, 'w')
        output.write("Generated on: %s\n" % (time.strftime("%Y.%m.%d %H:%M:%S %z", time.gmtime(time.time()))))
        output.write("Arch order is: %s\n" % ", ".join(self.options.architectures))

        # TODO: process hints!
        self.do_all(output)

        output.close()
        self.__log("Test completed!", type="I")

    def main(self):
        """Main method
        
        This is the entry point for the class: it includes the list of calls
        for the member methods which will produce the output files.
        """
        self.write_excuses()
        self.upgrade_testing()

if __name__ == '__main__':
    Britney().main()
