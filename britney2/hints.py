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

import logging

from itertools import chain

from britney2.migrationitem import MigrationItem


class MalformedHintException(Exception):
    pass


class HintCollection(object):
    def __init__(self):
        self._hints = []

    @property
    def is_empty(self):
        return not self._hints

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

    def add_hint(self, hint):
        self._hints.append(hint)


class Hint(object):
    NO_VERSION = [ 'block', 'block-all', 'block-udeb' ]

    def __init__(self, user, hint_type, packages):
        self._user = user
        self._active = True
        self._type = hint_type
        self._packages = packages

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
        if self.type in self.__class__.NO_VERSION:
            return '%s %s' % (self._type, ' '.join(x.uvname for x in self._packages))
        else:
            return '%s %s' % (self._type, ' '.join(x.name for x in self._packages))

    def __eq__(self, other):
        if self.type != other.type:
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


def split_into_one_hint_per_package(hints, who, hint_name, *args):
    for package in args:
        hints.add_hint(Hint(who, hint_name, package))


def single_hint_taking_list_of_packages(hints, who, hint_type, *args):
    hints.add_hint(Hint(who, hint_type, args))


class HintParser(object):

    def __init__(self):
        logger_name = ".".join((self.__class__.__module__, self.__class__.__name__))
        self.logger = logging.getLogger(logger_name)
        self.hints = HintCollection()
        self._hint_table = {
            'remark': (0, lambda *x: None),

            # Migration grouping hints
            'easy': (2, single_hint_taking_list_of_packages), # Easy needs at least 2 to make sense
            'force-hint': (1, single_hint_taking_list_of_packages),
            'hint': (1, single_hint_taking_list_of_packages),

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

    @property
    def registered_hints(self):
        """A set of all known hints (and aliases thereof)"""
        return set(chain(self._hint_table.keys(), self._aliases.keys()))

    def register_hint_type(self, hint_name, parser_function, *, min_args=1, aliases=None):
        """Register a new hint that is supported by the parser

        This registers a new hint that can be parsed by the hint parser.  All hints are single words with a
        space-separated list of arguments (on a single line).  The hint parser will do some basic processing,
        the permission checking and minor validation on the hint before passing it on to the parser function
        given.

        The parser_function will receive the following arguments:
         * A hint collection
         * Identifier of the entity providing the hint
         * The hint_name (aliases will be mapped to the hint_name)
         * Zero or more string arguments for the hint (so the function needs to use *args)

        The parser_function will then have to process the arguments and call the hint collection's "add_hint"
        as needed.  Example implementations include "split_into_one_hint_per_package", which is used by almost
        all policy hints.

        :param hint_name: The name of the hint
        :param parser_function: A function to add the hint
        :param min_args: An optional positive integer (non-zero) denoting the number of arguments the hint takes.
        :param aliases: An optional iterable of aliases to the hint (use only for backwards compatibility)
        """
        if min_args < 1:
            raise ValueError("min_args must be at least 1")
        if hint_name in self._hint_table:
            raise ValueError("The hint type %s is already registered" % hint_name)
        if hint_name in self._aliases:
            raise ValueError("The hint type %s is already registered as an alias of %s" % (
                hint_name, self._aliases[hint_name]))
        self._hint_table[hint_name] = (min_args, parser_function)
        if aliases:
            for alias in aliases:
                self._aliases[alias] = hint_name

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
                self.logger.warning("Unknown hint found in %s (line %d): '%s'", filename, line_no, line)
                continue
            if hint_name not in permitted_hints and 'ALL' not in permitted_hints:
                reason = 'The hint is not a part of the permitted hints for ' + who
                self.logger.info("Ignoring \"%s\" hint from %s found in %s (line %d): %s",
                                 hint_name, who, filename, line_no, reason)
                continue
            min_args, hint_parser_impl = hint_table[hint_name]
            if len(l) - 1 < min_args:
                self.logger.warning("Malformed hint found in %s (line %d): Needs at least %d argument(s), got %d",
                                    filename, line_no, min_args, len(l) - 1)
                continue
            try:
                hint_parser_impl(hints, who, *l)
            except MalformedHintException as e:
                self.logger.warning("Malformed hint found in %s (line %d): \"%s\"", filename, line_no, e.args[0])
                continue
