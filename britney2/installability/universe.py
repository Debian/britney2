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


class BinaryPackageRelation(object):
    """All relations of a given binary package"""

    __slots__ = ['pkg_ids', 'dependencies', 'negative_dependencies', 'reverse_dependencies']

    def __init__(self, pkg_ids, dependencies, negative_dependencies, reverse_dependencies):
        self.pkg_ids = pkg_ids
        self.dependencies = dependencies
        self.negative_dependencies = negative_dependencies
        self.reverse_dependencies = reverse_dependencies


class BinaryPackageUniverse(object):
    """A "universe" of all binary packages and their relations

    The package universe is a read-only ("immutable") data structure
    that knows of all binary packages and their internal relations.
    The relations are either in Conjunctive Normal Form (CNF) represented
    via sets of sets of the package ids or simply sets of package ids.

    Being immutable, the universe does *not* track stateful data such
    as "which package is in what suite?" nor "is this package installable
    in that suite?".
    """

    def __init__(self, relations):
        self._relations = relations

    def dependencies_of(self, pkg_id):
        """Returns the set of dependencies of a given package

        :param pkg_id: The BinaryPackageId of a binary package.
        :return: A set containing the package ids all of the dependencies
        of the input package in CNF.
        """
        return self._relations[pkg_id].dependencies

    def negative_dependencies_of(self, pkg_id):
        """Returns the set of negative dependencies of a given package

        Note that there is no "reverse_negative_dependencies_of" method,
        since negative dependencies have no "direction" unlike positive
        dependencies.

        :param pkg_id: The BinaryPackageId of a binary package.
        :return: A set containing the package ids all of the negative
        dependencies of the input package.
        """
        return self._relations[pkg_id].negative_dependencies

    def reverse_dependencies_of(self, pkg_id):
        """Returns the set of reverse dependencies of a given package

        Note that a package is considered a reverse dependency of the
        given package as long as at least one of its dependency relations
        *could* be satisfied by the given package.

        :param pkg_id: The BinaryPackageId of a binary package.
        :return: A set containing the package ids all of the reverse
        dependencies of the input package.
        """
        return self._relations[pkg_id].reverse_dependencies

    def are_equivalent(self, pkg_id1, pkg_id2):
        """Test if pkg_id1 and pkg_id2 are equivalent

        :param pkg_id1 The id of the first package
        :param pkg_id2 The id of the second package
        :return: True if pkg_id1 and pkg_id2 have the same "signature" in
        the package dependency graph (i.e. relations can not tell
        them apart semantically except for their name). Otherwise False.

        Note that this can return True even if pkg_id1 and pkg_id2 can
        tell each other apart.
        """
        return pkg_id2 in self.packages_equivalent_to(pkg_id1)

    def packages_equivalent_to(self, pkg_id):
        """Determine which packages are equivalent to a given package

        :param pkg_id: The BinaryPackageId of a binary package.
        :return: A frozenset of all package ids that are equivalent to the
        input package.  Note that this set always includes the input
        package assuming it is a known package.
        """
        return self._relations[pkg_id].pkg_ids

    def relations_of(self, pkg_id):
        """Get the direct relations of a given packge

        :param pkg_id: The BinaryPackageId of a binary package.
        :return: A BinaryPackageRelation describing all known direct
        relations for the package.
        """
        return self._relations[pkg_id]

    def __contains__(self, pkg_id):
        return pkg_id in self._relations

    def __iter__(self):
        yield from self._relations
