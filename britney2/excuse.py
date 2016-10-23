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

from collections import defaultdict
import re


class Excuse(object):
    """Excuse class
    
    This class represents an update excuse, which is a detailed explanation
    of why a package can or cannot be updated in the testing distribution from
    a newer package in another distribution (like for example unstable).

    The main purpose of the excuses is to be written in an HTML file which
    will be published over HTTP. The maintainers will be able to parse it
    manually or automatically to find the explanation of why their packages
    have been updated or not.
    """

    ## @var reemail
    # Regular expression for removing the email address
    reemail = re.compile(r" *<.*?>")

    def __init__(self, name):
        """Class constructor
        
        This method initializes the excuse with the specified name and
        the default values.
        """
        self.name = name
        self.ver = ("-", "-")
        self.maint = None
        self.urgency = None
        self.daysold = None
        self.mindays = None
        self.section = None
        self._is_valid = False
        self._dontinvalidate = False
        self.needs_approval = False
        self.hints = []
        self.forced = False

        self.invalid_deps = []
        self.deps = {}
        self.sane_deps = []
        self.break_deps = []
        self.bugs = []
        self.newbugs = set()
        self.oldbugs = set()
        self.reason = {}
        self.htmlline = []
        self.missing_builds = set()
        self.missing_builds_ood_arch = set()
        self.old_binaries = defaultdict(set)
        self.policy_info = {}

    def sortkey(self):
        if self.daysold == None:
            return (-1, self.name)
        return (self.daysold, self.name)

    @property
    def is_valid(self):
        return self._is_valid

    @is_valid.setter
    def is_valid(self, value):
        self._is_valid = value

    @property
    def dontinvalidate(self):
        return self._dontinvalidate

    @dontinvalidate.setter
    def dontinvalidate(self, value):
        self._dontinvalidate = value

    def set_vers(self, tver, uver):
        """Set the testing and unstable versions"""
        if tver: self.ver = (tver, self.ver[1])
        if uver: self.ver = (self.ver[0], uver)

    def set_maint(self, maint):
        """Set the package maintainer's name"""
        self.maint = self.reemail.sub("", maint)

    def set_section(self, section):
        """Set the section of the package"""
        self.section = section

    def set_urgency(self, date):
        """Set the urgency of upload of the package"""
        self.urgency = date

    def add_dep(self, name, arch):
        """Add a dependency"""
        if name not in self.deps: self.deps[name]=[]
        self.deps[name].append(arch)

    def add_sane_dep(self, name):
        """Add a sane dependency"""
        if name not in self.sane_deps: self.sane_deps.append(name)

    def add_break_dep(self, name, arch):
        """Add a break dependency"""
        if (name, arch) not in self.break_deps:
            self.break_deps.append( (name, arch) )

    def invalidate_dep(self, name):
        """Invalidate dependency"""
        if name not in self.invalid_deps: self.invalid_deps.append(name)

    def setdaysold(self, daysold, mindays):
        """Set the number of days from the upload and the minimum number of days for the update"""
        self.daysold = daysold
        self.mindays = mindays

    def force(self):
        """Add force hint"""
        self.forced = True

    def addhtml(self, note):
        """Add a note in HTML"""
        self.htmlline.append(note)

    def missing_build_on_arch(self, arch):
        """Note that the item is missing a build on a given architecture"""
        self.missing_builds.add(arch)

    def missing_build_on_ood_arch(self, arch):
        """Note that the item is missing a build on a given "out of date" architecture"""
        self.missing_builds.add(arch)

    def add_old_binary(self, binary, from_source_version):
        """Denote than an old binary ("cruft") is available from a previous source version"""
        self.old_binaries[from_source_version].add(binary)

    def add_hint(self, hint):
        self.hints.append(hint)

    def html(self):
        """Render the excuse in HTML"""
        res = "<a id=\"%s\" name=\"%s\">%s</a> (%s to %s)\n<ul>\n" % \
            (self.name, self.name, self.name, self.ver[0], self.ver[1])
        if self.maint:
            res = res + "<li>Maintainer: %s\n" % (self.maint)
        if self.section and self.section.find("/") > -1:
            res = res + "<li>Section: %s\n" % (self.section)
        if self.daysold != None:
            if self.mindays == 0:
                res = res + ("<li>%d days old\n" % self.daysold)
            elif self.daysold < self.mindays:
                res = res + ("<li>Too young, only %d of %d days old\n" %
                (self.daysold, self.mindays))
            else:
                res = res + ("<li>%d days old (needed %d days)\n" %
                (self.daysold, self.mindays))
        for x in self.htmlline:
            res = res + "<li>" + x + "\n"
        lastdep = ""
        for x in sorted(self.deps, key=lambda x: x.split('/')[0]):
            dep = x.split('/')[0]
            if dep == lastdep: continue
            lastdep = dep
            if x in self.invalid_deps:
                res = res + "<li>Depends: %s <a href=\"#%s\">%s</a> (not considered)\n" % (self.name, dep, dep)
            else:
                res = res + "<li>Depends: %s <a href=\"#%s\">%s</a>\n" % (self.name, dep, dep)
        for (n,a) in self.break_deps:
            if n not in self.deps:
                res += "<li>Ignoring %s depends: <a href=\"#%s\">%s</a>\n" % (a, n, n)
        if self.is_valid:
            res += "<li>Valid candidate\n"
        else:
            res += "<li>Not considered\n"
        res = res + "</ul>\n"
        return res

    def setbugs(self, oldbugs, newbugs):
        """"Set the list of old and new bugs"""
        self.newbugs.update(newbugs)
        self.oldbugs.update(oldbugs)

    def addreason(self, reason):
        """"adding reason"""
        self.reason[reason] = 1

    # TODO: remove
    def _text(self):
        """Render the excuse in text"""
        res = []
        for x in self.htmlline:
            res.append("" + x + "")
        return res

    def excusedata(self):
        """Render the excuse in as key-value data"""
        source = self.name
        if '/' in source:
            source = source.split("/")[0]
        if source[0] == '-':
            source = source[1:]
        excusedata = {}
        excusedata["excuses"] = self._text()
        excusedata["item-name"] = self.name
        excusedata["source"] = source
        excusedata["old-version"] = self.ver[0]
        excusedata["new-version"] = self.ver[1]
        if self.maint:
            excusedata['maintainer'] = self.maint
        if self.section and self.section.find("/") > -1:
            excusedata['component'] = self.section.split('/')[0]
        if self.policy_info:
            excusedata['policy_info'] = self.policy_info
        if self.missing_builds or self.missing_builds_ood_arch:
            excusedata['missing-builds'] = {
                'on-architectures': sorted(self.missing_builds),
                'on-unimportant-architectures': sorted(self.missing_builds_ood_arch),
            }
        if self.deps or self.invalid_deps or self.break_deps:
            excusedata['dependencies'] = dep_data = {}
            migrate_after = sorted(x for x in self.deps if x not in self.invalid_deps)
            break_deps = [x for x, _ in self.break_deps if x not in self.deps]

            if self.invalid_deps:
                dep_data['blocked-by'] = sorted(self.invalid_deps)
            if migrate_after:
                dep_data['migrate-after'] = migrate_after
            if break_deps:
                dep_data['unimportant-dependencies'] = sorted(break_deps)
        if self.needs_approval:
            status = 'not-approved'
            for h in self.hints:
                if h.type == 'unblock':
                    status = 'approved'
                    break
            excusedata['manual-approval-status'] = status
        if self.hints:
            hint_info = [{
                             'hint-type': h.type,
                             'hint-from': h.user,
                         } for h in self.hints]

            excusedata['hints'] = hint_info
        if self.old_binaries:
            excusedata['old-binaries'] = {x: sorted(self.old_binaries[x]) for x in self.old_binaries}
        if self.forced:
            excusedata["forced-reason"] = sorted(list(self.reason.keys()))
            excusedata["reason"] = []
        else:
            excusedata["reason"] = sorted(list(self.reason.keys()))
        excusedata["is-candidate"] = self.is_valid
        return excusedata

