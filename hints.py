# -*- coding: utf-8 -*-

# Copyright (C) 2013 Adam D. Barratt <adsb@debian.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

from __future__ import print_function

from migrationitem import MigrationItem

class HintCollection(object):
    def __init__(self):
        self._hints = []

    def __getitem__(self, type=None):
        return self.search(type)

    def search(self, type=None, onlyactive=True, package=None, \
       version=None, removal=None):

        return [ hint for hint in self._hints if
                 (type is None or type == hint.type) and
                 (hint.active or not onlyactive) and
                 (package is None or package == hint.packages[0].package) and
                 (version is None or version == hint.packages[0].version) and
                 (removal is None or removal == hint.packages[0].is_removal)
               ]

    def add_hint(self, hint, user):
        try:
            self._hints.append(Hint(hint, user))
        except AssertionError:
            print("Ignoring broken hint %r from %s" % (hint, user))

class Hint(object):
    NO_VERSION = [ 'block', 'block-all', 'block-udeb' ]

    def __init__(self, hint, user):
        self._hint = hint
        self._user = user
        self._active = True
        self._days = None
        if isinstance(hint, list):
            self._type = hint[0]
            self._packages = hint[1:]
        else:
            self._type, self._packages = hint.split(' ', 1)

        if self._type == 'age-days':
            if isinstance(hint, list):
                self._days = self._packages[0]
                self._packages = self._packages[1:]
            else:
                self._days, self._packages = self._packages.split(' ', 1)

        if isinstance(self._packages, str):
            self._packages = self._packages.split(' ')

        self._packages = [MigrationItem(x) for x in self._packages]
        
        self.check()
        
    def check(self):
        for package in self.packages:
            if self.type in self.__class__.NO_VERSION:
                assert package.version is None, package
            else:
                assert package.version is not None, package

    def set_active(self, active):
        self._active = active

    def __str__(self):
        return self._hint

    def __eq__(self, other):
        if self.type != other.type:
            return False
        elif self.type == 'age-days' and self.days != other.days:
            return False
        else:
            return frozenset(self.packages) == frozenset(other.packages)

    @property
    def type(self):
        return self._type

    @property
    def packages(self):
        return self._packages

    @property
    def active(self):
        return self._active

    @property
    def user(self):
        return self._user

    @property
    def days(self):
        return self._days

    @property
    def package(self):
        if self.packages:
            assert len(self.packages) == 1, self.packages
            return self.packages[0].package
        else:
            return None

    @property
    def version(self):
        if self.packages:
            assert len(self.packages) == 1, self.packages
            return self.packages[0].version
        else:
            return None

