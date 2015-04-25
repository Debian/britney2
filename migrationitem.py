# -*- coding: utf-8 -*-

# Copyright (C) 2011 Adam D. Barratt <adsb@debian.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

class MigrationItem(object):
    _architectures = []

    @classmethod
    def set_architectures(cls, architectures = None):
        cls._architectures = architectures or []

    @classmethod
    def get_architectures(cls):
        return cls._architectures

    def __init__(self, name = None, versionned = True):
        self._name = None
        self._uvname = None
        self._package = None
        self._version = None
        self._architecture = None
        self._suite = None
        self._versionned = versionned

        if name:
            self.name = name

    def __str__(self):
        if self._versionned and self.version is not None:
            return self.name
        else:
            return self.uvname

    def __eq__(self, other):
        isequal = False
        if self.uvname == other.uvname:
            if self.version is None or other.version is None:
                isequal = True
            else:
                isequal = self.version == other.version

        return isequal

    def __hash__(self):
        return hash((self.uvname, self.version))

    def __lt__(self, other):
        return (self.uvname, self.version) < (other.uvname, other.version)

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._version = None
        self._name = value
        if value.startswith('-'):
            value = value[1:]
        parts = value.split('/', 3)
        package = parts[0]
        if '_' in package:
            self._package, self._suite = package.split('_', 2)
        else:
            self._package, self._suite = (package, 'unstable')
        if self._versionned and len(parts) > 1:
            if len(parts) == 3:
                self._architecture = parts[1]
                self._version = parts[2]
            else:
                self._architecture = 'source'
                self._version = parts[1]
        else:
            if len(parts) >= 2:
                self._architecture = parts[1]
            else:
                self._architecture = 'source'

        if self._version in self.__class__.get_architectures():
            (self._architecture, self._version) = \
            (self._version, self._architecture)

        if '_' in self._architecture:
            self._architecture, self._suite = \
               self._architecture.split('_', 2)

        if self.is_removal:
            self._suite = 'testing'

        self._canonicalise_name()

    def _canonicalise_name(self):
        parts = self._name.split('/', 3)
        is_removal = self.is_removal
        if len(parts) == 1 or self._architecture == 'source':
            self._uvname = self._package
        else:
            self._uvname = "%s/%s" % (self._package, self._architecture)
        if self._suite not in ('testing', 'unstable'):
            self._uvname = '%s_%s' % (self._uvname, self._suite)
        if is_removal:
            self._uvname = '-%s' % (self._uvname)
        if self._versionned:
            self._name = '%s/%s' % (self._uvname, self._version)
        else:
            self._name = self._uvname

    @property
    def is_removal(self):
        return self._name.startswith('-')

    @property
    def architecture(self):
        return self._architecture

    @property
    def package(self):
        return self._package

    @property
    def suite(self):
        return self._suite

    @suite.setter
    def suite(self, value):
        self._suite = value
        self._canonicalise_name()

    @property
    def version(self):
        return self._version

    @property
    def uvname(self):
        return self._uvname

class UnversionnedMigrationItem(MigrationItem):
    def __init__(self, name = None):
        MigrationItem.__init__(self, name = name, versionned = False)
