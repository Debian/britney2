#!/usr/bin/env python

# Copyright 2001-6 Anthony Towns

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

import sys, re, string, time, whrandom, math
import britney

if len(sys.argv) != 4:
	print "Must specify testing, unstable, testing-updates directories."
	sys.exit(1)

testingdir = sys.argv[1]
unstabledir = sys.argv[2]
testingupdatesdir = sys.argv[3]

# Configuration information

expected_arches = 13
allarches = [ 'i386', 'sparc', 'alpha', 'powerpc', 'armel', 'hppa', 'ia64', 'mips', 'mipsel', 's390', 'amd64' , 'kfreebsd-i386', 'kfreebsd-amd64']

mindays = { "low" : 10, "medium" : 5, "high" : 2, "critical" : 0, 
	    "emergency" : 0 }
defaulturgency = "low"

# if you're not in this list, arch: all packages are allowed to break on you
nobreakarchallarches = ['i386']
# if you're in this list, your packages may not stay in sync with the source
fuckedarches = ['kfreebsd-i386','kfreebsd-amd64']
# if you're in this list, your uninstallability count may increase
breakarches = ['kfreebsd-i386','kfreebsd-amd64']
# new architectures
newarches = ['kfreebsd-i386','kfreebsd-amd64']

allarches.sort()
arches = [ x for x in allarches if x in nobreakarchallarches ]
arches += [ x for x in allarches if x not in arches and x not in fuckedarches ]
arches += [ x for x in allarches if x not in arches and x not in breakarches ]
arches += [ x for x in allarches if x not in arches and x not in newarches ]
arches += [ x for x in allarches if x not in arches ]

# Subs

def same_source(sv1, sv2):
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

def read_approvals(dir, approver, approved):
	f = open("%s/%s" % (dir, approver))
	line = f.readline()
	while line:
		l = string.split(line)
		if len(l) == 2:
			[pkg,ver] = l
			approved["%s_%s" % (pkg, ver)] = approver
		line = f.readline()
	f.close()

def read_bugs(file):
	bugsperpkg = {}

	f = open(file)
	line = f.readline()
	while line:
		l = string.split(line)
		if len(l) == 2:
			bugsperpkg[l[0]] = string.atoi(l[1])
		line = f.readline()
	f.close()
	return bugsperpkg

def write_bugs(file, bugs):
	f = open(file, 'w')
	pkgs = bugs.keys()
	pkgs.sort()
	for pkg in pkgs:
		if bugs[pkg] == 0: continue
		f.write("%s %d\n" % (pkg, bugs[pkg]))
	f.close()

def read_dates(file):
	dates = {}

	f = open(file)
	line = f.readline()
	while line:
		l = string.split(line)
		if len(l) == 3:
			dates[l[0]] = (l[1], string.atoi(l[2]))
		line = f.readline()
	f.close()
	return dates

def write_dates(file, dates):
	f = open(file, 'w')
	pkgs = dates.keys()
	pkgs.sort()
	for pkg in dates.keys():
		f.write("%s %s %d\n" % ((pkg,) + dates[pkg]))
	f.close()

def read_urgencies(file, testing, unstable):
	urgency = {}

	f = open(file)
	line = f.readline()
	while line:
		l = string.split(line)
		if len(l) == 3:
			uo = urgency.get(l[0], defaulturgency)
			mo = mindays.get(uo, mindays[defaulturgency])
			mn = mindays.get(l[2], mindays[defaulturgency])
			if mo <= mn: 
				line = f.readline()
				continue

			tsrcv = testing.get_version(l[0])
			if tsrcv and britney.versioncmp(tsrcv, l[1]) >= 0:
				line = f.readline()
				continue
			usrcv = unstable.get_version(l[0])
			if not usrcv or britney.versioncmp(usrcv, l[1]) < 0:
				line = f.readline()
				continue
			
			urgency[l[0]] = l[2]

		line = f.readline()
	f.close()
	return urgency

def read_hints(dir, hinter, hints, allowed):
	res = {}
	for k in allowed:
		res[k] = []

	try:
		f = open("%s/%s" % (dir, hinter))
	except IOError:
		return res

	while 1:
		line = f.readline()
		if not line: break

		l = string.split(line)
		if len(l) == 0 or line[0] == "#": 
			continue

		type = l[0]

		if type == "finished":
			break

		if type not in allowed:
			continue

		def mysplit(str):
			x = str.rfind("/")
			if x == -1: return [str]
			return [str[:x], str[x+1:]]

		if type in ["easy", "hint", "force-hint"]:
			l = [ tuple(mysplit(y)) for y in l[1:] ]
			l = [ k for k in l if len(k) == 2 ]
			res[type].append((hinter, l))

		if type in ["block-all"]:
			l = [ (y, hinter) for y in l[1:] ]
			res[type].extend(l)

		if type in ["block"]:
			l = [ (y, hinter) for y in l[1:] ]
			res[type].extend(l)

		if type in ["remove", "approve", "unblock", "force", "urgent"]:
			l = [ tuple(mysplit(y)+[hinter]) for y in l[1:] ]
			l = [ k for k in l if len(k) == 3 ]
			l = [ (p, (v,h)) for (p,v,h) in l ]
			res[type].extend(l)

	f.close()
	return res

class Excuse:
	reemail = re.compile(r"<.*?>")

	def __init__(self, name):
		self.name = name
		self.ver = ("-", "-")
		self.maint = None
		self.pri = None
		self.date = None
		self.urgency = None
		self.daysold = None
		self.mindays = None
		self.section = None
		self.dontinvalidate = 0

		self.invalid_deps = []
		self.deps = []
		self.break_deps = []
		self.bugs = []
		self.htmlline = []

	def set_vers(self, tver, uver):
		if tver: self.ver = (tver, self.ver[1])
		if uver: self.ver = (self.ver[0], uver)

	def set_maint(self, maint):
		self.maint = self.reemail.sub("",maint)
#		self.maint = maint

	def set_section(self, section):
		self.section = section

	def set_priority(self, pri):
		self.pri = pri

	def set_date(self, date):
		self.date = date

	def set_urgency(self, date):
		self.urgency = date

	def add_dep(self, name):
		if name not in self.deps: self.deps.append(name)
	def add_break_dep(self, name, arch):
		if (name, arch) not in self.break_deps:
			self.break_deps.append( (name, arch) )

	def invalidate_dep(self, name):
		if name not in self.invalid_deps: self.invalid_deps.append(name)

	def setdaysold(self, daysold, mindays):
		self.daysold = daysold
		self.mindays = mindays

	def addhtml(self, note):
		self.htmlline.append(note)

	def html(self):
		res = "<a id=\"%s\" name=\"%s\">%s</a> (%s to %s)\n<ul>\n" % \
			(self.name, self.name, self.name, self.ver[0], self.ver[1])
		if self.maint:
			res = res + "<li>Maintainer: %s\n" % (self.maint)
		if self.section and string.find(self.section, "/") > -1:
			res = res + "<li>Section: %s\n" % (self.section)
		if self.daysold != None:
			if self.daysold < self.mindays:
			    res = res + ("<li>Too young, only %d of %d days old\n" %
				(self.daysold, self.mindays))
			else:
			    res = res + ("<li>%d days old (needed %d days)\n" %
				(self.daysold, self.mindays))
		for x in self.htmlline:
			res = res + "<li>" + x + "\n"
		for x in self.deps:
			if x in self.invalid_deps:
				res = res + "<li>Depends: %s <a href=\"#%s\">%s</a> (not considered)\n" % (self.name, x, x)
			else:
				res = res + "<li>Depends: %s <a href=\"#%s\">%s</a>\n" % (self.name, x, x)
		for (n,a) in self.break_deps:
			if n not in self.deps:
				res += "<li>Ignoring %s depends: <a href=\"#%s\">%s</a>\n" % (a, n, n)
		res = res + "</ul>\n"
		return res
		


def should_remove_source(src, orig, new, excs):
	if new.is_present(src): return 0

	okay = 1

	exc = Excuse("-" + src)

	exc.set_vers(orig.get_version(src), None)
	m = orig.get_field(src, "Maintainer")
	if m: exc.set_maint(string.strip(m))
	s = orig.get_field(src, "Section")
	if s: exc.set_section(string.strip(s))

	if hints["block"].has_key("-" + src):
		blocked = hints["block"]["-" + src]
		exc.addhtml("Not touching package, as requested by %s (contact debian-release if update is needed)" % (blocked))
		okay = 0

	if okay:
		exc.addhtml("Valid candidate")
	else:
		exc.addhtml("Not considered")

	excs.append(exc)

	return okay

def should_upgrade_srcarch(src, arch, suite, tsrcv, orig, opkgsa, new, npkgsa, excs):
	# binnmu this arch?
	anywrongver = 0
	anyworthdoing = 0

	ref = "%s/%s" % (src, arch)
	if suite: ref = ref + "_%s" % (suite)

	e = Excuse(ref)
	e.set_vers(tsrcv, tsrcv)
	m = new.get_field(src, "Maintainer")
	if m: e.set_maint(string.strip(m))
	s = new.get_field(src, "Section")
	if s: e.set_section(string.strip(s))

	if hints["remove"].has_key(src):
		if same_source(tsrcv, hints["remove"][src][0]):
			e.addhtml("Removal request by %s" %
				(hints["remove"][src][1]))
			e.addhtml("Trying to remove package, not update it")
			e.addhtml("Not considered")
			excs.append(e)
			return 0

	for pkg in new.binaries(src, arch):
		pkgv = npkgsa.get_version(pkg)
		pkgsv = npkgsa.get_sourcever(pkg)

		if npkgsa.is_arch_all(pkg):
			e.addhtml("Ignoring %s %s (from %s) as it is arch: all"
				% (pkg, pkgv, pkgsv))
			continue

		if not same_source(tsrcv, pkgsv):
			anywrongver = 1
			e.addhtml("From wrong source: %s %s (%s not %s)" % (
				pkg, pkgv, pkgsv, tsrcv))
			break

		excuse_unsat_deps(pkg, arch, opkgsa, npkgsa, e, 0)

		if not opkgsa.is_present(pkg):
			e.addhtml("New binary: %s (%s)" % (pkg, pkgv))
			anyworthdoing = 1
			continue

		tpkgv = opkgsa.get_version(pkg)
		if britney.versioncmp(tpkgv, pkgv) > 0:
			anywrongver = 1
			e.addhtml("Not downgrading: %s (%s to %s)" % (
				pkg, tpkgv, pkgv))
			break
		elif britney.versioncmp(tpkgv, pkgv) < 0:
			e.addhtml("Updated binary: %s (%s to %s)" % (
				pkg, tpkgv, pkgv))
			anyworthdoing = 1

	if not anywrongver and (anyworthdoing or not new.is_fake(src)):
		srcv = new.get_version(src)
		ssrc = same_source(tsrcv, srcv)
		for pkg in orig.binaries(src, arch):
			if opkgsa.is_arch_all(pkg):
				e.addhtml("Ignoring removal of %s as it is arch: all"
					% (pkg))
				continue
			if not npkgsa.is_present(pkg):
				tpkgv = opkgsa.get_version(pkg)
				e.addhtml("Removed binary: %s %s" % (
					pkg, tpkgv))
				if ssrc: anyworthdoing = 1

	if not anywrongver and anyworthdoing:
		e.addhtml("Valid candidate")
		excs.append(e)
		return 1
	else:
		if anyworthdoing:
			e.addhtml("Not considered")
			excs.append(e)
		return 0	

def excuse_unsat_deps(pkg, arch, tpkgsarch, upkgsarch, exc, ignore_break=0):
	for d in ['Pre-Depends', 'Depends']:
		udt = tpkgsarch.unsatisfiable_deps(upkgsarch, pkg, d)
		udu = upkgsarch.unsatisfiable_deps(upkgsarch, pkg, d)

		for t,u in map(None, udt, udu):
			if t[1]: continue
			l = []
			for e in u[1]:
				s = upkgsarch.get_source(e)
				if s not in l: l.append(s)
			if src in l: continue
			if l == []:
				exc.addhtml("%s/%s unsatisfiable %s: %s" % (pkg, arch, d, t[0]))
			for s in l:
				if ignore_break or arch not in breakarches:
					exc.add_dep(s)
				else:
					exc.add_break_dep(s, arch)

def should_upgrade_src(src, suite, orig, origpkgs, new, newpkgs, approvals, 
                       excs):
	srcv = new.get_version(src)

	if orig.is_present(src):
		tsrcv = orig.get_version(src)
		if britney.versioncmp(srcv, tsrcv) == 0:
			# Candidate for binnmus only	
			return 0
	else:
		tsrcv = None

	updatecand = 1

	ref = src
	if suite: ref = ref + "_tpu"

	exc = Excuse(ref)
	exc.set_vers(tsrcv, srcv)
	m = new.get_field(src, "Maintainer")
	if m: exc.set_maint(string.strip(m))
	s = new.get_field(src, "Section")
	if s: exc.set_section(string.strip(s))

	if tsrcv and britney.versioncmp(srcv, tsrcv) < 0:
		# Version in unstable is older!
		exc.addhtml("ALERT: %s is newer in testing (%s %s)" % (src, tsrcv, srcv))
		excs.append(exc)
		return 0

	if unstable.is_fake(src):
		exc.addhtml("%s source package doesn't exist" % (src))
		updatecand = 0

	urgency = unstableurg.get(src, defaulturgency)
	if not tsrcv and urgency != defaulturgency:
		exc.addhtml("Ignoring %s urgency setting for NEW package" % (urgency))
		urgency = defaulturgency

        if hints["remove"].has_key(src):
                if (tsrcv and same_source(tsrcv, hints["remove"][src][0])) or \
		  same_source(srcv, hints["remove"][src][0]):
                        exc.addhtml("Removal request by %s" %
                                (hints["remove"][src][1]))
                        exc.addhtml("Trying to remove package, not update it")
			updatecand = 0

	blocked = None
	if hints["block"].has_key(src):
		blocked = hints["block"][src]
	elif hints["block-all"].has_key("source"):
		blocked = hints["block-all"]["source"]

	if blocked:
		ubv = hints["unblock"].get(src,(None,None))[0]
		if ubv != None and same_source(ubv, srcv):
			exc.addhtml("Ignoring request to block package by %s, due to unblock request by %s" % (blocked, hints["unblock"][src][1]))
		else:
			if ubv != None:
				exc.addhtml("Unblock request by %s ignored due to version mismatch: %s" % (hints["unblock"][src][1], hints["unblock"][src][0]))
			exc.addhtml("Not touching package, as requested by %s (contact debian-release if update is needed)" % (blocked))
			updatecand = 0

	if suite == None:
		if not unstabledates.has_key(src):
			unstabledates[src] = (srcv, datenow)
		elif not same_source(unstabledates[src][0], srcv):
			unstabledates[src] = (srcv, datenow)

		daysold = datenow - unstabledates[src][1]
		mymindays = mindays[urgency]
		exc.setdaysold(daysold, mymindays)
		if daysold < mymindays:
			if hints["urgent"].has_key(src) and same_source(srcv, hints["urgent"][src][0]):
				exc.addhtml("Too young, but urgency pushed by %s" % (hints["urgent"][src][1]))
			else:
				updatecand = 0

	pkgs = { src: ["source"] }
	anybins = 0
	for arch in arches:
		oodbins = {}
		for pkg in new.binaries(src,arch):
			anybins = 1
			if not pkgs.has_key(pkg): pkgs[pkg] = []
			pkgs[pkg].append(arch)

			pkgsv = newpkgs[arch].get_sourcever(pkg)
			if not same_source(srcv, pkgsv):
				if not oodbins.has_key(pkgsv):
					oodbins[pkgsv] = []
				oodbins[pkgsv].append(pkg)
				continue

			if newpkgs[arch].isnt_arch_all(pkg) or \
			  arch in nobreakarchallarches:
				excuse_unsat_deps(pkg, arch, 
					origpkgs[arch], newpkgs[arch], exc)

		if oodbins:
			oodtxt = ""
			for v in oodbins.keys():
				if oodtxt: oodtxt = oodtxt + "; "
				oodtxt = oodtxt + "%s (from <a href=\"http://buildd.debian.org/build.php?arch=%s&pkg=%s&ver=%s\" target=\"_blank\">%s</a>)" % \
					(", ".join(oodbins[v]), arch, src, v, v)
			text = "out of date on <a href=\"http://buildd.debian.org/build.php?arch=%s&pkg=%s&ver=%s\" target=\"_blank\">%s</a>: %s" % (arch, src, srcv, arch, oodtxt)

			if arch in fuckedarches:
				text = text + " (but %s isn't keeping up," % \
					(arch) + " so nevermind)"
			else:
				updatecand = 0

			if datenow != unstabledates[src][1]:
				exc.addhtml(text)

	if not anybins:
		exc.addhtml("%s has no binaries on any arch" % src)
		updatecand = 0

	if suite == None:
		for pkg in pkgs.keys():
			if not testingbugs.has_key(pkg): testingbugs[pkg] = 0
			if not unstablebugs.has_key(pkg): unstablebugs[pkg] = 0

			if unstablebugs[pkg] > testingbugs[pkg]:
				exc.addhtml("%s (%s) is <a href=\"http://bugs.debian.org/cgi-bin/pkgreport.cgi?which=pkg&data=%s&sev-inc=critical&sev-inc=grave&sev-inc=serious\" target=\"_blank\">buggy</a>! (%d > %d)" % \
					(pkg, ", ".join(pkgs[pkg]), pkg,
					unstablebugs[pkg], testingbugs[pkg]))
				updatecand = 0
			elif unstablebugs[pkg] > 0:
				exc.addhtml("%s (%s) is (less) <a href=\"http://bugs.debian.org/cgi-bin/pkgreport.cgi?which=pkg&data=%s&sev-inc=critical&sev-inc=grave&sev-inc=serious\" target=\"_blank\">buggy</a>! (%d <= %d)" % \
					(pkg, ", ".join(pkgs[pkg]), pkg,
					unstablebugs[pkg], testingbugs[pkg]))

	if not updatecand and hints["force"].has_key(src) and same_source(srcv, hints["force"][src][0]) :
		exc.dontinvalidate = 1
		exc.addhtml("Should ignore, but forced by %s" % (hints["force"][src][1]))
		updatecand = 1

	if approvals:
		if approvals.has_key("%s_%s" % (src, srcv)):
			exc.addhtml("Approved by %s" % 
			              approvals["%s_%s" % (src, srcv)])
		else:
			exc.addhtml("NEEDS APPROVAL BY RM")
			updatecand = 0

	if updatecand:
		exc.addhtml("Valid candidate")
	else:
		exc.addhtml("Not considered")

	excuses.append(exc)

	return updatecand

###

# Brute force stuff

class UpgradeRun:
	def __init__(self, sn, u, tu, ps):
		self.srcsn = sn
		self.unstable = u
		self.testingupdates = tu
		self.packages = ps

		self.sortpkgs()

		self.output = open("update.OUTPUT_py", "w");
		
		self.arches = [ x for x in arches if x in srcsn.arches ]
		self.srcsnpkgs = {}
		for arch in arches:
			self.srcsnpkgs[arch] = self.srcsn.Packages(arch)

	#def __del__():
	#	self.output.close()

	def sortpkgs(self):
		p = self.packages
		p.sort()
		self.packages = p

	def writeout(self, text):
		self.output.write(text)
		sys.stdout.write(text)
		self.output.flush()
		sys.stdout.flush()

	def doop_source(self, op):
		# removals = "-<source>", 
		# arch = "<source>/<arch>", 
		# normal = "<source>"
		which = self.unstable
		if "_" in op:
			ind = string.index(op, "_")
			if op[ind+1:] == "tpu":
				which = self.testingupdates
			op = op[:ind]

		if op[0] == "-":
			self.srcsn.remove_source(op[1:])
		elif "/" in op:
			ind = string.index(op, "/")
			self.srcsn.upgrade_arch(which, op[:ind], op[ind+1:])
		else:
			self.srcsn.upgrade_source(which, op)

	def get_nuninst(self):
		nuninst = {}
		for arch in self.arches:
			con = self.srcsnpkgs[arch].packages
			if arch not in nobreakarchallarches:
				con = filter(
					self.srcsnpkgs[arch].isnt_arch_all,
					con)
			nuninst[arch] = filter(
				self.srcsnpkgs[arch].is_uninstallable,
				con)
		return nuninst

	def get_improved_nuninst(self, old):
		new = {}
		for arch in self.arches:
		        con = self.srcsnpkgs[arch].packages
			if arch not in nobreakarchallarches:
				con = filter(
					self.srcsnpkgs[arch].isnt_arch_all,
					con)
			new[arch] = filter(
				self.srcsnpkgs[arch].is_uninstallable, con)
			if arch in breakarches: continue
			if len(new[arch]) > len(old[arch]):
				return (0, new)
		return (1, new)

	def arch_improved_nuninst(self, old, arch):
		new = old.copy()
		if "_" in arch: arch = arch[:arch.index("_")]
		con = self.srcsnpkgs[arch].packages
		if arch not in nobreakarchallarches:
			con = filter(self.srcsnpkgs[arch].isnt_arch_all, con)
		new[arch] = filter(self.srcsnpkgs[arch].is_uninstallable, con)
		if arch not in newarches and len(new[arch]) > len(old[arch]):
			return (0, new)
		return (1, new)

	def is_nuninst_asgood(self, old, new):
		for arch in self.arches:
			if arch in breakarches: continue
			if len(new[arch]) > len(old[arch]):
				return 0
		return 1

	def is_nuninst_asgood_generous(self, old, new):
		diff = 0
		for arch in self.arches:
			if arch in breakarches: continue
			diff = diff + (len(new[arch]) - len(old[arch]))
		return diff <= 0

	def eval_nuninst(self, nuninst):
		res = []
		total = 0
		totalbreak = 0
		for arch in self.arches:
			if nuninst.has_key(arch):
				n = len(nuninst[arch])
				if arch in breakarches:
					totalbreak = totalbreak + n
				else:
					total = total + n
				res.append("%s-%d" % (arch[0], n))
		return "%d+%d: %s" % (total, totalbreak, ":".join(res))

	def slist_subtract(self, base, sub):
		res = []
		for x in base:
			if x not in sub: res.append(x)
		return res

	def newlyuninst(self, nuold, nunew):
		res = {}
		for arch in self.arches:
			if not nuold.has_key(arch) or not nunew.has_key(arch):
				continue
			res[arch] = \
				self.slist_subtract(nunew[arch], nuold[arch])
		return res

	def eval_uninst(self, nuninst):
		res = ""
		for arch in self.arches:
			if nuninst.has_key(arch) and nuninst[arch] != []:
				res = res + "    * %s: %s\n" % (arch, 
					", ".join(nuninst[arch]))
		return res

	def do_all(self, maxdepth = 0, init = []):
		self.selected = []
		self.selected_committed = 0
		packages = self.packages[:]

		earlyabort = 0
		if maxdepth == "easy":
			earlyabort = 1
			maxdepth = 0

		# meaningless to try forcing something _and_ recurse
		force = 0
		if maxdepth < 0:
			force = 1
			maxdepth = 0
			earlyabort = 1

		nuninst_start = self.get_nuninst()

		if init:
			self.writeout("leading: %s\n" % (",".join(init)))
			
		for x in init:
			if x not in packages:
				self.writeout("failed: %s\n" % (x))
				return None
			y = packages.index(x)
			self.selected.append(packages.pop(y))

		for x in init:
			self.doop_source(x)
	
		if force:
			self.nuninst_orig = self.get_nuninst()
		else:
			self.nuninst_orig = nuninst_start

		self.writeout("start: %s\n" %
			self.eval_nuninst(nuninst_start))
		self.writeout("orig: %s\n" %
			self.eval_nuninst(self.nuninst_orig))

		if earlyabort:
			nuninst_end = self.get_nuninst()
		        self.writeout("easy: %s\n" %
		   	    (self.eval_nuninst(nuninst_end)))
		        self.writeout(self.eval_uninst(
			    self.newlyuninst(self.nuninst_orig, nuninst_end)))
		        self.writeout("\n")
			if not self.is_nuninst_asgood_generous(
							self.nuninst_orig, 
							nuninst_end):
				nuninst_end, respackages = None, None
			else:
				respackages = packages[:]
				self.selected_committed = len(self.selected)
		else:
			nuninst_end, respackages = \
				self.iter_some(maxdepth, packages, [])

		if nuninst_end:
			assert(len(self.selected) == self.selected_committed)

			self.writeout("final: %s\n" % 
				",".join(self.selected))
			self.writeout("start: %s\n" %
				self.eval_nuninst(nuninst_start))
			self.writeout(" orig: %s\n" %
				self.eval_nuninst(self.nuninst_orig))
			self.writeout("  end: %s\n" %
				self.eval_nuninst(nuninst_end))

			if force:
		            self.writeout("force breaks:\n")
		            self.writeout(self.eval_uninst(
			        self.newlyuninst(nuninst_start, nuninst_end)))
		            self.writeout("\n")

			if not self.is_nuninst_asgood_generous(
							self.nuninst_orig, 
							nuninst_end):
				print "NON-None RETURN THAT'S NOT BETTER"

			self.srcsn.commit_changes()

			self.writeout("SUCCESS (%d/%d)\n" % 
				(len(self.packages), len(respackages)))
			self.packages = respackages
			self.sortpkgs()

			return self.selected

		else:
			assert(len(self.selected) == len(init))
			assert(self.selected_committed == 0)

			for x in init:
				self.srcsn.undo_change()
			if self.srcsn.can_undo:
				print "MORE OPS LEFT TO UNDO THAN DONE"

			self.writeout("FAILED\n")
			return None

	def iter_end(self, available):
		extra = []
		count = 0
		nuninst_comp = self.get_nuninst()
		while available:
			x = available.pop(0)
			self.writeout("trying: %s\n" % (x))

			self.doop_source(x)

			if "/" in x:
				better, nuninst_new = self.arch_improved_nuninst(
					nuninst_comp, x[x.index("/")+1:])
			else:
				better, nuninst_new = self.get_improved_nuninst(
					nuninst_comp)

			if better:
				self.selected.append(x)
				count = count + 1
				available.extend(extra)
				extra = []

				self.writeout("accepted: %s\n" % (x))
				self.writeout("   ori: %s\n" % 
					(self.eval_nuninst(self.nuninst_orig)))
				self.writeout("   pre: %s\n" % 
					(self.eval_nuninst(nuninst_comp)))
				self.writeout("   now: %s\n" %
					(self.eval_nuninst(nuninst_new)))
				if len(self.selected) <= 20:
					self.writeout("   all: %s\n" % (
						" ".join(self.selected)))
				else:
					self.writeout("  most: (%d) .. %s\n" %
					  (len(self.selected),
					  " ".join(self.selected[-20:])))

				nuninst_comp = nuninst_new
			else:
				self.writeout("skipped: %s (%d <- %d)\n" % (
					x, len(extra), len(available)))
				self.writeout("    got: %s\n%s" % (
					self.eval_nuninst(nuninst_new),
					self.eval_uninst(self.newlyuninst(
					  nuninst_comp, nuninst_new))))

				self.srcsn.undo_change()
				extra.append(x)
		self.writeout(" finish: [%s]\n" %
		    ",".join(self.selected[self.selected_committed:]))
		self.writeout("endloop: %s\n" % 
			(self.eval_nuninst(self.nuninst_orig)))
		self.writeout("    now: %s\n" %
			(self.eval_nuninst(nuninst_comp)))
		self.writeout(self.eval_uninst(
			self.newlyuninst(self.nuninst_orig, nuninst_comp)))
		self.writeout("\n")

		if self.is_nuninst_asgood_generous(self.nuninst_orig,
		  nuninst_comp):
			self.writeout("Apparently successful\n")
			self.selected_committed = len(self.selected)
			return (nuninst_comp, extra)

		while count > 0:
			self.srcsn.undo_change()
			self.selected.pop()
			count = count - 1

		return (None, None)

	def iter_some(self, depth, available, extra):
		self.writeout("recur: [%s] %s %d/%d\n" % (
		    ",".join(self.selected[:self.selected_committed]), 
		    ",".join(self.selected[self.selected_committed:]), 
		    len(available), len(extra)))

		if depth == 0:
			extra.extend(available)
			return self.iter_end(extra)

		nuninst = None
		
		while len(available) > depth:
			x = available.pop(0)

			if not skiphint(x):
				self.doop_source(x)
				self.selected.append(x)

				res = self.iter_some(depth - 1, available[:], extra[:])
				if res[0]:
					nuninst = res[0]
					available = filter(lambda x, y=res[1]: x in y,
						available + extra)
					# reset nuninst_orig too
					self.nuninst_orig = nuninst
					extra = []
					continue

				self.srcsn.undo_change()
				self.selected.pop()

			extra.append(x)

		return (nuninst, extra)

# Package information

testing = britney.Sources(testingdir, arches)
testingpkgs = {}
for arch in arches:
	testingpkgs[arch] = testing.Packages(arch)
testingbugs = read_bugs(testingdir + "/Bugs")

unstable = britney.Sources(unstabledir, arches)
unstablepkgs = {}
for arch in arches:
	unstablepkgs[arch] = unstable.Packages(arch)
unstablebugs = read_bugs(unstabledir + "/Bugs")
unstabledates = read_dates(testingdir + "/Dates")
unstableurg = read_urgencies(testingdir + "/Urgency", testing, unstable)

testingupdates = britney.Sources(testingupdatesdir, arches)
testingupdatespkgs = {}
for arch in arches:
	testingupdatespkgs[arch] = testingupdates.Packages(arch)
testingupdatesapproved = {} # pkg_ver -> who
for approver in ["ajt", "security-team", "ftpmaster", "cjwatson", "vorlon"]:
	read_approvals(testingupdatesdir + "/Approved", approver,
		testingupdatesapproved)

hlphints = ["easy", "hint", "remove", "block", "unblock", "approve"]
stdhints = ["easy", "hint", "remove", "block", "unblock", "urgent", "approve"]
allhints = ["force", "force-hint", "block-all"] + stdhints
hintsallowed = {
	"ajt": allhints,
	"rmurray": allhints,
	"cjwatson": allhints,
	"vorlon": allhints,
	"aba": allhints,

	"joeyh": stdhints + ["force"],
	"djpig": stdhints,

	"he": hlphints,
	"adeodato": hlphints,
	"ballombe": hlphints,
	"luk": hlphints,

	"freeze": ["block", "block-all"],
	"ftpteam": ["block"]
}

hints = {"easy":[], "hint":[], "force-hint":[], "remove":[], "block":[], "block-all":[], "unblock":[], "force":[], "urgent":[], "approve":[]}
for who in hintsallowed.keys():
	h = read_hints(unstabledir + "/Hints", who, hints, hintsallowed[who])
	for k in hintsallowed[who]:
		hints[k].extend(h[k])

for x in ["block", "block-all", "unblock", "force", "urgent", "remove"]:
	z = {}
	for a, b in hints[x]:
		if z.has_key(a):
			print "Overriding %s[%s] = %s with %s" % (x, a, z[a], b)
		z[a] = b
	hints[x] = z

for p, vh in hints["approve"]:
	(v,h) = vh
	testingupdatesapproved["%s_%s" % (p,v)] = h
	hints["unblock"]["%s" % p] = (v,h)

def maxver(pkg, source, pkgs):
	maxver = source.get_version(pkg)
	for arch in arches:
		pkgv = pkgs[arch].get_version(pkg)
		if pkgv == None: continue
		if maxver == None or britney.versioncmp(pkgv, maxver) > 0:
			maxver = pkgv
	return maxver

for pkg in testingbugs.keys() + unstablebugs.keys():
	if not testingbugs.has_key(pkg): testingbugs[pkg] = 0
	if not unstablebugs.has_key(pkg): unstablebugs[pkg] = 0

	maxvert = maxver(pkg, testing, testingpkgs)
	if maxvert == None: 
		testingbugs[pkg] = 0
		continue

	if testingbugs[pkg] == unstablebugs[pkg]: continue
	maxveru = maxver(pkg, unstable, unstablepkgs)
	
	if maxveru == None: 
		continue
	if britney.versioncmp(maxvert, maxveru) >= 0:
		testingbugs[pkg] = unstablebugs[pkg]

datenow = int(((time.time() / (60*60)) - 15) / 24);

# Next, work out which packages are candidates to be changed.

upgrademe = []
excuses = []

# Packages to be removed
for src in testing.sources:
	if should_remove_source(src, testing, unstable,  excuses):
		upgrademe.append("-" + src)

# Packages to be upgraded from unstable:
for src in unstable.sources:
	if testing.is_present(src):
		tsrcv = testing.get_version(src) # silly optimisation
		for arch in arches:
			if should_upgrade_srcarch(src, arch, None, tsrcv, 
			                          testing, testingpkgs[arch], 
			                          unstable, unstablepkgs[arch],
						  excuses):
				upgrademe.append("%s/%s" % (src, arch))

	if should_upgrade_src(src, None, testing, testingpkgs, 
	                      unstable, unstablepkgs, None, excuses):
		upgrademe.append(src)

for src in testingupdates.sources:
	if testing.is_present(src):
		tsrcv = testing.get_version(src) # silly optimisation
		for arch in arches:
			if should_upgrade_srcarch(src, arch, "tpu", tsrcv, 
			                          testing, testingpkgs[arch], 
			                          testingupdates,
						   testingupdatespkgs[arch],
						  excuses):
				upgrademe.append("%s/%s_tpu" % (src, arch))

	if should_upgrade_src(src, "tpu", testing, testingpkgs,
	                      testingupdates, testingupdatespkgs, 
	                      testingupdatesapproved, excuses):
		upgrademe.append("%s_tpu" % src)

for src in hints["remove"].keys():
	if src in upgrademe: continue
	if ("-"+src) in upgrademe: continue
	if not testing.is_present(src): continue

	tsrcv = testing.get_version(src)
	if not same_source(tsrcv, hints["remove"][src][0]): continue

	upgrademe.append("-%s" % (src))
	exc = Excuse("-%s" % (src))
	exc.set_vers(tsrcv, None)
	exc.addhtml("Removal request by %s" % (hints["remove"][src][1]))
	exc.addhtml("Package is broken, will try to remove")
	excuses.append(exc)

def cmpexcuses(el, er):
	return cmp(el.daysold, er.daysold) or cmp(el.name, er.name)
excuses.sort(cmpexcuses)

def reversed_exc_deps(excuses):
	res = {}
	for exc in excuses:
		for d in exc.deps:
			if not res.has_key(d): res[d] = []
			res[d].append(exc.name)
	return res

def invalidate(excuses, valid, invalid):
	i = 0
	exclookup = {}
	for e in excuses:
		exclookup[e.name] = e
	revdeps = reversed_exc_deps(excuses)
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

unconsidered = []
for exc in excuses:
	if exc.name not in upgrademe: unconsidered.append(exc.name)

for exc in excuses:
	for d in exc.deps:
		if d not in upgrademe and d not in unconsidered:
			exc.addhtml("Unpossible dep: %s -> %s" % (exc.name, d))

invalidate(excuses, upgrademe, unconsidered)

f = open("update.EXCUSES_py", 'w')

f.write("<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.01//EN\" \"http://www.w3.org/TR/REC-html40/strict.dtd\">\n")
f.write("<html><head><title>excuses...</title>")
f.write("<meta http-equiv=\"Content-Type\" content=\"text/html;charset=utf-8\"></head><body>\n")
f.write("<p>Generated: " + time.strftime("%Y.%m.%d %H:%M:%S %z", time.gmtime(time.time())) + "</p>\n")
f.write("<ul>\n")

for exc in excuses:
	f.write("<li>%s" % exc.html())
f.write("</ul></body></html>\n")

f.close()

del excuses

# Changes

srcsn = britney.SourcesNote(arches)

# Initialise new testing to be the old testing

for src in testing.sources:
	srcsn.upgrade_source(testing, src)

srcsn.commit_changes()

#print "Things to do:"
#for x in upgrademe:
#	print "        " + x

run = UpgradeRun(srcsn, unstable, testingupdates, upgrademe)

def skiphint(candidate):
	if "/" in candidate and candidate[candidate.rfind("/")+1:] in breakarches:
		return 1
	return 0

def do_hint(type, who, pkgvers):
	hintinfo = {"easy":       "easy",
		    "hint":       0,
        	    "force-hint": -1,
		   }
	hintdoall = hintinfo[type]

	run.writeout("Trying %s from %s: %s\n" % (type, who, 
		" ".join( ["%s/%s" % (p,v) for (p,v) in pkgvers] )))

	ok = 1
	for xp,v in pkgvers:
		# is this version of this package present in unstable?
		# (if it's also present in testing, do_all will skip it)
		if "/" in xp:
			p = xp[:xp.find("/")]
		else:
			p = xp

		if p[0] == "-":
			pass
		elif p.endswith("_tpu"):
			if britney.versioncmp(run.testingupdates.get_version(p[:-4]),v) != 0:
				ok = 0
				run.writeout(" Version mismatch, %s %s != %s\n" %
					     (p, v, run.testingupdates.get_version(p[:-4])))
		elif run.unstable.get_version(p) == None:
			ok = 0
			run.writeout(" Source %s has no version in unstable\n" % p)
		elif britney.versioncmp(run.unstable.get_version(p), v) != 0:
			ok = 0
			run.writeout(" Version mismatch, %s %s != %s\n" %
				(p, v, run.unstable.get_version(p)))
	if ok:
		run.do_all(hintdoall, map(lambda hp: hp[0], x[1]))
	else:
		run.writeout("Not using hint\n")
	return ok

run.writeout("Generated on: %s\n" % (time.strftime("%Y.%m.%d %H:%M:%S %z", time.gmtime(time.time()))))
run.writeout("Arch order is: %s\n" % ", ".join(arches))

for x in hints["easy"]:
	do_hint("easy", x[0], x[1])
for x in hints["force-hint"]:
	do_hint("force-hint", x[0], x[1])

allpackages = []
normpackages = run.packages[:]
archpackages = {}
for a in breakarches:
    la = len(a) + 1
    archpackages[a] = [ p for p in normpackages if p[-la:] == "/" + a ]
    normpackages = [ p for p in normpackages if p[-la:] != "/" + a ]
run.packages = normpackages
run.writeout("info: main run\n");
run.do_all()
allpackages += run.packages
for a in breakarches:
    x = breakarches
    breakarches = [ ba for ba in breakarches if ba != a ]
    run.packages = archpackages[a]
    run.writeout("info: broken arch run for %s\n" % (a))
    run.do_all()
    #run.do_all(1)
    breakarches = x
    allpackages += run.packages
run.packages = allpackages

#run.do_all(0,["caudium", "sablotron"])

hintcnt = 1

rand = whrandom.whrandom()
rand.seed(23,187,96)
for q in range(datenow): 
	rand.random()
q = rand.random()
q = 1.0
run.writeout("Current value is %f\n" % (q))
if q < 0.2:
	q = 0.2
	run.writeout("Current value bumped to %f\n" % (q))
maxloops = int(math.ceil(math.log(100/(q**0.5)) / math.log(1+len(run.packages))))
maxloops = 1
run.writeout("Max loops for q=%.2f is %d\n" % (q, maxloops))

for x in hints["hint"]:
	if hintcnt > 50:
		run.writeout("Skipping remaining hints...")
		break

	if len(x[1]) < maxloops:
		run.writeout("Skipping simple hint from %s (%d<%d): %s\n" 
			% (x[0], len(x[1]), maxloops, str(x[1])))
		continue

	if do_hint("hint", x[0], x[1]):
		hintcnt += 1

for i in range(1,maxloops):
	run.do_all(i)

if maxloops <= 1 and len(run.packages) < 500:
	# too many to do all of them, let's try 5 at random
	num_at_random = 5
	if len(run.packages) > num_at_random:
		run.writeout("Trying %d at random\n" % num_at_random)
		for k in range(num_at_random):
			special = rand.choice(run.packages)
			if skiphint(special): continue
			run.writeout("Randomly trying %s\n" % (special))
			run.do_all(0, [special])

run.srcsn.write_notes(testingdir)

write_bugs(testingdir + "/Bugs", testingbugs)
write_dates(testingdir + "/Dates", unstabledates)

f = open(testingdir + '/HeidiResult', 'w')

for arch in arches:
	pkgs = srcsn.Packages(arch)
	for pkg in pkgs.packages:
		pkgv = pkgs.get_version(pkg)
		pkgarch = pkgs.get_field(pkg, 'Architecture')
		pkgsec = pkgs.get_field(pkg, 'Section')
		if pkgsec == None: pkgsec = 'unknown\n'
		pkgarch = pkgarch[:-1]
		pkgsec = pkgsec[:-1]
		f.write('%s %s %s %s\n' % (pkg, pkgv, pkgarch, pkgsec))

for src in srcsn.sources:
	srcv = srcsn.get_version(src)
	srcsec = srcsn.get_field(src, 'Section')
	if srcsec == None: srcsec = 'unknown\n'
	if srcsn.is_fake(src): srcsec = 'faux\n'
	srcsec = srcsec[:-1]
	f.write('%s %s source %s\n' % (src, srcv, srcsec))

f.close()

if len(arches) != expected_arches:
	sys.exit(1)
