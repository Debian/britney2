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

class MigrationItem:
    def __init__(self, name = None):
        self._name = None
        self._version = None
        self._architecture = None
        self._suite = None

        if name:
            self._set_name(name)

    def _get_name(self):
        return self._name

    def _set_name(self, value):
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
        if len(parts) == 2:
            self._architecture = parts[1]
        else:
            self._architecture = 'source'

        if '_' in self._architecture:
            self_architecture, self._suite = \
               self._architecture.split('_', 2)

        if self.is_removal:
            self._suite = 'testing'
	    
    name = property(_get_name, _set_name)

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

    @property
    def version(self):
        return self._version
