# -*- coding: utf-8 -*-

# Copyright (C) 2012 Niels Thykier <niels@thykier.net>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

import apt_pkg
from collections import defaultdict
from itertools import product

from britney2.utils import ifilter_except, iter_except, get_dependency_solvers
from britney2.installability.solver import InstallabilitySolver


def build_installability_tester(suite_info, archs):
    """Create the installability tester"""

    builder = InstallabilityTesterBuilder()

    for (suite, arch) in product(suite_info, archs):
        _build_inst_tester_on_suite_arch(builder, suite_info, suite, arch)

    return builder.build()


def _build_inst_tester_on_suite_arch(builder, suite_info, suite, arch):
    packages_s_a = suite.binaries[arch][0]
    is_target = suite.suite_class.is_target
    bin_prov = [s.binaries[arch] for s in suite_info]
    solvers = get_dependency_solvers
    for pkgdata in packages_s_a.values():
        pkg_id = pkgdata.pkg_id
        if not builder.add_binary(pkg_id,
                                  essential=pkgdata.is_essential,
                                  in_testing=is_target):
            continue

        if pkgdata.conflicts:
            conflicts = []
            conflicts_parsed = apt_pkg.parse_depends(pkgdata.conflicts, False)
            # Breaks/Conflicts are so simple that we do not need to keep align the relation
            # with the suite.  This enables us to do a few optimizations.
            for dep_binaries_s_a, dep_provides_s_a in bin_prov:
                for block in (relation for relation in conflicts_parsed):
                    # if a package satisfies its own conflicts relation, then it is using §7.6.2
                    conflicts.extend(s.pkg_id for s in solvers(block, dep_binaries_s_a, dep_provides_s_a)
                                     if s.pkg_id != pkg_id)
        else:
            conflicts = None

        if pkgdata.depends:
            depends = _compute_depends(pkgdata, bin_prov, solvers)
        else:
            depends = None

        builder.set_relations(pkg_id, depends, conflicts)


def _compute_depends(pkgdata, bin_prov, solvers):
    depends = []
    possible_dep_ranges = {}
    for block in apt_pkg.parse_depends(pkgdata.depends, False):
        sat = {s.pkg_id for binaries_s_a, provides_s_a in bin_prov
               for s in solvers(block, binaries_s_a, provides_s_a)}

        if len(block) != 1:
            depends.append(sat)
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

    if possible_dep_ranges:
        depends.extend(possible_dep_ranges.values())

    return depends


class InstallabilityTesterBuilder(object):
    """Builder to create instances of InstallabilityTester"""

    def __init__(self):
        self._package_table = {}
        self._reverse_package_table = {}
        self._essentials = set()
        self._testing = set()
        self._internmap = {}
        self._broken = set()
        self._empty_set = self._intern_set(frozenset())

    def add_binary(self, binary, essential=False, in_testing=False,
                   frozenset=frozenset):
        """Add a new binary package

        Adds a new binary package.  The binary must be given as a
        (name, version, architecture)-tuple.  Returns True if this
        binary is new (i.e. has never been added before) or False
        otherwise.

        Keyword arguments:
        * essential  - Whether this package is "Essential: yes".
        * in_testing - Whether this package is in testing.

        The frozenset argument is a private optimisation.

        Cave-at: arch:all packages should be "re-mapped" to given
        architecture.  That is, (pkg, version, "all") should be
        added as:

            for arch in architectures:
                binary = (pkg, version, arch)
                it.add_binary(binary)

        The resulting InstallabilityTester relies on this for
        correctness!
        """
        # Note, even with a dup, we need to do these
        if in_testing:
            self._testing.add(binary)
        if essential:
            self._essentials.add(binary)

        if binary not in self._package_table:
            # Allow binaries to be added multiple times (happens
            # when sid and testing have the same version)
            self._package_table[binary] = (frozenset(), frozenset())
            return True
        return False

    def set_relations(self, pkg_id, dependency_clauses, breaks):
        """The dependency and breaks realtions for a given package

        :param pkg_id: BinaryPackageID determining which package will have its relations set
        :param dependency_clauses: A list/set of OR clauses (i.e. CNF with each element in
          dependency_clauses being a disjunction).  Each OR cause (disjunction) should be a
          set/list of BinaryPackageIDs that satisfy that relation.
        :param breaks: An list/set of BinaryPackageIDs that has a Breaks/Conflicts relation
            on the current package.  Can be None
        :return: No return value
        """
        if dependency_clauses is not None:
            interned_or_clauses = self._intern_set(self._intern_set(c) for c in dependency_clauses)
            satisfiable = True
            for or_clause in interned_or_clauses:
                if not or_clause:
                    satisfiable = False
                for dep_tuple in or_clause:
                    rdeps, _, rdep_relations = self._reverse_relations(dep_tuple)
                    rdeps.add(pkg_id)
                    rdep_relations.add(or_clause)

            if not satisfiable:
                self._broken.add(pkg_id)
        else:
            interned_or_clauses = self._empty_set

        if breaks is not None:
            # Breaks
            breaks_relations = self._intern_set(breaks)
            for broken_binary in breaks_relations:
                reverse_relations = self._reverse_relations(broken_binary)
                reverse_relations[1].add(pkg_id)
        else:
            breaks_relations = self._empty_set

        self._package_table[pkg_id] = (interned_or_clauses, breaks_relations)

    def _intern_set(self, s, frozenset=frozenset):
        """Freeze and intern a given sequence (set variant of intern())

        Given a sequence, create a frozenset copy (if it is not
        already a frozenset) and intern that frozen set.  Returns the
        interned set.

        At first glance, interning sets may seem absurd.  However,
        it does enable memory savings of up to 600MB when applied
        to the "inner" sets of the dependency clauses and all the
        conflicts relations as well.
        """
        if type(s) == frozenset:
            fset = s
        else:
            fset = frozenset(s)
        if fset in self._internmap:
            return self._internmap[fset]
        self._internmap[fset] = fset
        return fset

    def _reverse_relations(self, binary, set=set):
        """Return the reverse relations for a binary

        Fetch the reverse relations for a given binary, which are
        created lazily.
        """

        if binary in self._reverse_package_table:
            return self._reverse_package_table[binary]
        rel = [set(), set(), set()]
        self._reverse_package_table[binary] = rel
        return rel

    def build(self):
        """Compile the installability tester

        This method will compile an installability tester from the
        information given and (where possible) try to optimise a
        few things.
        """
        package_table = self._package_table
        reverse_package_table = self._reverse_package_table
        intern_set = self._intern_set
        broken = self._broken
        not_broken = ifilter_except(broken)
        check = set(broken)

        # Merge reverse conflicts with conflicts - this saves some
        # operations in _check_loop since we only have to check one
        # set (instead of two) and we remove a few duplicates here
        # and there.
        #
        # At the same time, intern the rdep sets
        for pkg in reverse_package_table:
            if pkg not in package_table:  # pragma: no cover
                raise AssertionError("%s referenced but not added!" % str(pkg))
            deps, con = package_table[pkg]
            rdeps, rcon, rdep_relations = reverse_package_table[pkg]
            if rcon:
                if not con:
                    con = intern_set(rcon)
                else:
                    con = intern_set(con | rcon)
                package_table[pkg] = (deps, con)
            reverse_package_table[pkg] = (intern_set(rdeps), con,
                                          intern_set(rdep_relations))

        # Check if we can expand broken.
        for t in not_broken(iter_except(check.pop, KeyError)):
            # This package is not known to be broken... but it might be now
            isb = False
            for depgroup in package_table[t][0]:
                if not any(not_broken(depgroup)):
                    # A single clause is unsatisfiable, the
                    # package can never be installed - add it to
                    # broken.
                    isb = True
                    break

            if not isb:
                continue

            broken.add(t)

            if t not in reverse_package_table:
                continue
            check.update(reverse_package_table[t][0] - broken)

        if broken:
            # Since a broken package will never be installable, nothing that depends on it
            # will ever be installable.  Thus, there is no point in keeping relations on
            # the broken package.
            seen = set()
            empty_set = frozenset()
            null_data = (frozenset([empty_set]), empty_set)
            for b in (x for x in broken if x in reverse_package_table):
                for rdep in (r for r in not_broken(reverse_package_table[b][0])
                             if r not in seen):
                    ndep = intern_set((x - broken) for x in package_table[rdep][0])
                    package_table[rdep] = (ndep, package_table[rdep][1] - broken)
                    seen.add(rdep)

            # Since they won't affect the installability of any other package, we might as
            # as well null their data.  This memory for these packages, but likely there
            # will only be a handful of these "at best" (fsvo of "best")
            for b in broken:
                package_table[b] = null_data
                if b in reverse_package_table:
                    del reverse_package_table[b]

        eqv_table = self._build_eqv_packages_table(package_table, reverse_package_table)

        return InstallabilitySolver(package_table,
                                    reverse_package_table,
                                    self._testing,
                                    self._broken,
                                    self._essentials,
                                    eqv_table)

    def _build_eqv_packages_table(self, package_table,
                                  reverse_package_table,
                                  frozenset=frozenset):
        """Attempt to build a table of equivalent packages

        This method attempts to create a table of packages that are
        equivalent (in terms of installability).  If two packages (A
        and B) are equivalent then testing the installability of A is
        the same as testing the installability of B.  This equivalency
        also applies to co-installability.

        The example cases:
        * aspell-*
        * ispell-*

        Cases that do *not* apply:
        * MTA's

        The theory:

        The packages A and B are equivalent iff:

          reverse_depends(A) == reverse_depends(B) AND
                conflicts(A) == conflicts(B)       AND
                  depends(A) == depends(B)

        Where "reverse_depends(X)" is the set of reverse dependencies
        of X, "conflicts(X)" is the set of negative dependencies of X
        (Breaks and Conflicts plus the reverse ones of those combined)
        and "depends(X)" is the set of strong dependencies of X
        (Depends and Pre-Depends combined).

        To be honest, we are actually equally interested another
        property as well, namely substitutability.  The package A can
        always used instead of B, iff:

          reverse_depends(A) >= reverse_depends(B) AND
                conflicts(A) <= conflicts(B)       AND
                  depends(A) == depends(B)

        (With the same definitions as above).  Note that equivalency
        is just a special-case of substitutability, where A and B can
        substitute each other (i.e. a two-way substituation).

        Finally, note that the "depends(A) == depends(B)" for
        substitutability is actually not a strict requirement.  There
        are cases where those sets are different without affecting the
        property.
        """
        # Despite talking about substitutability, the method currently
        # only finds the equivalence cases.  Lets leave
        # substitutability for a future version.

        find_eqv_table = defaultdict(list)
        eqv_table = {}

        for pkg in reverse_package_table:
            rdeps = reverse_package_table[pkg][2]
            if not rdeps:
                # we don't care for things without rdeps (because
                # it is not worth it)
                continue
            deps, con = package_table[pkg]
            ekey = (deps, con, rdeps)
            find_eqv_table[ekey].append(pkg)

        for pkg_list in find_eqv_table.values():
            if len(pkg_list) < 2:
                continue

            eqv_set = frozenset(pkg_list)
            for pkg in pkg_list:
                eqv_table[pkg] = eqv_set

        return eqv_table
