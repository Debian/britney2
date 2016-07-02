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


class MalformedHintException(Exception):
    pass


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

    def add_hint(self, user, hint):
        self._hints.append(Hint(user, hint))


class Hint(object):
    NO_VERSION = [ 'block', 'block-all', 'block-udeb' ]

    def __init__(self, user, hint):
        self._hint = hint
        self._user = user
        self._active = True
        self._days = None
        if isinstance(hint, list) or isinstance(hint, tuple):
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
                if package.version is not None:
                    raise MalformedHintException("\"%s\" needs unversioned packages, got \"%s\"" % (self.type, package))
            else:
                if package.version is None:
                    raise MalformedHintException("\"%s\" needs versioned packages, got \"%s\"" % (self.type, package))

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


def age_day_hint(hints, who, hint_name, new_age, *args):
    for package in args:
        h = [hint_name, new_age] + package.split(' ')
        hints.add_hint(who, h)


def split_into_one_hint_per_package(hints, who, hint_name, *args):
    for package in args:
        hints.add_hint(who, [hint_name, package])


def single_hint_taking_list_of_packages(hints, who, *args):
    hints.add_hint(who, args)


class HintParser(object):

    def __init__(self, britney):
        self._britney = britney
        self.hints = HintCollection()
        self._hint_table = {
            'remark': (0, lambda *x: None),

            # Migration grouping hints
            'easy': (2, single_hint_taking_list_of_packages), # Easy needs at least 2 to make sense
            'force-hint': (1, single_hint_taking_list_of_packages),
            'hint': (1, single_hint_taking_list_of_packages),

            # Age / urgent
            'urgent': (1, split_into_one_hint_per_package),
            'age-days': (2, age_day_hint),

            # Block / freeze related hints
            'block': (1, split_into_one_hint_per_package),
            'block-all': (1, split_into_one_hint_per_package),
            'block-udeb': (1, split_into_one_hint_per_package),
            'unblock': (1, split_into_one_hint_per_package),
            'unblock-udeb': (1, split_into_one_hint_per_package),

            # Other
            'remove': (1, split_into_one_hint_per_package),
            'force': (1, split_into_one_hint_per_package),
        }
        self._aliases = {
            'approve': 'unblock',
        }

    def parse_hints(self, who, permitted_hints, filename, lines):
        hint_table = self._hint_table
        line_no = 0
        hints = self.hints
        aliases = self._aliases
        for line in lines:
            line = line.strip()
            line_no += 1
            if line == "" or line.startswith('#'):
                continue
            l = line.split()
            hint_name = l[0]
            if hint_name in aliases:
                hint_name = aliases[hint_name]
                l[0] = hint_name
            if hint_name == 'finished':
                break
            if hint_name not in hint_table:
                self.log("Unknown hint found in %s (line %d): '%s'" % (filename, line_no, line), type="W")
                continue
            if hint_name not in permitted_hints:
                reason = 'The hint is not a part of the permitted hints for ' + who
                self.log("Ignoring \"%s\" hint from %s found in %s (line %d): %s" % (
                    hint_name, who, filename, line_no, reason), type="I")
                continue
            min_args, hint_parser_impl = hint_table[hint_name]
            if len(l) - 1 < min_args:
                self.log("Malformed hint found in %s (line %d): Needs at least %d argument(s), got %d" % (
                    filename, line_no, min_args, len(l) - 1), type="W")
                continue
            try:
                hint_parser_impl(hints, who, *l)
            except MalformedHintException as e:
                self.log("Malformed hint found in %s (line %d): \"%s\"" % (
                    filename, line_no, e.args[0]), type="W")
                continue

    def log(self, msg, type="I"):
        self._britney.log(msg, type=type)
