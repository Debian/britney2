from collections import namedtuple
from enum import Enum, unique


@unique
class SuiteClass(Enum):

    TARGET_SUITE = (False, False)
    PRIMARY_SOURCE_SUITE = (True, True)
    ADDITIONAL_SOURCE_SUITE = (True, False)

    @property
    def is_source(self):
        return self.value[0]

    @property
    def is_target(self):
        return not self.is_source

    @property
    def is_primary_source(self):
        return self is SuiteClass.PRIMARY_SOURCE_SUITE

    @property
    def is_additional_source(self):
        return self is SuiteClass.ADDITIONAL_SOURCE_SUITE


class Suite(object):

    def __init__(self, suite_class, name, path, suite_short_name=None):
        self.suite_class = suite_class
        self.name = name
        self.path = path
        self.suite_short_name = suite_short_name if suite_short_name else ''
        self.sources = {}
        self.binaries = {}

    @property
    def excuses_suffix(self):
        return self.suite_short_name


class Suites(object):

    def __init__(self, target_suite, source_suites):
        self._suites = {}
        self._by_name_or_alias = {}
        self.target_suite = target_suite
        self.source_suites = source_suites
        self._suites[target_suite.name] = target_suite
        self._by_name_or_alias[target_suite.name] = target_suite
        if target_suite.suite_short_name:
            self._by_name_or_alias[target_suite.suite_short_name] = target_suite
        for suite in source_suites:
            self._suites[suite.name] = suite
            self._by_name_or_alias[suite.name] = suite
            if suite.suite_short_name:
                self._by_name_or_alias[suite.suite_short_name] = suite

    @property
    def primary_source_suite(self):
        return self.source_suites[0]

    @property
    def by_name_or_alias(self):
        return self._by_name_or_alias

    @property
    def additional_source_suites(self):
        return self.source_suites[1:]

    def __getitem__(self, item):
        return self._suites[item]

    def __len__(self):
        return len(self.source_suites) + 1

    def __contains__(self, item):
        return item in self._suites

    def __iter__(self):
        # Sources first (as we will rely on this for loading data in the old live-data tests)
        yield from self.source_suites
        yield self.target_suite


class SourcePackage(object):

    __slots__ = ['version', 'section', 'binaries', 'maintainer', 'is_fakesrc', 'build_deps_arch', 'testsuite', 'testsuite_triggers']

    def __init__(self, version, section, binaries, maintainer, is_fakesrc, build_deps_arch, testsuite, testsuite_triggers):
        self.version = version
        self.section = section
        self.binaries = binaries
        self.maintainer = maintainer
        self.is_fakesrc = is_fakesrc
        self.build_deps_arch = build_deps_arch
        self.testsuite = testsuite
        self.testsuite_triggers = testsuite_triggers

    def __getitem__(self, item):
        return getattr(self, self.__slots__[item])


BinaryPackageId = namedtuple('BinaryPackageId', [
    'package_name',
    'version',
    'architecture',
])

BinaryPackage = namedtuple('BinaryPackage', [
    'version',
    'section',
    'source',
    'source_version',
    'architecture',
    'multi_arch',
    'depends',
    'conflicts',
    'provides',
    'is_essential',
    'pkg_id',
])
