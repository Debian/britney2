# This file is merged from Debian's tests and Ubuntu's autopktest implementation
# For Ubuntu's part Canonical is the original copyright holder.
#
# (C) 2015 Canonical Ltd.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

## Debian's part
from britney2 import BinaryPackageId
from britney2.installability.builder import InstallabilityTesterBuilder

TEST_HINTER = 'test-hinter'
HINTS_ALL = ('ALL')
DEFAULT_URGENCY = 'medium'

## autopkgtest part
import os
import shutil
import subprocess
import tempfile
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

architectures = ['amd64', 'arm64', 'armhf', 'i386', 'powerpc', 'ppc64el']
##


def new_pkg_universe_builder():
    return UniverseBuilder()


class MockObject(object):

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class PkgUniversePackageBuilder(object):

    def __init__(self, uni_builder, pkg_id):
        self._uni_builder = uni_builder
        self._pkg_id = pkg_id
        self._dependencies = set()
        self._conflicts = set()
        self._in_testing = True
        self._is_essential = False

    def is_essential(self):
        self._is_essential = True
        return self

    def in_testing(self):
        self._in_testing = True
        return self

    def not_in_testing(self):
        self._in_testing = False
        return self

    def depends_on(self, pkg):
        return self.depends_on_any_of(pkg)

    def depends_on_any_of(self, *pkgs):
        self._dependencies.add(frozenset(self._uni_builder._fetch_pkg_id(x) for x in pkgs))
        return self

    def conflicts_with(self, *pkgs):
        self._conflicts.update(self._uni_builder._fetch_pkg_id(x) for x in pkgs)
        return self

    def new_package(self, *args, **kwargs):
        return self._uni_builder.new_package(*args, **kwargs)

    @property
    def pkg_id(self):
        return self._pkg_id

    def universe_builder(self):
        return self._uni_builder

    def build(self, *args, **kwargs):
        return self._uni_builder.build(*args, **kwargs)


class UniverseBuilder(object):

    def __init__(self):
        self._cache = {}
        self._packages = {}
        self._default_version = '1.0-1'
        self._default_architecture = 'amd64'

    def _fetch_pkg_id(self, pkgish, version=None, architecture=None):
        if pkgish in self._cache:
            return self._cache[pkgish]
        if version is None:
            version = self._default_version
        if architecture is None:
            architecture = self._default_architecture
        if type(pkgish) == str:
            pkg_id = BinaryPackageId(pkgish, version, architecture)
        elif type(pkgish) == tuple:
            if len(pkgish) == 2:
                pkg_id = BinaryPackageId(pkgish[0], pkgish[1], architecture)
            else:
                pkg_id = BinaryPackageId(*pkgish)
        elif isinstance(pkgish, PkgUniversePackageBuilder):
            pkg_id = pkgish._pkg_id
        else:
            raise ValueError("No clue on how to convert %s into a package id" % pkgish)
        self._cache[pkg_id] = pkg_id
        return pkg_id

    def new_package(self, raw_pkg_id_or_pkg, *, version=None, architecture=None):
        pkg_id = self._fetch_pkg_id(raw_pkg_id_or_pkg, version=version, architecture=architecture)
        pkg_builder = PkgUniversePackageBuilder(self, pkg_id)
        if pkg_id in self._packages:
            raise ValueError("Package %s already added previously" % pkg_id)
        self._packages[pkg_id] = pkg_builder
        return pkg_builder

    def build(self):
        builder = InstallabilityTesterBuilder()
        for pkg_id, pkg_builder in self._packages.items():
            builder.add_binary(pkg_id,
                               essential=pkg_builder._is_essential,
                               in_testing=pkg_builder._in_testing,
                               )
            with builder.relation_builder(pkg_id) as rel:
                for or_clause in pkg_builder._dependencies:
                    rel.add_dependency_clause(or_clause)
                for break_pkg_id in pkg_builder._conflicts:
                    rel.add_breaks(break_pkg_id)
        return builder.build()

    def pkg_id(self, pkgish):
        return self._fetch_pkg_id(pkgish)

    def update_package(self, pkgish):
        pkg_id = self._fetch_pkg_id(pkgish)
        if pkg_id not in self._packages:
            raise ValueError("Package %s has not been added yet" % pkg_id)
        return self._packages[pkg_id]

# autopkgtest classes
class TestData:

    def __init__(self):
        '''Construct local test package indexes.

        The archive is initially empty. You can create new packages with
        create_deb(). self.path contains the path of the archive, and
        self.apt_source provides an apt source "deb" line.

        It is kept in a temporary directory which gets removed when the Archive
        object gets deleted.
        '''
        self.path = tempfile.mkdtemp(prefix='testarchive.')
        self.apt_source = 'deb file://%s /' % self.path
        self.suite_testing = 'testing'
        self.suite_unstable = 'unstable'
        self.compute_migrations = ''
        self.dirs = {False: os.path.join(self.path, 'data', self.suite_testing),
                     True: os.path.join(self.path, 'data', self.suite_unstable)}
        os.makedirs(self.dirs[False])
        os.mkdir(self.dirs[True])
        self.added_sources = {False: set(), True: set()}
        self.added_binaries = {False: set(), True: set()}

        # pre-create all files for all architectures
        for arch in architectures:
            for dir in self.dirs.values():
                with open(os.path.join(dir, 'Packages_' + arch), 'w'):
                    pass
        for dir in self.dirs.values():
            for fname in ['Dates', 'Blocks', 'Urgency', 'BugsV']:
                with open(os.path.join(dir, fname), 'w'):
                    pass
        os.mkdir(os.path.join(self.path, 'data', 'hints'))
        shutil.copytree(os.path.join(PROJECT_DIR, 'tests', 'policy-test-data', 'piuparts', 'basic'), os.path.join(self.dirs[False], 'state'))

        os.mkdir(os.path.join(self.path, 'output'))

        # create temporary home dir for proposed-migration autopktest status
        self.home = os.path.join(self.path, 'home')
        os.environ['HOME'] = self.home
        os.makedirs(os.path.join(self.home, 'proposed-migration',
                                 'autopkgtest', 'work'))

    def __del__(self):
        shutil.rmtree(self.path)

    def add(self, name, unstable, fields={}, add_src=True, testsuite=None, srcfields=None):
        '''Add a binary package to the index file.

        You need to specify at least the package name and in which list to put
        it (unstable==True for unstable/proposed, or False for
        testing/release). fields specifies all additional entries, e. g.
        {'Depends': 'foo, bar', 'Conflicts: baz'}. There are defaults for most
        fields.

        Unless add_src is set to False, this will also automatically create a
        source record, based on fields['Source'] and name. In that case, the
        "Testsuite:" field is set to the testsuite argument.
        '''
        assert (name not in self.added_binaries[unstable])
        self.added_binaries[unstable].add(name)

        fields.setdefault('Architecture', 'any')
        fields.setdefault('Version', '1')
        fields.setdefault('Priority', 'optional')
        fields.setdefault('Section', 'devel')
        fields.setdefault('Description', 'test pkg')
        if fields['Architecture'] == 'any':
            fields_local_copy = fields.copy()
            for a in architectures:
                fields_local_copy['Architecture'] = a
                self._append(name, unstable, 'Packages_' + a, fields_local_copy)
        elif fields['Architecture'] == 'all':
            for a in architectures:
                self._append(name, unstable, 'Packages_' + a, fields)
        else:
            self._append(name, unstable, 'Packages_' + fields['Architecture'],
                         fields)

        if add_src:
            src = fields.get('Source', name)
            if src not in self.added_sources[unstable]:
                if srcfields is None:
                    srcfields = {}
                srcfields['Version'] = fields['Version']
                srcfields['Section'] = fields['Section']
                if testsuite:
                    srcfields['Testsuite'] = testsuite
                self.add_src(src, unstable, srcfields)

    def add_src(self, name, unstable, fields={}):
        '''Add a source package to the index file.

        You need to specify at least the package name and in which list to put
        it (unstable==True for unstable/proposed, or False for
        testing/release). fields specifies all additional entries, which can be
        Version (default: 1), Section (default: devel), Testsuite (default:
        none), and Extra-Source-Only.
        '''
        assert (name not in self.added_sources[unstable])
        self.added_sources[unstable].add(name)

        fields.setdefault('Version', '1')
        fields.setdefault('Section', 'devel')
        self._append(name, unstable, 'Sources', fields)

    def _append(self, name, unstable, file_name, fields):
        with open(os.path.join(self.dirs[unstable], file_name), 'a') as f:
            f.write('''Package: %s
Maintainer: Joe <joe@example.com>
''' % name)

            for k, v in fields.items():
                f.write('%s: %s\n' % (k, v))
            f.write('\n')

    def remove_all(self, unstable):
        '''Remove all added packages'''

        self.added_binaries[unstable] = set()
        self.added_sources[unstable] = set()
        for a in architectures:
            open(os.path.join(self.dirs[unstable], 'Packages_' + a), 'w').close()
        open(os.path.join(self.dirs[unstable], 'Sources'), 'w').close()

    def add_default_packages(self, libc6=True, green=True, lightgreen=True, darkgreen=True, blue=True, black=True, grey=True):
        '''To avoid duplication, add packages we need all the time'''

        # libc6 (always)
        self.add('libc6', False)
        if (libc6 is True):
            self.add('libc6', True)

        # src:green
        self.add('libgreen1', False, {'Source': 'green',
                                          'Depends': 'libc6 (>= 0.9)'},
                      testsuite='autopkgtest')
        if (green is True):
            self.add('libgreen1', True, {'Source': 'green',
                                              'Depends': 'libc6 (>= 0.9)'},
                          testsuite='autopkgtest')
        self.add('green', False, {'Depends': 'libc6 (>= 0.9), libgreen1',
                                       'Conflicts': 'blue'},
                      testsuite='autopkgtest')
        if (green is True):
            self.add('green', True, {'Depends': 'libc6 (>= 0.9), libgreen1',
                                           'Conflicts': 'blue'},
                          testsuite='autopkgtest')

        # lightgreen
        self.add('lightgreen', False, {'Depends': 'libgreen1'},
                      testsuite='autopkgtest')
        if (lightgreen is True):
            self.add('lightgreen', True, {'Depends': 'libgreen1'},
                          testsuite='autopkgtest')

        ## autodep8 or similar test
        # darkgreen
        self.add('darkgreen', False, {'Depends': 'libgreen1'},
                      testsuite='autopkgtest-pkg-foo')
        if (darkgreen is True):
            self.add('darkgreen', True, {'Depends': 'libgreen1'},
                          testsuite='autopkgtest-pkg-foo')

        # blue
        self.add('blue', False, {'Depends': 'libc6 (>= 0.9)',
                                      'Conflicts': 'green'},
                      testsuite='specialtest')
        if blue is True:
            self.add('blue', True, {'Depends': 'libc6 (>= 0.9)',
                                         'Conflicts': 'green'},
                          testsuite='specialtest')

        # black
        self.add('black', False, {},
                      testsuite='autopkgtest')
        if black is True:
            self.add('black', True, {},
                          testsuite='autopkgtest')

        # grey
        self.add('grey', False, {},
                      testsuite='autopkgtest')
        if grey is True:
            self.add('grey', True, {},
                          testsuite='autopkgtest')


class TestBase(unittest.TestCase):

    def setUp(self):
        super(TestBase, self).setUp()
        self.maxDiff = None
        self.data = TestData()
        self.britney = os.path.join(PROJECT_DIR, 'britney.py')
        # create temporary config so that tests can hack it
        self.britney_conf = os.path.join(self.data.path, 'britney.conf')
        with open(self.britney_conf, 'w') as f:
            f.write('''
TESTING           = data/testing
UNSTABLE          = data/unstable

NONINST_STATUS    = data/testing/non-installable-status
EXCUSES_OUTPUT    = output/excuses.html
EXCUSES_YAML_OUTPUT = output/excuses.yaml
UPGRADE_OUTPUT    = output/output.txt
HEIDI_OUTPUT      = output/HeidiResult

STATIC_INPUT_DIR  = data/testing/input
STATE_DIR         = data/testing/state

ARCHITECTURES     = amd64 arm64 armhf i386 powerpc ppc64el
NOBREAKALL_ARCHES = amd64 arm64 armhf i386 powerpc ppc64el
OUTOFSYNC_ARCHES  =
BREAK_ARCHES      =
NEW_ARCHES        =

MINDAYS_LOW       = 0
MINDAYS_MEDIUM    = 0
MINDAYS_HIGH      = 0
MINDAYS_CRITICAL  = 0
MINDAYS_EMERGENCY = 0
DEFAULT_URGENCY   = medium
NO_PENALTIES      = high critical emergency
BOUNTY_MIN_AGE    = 8

HINTSDIR = data/hints

HINTS_AUTOPKGTEST = ALL
HINTS_FREEZE      = block block-all block-udeb
HINTS_FREEZE-EXCEPTION = unblock unblock-udeb
HINTS_SATBRITNEY  = easy
HINTS_AUTO-REMOVALS = remove

SMOOTH_UPDATES    = badgers

IGNORE_CRUFT      = 0

REMOVE_OBSOLETE   = no

ADT_ENABLE        = yes
ADT_ARCHES        = amd64 i386
ADT_AMQP          = file://output/debci.input
ADT_PPAS          =
ADT_SHARED_RESULTS_CACHE =

ADT_SWIFT_URL     = http://localhost:18085
ADT_CI_URL        = https://autopkgtest.ubuntu.com/
ADT_HUGE          = 20

ADT_SUCCESS_BOUNTY     =
ADT_REGRESSION_PENALTY =
ADT_BASELINE           =
''')
        assert os.path.exists(self.britney)


    def tearDown(self):
        del self.data

    def run_britney(self, args=[]):
        '''Run britney.

        Assert that it succeeds and does not produce anything on stderr.
        Return (excuses.yaml, excuses.html, britney_out).
        '''
        britney = subprocess.Popen([self.britney, '-v', '-c', self.britney_conf,
                                   '%s' % self.data.compute_migrations],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   cwd=self.data.path,
                                   universal_newlines=True)
        (out, err) = britney.communicate()
        self.assertEqual(britney.returncode, 0, out + err)
        self.assertEqual(err, '')

        with open(os.path.join(self.data.path, 'output',
                               'excuses.yaml'), encoding='utf-8') as f:
            yaml = f.read()
        with open(os.path.join(self.data.path, 'output',
                               'excuses.html'), encoding='utf-8') as f:
            html = f.read()

        return (yaml, html, out)

    def create_hint(self, username, content):
        '''Create a hint file for the given username and content'''

        hints_path = os.path.join(
            self.data.path, 'data', 'hints', username)
        with open(hints_path, 'a') as fd:
            fd.write(content)
            fd.write('\n')
