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

from functools import partial
from itertools import filterfalse

from britney_util import iter_except

class InstallabilityTester(object):

    def __init__(self, universe, revuniverse, testing, broken, essentials,
                 safe_set, eqv_table):
        """Create a new installability tester

        universe is a dict mapping package tuples to their
        dependencies and conflicts.

        revuniverse is a set of all packages with reverse relations

        testing is a (mutable) set of package tuples that determines
        which of the packages in universe are currently in testing.

        broken is a (mutable) set of package tuples that are known to
        be uninstallable.

        essentials is a set of packages with "Essential: yes".

        safe_set is a set of all packages which have no conflicts and
        either have no dependencies or only depends on other "safe"
        packages.

        Package tuple: (pkg_name, pkg_version, pkg_arch)
          - NB: arch:all packages are "re-mapped" to given architecture.
            (simplifies caches and dependency checking)
        """

        self._universe = universe
        self._testing = testing
        self._broken = broken
        self._essentials = essentials
        self._revuniverse = revuniverse
        self._safe_set = safe_set
        self._eqv_table = eqv_table

        # Cache of packages known to be broken - we deliberately do not
        # include "broken" in it.  See _optimize for more info.
        self._cache_broken = set()
        # Cache of packages known to be installable
        self._cache_inst = set()
        # Per "arch" cache of the "minimal" (possibly incomplete)
        # pseudo-essential set.  This includes all the packages that
        # are essential and packages that will always follow.
        #
        # It may not be a complete essential set, since alternatives
        # are not always resolved.  Noticably cases like "awk" may be
        # left out (since it could be either gawk, mawk or
        # original-awk) unless something in this sets depends strictly
        # on one of them
        self._cache_ess = {}

    def compute_testing_installability(self):
        """Computes the installability of packages in testing

        This method computes the installability of all packages in
        testing and caches the result.  This has the advantage of
        making "is_installable" queries very fast for all packages
        in testing.
        """

        check_inst = self._check_inst
        cbroken = self._cache_broken
        cache_inst = self._cache_inst
        eqv_table = self._eqv_table
        testing = self._testing
        tcopy = [x for x in testing]
        for t in filterfalse(cache_inst.__contains__, tcopy):
            if t in cbroken:
                continue
            res = check_inst(t)
            if t in eqv_table:
                eqv = (x for x in eqv_table[t] if x in testing)
                if res:
                    cache_inst.update(eqv)
                else:
                    eqv_set = frozenset(eqv)
                    testing -= eqv_set
                    cbroken |= eqv_set


    def are_equivalent(self, p1, p2):
        """Test if p1 and p2 are equivalent

        Returns True if p1 and p2 have the same "signature" in
        the package dependency graph (i.e. relations can not tell
        them appart sematically except for their name)
        """
        eqv_table = self._eqv_table
        return p1 in eqv_table and p2 in eqv_table[p1]


    def add_testing_binary(self, pkg_name, pkg_version, pkg_arch):
        """Add a binary package to "testing"

        If the package is not known, this method will throw an
        Keyrror.
        """

        t = (pkg_name, pkg_version, pkg_arch)

        if t not in self._universe:
            raise KeyError(str(t))

        if t in self._broken:
            self._testing.add(t)
        elif t not in self._testing:
            self._testing.add(t)
            self._cache_inst = set()
            if self._cache_broken:
                # Re-add broken packages as some of them may now be installable
                self._testing |= self._cache_broken
                self._cache_broken = set()
            if t in self._essentials and t[2] in self._cache_ess:
                # Adds new essential => "pseudo-essential" set needs to be
                # recomputed
                del self._cache_ess[t[2]]

        return True

    def remove_testing_binary(self, pkg_name, pkg_version, pkg_arch):
        """Remove a binary from "testing"

        If the package is not known, this method will throw an
        Keyrror.
        """

        t = (pkg_name, pkg_version, pkg_arch)

        if t not in self._universe:
            raise KeyError(str(t))

        self._cache_broken.discard(t)

        if t in self._testing:
            self._testing.remove(t)
            if t[2] in self._cache_ess and t in self._cache_ess[t[2]][0]:
                # Removes a package from the "pseudo-essential set"
                del self._cache_ess[t[2]]

            if t not in self._revuniverse:
                # no reverse relations - safe
                return True
            if t not in self._broken and t in self._cache_inst:
                # It is in our cache (and not guaranteed to be broken) - throw out the cache
                self._cache_inst = set()

        return True

    def is_installable(self, pkg_name, pkg_version, pkg_arch):
        """Test if a package is installable in this package set

        The package is assumed to be in "testing" and only packages in
        "testing" can be used to satisfy relations.

        Returns True iff the package is installable.
        Returns False otherwise.
        """

        t = (pkg_name, pkg_version, pkg_arch)

        if t not in self._universe:
            raise KeyError(str(t))

        if t not in self._testing or t in self._broken:
            return False

        if t in self._cache_inst:
            return True

        return self._check_inst(t)


    def _check_inst(self, t, musts=None, never=None, choices=None):
        # See the explanation of musts, never and choices below.

        cache_inst = self._cache_inst

        if t in cache_inst and not never:
            # use the inst cache only for direct queries/simple queries.
            cache = True
            if choices:
                # This is a recursive call, where there is no "never" so far.
                # We know t satisfies at least one of the remaining choices.
                # If it satisfies all remaining choices, we can use the cache
                # in this case (since never is empty).
                #
                # Otherwise, a later choice may be incompatible with t.
                for choice in choices:
                    if t in choice:
                        continue
                    cache = False
                    break
            if cache:
                return True


        universe = self._universe
        testing = self._testing
        cbroken = self._cache_broken
        safe_set = self._safe_set
        eqv_table = self._eqv_table

        # Our installability verdict - start with "yes" and change if
        # prove otherwise.
        verdict = True

        # set of packages that must be installed with this package
        if musts is None:
            musts = set()
        musts.add(t)
        # set of packages we can *never* choose (e.g. due to conflicts)
        if never is None:
            never = set()
        # set of relations were we have a choice, but where we have not
        # committed ourselves yet.  Hopefully some choices may be taken
        # for us (if one of the alternatives appear in "musts")
        if choices is None:
            choices = set()

        # The subset of musts we haven't checked yet.
        check = set([t])

        if len(musts) == 1:
            # Include the essential packages in testing as a starting point.
            if t[2] not in self._cache_ess:
                # The minimal essential set cache is not present -
                # compute it now.
                (start, ess_never) = self._get_min_pseudo_ess_set(t[2])
            else:
                (start, ess_never) = self._cache_ess[t[2]]

            if t in ess_never:
                # t conflicts with something in the essential set or the essential
                # set conflicts with t - either way, t is f***ed
                cbroken.add(t)
                testing.remove(t)
                return False
            musts.update(start)
            never.update(ess_never)

        # curry check_loop
        check_loop = partial(self._check_loop, universe, testing,
                             eqv_table, musts, never, choices,
                             cbroken)


        # Useful things to remember:
        #
        # * musts and never are disjointed at all times
        #   - if not, t cannot be installable.  Either t, or one of
        #     its dependencies conflict with t or one of its (other)
        #     dependencies.
        #
        # * choices should generally be avoided as much as possible.
        #   - picking a bad choice requires backtracking
        #   - sometimes musts/never will eventually "solve" the choice.
        #
        # * check never includes choices (these are always in choices)
        #
        # * A package is installable if never and musts are disjoined
        #   and both check and choices are empty.
        #   - exception: _pick_choice may determine the installability
        #     of t via recursion (calls _check_inst).  In this case
        #     check and choices are not (always) empty.

        def _pick_choice(rebuild, set=set, len=len):
            """Picks a choice from choices and updates rebuild.

            Prunes the choices and updates "rebuild" to reflect the
            pruned choices.

            Returns True if t is installable (determined via recursion).
            Returns False if a choice was picked and added to check.
            Returns None if t is uninstallable (no choice can be picked).

            NB: If this returns False, choices should be replaced by
            rebuild.
            """

            # We already satisfied/chosen at least one of the litterals
            # in the choice, so the choice is gone
            for choice in filter(musts.isdisjoint, choices):
                # cbroken is needed here because (in theory) it could
                # have changed since the choice was discovered and it
                # is smaller than testing (so presumably faster)
                remain = choice - never - cbroken

                if len(remain) > 1 and not remain.isdisjoint(safe_set):
                    first = None
                    for r in filter(safe_set.__contains__, remain):
                        # don't bother giving extra arguments to _check_inst.  "safe" packages are
                        # usually trivial to satisfy on their own and will not involve conflicts
                        # (so never will not help)
                        if r in cache_inst or self._check_inst(r):
                            first = r
                            break
                    if first:
                        musts.add(first)
                        check.add(first)
                        continue
                    # None of the safe set choices are installable, so drop them
                    remain -= safe_set

                if len(remain) == 1:
                    # the choice was reduced to one package we haven't checked - check that
                    check.update(remain)
                    musts.update(remain)
                    continue

                if not remain:
                    # all alternatives would violate the conflicts or are uninstallable
                    # => package is not installable
                    return None

                # The choice is still deferred
                rebuild.add(frozenset(remain))

            if check or not rebuild:
                return False

            choice = iter(rebuild.pop())
            last = next(choice) # pick one to go last
            for p in choice:
                musts_copy = musts.copy()
                never_tmp = set()
                choices_tmp = set()
                check_tmp = set([p])
                if not self._check_loop(universe, testing, eqv_table,
                                        musts_copy, never_tmp,
                                        choices_tmp, cbroken,
                                        check_tmp):
                    # p cannot be chosen/is broken (unlikely, but ...)
                    continue

                # Test if we can pick p without any consequences.
                # - when we can, we avoid a backtrack point.
                if never_tmp <= never and choices_tmp <= rebuild:
                    # we can pick p without picking up new conflicts
                    # or unresolved choices.  Therefore we commit to
                    # using p.
                    #
                    # NB: Optimally, we would go to the start of this
                    # routine, but to conserve stack-space, we return
                    # and expect to be called again later.
                    musts.update(musts_copy)
                    return False

                if not musts.isdisjoint(never_tmp):
                    # If we pick p, we will definitely end up making
                    # t uninstallable, so p is a no-go.
                    continue

                # We are not sure that p is safe, setup a backtrack
                # point and recurse.
                never_tmp |= never
                choices_tmp |= rebuild
                if self._check_inst(p, musts_copy, never_tmp,
                                    choices_tmp):
                    # Success, p was a valid choice and made it all
                    # installable
                    return True

                # If we get here, we failed to find something that
                # would satisfy choice (without breaking the
                # installability of t).  This means p cannot be used
                # to satisfy the dependencies, so pretend to conflict
                # with it - hopefully it will reduce future choices.
                never.add(p)

            # Optimization for the last case; avoid the recursive call
            # and just assume the last will lead to a solution.  If it
            # doesn't there is no solution and if it does, we don't
            # have to back-track anyway.
            check.add(last)
            musts.add(last)
            return False
        # END _pick_choice

        while check:
            if not check_loop(check):
                verdict = False
                break

            if choices:
                rebuild = set()
                # We have to "guess" now, which is always fun, but not cheap
                r = _pick_choice(rebuild)
                if r is None:
                    verdict = False
                    break
                if r:
                    # The recursive call have already updated the
                    # cache so there is not point in doing it again.
                    return True
                choices = rebuild

        if verdict:
            # if t is installable, then so are all packages in musts
            self._cache_inst.update(musts)

        return verdict


    def _check_loop(self, universe, testing, eqv_table, musts, never,
                    choices, cbroken, check, len=len,
                    frozenset=frozenset):
        """Finds all guaranteed dependencies via "check".

        If it returns False, t is not installable.  If it returns True
        then "check" is exhausted.  If "choices" are empty and this
        returns True, then t is installable.
        """
        # Local variables for faster access...
        not_satisfied = partial(filter, musts.isdisjoint)

        # While we have guaranteed dependencies (in check), examine all
        # of them.
        for cur in iter_except(check.pop, KeyError):
            (deps, cons) = universe[cur]

            if cons:
                # Conflicts?
                if cur in never:
                    # cur adds a (reverse) conflict, so check if cur
                    # is in never.
                    #
                    # - there is a window where two conflicting
                    #   packages can be in check.  Example "A" depends
                    #   on "B" and "C".  If "B" conflicts with "C",
                    #   then both "B" and "C" could end in "check".
                    return False
                # We must install cur for the package to be installable,
                # so "obviously" we can never choose any of its conflicts
                never.update(cons & testing)

            # depgroup can be satisifed by picking something that is
            # already in musts - lets pick that (again).  :)
            for depgroup in not_satisfied(deps):

                # Of all the packages listed in the relation remove those that
                # are either:
                #  - not in testing
                #  - known to be broken (by cache)
                #  - in never
                candidates = frozenset((depgroup & testing) - never)

                if len(candidates) == 0:
                    # We got no candidates to satisfy it - this
                    # package cannot be installed with the current
                    # testing
                    if cur not in cbroken and depgroup.isdisjoint(never):
                        # cur's dependency cannot be satisfied even if never was empty.
                        # This means that cur itself is broken (as well).
                        cbroken.add(cur)
                        testing.remove(cur)
                    return False
                if len(candidates) == 1:
                    # only one possible solution to this choice and we
                    # haven't seen it before
                    check.update(candidates)
                    musts.update(candidates)
                else:
                    possible_eqv = set(x for x in candidates if x in eqv_table)
                    if len(possible_eqv) > 1:
                        # Exploit equivalency to reduce the number of
                        # candidates if possible.  Basically, this
                        # code maps "similar" candidates into a single
                        # candidate that will give a identical result
                        # to any other candidate it eliminates.
                        #
                        # See InstallabilityTesterBuilder's
                        # _build_eqv_packages_table method for more
                        # information on how this works.
                        new_cand = set(x for x in candidates if x not in possible_eqv)
                        for chosen in iter_except(possible_eqv.pop, KeyError):
                            new_cand.add(chosen)
                            possible_eqv -= eqv_table[chosen]
                        if len(new_cand) == 1:
                            check.update(new_cand)
                            musts.update(new_cand)
                            continue
                        candidates = frozenset(new_cand)
                    # defer this choice till later
                    choices.add(candidates)
        return True


    def _get_min_pseudo_ess_set(self, arch):
        if arch not in self._cache_ess:
            # The minimal essential set cache is not present -
            # compute it now.
            testing = self._testing
            eqv_table = self._eqv_table
            cbroken = self._cache_broken
            universe = self._universe
            safe_set = self._safe_set

            ess_base = set(x for x in self._essentials if x[2] == arch and x in testing)
            start = set(ess_base)
            ess_never = set()
            ess_choices = set()
            not_satisified = partial(filter, start.isdisjoint)

            while ess_base:
                self._check_loop(universe, testing, eqv_table,
                                 start, ess_never, ess_choices,
                                 cbroken, ess_base)
                if ess_choices:
                    # Try to break choices where possible
                    nchoice = set()
                    for choice in not_satisified(ess_choices):
                        b = False
                        for c in choice:
                            if universe[c][1] <= ess_never and \
                                    not any(not_satisified(universe[c][0])):
                                ess_base.add(c)
                                b = True
                                break
                        if not b:
                            nchoice.add(choice)
                    ess_choices = nchoice
                else:
                    break

            for x in start:
                ess_never.update(universe[x][1])
            self._cache_ess[arch] = (frozenset(start), frozenset(ess_never))

        return self._cache_ess[arch]

