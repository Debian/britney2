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
        self.parser.add_option("-c", "--config", action="store", dest="config", default="/etc/britney.conf",
                               help="path for the configuration file")
        self.parser.add_option("", "--architectures", action="store", dest="architectures", default=None,
                               help="override architectures from configuration file")
        self.parser.add_option("", "--actions", action="store", dest="actions", default=None,
                               help="override the list of actions to be performed")
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
            elif not hasattr(self.options, k.lower()) or \
                 not getattr(self.options, k.lower()):
                setattr(self.options, k.lower(), v)

        # Sort the architecture list
        allarches = sorted(self.options.architectures.split())
        arches = [x for x in allarches if x in self.options.nobreakall_arches]
        arches += [x for x in allarches if x not in arches and x not in self.options.fucked_arches]
        arches += [x for x in allarches if x not in arches and x not in self.options.break_arches]
        arches += [x for x in allarches if x not in arches and x not in self.options.new_arches]
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
        Packages = apt_pkg.ParseTagFile(open(filename))
        get_field = Packages.Section.get
        while Packages.Step():
            pkg = get_field('Package')
            sources[pkg] = {'binaries': [],
                            'version': get_field('Version'),
                            'maintainer': get_field('Maintainer'),
                            'section': get_field('Section'),
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
        sources = self.sources
        package = None

        filename = os.path.join(basedir, "Packages_%s" % arch)
        self.__log("Loading binary packages from %s" % filename)
        Packages = apt_pkg.ParseTagFile(open(filename))
        get_field = Packages.Section.get
        while Packages.Step():
            pkg = get_field('Package')
            version = get_field('Version')
            dpkg = {'version': version,
                    'source': pkg, 
                    'source-ver': version,
                    'architecture': get_field('Architecture'),
                    'rdepends': [],
                    'rconflicts': [],
                    }
            for k in ('Pre-Depends', 'Depends', 'Provides', 'Conflicts'):
                v = get_field(k)
                if v: dpkg[k.lower()] = v

            # retrieve the name and the version of the source package
            source = get_field('Source')
            if source:
                dpkg['source'] = source.split(" ")[0]
                if "(" in source:
                    dpkg['source-ver'] = source[source.find("(")+1:source.find(")")]

            # if the source package is available in the distribution, then register this binary package
            if dpkg['source'] in sources[distribution]:
                sources[distribution][dpkg['source']]['binaries'].append(pkg + "/" + arch)
            # if the source package doesn't exist, create a fake one
            else:
                sources[distribution][dpkg['source']] = {'binaries': [pkg + "/" + arch],
                    'version': dpkg['source-ver'], 'maintainer': None, 'section': None, 'fake': True}

            # register virtual packages and real packages that provide them
            if 'provides' in dpkg:
                parts = map(string.strip, dpkg['provides'].split(","))
                for p in parts:
                    if p not in provides:
                        provides[p] = []
                    provides[p].append(pkg)
                dpkg['provides'] = parts
            else: dpkg['provides'] = []

            # add the resulting dictionary to the package list
            packages[pkg] = dpkg

        # loop again on the list of packages to register reverse dependencies and conflicts
        register_reverses = self.register_reverses
        for pkg in packages:
            register_reverses(pkg, packages, provides, check_doubles=False)

        # return a tuple with the list of real and virtual packages
        return (packages, provides)

    def register_reverses(self, pkg, packages, provides, check_doubles=True, parse_depends=apt_pkg.ParseDepends):
        """Register reverse dependencies and conflicts for the specified package

        This method register the reverse dependencies and conflicts for
        a give package using `packages` as list of packages and `provides`
        as list of virtual packages.

        The method has an optional parameter parse_depends which is there
        just for performance reasons and is not meant to be overwritten.
        """
        # register the list of the dependencies for the depending packages
        dependencies = []
        if 'depends' in packages[pkg]:
            dependencies.extend(parse_depends(packages[pkg]['depends']))
        if 'pre-depends' in packages[pkg]:
            dependencies.extend(parse_depends(packages[pkg]['pre-depends']))
        # go through the list
        for p in dependencies:
            for a in p:
                # register real packages
                if a[0] in packages and (not check_doubles or pkg not in packages[a[0]]['rdepends']):
                    packages[a[0]]['rdepends'].append(pkg)
                # register packages which provides a virtual package
                elif a[0] in provides:
                    for i in provides.get(a[0]):
                        if i not in packages: continue
                        if not check_doubles or pkg not in packages[i]['rdepends']:
                            packages[i]['rdepends'].append(pkg)
        # register the list of the conflicts for the conflicting packages
        if 'conflicts' in packages[pkg]:
            for p in parse_depends(packages[pkg]['conflicts']):
                for a in p:
                    # register real packages
                    if a[0] in packages and (not check_doubles or pkg not in packages[a[0]]['rconflicts']):
                        packages[a[0]]['rconflicts'].append(pkg)
                    # register packages which provides a virtual package
                    elif a[0] in provides:
                        for i in provides[a[0]]:
                            if i not in packages: continue
                            if not check_doubles or pkg not in packages[i]['rconflicts']:
                                packages[i]['rconflicts'].append(pkg)
     
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
            l = line.split()
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
        if pkg in self.sources[dist]:
            maxver = self.sources[dist][pkg]['version']
        for arch in self.options.architectures:
            if pkg not in self.binaries[dist][arch][0]: continue
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
            if pkg not in self.bugs['testing']:
                self.bugs['testing'][pkg] = 0
            elif pkg not in self.bugs['unstable']:
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
            l = line.split()
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
            l = line.split()
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
                l = line.split()
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
                if a in z:
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

    def get_dependency_solvers(self, block, arch, distribution, excluded=[], strict=False):
        """Find the packages which satisfy a dependency block

        This method returns the list of packages which satisfy a dependency
        block (as returned by apt_pkg.ParseDepends) for the given architecture
        and distribution.

        It returns a tuple with two items: the first is a boolean which is
        True if the dependency is satisfied, the second is the list of the
        solving packages.
        """

        packages = []

        # local copies for better performances
        binaries = self.binaries[distribution][arch]

        # for every package, version and operation in the block
        for name, version, op in block:
            # look for the package in unstable
            if name not in excluded and name in binaries[0]:
                package = binaries[0][name]
                # check the versioned dependency (if present)
                if op == '' and version == '' or apt_pkg.CheckDep(package['version'], op, version):
                    packages.append(name)

            # look for the package in the virtual packages list and loop on them
            for prov in binaries[1].get(name, []):
                if prov in excluded or \
                   prov not in binaries[0]: continue
                package = binaries[0][prov]
                # check the versioned dependency (if present)
                # TODO: this is forbidden by the debian policy, which says that versioned
                #       dependencies on virtual packages are never satisfied. The old britney
                #       does it and we have to go with it, but at least a warning should be raised.
                if op == '' and version == '' or not strict and apt_pkg.CheckDep(package['version'], op, version):
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

        # local copies for better performances
        parse_depends = apt_pkg.ParseDepends
        get_dependency_solvers = self.get_dependency_solvers

        # analyze the dependency fields (if present)
        for type in ('Pre-Depends', 'Depends'):
            type_key = type.lower()
            if type_key not in binary_u:
                continue

            # for every block of dependency (which is formed as conjunction of disconjunction)
            for block, block_txt in zip(parse_depends(binary_u[type_key]), binary_u[type_key].split(',')):
                # if the block is satisfied in testing, then skip the block
                solved, packages = get_dependency_solvers(block, arch, 'testing', excluded, strict=(excuse == None))
                if solved: continue

                # check if the block can be satisfied in unstable, and list the solving packages
                solved, packages = get_dependency_solvers(block, arch, suite)
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
        if pkg in self.sources['unstable']:
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
        if src in self.hints["remove"] and \
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
        if not anywrongver and (anyworthdoing or 'fake' in self.sources[suite][src]):
            srcv = self.sources[suite][src]['version']
            ssrc = self.same_source(source_t['version'], srcv)
            # for every binary package produced by this source in testing for this architecture
            for pkg in sorted([x.split("/")[0] for x in self.sources['testing'][src]['binaries'] if x.endswith("/"+arch)]):
                # if the package is architecture-independent, then ignore it
                if self.binaries['testing'][arch][0][pkg]['architecture'] == 'all':
                    excuse.addhtml("Ignoring removal of %s as it is arch: all" % (pkg))
                    continue
                # if the package is not produced by the new source package, then remove it from testing
                if pkg not in self.binaries[suite][arch][0]:
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
        if 'fake' in source_u:
            excuse.addhtml("%s source package doesn't exist" % (src))
            update_candidate = False

        # retrieve the urgency for the upload, ignoring it if this is a NEW package (not present in testing)
        urgency = self.urgencies.get(src, self.options.default_urgency)
        if not source_t and urgency != self.options.default_urgency:
            excuse.addhtml("Ignoring %s urgency setting for NEW package" % (urgency))
            urgency = self.options.default_urgency

        # if there is a `remove' hint and the requested version is the same of the
        # version in testing, then stop here and return False
        if src in self.hints["remove"]:
            if source_t and self.same_source(source_t['version'], self.hints['remove'][src][0]) or \
               self.same_source(source_u['version'], self.hints['remove'][src][0]):
                excuse.addhtml("Removal request by %s" % (self.hints["remove"][src][1]))
                excuse.addhtml("Trying to remove package, not update it")
                update_candidate = False

        # check if there is a `block' hint for this package or a `block-all source' hint
        blocked = None
        if src in self.hints["block"]:
            blocked = self.hints["block"][src]
        elif 'source' in self.hints["block-all"]:
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
            if src not in self.dates:
                self.dates[src] = (source_u['version'], self.date_now)
            elif not self.same_source(self.dates[src][0], source_u['version']):
                self.dates[src] = (source_u['version'], self.date_now)

            days_old = self.date_now - self.dates[src][1]
            min_days = self.MINDAYS[urgency]
            excuse.setdaysold(days_old, min_days)
            if days_old < min_days:
                if src in self.hints["urgent"] and self.same_source(source_u['version'], self.hints["urgent"][src][0]):
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
                if pkg not in pkgs: pkgs[pkg] = []
                pkgs[pkg].append(arch)

                # retrieve the binary package and its source version
                binary_u = self.binaries[suite][arch][0][pkg]
                pkgsv = binary_u['source-ver']

                # if it wasn't builded by the same source, it is out-of-date
                if not self.same_source(source_u['version'], pkgsv):
                    if pkgsv not in oodbins:
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
                if pkg not in self.bugs['testing']:
                    self.bugs['testing'][pkg] = 0
                if pkg not in self.bugs['unstable']:
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
        if not update_candidate and src in self.hints["force"] and \
           self.same_source(source_u['version'], self.hints["force"][src][0]):
            excuse.dontinvalidate = 1
            excuse.addhtml("Should ignore, but forced by %s" % (self.hints["force"][src][1]))
            update_candidate = True

        # if the suite is testing-proposed-updates, the package needs an explicit approval in order to go in
        if suite == "tpu":
            key = "%s_%s" % (src, source_u['version'])
            if key in self.approvals:
                excuse.addhtml("Approved by %s" % approvals[key])
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
                if d not in res: res[d] = []
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
            if invalid[i] not in revdeps:
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

        # list of local methods and variables (for better performance)
        sources = self.sources
        architectures = self.options.architectures
        should_remove_source = self.should_remove_source
        should_upgrade_srcarch = self.should_upgrade_srcarch
        should_upgrade_src = self.should_upgrade_src

        # this list will contain the packages which are valid candidates;
        # if a package is going to be removed, it will have a "-" prefix
        upgrade_me = []

        # for every source package in testing, check if it should be removed
        for pkg in sources['testing']:
            if should_remove_source(pkg):
                upgrade_me.append("-" + pkg)

        # for every source package in unstable check if it should be upgraded
        for pkg in sources['unstable']:
            # if the source package is already present in testing,
            # check if it should be upgraded for every binary package
            if pkg in sources['testing']:
                for arch in architectures:
                    if should_upgrade_srcarch(pkg, arch, 'unstable'):
                        upgrade_me.append("%s/%s" % (pkg, arch))

            # check if the source package should be upgraded
            if should_upgrade_src(pkg, 'unstable'):
                upgrade_me.append(pkg)

        # for every source package in testing-proposed-updates, check if it should be upgraded
        for pkg in sources['tpu']:
            # if the source package is already present in testing,
            # check if it should be upgraded for every binary package
            if pkg in sources['testing']:
                for arch in architectures:
                    if should_upgrade_srcarch(pkg, arch, 'tpu'):
                        upgrade_me.append("%s/%s_tpu" % (pkg, arch))

            # check if the source package should be upgraded
            if should_upgrade_src(pkg, 'tpu'):
                upgrade_me.append("%s_tpu" % pkg)

        # process the `remove' hints, if the given package is not yet in upgrade_me
        for src in self.hints["remove"].keys():
            if src in upgrade_me: continue
            if ("-"+src) in upgrade_me: continue
            if src not in sources['testing']: continue

            # check if the version specified in the hint is the same of the considered package
            tsrcv = sources['testing'][src]['version']
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

        # sort the list of candidates
        self.upgrade_me = sorted(upgrade_me)

        # write excuses to the output file
        self.__log("> Writing Excuses to %s" % self.options.excuses_output, type="I")

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

    def newlyuninst(self, nuold, nunew):
        """Return a nuninst statstic with only new uninstallable packages

        This method subtract the uninstallabla packages of the statistic
        `nunew` from the statistic `nuold`.

        It returns a dictionary with the architectures as keys and the list
        of uninstallable packages as values.
        """
        res = {}
        for arch in nuold:
            if arch not in nunew: continue
            res[arch] = [x for x in nunew[arch] if x not in nuold[arch]]
        return res

    def get_nuninst(self):
        """Return the uninstallability statistic for all the architectures

        To calculate the uninstallability counters, the method checks the
        installability of all the packages for all the architectures, and
        tracking dependencies in a recursive way. The architecture
        indipendent packages are checked only for the `nobreakall`
        architectures.

        It returns a dictionary with the architectures as keys and the list
        of uninstallable packages as values.
        """
        nuninst = {}

        # local copies for better performances
        binaries = self.binaries['testing']
        check_installable = self.check_installable

        # when a new uninstallable package is discovered, check again all the
        # reverse dependencies and if they are uninstallable, too, call itself
        # recursively
        def add_nuninst(pkg, arch):
            if pkg not in nuninst[arch]:
                nuninst[arch].append(pkg)
                for p in binaries[arch][0][pkg]['rdepends']:
                    tpkg = binaries[arch][0][p]
                    if skip_archall and tpkg['architecture'] == 'all':
                        continue
                    r = check_installable(p, arch, 'testing', excluded=nuninst[arch], conflicts=False)
                    if not r:
                        add_nuninst(p, arch)

        # for all the architectures
        for arch in self.options.architectures:
            # if it is in the nobreakall ones, check arch-indipendent packages too
            if arch not in self.options.nobreakall_arches:
                skip_archall = True
            else: skip_archall = False

            # check all the packages for this architecture, calling add_nuninst if a new
            # uninstallable package is found
            nuninst[arch] = []
            for pkg_name in binaries[arch][0]:
                pkg = binaries[arch][0][pkg_name]
                if skip_archall and pkg['architecture'] == 'all':
                    continue
                r = check_installable(pkg_name, arch, 'testing', excluded=nuninst[arch], conflicts=False)
                if not r:
                    add_nuninst(pkg_name, arch)

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

    def eval_uninst(self, nuninst):
        """Return a string which represents the uninstallable packages

        This method returns a string which represents the uninstallable
        packages reading the uninstallability statistics `nuninst`.

        An example of the output string is:
            * i386: broken-pkg1, broken-pkg2
        """
        parts = []
        for arch in self.options.architectures:
            if arch in nuninst and len(nuninst[arch]) > 0:
                parts.append("    * %s: %s\n" % (arch,", ".join(sorted(nuninst[arch]))))
        return "".join(parts)

    def check_installable(self, pkg, arch, suite, excluded=[], conflicts=False):
        """Check if a package is installable

        This method analyzes the dependencies of the binary package specified
        by the parameter `pkg' for the architecture `arch' within the suite
        `suite'. If the dependency can be satisfied in the given `suite` and
        `conflicts` parameter is True, then the co-installability with 
        conflicts handling is checked.

        The dependency fields checked are Pre-Depends and Depends.

        The method returns a boolean which is True if the given package is
        installable.
        """
        # retrieve the binary package from the specified suite and arch
        binary_u = self.binaries[suite][arch][0][pkg]

        # local copies for better performances
        parse_depends = apt_pkg.ParseDepends
        get_dependency_solvers = self.get_dependency_solvers

        # analyze the dependency fields (if present)
        for type in ('pre-depends', 'depends'):
            if type not in binary_u:
                continue

            # for every block of dependency (which is formed as conjunction of disconjunction)
            for block in parse_depends(binary_u[type]):
                # if the block is not satisfied, return False
                solved, packages = get_dependency_solvers(block, arch, 'testing', excluded, strict=True)
                if not solved:
                    return False

        # otherwise, the package is installable (not considering conflicts)
        # if the conflicts handling is enabled, then check conflicts before
        # saying that the package is really installable
        if conflicts:
            return self.check_conflicts(pkg, arch, excluded, {}, {})

        return True

    def check_conflicts(self, pkg, arch, broken, system, conflicts):
        """Check if a package can be installed satisfying the conflicts

        This method checks if the `pkg` package from the `arch` architecture
        can be installed (excluding `broken` packages) within the system
        `system` along with all its dependencies. This means that all the
        conflicts relationships are checked in order to achieve the test
        co-installability of the package.

        The method returns a boolean which is True if the given package is
        co-installable in the given system.
        """

        # local copies for better performances
        binaries = self.binaries['testing'][arch]
        parse_depends = apt_pkg.ParseDepends
        check_depends = apt_pkg.CheckDep

        # unregister conflicts, local method to remove conflicts
        # registered from a given package.
        def unregister_conflicts(pkg, conflicts):
            for c in conflicts.keys():
                if conflicts[c][3] == pkg:
                    del conflicts[c]

        # handle a conflict, local method to solve a conflict which happened
        # in the system; the behaviour of the conflict-solver is:
        #   1. If there are alternatives for the package which must be removed,
        #      try them, and if one of them resolves the system return True;
        #   2. If none of the alternatives can solve the conflict, then call
        #      itself for the package which depends on the conflicting package.
        #   3. If the top of the dependency tree is reached, then the conflict
        #      can't be solved, so return False.
        def handle_conflict(pkg, source, system, conflicts):
            # reached the top of the tree
            if not system[source][1]:
                return False
            # remove its conflicts
            unregister_conflicts(source, conflicts)
            # if there are alternatives, try them
            alternatives = system[source][0]
            for alt in alternatives:
                if satisfy(alt, [x for x in alternatives if x != alt], pkg_from=system[source][1],
                        system=system, conflicts=conflicts, excluded=[source]):
                    return (system, conflicts)
            # there are no good alternatives, so remove the package which depends on it
            return handle_conflict(pkg, system[source][1], system, conflicts)

        # dependency tree satisfier, local method which tries to satisfy the dependency
        # tree for a given package. It calls itself recursively in order to check the
        # co-installability of the full tree of dependency of the starting package.
        # If a conflict is detected, it tries to handle it calling the handle_conflict
        # method; if it can't be resolved, then it returns False.
        def satisfy(pkg, pkg_alt=None, pkg_from=None, system=system, conflicts=conflicts, excluded=[]):
            # if it is real package and it is already installed, skip it and return True
            if pkg in binaries[0]:
                if pkg in system:
                    return True
                binary_u = binaries[0][pkg]
            else: binary_u = None

            # if it is a virtual package
            providers = []
            if pkg in binaries[1]:
                providers = binaries[1][pkg]
                # it is both real and virtual, so the providers are alternatives
                if binary_u:
                    providers = filter(lambda x: (not pkg_alt or x not in pkg_alt) and x != pkg, providers)
                    if not pkg_alt:
                        pkg_alt = []
                    pkg_alt.extend(providers)
                # try all the alternatives and if none of them suits, give up and return False
                else:
                    # if we already have a provider in the system, everything is ok and return True
                    if len(filter(lambda x: x in providers and x not in excluded, system)) > 0:
                        return True
                    for p in providers:
                        # try to install the providers skipping excluded packages,
                        # which we already tried but do not work
                        if p in excluded: continue
                        elif satisfy(p, [a for a in providers if a != p], pkg_from):
                            return True
                    # if none of them suits, return False
                    return False

            # if the package doesn't exist, return False
            if not binary_u: return False

            # install the package itto the system, recording which package required it
            # FIXME: what if more than one package requires it???
            system[pkg] = (pkg_alt, pkg_from)

            # register provided packages
            if binary_u['provides']:
                for p in binary_u['provides']:
                    system[p] = ([], pkg)

            # check the conflicts
            if pkg in conflicts:
                name, version, op, conflicting = conflicts[pkg]
                if conflicting not in binary_u['provides'] and ( \
                   op == '' and version == '' or check_depends(binary_u['version'], op, version)):
                    # if conflict is found, check if it can be solved removing
                    # already-installed packages without broking the system; if
                    # this is not possible, give up and return False
                    output = handle_conflict(pkg, conflicting, system.copy(), conflicts.copy())
                    if output:
                        system, conflicts = output
                    else:
                        del system[pkg]
                        return False

            # register conflicts from the just-installed package
            if 'conflicts' in binary_u:
                for block in map(operator.itemgetter(0), parse_depends(binary_u.get('conflicts', []))):
                    name, version, op = block
                    # skip conflicts for packages provided by itself
                    if name in binary_u['provides']: continue
                    # if the conflicting package is in the system (and it is not a self-conflict)
                    if block[0] != pkg and block[0] in system:
                        if block[0] in binaries[0]:
                            binary_c = binaries[0][block[0]]
                        else: binary_c = None
                        if op == '' and version == '' or binary_c and check_depends(binary_c['version'], op, version):
                            # if conflict is found, check if it can be solved removing
                            # already-installed packages without broking the system; if
                            # this is not possible, give up and return False
                            output = handle_conflict(name, pkg, system.copy(), conflicts.copy())
                            if output:
                                system, conflicts = output
                            else:
                                del system[pkg]
                                unregister_conflicts(pkg, conflicts)
                                return False
                    # FIXME: what if more than one package conflicts with it???
                    conflicts[block[0]] = (name, version, op, pkg)

            # list all its dependencies ...
            dependencies = []
            for type in ('pre-depends', 'depends'):
                if type not in binary_u: continue
                dependencies.extend(parse_depends(binary_u[type]))

            # ... and go through them
            for block in dependencies:
                # list the possible alternatives, in case of a conflict
                alternatives = map(operator.itemgetter(0), block)
                valid = False
                for name, version, op in block:
                    # if the package is broken, don't try it at all
                    if name in broken: continue
                    # otherwise, if it is already installed or it is installable, the block is satisfied
                    if name in system or satisfy(name, [a for a in alternatives if a != name], pkg):
                        valid = True
                        break
                # if the block can't be satisfied, the package is not installable so
                # we need to remove it, its conflicts and its provided packages and
                # return False
                if not valid:
                    del system[pkg]
                    unregister_conflicts(pkg, conflicts)
                    for p in providers:
                        if satisfy(p, [a for a in providers if a != p], pkg_from):
                            return True
                    return False

            # if all the blocks have been satisfied, the package is installable
            return True
    
        # check the package at the top of the tree
        return satisfy(pkg)

    def doop_source(self, pkg):
        """Apply a change to the testing distribution as requested by `pkg`

        This method apply the changes required by the action `pkg` tracking
        them so it will be possible to revert them.

        The method returns a list of the package name, the suite where the
        package comes from, the list of packages affected by the change and
        the dictionary undo which can be used to rollback the changes.
        """
        undo = {'binaries': {}, 'sources': {}, 'virtual': {}, 'nvirtual': []}

        affected = []
        arch = None

        # local copies for better performances
        sources = self.sources
        binaries = self.binaries['testing']

        # arch = "<source>/<arch>",
        if "/" in pkg:
            pkg_name, arch = pkg.split("/")
            suite = "unstable"
        # removal of source packages = "-<source>",
        elif pkg[0] == "-":
            pkg_name = pkg[1:]
            suite = "testing"
        # testing-proposed-updates = "<source>_tpu"
        elif pkg[0].endswith("_tpu"):
            pkg_name = pkg[:-4]
            suite = "tpu"
        # normal update of source packages = "<source>"
        else:
            pkg_name = pkg
            suite = "unstable"

        # remove all binary packages (if the source already exists)
        if not arch:
            if pkg_name in sources['testing']:
                source = sources['testing'][pkg_name]
                # remove all the binaries
                for p in source['binaries']:
                    binary, arch = p.split("/")
                    # save the old binary for undo
                    undo['binaries'][p] = binaries[arch][0][binary]
                    # all the reverse dependencies are affected by the change
                    for j in binaries[arch][0][binary]['rdepends']:
                        key = (j, arch)
                        if key not in affected: affected.append(key)
                    # remove the provided virtual packages
                    for j in binaries[arch][0][binary]['provides']:
                        key = j + "/" + arch
                        if key not in undo['virtual']:
                            undo['virtual'][key] = binaries[arch][1][j][:]
                        binaries[arch][1][j].remove(binary)
                        if len(binaries[arch][1][j]) == 0:
                            del binaries[arch][1][j]
                    # finally, remove the binary package
                    del binaries[arch][0][binary]
                # remove the source package
                undo['sources'][pkg_name] = source
                del sources['testing'][pkg_name]
            else:
                # the package didn't exist, so we mark it as to-be-removed in case of undo
                undo['sources']['-' + pkg_name] = True

        # single architecture update (eg. binNMU)
        else:
            if pkg_name in binaries[arch][0]:
                for j in binaries[arch][0][pkg_name]['rdepends']:
                    key = (j, arch)
                    if key not in affected: affected.append(key)
            source = {'binaries': [pkg]}

        # add the new binary packages (if we are not removing)
        if pkg[0] != "-":
            source = sources[suite][pkg_name]
            for p in source['binaries']:
                binary, arch = p.split("/")
                key = (binary, arch)
                # obviously, added/modified packages are affected
                if key not in affected: affected.append(key)
                # if the binary already exists (built from another source)
                if binary in binaries[arch][0]:
                    # save the old binary package
                    undo['binaries'][p] = binaries[arch][0][binary]
                    # all the reverse dependencies are affected by the change
                    for j in binaries[arch][0][binary]['rdepends']:
                        key = (j, arch)
                        if key not in affected: affected.append(key)
                    # all the reverse conflicts and their dependency tree are affected by the change
                    for j in binaries[arch][0][binary]['rconflicts']:
                        key = (j, arch)
                        if key not in affected: affected.append(key)
                        for p in self.get_full_tree(j, arch, 'testing'):
                            key = (p, arch)
                            if key not in affected: affected.append(key)
                # add/update the binary package
                binaries[arch][0][binary] = self.binaries[suite][arch][0][binary]
                # register new provided packages
                for j in binaries[arch][0][binary]['provides']:
                    key = j + "/" + arch
                    if j not in binaries[arch][1]:
                        undo['nvirtual'].append(key)
                        binaries[arch][1][j] = []
                    elif key not in undo['virtual']:
                        undo['virtual'][key] = binaries[arch][1][j][:]
                    binaries[arch][1][j].append(binary)
                # all the reverse dependencies are affected by the change
                for j in binaries[arch][0][binary]['rdepends']:
                    key = (j, arch)
                    if key not in affected: affected.append(key)
                # FIXME: why not the conflicts and their tree, too?

            # register reverse dependencies and conflicts for the new binary packages
            for p in source['binaries']:
                binary, arch = p.split("/")
                self.register_reverses(binary, binaries[arch][0] , binaries[arch][1])

            # add/update the source package
            sources['testing'][pkg_name] = sources[suite][pkg_name]

        # return the package name, the suite, the list of affected packages and the undo dictionary
        return (pkg_name, suite, affected, undo)

    def get_full_tree(self, pkg, arch, suite):
        """Calculate the full dependency tree for the given package

        This method returns the full dependency tree for the package `pkg`,
        inside the `arch` architecture for the suite `suite`.
        """
        packages = [pkg]
        binaries = self.binaries[suite][arch][0]
        l = n = 0
        while len(packages) > l:
            l = len(packages)
            for p in packages[n:]:
                packages.extend([x for x in binaries[p]['rdepends'] if x not in packages and x in binaries])
            n = l
        return packages

    def iter_packages(self, packages, output):
        """Iter on the list of actions and apply them one-by-one

        This method apply the changes from `packages` to testing, checking the uninstallability
        counters for every action performed. If the action do not improve the it, it is reverted.
        The method returns the new uninstallability counters and the remaining actions if the
        final result is successful, otherwise (None, None).
        """
        extra = []
        nuninst_comp = self.get_nuninst()

        # local copies for better performances
        check_installable = self.check_installable
        binaries = self.binaries['testing']
        sources = self.sources
        architectures = self.options.architectures
        nobreakall_arches = self.options.nobreakall_arches
        new_arches = self.options.new_arches
        break_arches = self.options.break_arches

        output.write("recur: [%s] %s %d/%d\n" % (",".join(self.selected), "", len(packages), len(extra)))

        # loop on the packages (or better, actions)
        while packages:
            pkg = packages.pop(0)
            output.write("trying: %s\n" % (pkg))

            better = True
            nuninst = {}

            # apply the changes
            pkg_name, suite, affected, undo = self.doop_source(pkg)

            # check the affected packages on all the architectures
            for arch in ("/" in pkg and (pkg.split("/")[1],) or architectures):
                if arch not in nobreakall_arches:
                    skip_archall = True
                else: skip_archall = False

                nuninst[arch] = [x for x in nuninst_comp[arch] if x in binaries[arch][0]]
                broken = nuninst[arch][:]
                to_check = [x[0] for x in affected if x[1] == arch]

                # broken packages (first round)
                old_broken = None
                last_broken = None
                while old_broken != broken:
                    old_broken = broken[:]
                    for p in to_check:
                        if p == last_broken: break
                        if p not in binaries[arch][0] or \
                           skip_archall and binaries[arch][0][p]['architecture'] == 'all': continue
                        r = check_installable(p, arch, 'testing', excluded=broken, conflicts=True)
                        if not r and p not in broken:
                            last_broken = p
                            broken.append(p)
                        elif r and p in nuninst[arch]:
                            last_broken = p
                            broken.remove(p)
                            nuninst[arch].remove(p)

                # broken packages (second round, reverse dependencies of the first round)
                l = 0
                last_broken = None
                while l < len(broken):
                    l = len(broken)
                    for j in broken:
                        if j not in binaries[arch][0]: continue
                        for p in binaries[arch][0][j]['rdepends']:
                            if p in broken or p not in binaries[arch][0] or \
                               skip_archall and binaries[arch][0][p]['architecture'] == 'all': continue
                            r = check_installable(p, arch, 'testing', excluded=broken, conflicts=True)
                            if not r and p not in broken:
                                l = -1
                                last_broken = j
                                broken.append(p)
                    if l != -1 and last_broken == j: break

                # update the uninstallability counter
                for b in broken:
                    if b not in nuninst[arch]:
                        nuninst[arch].append(b)

                # if the uninstallability counter is worse than before, break the loop
                if (("/" in pkg and arch not in new_arches) or \
                    (arch not in break_arches)) and len(nuninst[arch]) > len(nuninst_comp[arch]):
                    better = False
                    break

            # check if the action improved the uninstallability counters
            if better:
                self.selected.append(pkg)
                packages.extend(extra)
                extra = []
                output.write("accepted: %s\n" % (pkg))
                output.write("   ori: %s\n" % (self.eval_nuninst(self.nuninst_orig)))
                output.write("   pre: %s\n" % (self.eval_nuninst(nuninst_comp)))
                output.write("   now: %s\n" % (self.eval_nuninst(nuninst)))
                if len(self.selected) <= 20:
                    output.write("   all: %s\n" % (" ".join(self.selected)))
                else:
                    output.write("  most: (%d) .. %s\n" % (len(self.selected), " ".join(self.selected[-20:])))
                for k in nuninst:
                    nuninst_comp[k] = nuninst[k]
            else:
                output.write("skipped: %s (%d <- %d)\n" % (pkg, len(extra), len(packages)))
                output.write("    got: %s\n" % (self.eval_nuninst(nuninst, "/" in pkg and nuninst_comp or None)))
                output.write("    * %s: %s\n" % (arch, ", ".join(sorted([b for b in broken if b not in nuninst_comp[arch]]))))
                extra.append(pkg)

                # undo the changes (source)
                for k in undo['sources'].keys():
                    if k[0] == '-':
                        del sources['testing'][k[1:]]
                    else: sources['testing'][k] = undo['sources'][k]

                # undo the changes (new binaries)
                if pkg in sources[suite]:
                    for p in sources[suite][pkg]['binaries']:
                        binary, arch = p.split("/")
                        del binaries[arch][0][binary]

                # undo the changes (binaries)
                for p in undo['binaries'].keys():
                    binary, arch = p.split("/")
                    binaries[arch][0][binary] = undo['binaries'][p]

                # undo the changes (virtual packages)
                for p in undo['nvirtual']:
                    j, arch = p.split("/")
                    del binaries[arch][1][j]
                for p in undo['virtual']:
                    j, arch = p.split("/")
                    if j[0] == '-':
                        del binaries[arch][1][j[1:]]
                    else: binaries[arch][1][j] = undo['virtual'][p]

        output.write(" finish: [%s]\n" % ",".join(self.selected))
        output.write("endloop: %s\n" % (self.eval_nuninst(self.nuninst_orig)))
        output.write("    now: %s\n" % (self.eval_nuninst(nuninst_comp)))
        output.write(self.eval_uninst(self.newlyuninst(self.nuninst_orig, nuninst_comp)))
        output.write("\n")

        output.write("Apparently successful\n")
        return (nuninst_comp, extra)

    def do_all(self, output, maxdepth=0, init=None):
        """Testing update runner

        This method tries to update testing checking the uninstallability
        counters before and after the actions to decide if the update was
        successful or not.
        """
        self.__log("> Calculating current uninstallability counters", type="I")
        nuninst_start = self.get_nuninst()
        output.write("start: %s\n" % self.eval_nuninst(nuninst_start))
        output.write("orig: %s\n" % self.eval_nuninst(nuninst_start))

        self.__log("> First loop on the packages with depth = 0", type="I")
        self.selected = []
        self.nuninst_orig = nuninst_start
        (nuninst_end, extra) = self.iter_packages(self.upgrade_me[:], output)

        if nuninst_end:
            output.write("final: %s\n" % ",".join(self.selected))
            output.write("start: %s\n" % self.eval_nuninst(nuninst_start))
            output.write(" orig: %s\n" % self.eval_nuninst(self.nuninst_orig))
            output.write("  end: %s\n" % self.eval_nuninst(nuninst_end))
            output.write("SUCCESS (%d/%d)\n" % (len(self.upgrade_me), len(extra)))

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
        if not self.options.actions:
            self.write_excuses()
        else: self.upgrade_me = self.options.actions.split()

        self.upgrade_testing()

if __name__ == '__main__':
    Britney().main()
