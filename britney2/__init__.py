import logging
from collections import namedtuple
from enum import Enum, unique


class DependencyType(Enum):
    DEPENDS = ('Depends', 'depends', 'dependency')
    # BUILD_DEPENDS includes BUILD_DEPENDS_ARCH
    BUILD_DEPENDS = ('Build-Depends(-Arch)', 'build-depends', 'build-dependency')
    BUILD_DEPENDS_INDEP = ('Build-Depends-Indep', 'build-depends-indep', 'build-dependency (indep)')
    BUILT_USING = ('Built-Using', 'built-using', 'built-using')

    def __str__(self):
        return self.value[0]

    def get_reason(self):
        return self.value[1]

    def get_description(self):
        return self.value[2]


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
        self._binaries = {}
        self.provides_table = {}
        self._all_binaries_in_suite = None

    @property
    def excuses_suffix(self):
        return self.suite_short_name

    @property
    def binaries(self):
        return self._binaries

    @binaries.setter
    def binaries(self, binaries):
        self._binaries = binaries
        self._all_binaries_in_suite = {x.pkg_id: x for a in binaries for x in binaries[a].values()}

    def any_of_these_are_in_the_suite(self, pkgs):
        """Test if at least one package of a given set is in the suite

        :param pkgs: A set of BinaryPackageId
        :return: True if any of the packages in pkgs are currently in the suite
        """
        return not self._all_binaries_in_suite.isdisjoint(pkgs)

    def is_pkg_in_the_suite(self, pkg_id):
        """Test if the package of is in testing

        :param pkg_id: A BinaryPackageId
        :return: True if the pkg is currently in the suite
        """
        return pkg_id in self._all_binaries_in_suite


class TargetSuite(Suite):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inst_tester = None
        logger_name = ".".join((self.__class__.__module__, self.__class__.__name__))
        self._logger = logging.getLogger(logger_name)

    def any_of_these_are_in_the_suite(self, pkg_ids):
        """Test if at least one package of a given set is in the suite

        :param pkg_ids: A set of BinaryPackageId
        :return: True if any of the packages in pkgs are currently in the suite
        """
        return self.inst_tester.any_of_these_are_in_the_suite(pkg_ids)

    def is_pkg_in_the_suite(self, pkg_id):
        """Test if the package of is in testing

        :param pkg_id: A BinaryPackageId
        :return: True if the pkg is currently in the suite
        """
        return self.inst_tester.is_pkg_in_the_suite(pkg_id)

    def is_installable(self, pkg_id):
        """Determine whether the given package can be installed in the suite

        :param pkg_id: A BinaryPackageId
        :return: True if the pkg is currently installable in the suite
        """
        return self.inst_tester.is_installable(pkg_id)

    def add_binary(self, pkg_id):
        """Add a binary package to the suite

        If the package is not known, this method will throw an
        KeyError.

        :param pkg_id The id of the package
        """
        self.inst_tester.add_binary(pkg_id)

    def remove_binary(self, pkg_id):
        """Remove a binary from the suite

        :param pkg_id The id of the package
        If the package is not known, this method will throw an
        KeyError.
        """
        self.inst_tester.remove_binary(pkg_id)

    def check_suite_source_pkg_consistency(self, comment):
        sources_t = self.sources
        binaries_t = self.binaries
        logger = self._logger
        issues_found = False

        logger.info("check_target_suite_source_pkg_consistency %s", comment)

        for arch in binaries_t:
            for pkg_name in binaries_t[arch]:
                pkg = binaries_t[arch][pkg_name]
                src = pkg.source

                if src not in sources_t:  # pragma: no cover
                    issues_found = True
                    logger.error("inconsistency found (%s): src %s not in target, target has pkg %s with source %s" % (
                        comment, src, pkg_name, src))

        for src in sources_t:
            source_data = sources_t[src]
            for pkg_id in source_data.binaries:
                binary, _, parch = pkg_id
                if binary not in binaries_t[parch]:  # pragma: no cover
                    issues_found = True
                    logger.error("inconsistency found (%s): binary %s from source %s not in binaries_t[%s]" % (
                        comment, binary, src, parch))

        if issues_found:  # pragma: no cover
            raise AssertionError("inconsistencies found in target suite")


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

    __slots__ = ['version', 'section', 'binaries', 'maintainer', 'is_fakesrc', 'build_deps_arch', 'build_deps_indep',
                 'testsuite', 'testsuite_triggers']

    def __init__(self, version, section, binaries, maintainer, is_fakesrc, build_deps_arch, build_deps_indep,
                 testsuite, testsuite_triggers):
        self.version = version
        self.section = section
        self.binaries = binaries
        self.maintainer = maintainer
        self.is_fakesrc = is_fakesrc
        self.build_deps_arch = build_deps_arch
        self.build_deps_indep = build_deps_indep
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
    'builtusing',
])
