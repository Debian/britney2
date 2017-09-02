from collections import namedtuple

SuiteInfo = namedtuple('SuiteInfo', [
    'name',
    'path',
    'excuses_suffix',
])


class SourcePackage(object):

    __slots__ = ['version', 'section', 'binaries', 'maintainer', 'is_fakesrc', 'testsuite', 'testsuite_triggers']

    def __init__(self, version, section, binaries, maintainer, is_fakesrc, testsuite, testsuite_triggers):
        self.version = version
        self.section = section
        self.binaries = binaries
        self.maintainer = maintainer
        self.is_fakesrc = is_fakesrc
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
