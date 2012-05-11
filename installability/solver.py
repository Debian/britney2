# -*- coding: utf-8 -*-

# Copyright (C) 2012 Niels Thykier <niels@thykier.net>
# - Includes code by Paul Harrison
#   (http://www.logarithmic.net/pfh-files/blog/01208083168/sort.py)

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

from functools import partial
import os

from installability.tester import InstallabilityTester
from britney_util import (ifilter_only, iter_except)


class InstallabilitySolver(InstallabilityTester):

    def __init__(self, universe, revuniverse, testing, broken, essentials,
                 safe_set):
        """Create a new installability solver

        universe is a dict mapping package tuples to their
        dependencies and conflicts.

        revuniverse is a dict mapping package tuples to their reverse
        dependencies and reverse conflicts.

        testing is a (mutable) set of package tuples that determines
        which of the packages in universe are currently in testing.

        broken is a (mutable) set of package tuples that are known to
        be uninstallable.

        Package tuple: (pkg_name, pkg_version, pkg_arch)
          - NB: arch:all packages are "re-mapped" to given architecture.
            (simplifies caches and dependency checking)
        """
        InstallabilityTester.__init__(self, universe, revuniverse, testing,
                                      broken, essentials, safe_set)


    def solve_groups(self, groups):
        sat_in_testing = self._testing.isdisjoint
        universe = self._universe
        revuniverse = self._revuniverse
        result = []
        emitted = set()
        check = set()
        order = {}
        ptable = {}
        key2item = {}
        going_out = set()
        going_in = set()
        debug_solver = 0

        try:
            debug_solver = int(os.environ.get('BRITNEY_DEBUG', '0'))
        except:
            pass

        # Build the tables
        for (item, adds, rms) in groups:
            key = str(item)
            key2item[key] = item
            order[key] = {'before': set(), 'after': set()}
            going_in.update(adds)
            going_out.update(rms)
            for a in adds:
                ptable[a] = key
            for r in rms:
                ptable[r] = key

        # This large loop will add ordering constrains on each "item"
        # that migrates based on various rules.
        for (item, adds, rms) in groups:
            key = str(item)
            oldcons = set()
            newcons = set()
            for r in rms:
                oldcons.update(universe[r][1])
            for a in adds:
                newcons.update(universe[a][1])
            current = newcons & oldcons
            oldcons -= current
            newcons -= current
            if oldcons:
                # Some of the old binaries have "conflicts" that will
                # be removed.
                for o in ifilter_only(ptable, oldcons):
                    # "key" removes a conflict with one of
                    # "other"'s binaries, so it is probably a good
                    # idea to migrate "key" before "other"
                    other = ptable[o]
                    if other == key:
                        # "Self-conflicts" => ignore
                        continue
                    if debug_solver and other not in order[key]['before']:
                        print "N: Conflict induced order: %s before %s" % (key, other)
                    order[key]['before'].add(other)
                    order[other]['after'].add(key)

            for r in ifilter_only(revuniverse, rms):
                # The binaries have reverse dependencies in testing;
                # check if we can/should migrate them first.
                for rdep in revuniverse[r][0]:
                    for depgroup in universe[rdep][0]:
                        rigid = depgroup - going_out
                        if not sat_in_testing(rigid):
                            # (partly) satisfied by testing, assume it is okay
                            continue
                        if rdep in ptable:
                            other = ptable[rdep]
                            if other == key:
                                # "Self-dependency" => ignore
                                continue
                            if debug_solver and other not in order[key]['after']:
                                print "N: Removal induced order: %s before %s" % (key, other)
                            order[key]['after'].add(other)
                            order[other]['before'].add(key)

            for a in adds:
                # Check if this item should migrate before others
                # (e.g. because they depend on a new [version of a]
                # binary provided by this item).
                for depgroup in universe[a][0]:
                    rigid = depgroup - going_out
                    if not sat_in_testing(rigid):
                        # (partly) satisfied by testing, assume it is okay
                        continue
                    # okay - we got three cases now.
                    # - "swap" (replace existing binary with a newer version)
                    # - "addition" (add new binary without removing any)
                    # - "removal" (remove binary without providing a new)
                    #
                    # The problem is that only the two latter requires
                    # an ordering.  A "swap" (in itself) should not
                    # affect us.
                    other_adds = set()
                    other_rms = set()
                    for d in ifilter_only(ptable, depgroup):
                        if d in going_in:
                            # "other" provides something "key" needs,
                            # schedule accordingly.
                            other = ptable[d]
                            other_adds.add(other)
                        else:
                            # "other" removes something "key" needs,
                            # schedule accordingly.
                            other = ptable[d]
                            other_rms.add(other)

                    for other in (other_adds - other_rms):
                        if debug_solver and other != key and other not in order[key]['after']:
                            print "N: Dependency induced order (add): %s before %s" % (key, other)
                        order[key]['after'].add(other)
                        order[other]['before'].add(key)

                    for other in (other_rms - other_adds):
                        if debug_solver and other != key and other not in order[key]['before']:
                            print "N: Dependency induced order (remove): %s before %s" % (key, other)
                        order[key]['before'].add(other)
                        order[other]['after'].add(key)

        ### MILESTONE: Partial-order constrains computed ###

        # At this point, we have computed all the partial-order
        # constrains needed.  Some of these may have created strongly
        # connected components (SSC) [of size 2 or greater], which
        # represents a group of items that (we believe) must migrate
        # together.
        #
        # Each one of those components will become an "easy" hint.

        comps = self._compute_scc(order, ptable)
        merged = {}
        scc = {}
        # Now that we got the SSCs (in comps), we select on item from
        # each SSC to represent the group and become an ID for that
        # SSC.
        #  * ssc[ssc_id] => All the items in that SSC
        #  * merged[item] => The ID of the SSC to which the item belongs.
        #
        # We also "repair" the ordering, so we know in which order the
        # hints should be emitted.
        for com in comps:
            scc_id = com[0]
            scc[scc_id] = com
            merged[scc_id] = scc_id
            if len(com) > 1:
                so_before = order[scc_id]['before']
                so_after = order[scc_id]['after']
                for n in com:
                    if n == scc_id:
                        continue
                    so_before.update(order[n]['before'])
                    so_after.update(order[n]['after'])
                    merged[n] = scc_id
                    del order[n]
                if debug_solver:
                    print "N: SCC: %s -- %s" % (scc_id, str(sorted(com)))

        for com in comps:
            node = com[0]
            nbefore = set(merged[b] for b in order[node]['before'])
            nafter = set(merged[b] for b in order[node]['after'])

            # Drop self-relations (usually caused by the merging)
            nbefore.discard(node)
            nafter.discard(node)
            order[node]['before'] = nbefore
            order[node]['after'] = nafter


        if debug_solver:
            print "N: -- PARTIAL ORDER --"

        for com in sorted(order):
            if debug_solver and order[com]['before']:
                print "N: %s <= %s" % (com, str(sorted(order[com]['before'])))
            if not order[com]['after']:
                # This component can be scheduled immediately, add it
                # to "check"
                check.add(com)
            elif debug_solver:
                print "N: %s >= %s" % (com, str(sorted(order[com]['after'])))

        if debug_solver:
            print "N: -- END PARTIAL ORDER --"
            print "N: -- LINEARIZED ORDER --"

        for cur in iter_except(check.pop, KeyError):
            if order[cur]['after'] <= emitted:
                # This item is ready to be emitted right now
                if debug_solver:
                    print "N: %s -- %s" % (cur, sorted(scc[cur]))
                emitted.add(cur)
                result.append([key2item[x] for x in scc[cur]])
                if order[cur]['before']:
                    # There are components that come after this one.
                    # Add it to "check":
                    # - if it is ready, it will be emitted.
                    # - else, it will be dropped and re-added later.
                    check.update(order[cur]['before'] - emitted)

        if debug_solver:
            print "N: -- END LINEARIZED ORDER --"

        return result


    def _compute_scc(self, order, ptable):
        """
        Tarjan's algorithm and topological sorting implementation in Python

        Find the strongly connected components in a graph using
        Tarjan's algorithm.

        by Paul Harrison

        Public domain, do with it as you will
        """

        result = [ ]
        stack = [ ]
        low = { }

        def visit(node):
            if node in low:
                return

            num = len(low)
            low[node] = num
            stack_pos = len(stack)
            stack.append(node)

            for successor in order[node]['before']:
                visit(successor)
                low[node] = min(low[node], low[successor])

            if num == low[node]:
                component = tuple(stack[stack_pos:])
                del stack[stack_pos:]
                result.append(component)
                for item in component:
                    low[item] = len(ptable)

        for node in order:
            visit(node)

        return result

