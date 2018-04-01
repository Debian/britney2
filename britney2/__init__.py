from collections import namedtuple

SuiteInfo = namedtuple('SuiteInfo', [
    'name',
    'path',
    'excuses_suffix',
])


class Suites(object):

    def __init__(self, target_suite, source_suites):
        self._suites = {}
        self._by_name_or_alias = {}
        self.target_suite = target_suite
        self.source_suites = source_suites
        self._suites[target_suite.name] = target_suite
        self._by_name_or_alias[target_suite.name] = target_suite
        if target_suite.excuses_suffix:
            self._by_name_or_alias[target_suite.excuses_suffix] = target_suite
        for suite in source_suites:
            self._suites[suite.name] = suite
            self._by_name_or_alias[suite.name] = suite
            if suite.excuses_suffix:
                self._by_name_or_alias[suite.excuses_suffix] = suite

    @property
    def primary_source_suite(self):
        return self.source_suites[0]

    @property
    def by_name_or_alias(self):
        return self._by_name_or_alias

    def __getitem__(self, item):
        return self._suites[item]

    def __len__(self):
        return len(self.source_suites) + 1

    def __iter__(self):
        yield from self._suites


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
