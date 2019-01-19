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

import logging
from collections import deque
from itertools import chain

from britney2.utils import (ifilter_only, iter_except)


def compute_scc(graph):
    """Iterative algorithm for strongly-connected components

    Iterative variant of Tarjan's algorithm for finding strongly-connected
    components.

    :param graph: Table of all nodes along which their edges (in "before" and "after")
    :return: List of components (each component is a list of items)
    """
    result = []
    low = {}
    node_stack = []

    def _handle_succ(parent, parent_num, successors_remaining):
        while successors_remaining:
            succ = successors_remaining.pop()
            succ_num = low.get(succ, None)
            if succ_num is not None:
                if succ_num < parent_num:
                    # These two nodes are part of the probably
                    # same SSC (or succ is isolated
                    low[parent] = parent_num = succ_num
                continue
            # It cannot be a part of a SCC if it does not have depends
            # or reverse depends.
            if not graph[succ]['before'] or not graph[succ]['after']:
                # Short-cut obviously isolated component
                result.append((succ,))
                # Set the item number so high that no other item might
                # mistakenly assume that they can form a component via
                # this item.
                # (Replaces the "is w on the stack check" for us from
                #  the original algorithm)
                low[succ] = len(graph) + 1
                continue
            succ_num = len(low)
            low[succ] = succ_num
            work_stack.append((succ, len(node_stack), succ_num, graph[succ]['before']))
            node_stack.append(succ)
            # "Recurse" into the child node first
            return True
        return False

    for n in graph:
        if n in low:
            continue
        # It cannot be a part of a SCC if it does not have depends
        # or reverse depends.
        if not graph[n]['before'] or not graph[n]['after']:
            # Short-cut obviously isolated component
            result.append((n,))
            # Set the item number so high that no other item might
            # mistakenly assume that they can form a component via
            # this item.
            # (Replaces the "is w on the stack check" for us from
            #  the original algorithm)
            low[n] = len(graph) + 1
            continue

        root_num = len(low)
        low[n] = root_num
        # DFS work-stack needed to avoid call recursion.  It (more or less)
        # replaces the variables on the call stack in Tarjan's algorithm
        work_stack = [(n, len(node_stack), root_num, graph[n]['before'])]
        node_stack.append(n)
        while work_stack:
            node, stack_idx, orig_node_num, successors = work_stack[-1]
            if successors and _handle_succ(node, low[node], successors):
                # _handle_succ has pushed a new node on to work_stack
                # and we need to "restart" the loop to handle that first
                continue

            # This node is done; remove it from the work stack
            work_stack.pop()

            # This node is out of successor.  Push up the "low" value
            # (Exception: root node has no parent)
            node_num = low[node]
            if work_stack:
                parent = work_stack[-1][0]
                parent_num = low[parent]
                if node_num <= parent_num:
                    # This node is a part of a component with its parent.
                    # We update the parent's node number and push the
                    # responsibility of building the component unto the
                    # parent.
                    low[parent] = node_num
                    continue
                if node_num != orig_node_num:
                    # The node is a part of an SCC with a ancestor (and parent)
                    continue
            # We got a component
            component = tuple(node_stack[stack_idx:])
            del node_stack[stack_idx:]
            result.append(component)
            # Re-number all items, so no other item might
            # mistakenly assume that they can form a component via
            # one of these items.
            # (Replaces the "is w on the stack check" for us from
            #  the original algorithm)
            new_num = len(graph) + 1
            for item in component:
                low[item] = new_num

    assert not node_stack

    return result


class InstallabilitySolver(object):

    def __init__(self, universe, inst_tester):
        """Create a new installability solver

        universe is a BinaryPackageUniverse.
        """
        self._universe = universe
        self._inst_tester = inst_tester
        logger_name = ".".join((self.__class__.__module__, self.__class__.__name__))
        self.logger = logging.getLogger(logger_name)

    def _compute_group_order_rms(self, rms, order, key, ptable, going_out):
        sat_in_testing = self._inst_tester.any_of_these_are_in_the_suite
        universe = self._universe
        debug_solver = self.logger.isEnabledFor(logging.DEBUG)
        for r in rms:
            # The binaries have reverse dependencies in testing;
            # check if we can/should migrate them first.
            for rdep in universe.reverse_dependencies_of(r):
                for depgroup in universe.dependencies_of(rdep):
                    rigid = depgroup - going_out
                    if sat_in_testing(rigid):
                        # (partly) satisfied by testing, assume it is okay
                        continue
                    if rdep in ptable:
                        other = ptable[rdep]
                        if other == key:
                            # "Self-dependency" => ignore
                            continue
                        if debug_solver and other not in order[key]['after']:  # pragma: no cover
                            self.logger.debug("Removal induced order: %s before %s", key, other)
                        order[key]['after'].add(other)
                        order[other]['before'].add(key)

    def _compute_group_order_adds(self, adds, order, key, ptable, going_out, going_in):
        sat_in_testing = self._inst_tester.any_of_these_are_in_the_suite
        universe = self._universe
        debug_solver = self.logger.isEnabledFor(logging.DEBUG)
        for a in adds:
            # Check if this item should migrate before others
            # (e.g. because they depend on a new [version of a]
            # binary provided by this item).
            for depgroup in universe.dependencies_of(a):
                rigid = depgroup - going_out
                if sat_in_testing(rigid):
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
                    other = ptable[d]
                    if d in going_in:
                        # "other" provides something "key" needs,
                        # schedule accordingly.
                        other_adds.add(other)
                    else:
                        # "other" removes something "key" needs,
                        # schedule accordingly.
                        other_rms.add(other)

                for other in (other_adds - other_rms):
                    if debug_solver and other != key and other not in order[key]['after']:  # pragma: no cover
                        self.logger.debug("Dependency induced order (add): %s before %s", key, other)
                    order[key]['after'].add(other)
                    order[other]['before'].add(key)

                for other in (other_rms - other_adds):
                    if debug_solver and other != key and other not in order[key]['before']:  # pragma: no cover
                        self.logger.debug("Dependency induced order (remove): %s before %s", key, other)
                    order[key]['before'].add(other)
                    order[other]['after'].add(key)

    def _compute_group_order(self, groups, key2item):
        universe = self._universe
        ptable = {}
        order = {}
        going_out = set()
        going_in = set()
        debug_solver = self.logger.isEnabledFor(logging.DEBUG)

        # Build the tables
        for (item, adds, rms) in groups:
            key = str(item)
            key2item[key] = item
            order[key] = {'before': set(), 'after': set()}
            going_in.update(adds)
            going_out.update(rms)
            for x in chain(adds, rms):
                ptable[x] = key

        if debug_solver:  # pragma: no cover
            self._dump_groups(groups)

        # This large loop will add ordering constrains on each "item"
        # that migrates based on various rules.
        for (item, adds, rms) in groups:
            key = str(item)
            oldcons = set(chain.from_iterable(universe.negative_dependencies_of(r) for r in rms))
            newcons = set(chain.from_iterable(universe.negative_dependencies_of(a) for a in adds))
            oldcons -= newcons
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
                if debug_solver and other not in order[key]['before']:  # pragma: no cover
                    self.logger.debug("Conflict induced order: %s before %s", key, other)
                order[key]['before'].add(other)
                order[other]['after'].add(key)

            self._compute_group_order_rms(rms, order, key, ptable, going_out)
            self._compute_group_order_adds(adds, order, key, ptable, going_out, going_in)

        return order

    def _merge_items_into_components(self, comps, order):
        merged = {}
        scc = {}
        debug_solver = self.logger.isEnabledFor(logging.DEBUG)
        for com in comps:
            scc_id = com[0]
            scc[scc_id] = com
            merged[scc_id] = scc_id
            if len(com) < 2:
                # Trivial case
                continue
            so_before = order[scc_id]['before']
            so_after = order[scc_id]['after']
            for n in com:
                if n == scc_id:
                    continue
                so_before.update(order[n]['before'])
                so_after.update(order[n]['after'])
                merged[n] = scc_id
                del order[n]
            if debug_solver:  # pragma: no cover
                self.logger.debug("SCC: %s -- %s", scc_id, str(sorted(com)))

        for com in comps:
            node = com[0]
            nbefore = set(merged[b] for b in order[node]['before'])
            nafter = set(merged[b] for b in order[node]['after'])

            # Drop self-relations (usually caused by the merging)
            nbefore.discard(node)
            nafter.discard(node)
            order[node]['before'] = nbefore
            order[node]['after'] = nafter

        for com in comps:
            scc_id = com[0]

            for other_scc_id in order[scc_id]['before']:
                order[other_scc_id]['after'].add(scc_id)
            for other_scc_id in order[scc_id]['after']:
                order[other_scc_id]['before'].add(scc_id)

        return scc

    def solve_groups(self, groups):
        result = []
        emitted = set()
        queue = deque()
        key2item = {}
        debug_solver = self.logger.isEnabledFor(logging.DEBUG)

        order = self._compute_group_order(groups, key2item)

        # === MILESTONE: Partial-order constrains computed ===

        # At this point, we have computed all the partial-order
        # constrains needed.  Some of these may have created strongly
        # connected components (SSC) [of size 2 or greater], which
        # represents a group of items that (we believe) must migrate
        # together.
        #
        # Each one of those components will become an "easy" hint.

        comps = compute_scc(order)
        # Now that we got the SSCs (in comps), we select on item from
        # each SSC to represent the group and become an ID for that
        # SSC.
        #  * scc_items[ssc_id] => All the items in that SSC
        #
        # We also "repair" the ordering, so we know in which order the
        # hints should be emitted.
        scc_items = self._merge_items_into_components(comps, order)

        if debug_solver:  # pragma: no cover
            self.logger.debug("-- PARTIAL ORDER --")

        initial_round = []
        for com in sorted(order):
            if debug_solver and order[com]['before']:  # pragma: no cover
                self.logger.debug("N: %s <= %s", com, str(sorted(order[com]['before'])))
            if not order[com]['after']:
                # This component can be scheduled immediately, add it
                # to the queue
                initial_round.append(com)
            elif debug_solver:  # pragma: no cover
                self.logger.debug("N: %s >= %s", com, str(sorted(order[com]['after'])))

        queue.extend(sorted(initial_round, key=len))
        del initial_round

        if debug_solver:  # pragma: no cover
            self.logger.debug("-- END PARTIAL ORDER --")
            self.logger.debug("-- LINEARIZED ORDER --")

        for cur in iter_except(queue.popleft, IndexError):
            if order[cur]['after'] <= emitted and cur not in emitted:
                # This item is ready to be emitted right now
                if debug_solver:  # pragma: no cover
                    self.logger.debug("%s -- %s", cur, sorted(scc_items[cur]))
                emitted.add(cur)
                result.append([key2item[x] for x in scc_items[cur]])
                if order[cur]['before']:
                    # There are components that come after this one.
                    # Add it to queue:
                    # - if it is ready, it will be emitted.
                    # - else, it will be dropped and re-added later.
                    queue.extend(sorted(order[cur]['before'] - emitted, key=len))

        if debug_solver:  # pragma: no cover
            self.logger.debug("-- END LINEARIZED ORDER --")

        return result

    def _dump_groups(self, groups):  # pragma: no cover
        self.logger.debug("=== Groups ===")
        for (item, adds, rms) in groups:
            self.logger.debug("%s =>  A: %s, R: %s", str(item), str(adds), str(rms))
        self.logger.debug("=== END Groups ===")
