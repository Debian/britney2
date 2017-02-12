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
from contextlib import contextmanager
from itertools import product

from britney2.utils import ifilter_except, iter_except, get_dependency_solvers
from britney2.installability.solver import InstallabilitySolver


def build_installability_tester(binaries, archs):
    """Create the installability tester"""

    solvers = get_dependency_solvers
    builder = InstallabilityTesterBuilder()

    for (dist, arch) in product(binaries, archs):
        testing = (dist == 'testing')
        for pkgname in binaries[dist][arch][0]:
            pkgdata = binaries[dist][arch][0][pkgname]
            pkg_id = pkgdata.pkg_id
            if not builder.add_binary(pkg_id,
                                      essential=pkgdata.is_essential,
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

                for (al, dep) in [(depends, True), (conflicts, False)]:

                    for block in al:
                        sat = set()

                        for dep_dist in binaries:
                            dep_binaries_s_a, dep_provides_s_a = binaries[dep_dist][arch]
                            pkgs = solvers(block, dep_binaries_s_a, dep_provides_s_a)
                            for p in pkgs:
                                # version and arch is already interned, but solvers use
                                # the package name extracted from the field and it is therefore
                                # not interned.
                                pdata = dep_binaries_s_a[p]
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

    return builder.build()


class _RelationBuilder(object):
    """Private helper class to "build" relations"""

    def __init__(self, itbuilder, binary):
        self._itbuilder = itbuilder
        self._binary = binary
        binary_data = itbuilder._package_table[binary]
        self._new_deps = set(binary_data[0])
        self._new_breaks = set(binary_data[1])


    def add_dependency_clause(self, or_clause):
        """Add a dependency clause

        The clause must be a sequence of (name, version, architecture)
        tuples.  The clause is an OR clause, i.e. any tuple in the
        sequence can satisfy the relation.  It is irrelevant if the
        dependency is from the "Depends" or the "Pre-Depends" field.

        Note that is the sequence is empty, the dependency is assumed
        to be unsatisfiable.

        The binaries in the clause are not required to have been added
        to the InstallabilityTesterBuilder when this method is called.
        However, they must be added before the "build()" method is
        called.
        """
        itbuilder = self._itbuilder
        clause = itbuilder._intern_set(or_clause)
        binary = self._binary
        okay = False
        for dep_tuple in clause:
            okay = True
            rdeps, _, rdep_relations = itbuilder._reverse_relations(dep_tuple)
            rdeps.add(binary)
            rdep_relations.add(clause)

        self._new_deps.add(clause)
        if not okay:
            itbuilder._broken.add(binary)


    def add_breaks(self, broken_binary):
        """Add a Breaks-clause

        Marks the given binary as being broken by the current
        package.  That is, the given package satisfies a relation
        in either the "Breaks" or the "Conflicts" field.  The binary
        given must be a (name, version, architecture)-tuple.

        The binary is not required to have been added to the
        InstallabilityTesterBuilder when this method is called.  However,
        it must be added before the "build()" method is called.
        """
        itbuilder = self._itbuilder
        self._new_breaks.add(broken_binary)
        reverse_relations = itbuilder._reverse_relations(broken_binary)
        reverse_relations[1].add(self._binary)


    def _commit(self):
        itbuilder = self._itbuilder
        data = (itbuilder._intern_set(self._new_deps),
                itbuilder._intern_set(self._new_breaks))
        itbuilder._package_table[self._binary] = data


class InstallabilityTesterBuilder(object):
    """Builder to create instances of InstallabilityTester"""

    def __init__(self):
        self._package_table = {}
        self._reverse_package_table = {}
        self._essentials = set()
        self._testing = set()
        self._internmap = {}
        self._broken = set()


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


    @contextmanager
    def relation_builder(self, binary):
        """Returns a _RelationBuilder for a given binary [context]

        This method returns a context-managed _RelationBuilder for a
        given binary.  So it should be used in a "with"-statment,
        like:

            with it.relation_builder(binary) as rel:
                rel.add_dependency_clause(dependency_clause)
                rel.add_breaks(pkgtuple)
                ...

        The binary given must be a (name, version, architecture)-tuple.

        Note, this method is optimised to be called at most once per
        binary.
        """
        if binary not in self._package_table:  # pragma: no cover
            raise ValueError("Binary %s/%s/%s does not exist" % binary)
        rel = _RelationBuilder(self, binary)
        yield rel
        rel._commit()


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
        safe_set = set()
        broken = self._broken
        not_broken = ifilter_except(broken)
        check = set(broken)

        def safe_set_satisfies(t):
            """Check if t's dependencies can be satisfied by the safe set"""
            if not package_table[t][0]:
                # If it has no dependencies at all, then it is safe.  :)
                return True
            for depgroup in package_table[t][0]:
                if not any(dep for dep in depgroup if dep in safe_set):
                    return False
            return True


        # Merge reverse conflicts with conflicts - this saves some
        # operations in _check_loop since we only have to check one
        # set (instead of two) and we remove a few duplicates here
        # and there.
        #
        # At the same time, intern the rdep sets
        for pkg in reverse_package_table:
            if pkg not in package_table:  # pragma: no cover
                raise RuntimeError("%s/%s/%s referenced but not added!" % pkg)
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

        # Now find an initial safe set (if any)
        check = set()
        for pkg in package_table:

            if package_table[pkg][1]:
                # has (reverse) conflicts - not safe
                continue
            if not safe_set_satisfies(pkg):
                continue
            safe_set.add(pkg)
            if pkg in reverse_package_table:
                # add all rdeps (except those already in the safe_set)
                check.update(reverse_package_table[pkg][0] - safe_set)

        # Check if we can expand the initial safe set
        for pkg in iter_except(check.pop, KeyError):
            if package_table[pkg][1]:
                # has (reverse) conflicts - not safe
                continue
            if safe_set_satisfies(pkg):
                safe_set.add(pkg)
                if pkg in reverse_package_table:
                    # add all rdeps (except those already in the safe_set)
                    check.update(reverse_package_table[pkg][0] - safe_set)

        eqv_table = self._build_eqv_packages_table(package_table,
                                       reverse_package_table)

        return InstallabilitySolver(package_table,
                                    reverse_package_table,
                                    self._testing, self._broken,
                                    self._essentials, safe_set,
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
            con_key = con
            if con:
                con_key = self._intern_set(con | {pkg})
            ekey = (deps, con_key, rdeps)
            find_eqv_table[ekey].append(pkg)

        for pkg_list in find_eqv_table.values():
            if len(pkg_list) < 2:
                continue

            eqv_set = frozenset(pkg_list)
            for pkg in pkg_list:
                eqv_table[pkg] = eqv_set

        return eqv_table
