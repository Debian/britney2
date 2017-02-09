from britney2 import BinaryPackageId
from britney2.installability.builder import InstallabilityTesterBuilder

TEST_HINTER = 'test-hinter'
HINTS_ALL = ('ALL')
DEFAULT_URGENCY = 'medium'


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
