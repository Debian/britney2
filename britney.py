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

import os
import re
import sys
import string
import time
import optparse

import apt_pkg

from excuse import Excuse

VERSION = '2.0.alpha1'


class Britney:
    """Debian testing updater script"""

    BINARY_FIELDS = ('Version', 'Pre-Depends', 'Depends', 'Conflicts', 'Provides', 'Source', 'Architecture', 'Version')
    SOURCE_FIELDS = ('Version', 'Maintainer', 'Section')

    HINTS_STANDARD = ("easy", "hint", "remove", "block", "unblock", "urgent", "approve")
    HINTS_ALL = ("force", "force-hint", "block-all") + HINTS_STANDARD

    def __init__(self):
        """Class constructor method: initialize and populate the data lists"""
        self.__parse_arguments()
        apt_pkg.init()
        self.date_now = int(((time.time() / (60*60)) - 15) / 24)
        self.sources = {'testing': self.read_sources(self.options.testing),
                        'unstable': self.read_sources(self.options.unstable),
                        'tpu': self.read_sources(self.options.tpu),}
        self.binaries = {'testing': {}, 'unstable': {}, 'tpu': {}}
        for arch in self.options.architectures.split():
            self.binaries['testing'][arch] = self.read_binaries(self.options.testing, "testing", arch)
            self.binaries['unstable'][arch] = self.read_binaries(self.options.unstable, "unstable", arch)
            self.binaries['tpu'][arch] = self.read_binaries(self.options.tpu, "tpu", arch)
        self.bugs = {'unstable': self.read_bugs(self.options.unstable),
                     'testing': self.read_bugs(self.options.testing),}
        self.normalize_bugs()
        self.dates = self.read_dates(self.options.testing)
        self.urgencies = self.read_urgencies(self.options.testing)
        self.approvals = self.read_approvals(self.options.tpu)
        self.hints = self.read_hints(self.options.unstable)
        self.excuses = []

    def __parse_arguments(self):
        """Parse command line arguments"""
        self.parser = optparse.OptionParser(version="%prog " + VERSION)
        self.parser.add_option("-v", "", action="count", dest="verbose", help="enable verbose output")
        self.parser.add_option("-c", "--config", action="store", dest="config",
                          default="/etc/britney.conf", help="path for the configuration file")
        (self.options, self.args) = self.parser.parse_args()
        if not os.path.isfile(self.options.config):
            self.__log("Unable to read the configuration file (%s), exiting!" % self.options.config, type="E")
            sys.exit(1)
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

    def __log(self, msg, type="I"):
        """Print info messages according to verbosity level"""
        if self.options.verbose or type in ("E", "W"):
            print "%s: [%s] - %s" % (type, time.asctime(), msg)

    # Data reading/writing

    def read_sources(self, basedir):
        """Read the list of source packages from the specified directory"""
        sources = {}
        package = None
        filename = os.path.join(basedir, "Sources")
        self.__log("Loading source packages from %s" % filename)
        for l in open(filename):
            if l.startswith(' ') or ':' not in l: continue
            fields = map(string.strip, l.split(":",1))
            if fields[0] == 'Package':
                package = fields[1]
                sources[package] = dict([(k.lower(), None) for k in self.SOURCE_FIELDS] + [('binaries', [])])
            elif fields[0] in self.SOURCE_FIELDS:
                sources[package][fields[0].lower()] = fields[1]
        return sources

    def read_bugs(self, basedir):
        """Read the RC bugs count from the specified directory"""
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

    def maxver(self, pkg, dist):
        maxver = None
        if self.sources[dist].has_key(pkg):
            maxver = self.sources[dist][pkg]['version']
        for arch in self.options.architectures.split():
            if not self.binaries[dist][arch][0].has_key(pkg): continue
            pkgv = self.binaries[dist][arch][0][pkg]['version']
            if maxver == None or apt_pkg.VersionCompare(pkgv, maxver) > 0:
                maxver = pkgv
        return maxver

    def normalize_bugs(self):
        """Normalize the RC bugs count for testing and unstable"""
        for pkg in set(self.bugs['testing'].keys() + self.bugs['unstable'].keys()):
            if not self.bugs['testing'].has_key(pkg):
                self.bugs['testing'][pkg] = 0
            elif not self.bugs['unstable'].has_key(pkg):
                self.bugs['unstable'][pkg] = 0

            maxvert = self.maxver(pkg, 'testing')
            if maxvert == None or \
               self.bugs['testing'][pkg] == self.bugs['unstable'][pkg]:
                continue

            maxveru = self.maxver(pkg, 'unstable')
            if maxveru == None:
                continue
            elif apt_pkg.VersionCompare(maxvert, maxveru) >= 0:
                self.bugs['testing'][pkg] = self.bugs['unstable'][pkg]

    def read_dates(self, basedir):
        """Read the upload data for the packages from the specified directory"""
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
        """Read the upload urgency of the packages from the specified directory"""
        urgencies = {}
        filename = os.path.join(basedir, "Urgency")
        self.__log("Loading upload urgencies from %s" % filename)
        for line in open(filename):
            l = line.strip().split()
            if len(l) != 3: continue

            urgency_old = urgencies.get(l[0], self.options.default_urgency)
            mindays_old = self.MINDAYS.get(urgency_old, self.MINDAYS[self.options.default_urgency])
            mindays_new = self.MINDAYS.get(l[2], self.MINDAYS[self.options.default_urgency])
            if mindays_old <= mindays_new:
                continue
            tsrcv = self.sources['testing'].get(l[0], None)
            if tsrcv and apt_pkg.VersionCompare(tsrcv['version'], l[1]) >= 0:
                continue
            usrcv = self.sources['unstable'].get(l[0], None)
            if not usrcv or apt_pkg.VersionCompare(usrcv['version'], l[1]) < 0:
                continue
            urgencies[l[0]] = l[2]

        return urgencies

    def read_approvals(self, basedir):
        """Read the approvals data from the specified directory"""
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
        """Read the approvals data from the specified directory"""
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

    def read_binaries(self, basedir, distribution, arch):
        """Read the list of binary packages from the specified directory"""
        packages = {}
        package = None
        filename = os.path.join(basedir, "Packages_%s" % arch)
        self.__log("Loading binary packages from %s" % filename)
        for l in open(filename):
            if l.startswith(' ') or ':' not in l: continue
            fields = map(string.strip, l.split(":",1))
            if fields[0] == 'Package':
                package = fields[1]
                packages[package] = dict([(k.lower(), None) for k in self.BINARY_FIELDS] + [('rdepends', [])])
                packages[package]['source'] = package
                packages[package]['source-ver'] = None
            elif fields[0] == 'Source':
                packages[package][fields[0].lower()] = fields[1].split(" ")[0]
                if "(" in fields[1]:
                    packages[package]['source-ver'] = fields[1].split("(")[1].split(")")[0]
            elif fields[0] in self.BINARY_FIELDS:
                packages[package][fields[0].lower()] = fields[1]

        provides = {}
        for pkgname in packages:
            if not packages[pkgname]['source-ver']:
                packages[pkgname]['source-ver'] = packages[pkgname]['version']
            if packages[pkgname]['source'] in self.sources[distribution]:
                self.sources[distribution][packages[pkgname]['source']]['binaries'].append(pkgname + "/" + arch)
            if not packages[pkgname]['provides']:
                continue
            parts = map(string.strip, packages[pkgname]["provides"].split(","))
            del packages[pkgname]["provides"]
            for p in parts:
                if p in provides:
                    provides[p].append(pkgname)
                else:
                    provides[p] = [pkgname]

        for pkgname in packages:
            dependencies = []
            if packages[pkgname]['depends']:
                packages[pkgname]['depends-txt'] = packages[pkgname]['depends']
                packages[pkgname]['depends'] = apt_pkg.ParseDepends(packages[pkgname]['depends'])
                dependencies.extend(packages[pkgname]['depends'])
            if packages[pkgname]['pre-depends']:
                packages[pkgname]['pre-depends-txt'] = packages[pkgname]['pre-depends']
                packages[pkgname]['pre-depends'] = apt_pkg.ParseDepends(packages[pkgname]['pre-depends'])
                dependencies.extend(packages[pkgname]['pre-depends'])
            for p in dependencies:
                for a in p:
                    if a[0] not in packages: continue
                    packages[a[0]]['rdepends'].append((pkgname, a[1], a[2]))

        return (packages, provides)

    # Package analisys

    def should_remove_source(self, pkg):
        """Check if a source package should be removed from testing"""
        if self.sources['unstable'].has_key(pkg):
            return False
        src = self.sources['testing'][pkg]
        excuse = Excuse("-" + pkg)
        excuse.set_vers(src['version'], None)
        src['maintainer'] and excuse.set_maint(src['maintainer'].strip())
        src['section'] and excuse.set_section(src['section'].strip())
        excuse.addhtml("Valid candidate")
        self.excuses.append(excuse)
        return True

    def same_source(self, sv1, sv2):
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

    def get_dependency_solvers(self, block, arch, distribution):
        packages = []
        missing = []

        for name, version, op in block:
            real_package = False
            if name in self.binaries[distribution][arch][0]:
                real_package = True
                package = self.binaries[distribution][arch][0][name]
                if op == '' and version == '' or apt_pkg.CheckDep(package['version'], op, version):
                    packages.append(name)
                    return (True, packages)

            # TODO: this would be enough according to policy, but not according to britney v.1
            #if op == '' and version == '' and name in self.binaries['unstable'][arch][1]:
            #    # packages.extend(self.binaries['unstable'][arch][1][name])
            #    return (True, packages)

            if name in self.binaries['unstable'][arch][1]:
                for prov in self.binaries['unstable'][arch][1][name]:
                    package = self.binaries['unstable'][arch][0][prov]
                    if op == '' and version == '' or apt_pkg.CheckDep(package['version'], op, version):
                        packages.append(name)
                        break
                if len(packages) > 0:
                    return (True, packages)

            if real_package:
                missing.append(name)

        return (False, missing)

    def excuse_unsat_deps(self, pkg, src, arch, suite, excuse, ignore_break=0):
        binary_u = self.binaries[suite][arch][0][pkg]
        for type in ('Pre-Depends', 'Depends'):
            type_key = type.lower()
            if not binary_u[type_key]:
                continue

            packages = []
            for block, block_txt in map(None, binary_u[type_key], binary_u[type_key + '-txt'].split(',')):
                solved, packages = self.get_dependency_solvers(block, arch, 'testing')
                if solved: continue

                solved, packages = self.get_dependency_solvers(block, arch, suite)
                packages = [self.binaries[suite][arch][0][p]['source'] for p in packages]
                if src in packages: continue

                if len(packages) == 0:
                    excuse.addhtml("%s/%s unsatisfiable %s: %s" % (pkg, arch, type, block_txt.strip()))

                for p in packages:
                    if ignore_break or arch not in self.options.break_arches.split():
                        excuse.add_dep(p)
                    else:
                        excuse.add_break_dep(p, arch)

    def should_upgrade_srcarch(self, src, arch, suite):
        # binnmu this arch?
        source_t = self.sources['testing'][src]
        source_u = self.sources[suite][src]

        ref = "%s/%s%s" % (src, arch, suite != 'unstable' and "_" + suite or "")

        excuse = Excuse(ref)
        excuse.set_vers(source_t['version'], source_t['version'])
        source_u['maintainer'] and excuse.set_maint(source_u['maintainer'].strip())
        source_u['section'] and excuse.set_section(source_u['section'].strip())
        
        anywrongver = False
        anyworthdoing = False

        if self.hints["remove"].has_key(src) and \
           self.same_source(source_t['version'], self.hints["remove"][src][0]):
            excuse.addhtml("Removal request by %s" % (self.hints["remove"][src][1]))
            excuse.addhtml("Trying to remove package, not update it")
            excuse.addhtml("Not considered")
            self.excuses.append(excuse)
            return False

        for pkg in source_u['binaries']:
            if not pkg.endswith("/" + arch): continue
            pkg_name = pkg.split("/")[0]

            binary_t = pkg in source_t['binaries'] and self.binaries['testing'][arch][0][pkg_name] or None
            binary_u = self.binaries[suite][arch][0][pkg_name]
            pkgsv = self.binaries[suite][arch][0][pkg_name]['source-ver']

            if binary_u['architecture'] == 'all':
                excuse.addhtml("Ignoring %s %s (from %s) as it is arch: all" % (pkg, binary_u['version'], pkgsv))
                continue

            if not self.same_source(source_t['version'], pkgsv):
                anywrongver = True
                excuse.addhtml("From wrong source: %s %s (%s not %s)" % (pkg, binary_u['version'], pkgsv, source_t['version']))
                break

            self.excuse_unsat_deps(pkg_name, src, arch, suite, excuse)

            if not binary_t:
                excuse.addhtml("New binary: %s (%s)" % (pkg, binary_u['version']))
                anyworthdoing = True
                continue

            vcompare = apt_pkg.VersionCompare(binary_t['version'], binary_u['version'])
            if vcompare > 0:
                anywrongver = True
                excuse.addhtml("Not downgrading: %s (%s to %s)" % (pkg, binary_t['version'], binary_u['version']))
                break
            elif vcompare < 0:
                excuse.addhtml("Updated binary: %s (%s to %s)" % (pkg, binary_t['version'], binary_u['version']))
                anyworthdoing = True

        if not anywrongver and (anyworthdoing or src in self.sources[suite]):
            srcv = self.sources[suite][src]['version']
            ssrc = self.same_source(source_t['version'], srcv)
            for pkg in set(k.split("/")[0] for k in self.sources['testing'][src]['binaries']):
                if self.binaries['testing'][arch][0][pkg]['architecture'] == 'all':
                    excuse.addhtml("Ignoring removal of %s as it is arch: all" % (pkg))
                    continue
                if not self.binaries[suite][arch][0].has_key(pkg):
                    tpkgv = self.binaries['testing'][arch][0][pkg]['version']
                    excuse.addhtml("Removed binary: %s %s" % (pkg, tpkgv))
                    if ssrc: anyworthdoing = True

        if not anywrongver and anyworthdoing:
            excuse.addhtml("Valid candidate")
            self.excuses.append(excuse)
        elif anyworthdoing:
            excuse.addhtml("Not considered")
            self.excuses.append(excuse)
            return False

        return True

    def should_upgrade_src(self, src, suite):
        source_u = self.sources[suite][src]
        if src in self.sources['testing']:
            source_t = self.sources['testing'][src]
            if apt_pkg.VersionCompare(source_t['version'], source_u['version']) == 0:
                # Candidate for binnmus only
                return False
        else:
            source_t = None

        ref = "%s%s" % (src, suite != 'unstable' and "_" + suite or "")

        update_candidate = True

        excuse = Excuse(ref)
        excuse.set_vers(source_t and source_t['version'] or None, source_u['version'])
        source_u['maintainer'] and excuse.set_maint(source_u['maintainer'].strip())
        source_u['section'] and excuse.set_section(source_u['section'].strip())
        
        if source_t and apt_pkg.VersionCompare(source_u['version'], source_t['version']) < 0:
            # Version in unstable is older!
            excuse.addhtml("ALERT: %s is newer in testing (%s %s)" % (src, source_t['version'], source_u['version']))
            self.excuses.append(excuse)
            return False

        urgency = self.urgencies.get(src, self.options.default_urgency)
        if not source_t and urgency != self.options.default_urgency:
            excuse.addhtml("Ignoring %s urgency setting for NEW package" % (urgency))
            urgency = self.options.default_urgency

        if self.hints["remove"].has_key(src):
            if source_t and self.same_source(source_t['version'], self.hints['remove'][src][0]) or \
               self.same_source(source_u['version'], self.hints['remove'][src][0]):
                excuse.addhtml("Removal request by %s" % (self.hints["remove"][src][1]))
                excuse.addhtml("Trying to remove package, not update it")
            update_candidate = False

        blocked = None
        if self.hints["block"].has_key(src):
            blocked = self.hints["block"][src]
        elif self.hints["block-all"].has_key("source"):
            blocked = self.hints["block-all"]["source"]

        if blocked:
            unblock = self.hints["unblock"].get(src,(None,None))
            if unblock[0] != None and self.same_source(unblock[0], source_u['version']):
                excuse.addhtml("Ignoring request to block package by %s, due to unblock request by %s" % (blocked, unblock[1]))
            else:
                if unblock[0] != None:
                    excuse.addhtml("Unblock request by %s ignored due to version mismatch: %s" % (unblock[1], unblock[0]))
                excuse.addhtml("Not touching package, as requested by %s (contact debian-release if update is needed)" % (blocked))
                update_candidate = False

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

        pkgs = {src: ["source"]}
        for arch in self.options.architectures.split():
            oodbins = {}
            for pkg in set(k.split("/")[0] for k in self.sources[suite][src]['binaries']):
                if not pkgs.has_key(pkg): pkgs[pkg] = []
                pkgs[pkg].append(arch)

                binary_u = self.binaries[suite][arch][0][pkg]
                pkgsv = binary_u['source-ver']
                if not self.same_source(source_u['version'], pkgsv):
                    if not oodbins.has_key(pkgsv):
                        oodbins[pkgsv] = []
                    oodbins[pkgsv].append(pkg)
                    continue

                if binary_u['architecture'] != 'all' or arch in self.options.nobreakall_arches:
                    self.excuse_unsat_deps(pkg, src, arch, suite, excuse)

            if oodbins:
                oodtxt = ""
                for v in oodbins.keys():
                    if oodtxt: oodtxt = oodtxt + "; "
                    oodtxt = oodtxt + "%s (from <a href=\"http://buildd.debian.org/build.php?arch=%s&pkg=%s&ver=%s\" target=\"_blank\">%s</a>)" % (", ".join(sorted(oodbins[v])), arch, src, v, v)
                text = "out of date on <a href=\"http://buildd.debian.org/build.php?arch=%s&pkg=%s&ver=%s\" target=\"_blank\">%s</a>: %s" % (arch, src, source_u['version'], arch, oodtxt)

                if arch in self.options.fucked_arches:
                    text = text + " (but %s isn't keeping up, so nevermind)" % (arch)
                else:
                    update_candidate = False

                if self.date_now != self.dates[src][1]:
                    excuse.addhtml(text)

        if len(self.sources[suite][src]['binaries']) == 0:
            excuse.addhtml("%s has no binaries on any arch" % src)
            update_candidate = False

        if suite == 'unstable':
            for pkg in pkgs.keys():
                if not self.bugs['testing'].has_key(pkg):
                    self.bugs['testing'][pkg] = 0
                if not self.bugs['unstable'].has_key(pkg):
                    self.bugs['unstable'][pkg] = 0

                if self.bugs['unstable'][pkg] > self.bugs['testing'][pkg]:
                    excuse.addhtml("%s (%s) is <a href=\"http://bugs.debian.org/cgi-bin/pkgreport.cgi?which=pkg&data=%s&sev-inc=critical&sev-inc=grave&sev-inc=serious\" target=\"_blank\">buggy</a>! (%d > %d)" % (pkg, ", ".join(pkgs[pkg]), pkg, self.bugs['unstable'][pkg], self.bugs['testing'][pkg]))
                    update_candidate = False
                elif self.bugs['unstable'][pkg] > 0:
                    excuse.addhtml("%s (%s) is (less) <a href=\"http://bugs.debian.org/cgi-bin/pkgreport.cgi?which=pkg&data=%s&sev-inc=critical&sev-inc=grave&sev-inc=serious\" target=\"_blank\">buggy</a>! (%d <= %d)" % (pkg, ", ".join(pkgs[pkg]), pkg, self.bugs['unstable'][pkg], self.bugs['testing'][pkg]))

        if not update_candidate and self.hints["force"].has_key(src) and self.same_source(source_u['version'], self.hints["force"][src][0]) :
            excuse.dontinvalidate = 1
            excuse.addhtml("Should ignore, but forced by %s" % (self.hints["force"][src][1]))
            update_candidate = True

        if suite == "tpu":
            if self.approvals.has_key("%s_%s" % (src, source_u['version'])):
                excuse.addhtml("Approved by %s" % approvals["%s_%s" % (src, source_u['version'])])
            else:
                excuse.addhtml("NEEDS APPROVAL BY RM")
                update_candidate = False

        if update_candidate:
            excuse.addhtml("Valid candidate")
        else:
            excuse.addhtml("Not considered")

        self.excuses.append(excuse)
        return update_candidate

    def reversed_exc_deps(self):
        res = {}
        for exc in self.excuses:
            for d in exc.deps:
                if not res.has_key(d): res[d] = []
                res[d].append(exc.name)
        return res

    def invalidate_excuses(self, valid, invalid):
        i = 0
        exclookup = {}
        for e in self.excuses:
            exclookup[e.name] = e
        revdeps = self.reversed_exc_deps()
        while i < len(invalid):
            if not revdeps.has_key(invalid[i]):
                i += 1
                continue
            if (invalid[i] + "_tpu") in valid:
                i += 1
                continue
            for x in revdeps[invalid[i]]:
                if x in valid and exclookup[x].dontinvalidate:
                    continue

                exclookup[x].invalidate_dep(invalid[i])
                if x in valid:
                    p = valid.index(x)
                    invalid.append(valid.pop(p))
                    exclookup[x].addhtml("Invalidated by dependency")
                    exclookup[x].addhtml("Not considered")
            i = i + 1
 
    def main(self):
        """Main method, entry point for the analisys"""

        upgrade_me = []

        # Packages to be removed
        for pkg in self.sources['testing']:
            if self.should_remove_source(pkg):
                upgrade_me.append("-" + pkg)

        # Packages to be upgraded from unstable
        for pkg in self.sources['unstable']:
            if self.sources['testing'].has_key(pkg):
                for arch in self.options.architectures.split():
                    if self.should_upgrade_srcarch(pkg, arch, 'unstable'):
                        upgrade_me.append("%s/%s" % (pkg, arch))

            if self.should_upgrade_src(pkg, 'unstable'):
                upgrade_me.append(pkg)

        # Packages to be upgraded from testing-proposed-updates
        for pkg in self.sources['tpu']:
            if self.sources['testing'].has_key(pkg):
                for arch in self.options.architectures.split():
                    if self.should_upgrade_srcarch(pkg, arch, 'tpu'):
                        upgrade_me.append("%s/%s_tpu" % (pkg, arch))

            if self.should_upgrade_src(pkg, 'tpu'):
                upgrade_me.append("%s_tpu" % pkg)

        # Process 'remove' hints
        for src in self.hints["remove"].keys():
            if src in upgrade_me: continue
            if ("-"+src) in upgrade_me: continue
            if not self.sources['testing'].has_key(src): continue

            tsrcv = self.sources['testing'][src]['version']
            if not self.same_source(tsrcv, self.hints["remove"][src][0]): continue

            upgrade_me.append("-%s" % (src))
            excuse = Excuse("-%s" % (src))
            excuse.set_vers(tsrcv, None)
            excuse.addhtml("Removal request by %s" % (self.hints["remove"][src][1]))
            excuse.addhtml("Package is broken, will try to remove")
            self.excuses.append(excuse)

        # Sort excuses by daysold and name
        self.excuses.sort(lambda x, y: cmp(x.daysold, y.daysold) or cmp(x.name, y.name))

        # Extract unconsidered packages
        unconsidered = [e.name for e in self.excuses if e.name not in upgrade_me]

        # Invalidate impossible excuses
        for e in self.excuses:
            for d in e.deps:
                if d not in upgrade_me and d not in unconsidered:
                    e.addhtml("Unpossible dep: %s -> %s" % (e.name, d))
        self.invalidate_excuses(upgrade_me, unconsidered)

        # Write excuses
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
        del self.excuses

        # Some examples ...
        # print self.sources['testing']['zsh-beta']['version']
        # print self.sources['unstable']['zsh-beta']['version']
        # print self.urgencies['zsh-beta']
        # Which packages depend on passwd?
        # for i in self.binaries['testing']['i386'][0]['passwd']['rdepends']:
        #     print i
        # Which packages provide mysql-server?
        # for i in self.binaries['testing']['i386'][1]['mysql-server']:
        #     print i
        # Which binary packages are build from php4 testing source package?
        # print self.sources['testing']['php4']['binaries']


if __name__ == '__main__':
    Britney().main()
