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

from collections import defaultdict
from functools import partial
import logging
from itertools import chain, filterfalse

from britney2.utils import iter_except


class InstallabilityTester(object):

    def __init__(self, universe, suite_contents):
        """Create a new installability tester

        universe is a BinaryPackageUniverse

        suite_contents is a (mutable) set of package ids that determines
        which of the packages in universe are currently in the suite.

        Package id: (pkg_name, pkg_version, pkg_arch)
          - NB: arch:all packages are "re-mapped" to given architecture.
            (simplifies caches and dependency checking)
        """

        self._universe = universe
        # FIXME: Move this field to TargetSuite
        self._suite_contents = suite_contents
        self._stats = InstallabilityStats()
        logger_name = ".".join((self.__class__.__module__, self.__class__.__name__))
        self.logger = logging.getLogger(logger_name)

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

    def compute_installability(self):
        """Computes the installability of all the packages in the suite

        This method computes the installability of all packages in
        the suite and caches the result.  This has the advantage of
        making "is_installable" queries very fast for all packages
        in the suite.
        """

        universe = self._universe
        check_inst = self._check_inst
        cbroken = self._cache_broken
        cache_inst = self._cache_inst
        suite_contents = self._suite_contents
        tcopy = [x for x in suite_contents]
        for t in filterfalse(cache_inst.__contains__, tcopy):
            if t in cbroken:
                continue
            res = check_inst(t)
            if t in universe.equivalent_packages:
                eqv = (x for x in universe.packages_equivalent_to(t) if x in suite_contents)
                if res:
                    cache_inst.update(eqv)
                else:
                    eqv_set = frozenset(eqv)
                    suite_contents -= eqv_set
                    cbroken |= eqv_set

    @property
    def stats(self):
        return self._stats

    def any_of_these_are_in_the_suite(self, pkgs):
        """Test if at least one package of a given set is in the suite

        :param pkgs: A set of package ids (as defined in the constructor)
        :return: True if any of the packages in pkgs are currently in the suite
        """
        return not self._suite_contents.isdisjoint(pkgs)

    def is_pkg_in_the_suite(self, pkg_id):
        """Test if the package of is in the suite

        :param pkg_id: A package id (as defined in the constructor)
        :return: True if the pkg is currently in the suite
        """
        return pkg_id in self._suite_contents

    def which_of_these_are_in_the_suite(self, pkgs):
        """Iterate over all packages that are in the suite

        :param pkgs: An iterable of package ids
        :return: An iterable of package ids that are in the suite
        """
        yield from (x for x in pkgs if x in self._suite_contents)

    def add_binary(self, pkg_id):
        """Add a binary package to the suite

        If the package is not known, this method will throw an
        KeyError.

        :param pkg_id The id of the package
        """

        if pkg_id not in self._universe:  # pragma: no cover
            raise KeyError(str(pkg_id))

        if pkg_id in self._universe.broken_packages:
            self._suite_contents.add(pkg_id)
        elif pkg_id not in self._suite_contents:
            self._suite_contents.add(pkg_id)
            if self._cache_inst:
                self._stats.cache_drops += 1
            self._cache_inst = set()
            if self._cache_broken:
                # Re-add broken packages as some of them may now be installable
                self._suite_contents |= self._cache_broken
                self._cache_broken = set()
            if pkg_id in self._universe.essential_packages and pkg_id.architecture in self._cache_ess:
                # Adds new essential => "pseudo-essential" set needs to be
                # recomputed
                del self._cache_ess[pkg_id.architecture]

        return True

    def remove_binary(self, pkg_id):
        """Remove a binary from the suite

        :param pkg_id The id of the package
        If the package is not known, this method will throw an
        KeyError.
        """

        if pkg_id not in self._universe:  # pragma: no cover
            raise KeyError(str(pkg_id))

        self._cache_broken.discard(pkg_id)

        if pkg_id in self._suite_contents:
            self._suite_contents.remove(pkg_id)
            if pkg_id.architecture in self._cache_ess and pkg_id in self._cache_ess[pkg_id.architecture][0]:
                # Removes a package from the "pseudo-essential set"
                del self._cache_ess[pkg_id.architecture]

            if not self._universe.reverse_dependencies_of(pkg_id):
                # no reverse relations - safe
                return True
            if pkg_id not in self._universe.broken_packages and pkg_id in self._cache_inst:
                # It is in our cache (and not guaranteed to be broken) - throw out the cache
                self._cache_inst = set()
                self._stats.cache_drops += 1

        return True

    def is_installable(self, pkg_id):
        """Test if a package is installable in this package set

        The package is assumed to be in the suite and only packages in
        the suite can be used to satisfy relations.

        :param pkg_id The id of the package
        Returns True iff the package is installable.
        Returns False otherwise.
        """

        self._stats.is_installable_calls += 1

        if pkg_id not in self._universe:  # pragma: no cover
            raise KeyError(str(pkg_id))

        if pkg_id not in self._suite_contents or pkg_id in self._universe.broken_packages:
            self._stats.cache_hits += 1
            return False

        if pkg_id in self._cache_inst:
            self._stats.cache_hits += 1
            return True

        self._stats.cache_misses += 1
        return self._check_inst(pkg_id)

    def _check_inst(self, t, musts=None, never=None, choices=None):
        # See the explanation of musts, never and choices below.
        stats = self._stats
        universe = self._universe
        suite_contents = self._suite_contents
        cbroken = self._cache_broken

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
        check = [t]

        if len(musts) == 1:
            # Include the essential packages in the suite as a starting point.
            if t.architecture not in self._cache_ess:
                # The minimal essential set cache is not present -
                # compute it now.
                (start, ess_never, ess_choices) = self._get_min_pseudo_ess_set(t.architecture)
            else:
                (start, ess_never, ess_choices) = self._cache_ess[t.architecture]

            if t in ess_never:
                # t conflicts with something in the essential set or the essential
                # set conflicts with t - either way, t is f***ed
                cbroken.add(t)
                suite_contents.remove(t)
                stats.conflicts_essential += 1
                return False
            musts.update(start)
            never.update(ess_never)
            choices.update(ess_choices)

        # curry check_loop
        check_loop = partial(self._check_loop, universe, suite_contents,
                             stats, musts, never, cbroken)

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
        # * A package is installable if never and musts are disjointed
        #   and both check and choices are empty.
        #   - exception: resolve_choices may determine the installability
        #     of t via recursion (calls _check_inst).  In this case
        #     check and choices are not (always) empty.

        def _prune_choices(rebuild, len=len):
            """Picks a choice from choices and updates rebuild.

            Prunes the choices and updates "rebuild" to reflect the
            pruned choices.

            Returns True if t is installable (determined via recursion).
            Returns False if a choice was picked and added to check.
            Returns None if t is uninstallable (no choice can be picked).

            NB: If this returns False, choices should be replaced by
            rebuild.
            """

            # We already satisfied/chosen at least one of the literals
            # in the choice, so the choice is gone
            for choice in filter(musts.isdisjoint, choices):
                # cbroken is needed here because (in theory) it could
                # have changed since the choice was discovered and it
                # is smaller than suite_contents (so presumably faster)
                remain = choice - never - cbroken

                if len(remain) == 1:
                    # the choice was reduced to one package we haven't checked - check that
                    check.extend(remain)
                    musts.update(remain)
                    stats.choice_presolved += 1
                    continue

                if not remain:
                    # all alternatives would violate the conflicts or are uninstallable
                    # => package is not installable
                    stats.choice_presolved += 1
                    return False

                # The choice is still deferred
                rebuild.add(frozenset(remain))

            return True

        # END _prune_choices

        while check:
            if not check_loop(choices, check):
                verdict = False
                break

            if choices:
                rebuild = set()

                if not _prune_choices(rebuild):
                    verdict = False
                    break

                if not check and rebuild:
                    # We have to "guess" now, which is always fun, but not cheap. We
                    # stop guessing:
                    # - once we run out of choices to make (obviously), OR
                    # - if one of the choices exhaust all but one option
                    if self.resolve_choices(check, musts, never, rebuild):
                        # The recursive call have already updated the
                        # cache so there is not point in doing it again.
                        return True
                choices = rebuild

        if verdict:
            # if t is installable, then so are all packages in musts
            self._cache_inst.update(musts)
            stats.solved_installable += 1
        else:
            stats.solved_uninstallable += 1

        return verdict

    def resolve_choices(self, check, musts, never, choices):
        universe = self._universe
        suite_contents = self._suite_contents
        stats = self._stats
        cbroken = self._cache_broken

        while choices:
            choice_options = choices.pop()

            choice = iter(choice_options)
            last = next(choice)  # pick one to go last
            solved = False
            for p in choice:
                musts_copy = musts.copy()
                never_tmp = set()
                choices_tmp = set()
                check_tmp = [p]
                # _check_loop assumes that "musts" is up to date
                musts_copy.add(p)
                if not self._check_loop(universe, suite_contents,
                                        stats, musts_copy, never_tmp,
                                        cbroken, choices_tmp,
                                        check_tmp):
                    # p cannot be chosen/is broken (unlikely, but ...)
                    continue

                # Test if we can pick p without any consequences.
                # - when we can, we avoid a backtrack point.
                if never_tmp <= never and choices_tmp <= choices:
                    # we can pick p without picking up new conflicts
                    # or unresolved choices.  Therefore we commit to
                    # using p.
                    musts.update(musts_copy)
                    stats.choice_resolved_without_restore_point += 1
                    solved = True
                    break

                if not musts.isdisjoint(never_tmp):
                    # If we pick p, we will definitely end up making
                    # t uninstallable, so p is a no-go.
                    continue

                stats.backtrace_restore_point_created += 1
                # We are not sure that p is safe, setup a backtrack
                # point and recurse.
                never_tmp |= never
                choices_tmp |= choices
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
                stats.backtrace_restore_point_used += 1

            if not solved:
                # Optimization for the last case; avoid the recursive call
                # and just assume the last will lead to a solution.  If it
                # doesn't there is no solution and if it does, we don't
                # have to back-track anyway.
                check.append(last)
                musts.add(last)
                stats.backtrace_last_option += 1
                return False

    def _check_loop(self, universe, suite_contents, stats, musts, never,
                    cbroken, choices, check, len=len,
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
        for cur in iter_except(check.pop, IndexError):
            relations = universe.relations_of(cur)

            if relations.negative_dependencies:
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
                never.update(relations.negative_dependencies & suite_contents)

            # depgroup can be satisfied by picking something that is
            # already in musts - lets pick that (again).  :)
            for depgroup in not_satisfied(relations.dependencies):

                # Of all the packages listed in the relation remove those that
                # are either:
                #  - not in the suite
                #  - known to be broken (by cache)
                #  - in never
                candidates = (depgroup & suite_contents) - never

                if not candidates:
                    # We got no candidates to satisfy it - this
                    # package cannot be installed with the current
                    # (version of the) suite
                    if cur not in cbroken and depgroup.isdisjoint(never):
                        # cur's dependency cannot be satisfied even if never was empty.
                        # This means that cur itself is broken (as well).
                        cbroken.add(cur)
                        suite_contents.remove(cur)
                    return False
                if len(candidates) == 1:
                    # only one possible solution to this choice and we
                    # haven't seen it before
                    check.extend(candidates)
                    musts.update(candidates)
                else:
                    possible_eqv = set(x for x in candidates if x in universe.equivalent_packages)
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
                        stats.eqv_table_times_used += 1

                        for chosen in iter_except(possible_eqv.pop, KeyError):
                            new_cand.add(chosen)
                            possible_eqv -= universe.packages_equivalent_to(chosen)
                        stats.eqv_table_total_number_of_alternatives_eliminated += len(candidates) - len(new_cand)
                        if len(new_cand) == 1:
                            check.extend(new_cand)
                            musts.update(new_cand)
                            stats.eqv_table_reduced_to_one += 1
                            continue
                        elif len(candidates) == len(new_cand):
                            stats.eqv_table_reduced_by_zero += 1

                        candidates = frozenset(new_cand)
                    else:
                        # Candidates have to be a frozenset to be added to choices
                        candidates = frozenset(candidates)
                    # defer this choice till later
                    choices.add(candidates)
        return True

    def _get_min_pseudo_ess_set(self, arch):
        if arch not in self._cache_ess:
            # The minimal essential set cache is not present -
            # compute it now.
            suite_contents = self._suite_contents
            cbroken = self._cache_broken
            universe = self._universe
            stats = self._stats

            ess_base = [x for x in self._universe.essential_packages if x.architecture == arch and x in suite_contents]
            start = set(ess_base)
            ess_never = set()
            ess_choices = set()
            not_satisfied = partial(filter, start.isdisjoint)

            while ess_base:
                self._check_loop(universe, suite_contents, stats,
                                 start, ess_never, cbroken,
                                 ess_choices, ess_base)
                if ess_choices:
                    # Try to break choices where possible
                    nchoice = set()
                    for choice in not_satisfied(ess_choices):
                        b = False
                        for c in choice:
                            relations = universe.relations_of(c)
                            if relations.negative_dependencies <= ess_never and \
                                    not any(not_satisfied(relations.dependencies)):
                                ess_base.append(c)
                                b = True
                                break
                        if not b:
                            nchoice.add(choice)
                    ess_choices = nchoice
                else:
                    break

            for x in start:
                ess_never.update(universe.negative_dependencies_of(x))
            self._cache_ess[arch] = (frozenset(start), frozenset(ess_never), frozenset(ess_choices))

        return self._cache_ess[arch]

    def compute_stats(self):
        universe = self._universe
        graph_stats = defaultdict(ArchStats)
        seen_eqv = defaultdict(set)

        for pkg in universe:
            (pkg_name, pkg_version, pkg_arch) = pkg
            relations = universe.relations_of(pkg)
            arch_stats = graph_stats[pkg_arch]

            arch_stats.nodes += 1

            if pkg in universe.equivalent_packages and pkg not in seen_eqv[pkg_arch]:
                eqv = [e for e in universe.packages_equivalent_to(pkg) if e.architecture == pkg_arch]
                arch_stats.eqv_nodes += len(eqv)

            arch_stats.add_dep_edges(relations.dependencies)
            arch_stats.add_con_edges(relations.negative_dependencies)

        for stat in graph_stats.values():
            stat.compute_all()

        return graph_stats


class InstallabilityStats(object):

    def __init__(self):
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_drops = 0
        self.backtrace_restore_point_created = 0
        self.backtrace_restore_point_used = 0
        self.backtrace_last_option = 0
        self.choice_presolved = 0
        self.choice_resolved_without_restore_point = 0
        self.is_installable_calls = 0
        self.solved_installable = 0
        self.solved_uninstallable = 0
        self.conflicts_essential = 0
        self.eqv_table_times_used = 0
        self.eqv_table_reduced_to_one = 0
        self.eqv_table_reduced_by_zero = 0
        self.eqv_table_total_number_of_alternatives_eliminated = 0

    def stats(self):
        formats = [
            "Requests - is_installable: {is_installable_calls}",
            "Cache - hits: {cache_hits}, misses: {cache_misses}, drops: {cache_drops}",
            "Choices - pre-solved: {choice_presolved}, No RP: {choice_resolved_without_restore_point}",
            "Backtrace - RP created: {backtrace_restore_point_created}, RP used: {backtrace_restore_point_used}, reached last option: {backtrace_last_option}",
            "Solved - installable: {solved_installable}, uninstallable: {solved_uninstallable}, conflicts essential: {conflicts_essential}",
            "Eqv - times used: {eqv_table_times_used}, perfect reductions: {eqv_table_reduced_to_one}, failed reductions: {eqv_table_reduced_by_zero}, total no. of alternatives pruned: {eqv_table_total_number_of_alternatives_eliminated}",
        ]
        return [x.format(**self.__dict__) for x in formats]


class ArchStats(object):

    def __init__(self):
        self.nodes = 0
        self.eqv_nodes = 0
        self.dep_edges = []
        self.con_edges = []
        self.stats = defaultdict(lambda: defaultdict(int))

    def stat(self, statname):
        return self.stats[statname]

    def stat_summary(self):
        text = []
        for statname in ['nodes', 'dependency-clauses', 'dependency-clause-alternatives', 'negative-dependency-clauses']:
            stat = self.stats[statname]
            if statname != 'nodes':
                format_str = "%s, max: %d, min: %d, median: %d, average: %f (%d/%d)"
                values = [statname, stat['max'], stat['min'], stat['median'], stat['average'], stat['sum'], stat['size']]
                if 'average-per-node' in stat:
                    format_str += ", average-per-node: %f"
                    values.append(stat['average-per-node'])
            else:
                format_str = "nodes: %d, eqv-nodes: %d"
                values = (self.nodes, self.eqv_nodes)
            text.append(format_str % tuple(values))
        return text

    def add_dep_edges(self, edges):
        self.dep_edges.append(edges)

    def add_con_edges(self, edges):
        self.con_edges.append(edges)

    def _list_stats(self, stat_name, sorted_list, average_per_node=False):
        if sorted_list:
            stats = self.stats[stat_name]
            stats['max'] = sorted_list[-1]
            stats['min'] = sorted_list[0]
            stats['sum'] = sum(sorted_list)
            stats['size'] = len(sorted_list)
            stats['average'] = float(stats['sum'])/len(sorted_list)
            stats['median'] = sorted_list[len(sorted_list)//2]
            if average_per_node:
                stats['average-per-node'] = float(stats['sum'])/self.nodes

    def compute_all(self):
        dep_edges = self.dep_edges
        con_edges = self.con_edges
        sorted_no_dep_edges = sorted(len(x) for x in dep_edges)
        sorted_size_dep_edges = sorted(len(x) for x in chain.from_iterable(dep_edges))
        sorted_no_con_edges = sorted(len(x) for x in con_edges)
        self._list_stats('dependency-clauses', sorted_no_dep_edges)
        self._list_stats('dependency-clause-alternatives', sorted_size_dep_edges, average_per_node=True)
        self._list_stats('negative-dependency-clauses', sorted_no_con_edges)

