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

import apt_pkg
import logging
from britney2 import SuiteClass


class MigrationItem(object):

    def __init__(self, package=None, version=None, architecture=None, uvname=None, suite=None, is_cruft_removal=False):
        self._uvname = uvname
        self._package = package
        self._version = version
        self._architecture = architecture
        self._suite = suite
        self._is_cruft_removal = is_cruft_removal
        if version is not None:
            self._name = "%s/%s" % (uvname, version)
        else:
            self._name = uvname

    def __str__(self):
        if self.version is not None:
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

    @property
    def uvname(self):
        return self._uvname

    @property
    def is_cruft_removal(self):
        return self._is_cruft_removal


class MigrationItemFactory(object):

    def __init__(self, suites):
        self._suites = suites
        self._all_architectures = frozenset(suites.target_suite.binaries)
        logger_name = ".".join((self.__class__.__module__, self.__class__.__name__))
        self.logger = logging.getLogger(logger_name)

    def generate_removal_for_cruft_item(self, pkg_id):
        uvname = "-%s/%s" % (pkg_id.package_name, pkg_id.architecture)
        return MigrationItem(package=pkg_id.package_name,
                             version=pkg_id.version,
                             architecture=pkg_id.architecture,
                             uvname=uvname,
                             suite=self._suites.target_suite,
                             is_cruft_removal=True,
                             )

    @staticmethod
    def _is_right_version(suite, package_name, expected_version):
        if package_name not in suite.sources:
            return False

        actual_version = suite.sources[package_name].version
        if apt_pkg.version_compare(actual_version, expected_version) != 0:
            return False

        return True

    def _find_suite_for_item(self, suites, suite_name, package_name, version, auto_correct):
        suite = suites.by_name_or_alias[suite_name]
        assert suite.suite_class != SuiteClass.TARGET_SUITE
        if version is not None and auto_correct and not self._is_right_version(suite, package_name, version):
            for s in suites.source_suites:
                if self._is_right_version(s, package_name, version):
                    suite = s
                    break
        return suite

    def parse_item(self, item_text, versioned=True, auto_correct=True):
        """

        :param item_text: The string describing the item (e.g. "glibc/2.5")
        :param versioned: If true, a two-part item is assumed to be versioned.
          otherwise, it is assumed to be versionless.  This determines how
          items like "foo/bar" is parsed (if versioned, "bar" is assumed to
          be a version and otherwise "bar" is assumed to be an architecture).
          If in doubt, use versioned=True with auto_correct=True and the
          code will figure it out on its own.
        :param auto_correct: If True, minor issues are automatically fixed
          where possible. This includes handling architecture and version
          being in the wrong order and missing/omitting a suite reference
          for items.  This feature is useful for migration items provided
          by humans (e.g. via hints) to avoid rejecting the input over
          trivial/minor issues with the input.
          When False, there will be no attempt to correct the migration
          input.
        :return: A MigrationItem matching the spec
        """
        suites = self._suites
        version = None
        architecture = None
        is_removal = False
        if item_text.startswith('-'):
            item_text = item_text[1:]
            is_removal = True
        parts = item_text.split('/', 3)
        package_name = parts[0]
        suite_name = suites.primary_source_suite.name
        if '_' in package_name:
            package_name, suite_name = package_name.split('_', 2)

        if len(parts) == 3:
            architecture = parts[1]
            version = parts[2]
        elif len(parts) == 2:
            if versioned:
                version = parts[1]
            else:
                architecture = parts[1]

        if auto_correct and version in self._all_architectures:
            (architecture, version) = (version, architecture)

        if architecture is None:
            architecture = 'source'

        if '_' in architecture:
            architecture, suite_name = architecture.split('_', 2)

        if is_removal:
            suite = suites.target_suite
        else:
            suite = self._find_suite_for_item(suites, suite_name, package_name, version, auto_correct)

        uvname = self._canonicalise_uvname(item_text, package_name, architecture, suite, is_removal)

        return MigrationItem(package=package_name,
                             version=version,
                             architecture=architecture,
                             uvname=uvname,
                             suite=suite,
                             )

    def parse_items(self, *args, **kwargs):
        return [self.parse_item(x, **kwargs) for x in args]

    @staticmethod
    def _canonicalise_uvname(item_text_sans_removal, package, architecture, suite, is_removal):
        parts = item_text_sans_removal.split('/', 3)
        if len(parts) == 1 or architecture == 'source':
            uvname = package
        else:
            uvname = "%s/%s" % (package, architecture)
        if suite.suite_class.is_additional_source:
            uvname = '%s_%s' % (uvname, suite.suite_short_name)
        if is_removal:
            uvname = '-%s' % (uvname)
        return uvname
