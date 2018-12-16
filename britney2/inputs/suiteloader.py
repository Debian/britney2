from abc import abstractmethod
import apt_pkg
import logging
import os
import sys

from britney2 import SuiteClass, Suite, TargetSuite, Suites, BinaryPackage, BinaryPackageId, SourcePackage
from britney2.utils import (
    read_release_file, possibly_compressed, read_sources_file, create_provides_map, parse_provides
)


class MissingRequiredConfigurationError(RuntimeError):
    pass


class SuiteContentLoader(object):

    def __init__(self, base_config):
        self._base_config = base_config
        self._architectures = SuiteContentLoader.config_str_as_list(base_config.architectures)
        self._nobreakall_arches = SuiteContentLoader.config_str_as_list(base_config.nobreakall_arches, [])
        self._outofsync_arches = SuiteContentLoader.config_str_as_list(base_config.outofsync_arches, [])
        self._break_arches = SuiteContentLoader.config_str_as_list(base_config.break_arches, [])
        self._new_arches = SuiteContentLoader.config_str_as_list(base_config.new_arches, [])
        self._components = []
        self._all_binaries = {}
        logger_name = ".".join((self.__class__.__module__, self.__class__.__name__))
        self.logger = logging.getLogger(logger_name)

    @staticmethod
    def config_str_as_list(value, default_value=None):
        if value is None:
            return default_value
        if isinstance(value, str):
            return value.split()
        return value

    @property
    def architectures(self):
        return self._architectures

    @property
    def nobreakall_arches(self):
        return self._nobreakall_arches

    @property
    def outofsync_arches(self):
        return self._outofsync_arches

    @property
    def break_arches(self):
        return self._break_arches

    @property
    def new_arches(self):
        return self._new_arches

    @property
    def components(self):
        return self._components

    def all_binaries(self):
        return self._all_binaries

    @abstractmethod
    def load_suites(self):
        pass


class DebMirrorLikeSuiteContentLoader(SuiteContentLoader):

    CHECK_FIELDS = [
        'section',
        'source',
        'source_version',
        'architecture',
        'multi_arch',
        'depends',
        'conflicts',
        'provides',
    ]

    def load_suites(self):
        suites = []
        target_suite = None
        missing_config_msg = "Configuration %s is not set in the config (and cannot be auto-detected)"
        for suite in ('testing', 'unstable', 'pu', 'tpu'):
            suffix = suite if suite in {'pu', 'tpu'} else ''
            if hasattr(self._base_config, suite):
                suite_path = getattr(self._base_config, suite)
                suite_class = SuiteClass.TARGET_SUITE
                if suite != 'testing':
                    suite_class = SuiteClass.ADDITIONAL_SOURCE_SUITE if suffix else SuiteClass.PRIMARY_SOURCE_SUITE
                    suites.append(Suite(suite_class, suite, suite_path, suite_short_name=suffix))
                else:
                    target_suite = TargetSuite(suite_class, suite, suite_path, suite_short_name=suffix)
                    suites.append(target_suite)
            else:
                if suite in {'testing', 'unstable'}:  # pragma: no cover
                    self.logger.error(missing_config_msg, suite.upper())
                    raise MissingRequiredConfigurationError(missing_config_msg % suite.upper())
                # self.suite_info[suite] = SuiteInfo(name=suite, path=None, excuses_suffix=suffix)
                self.logger.info("Optional suite %s is not defined (config option: %s) ", suite, suite.upper())

        assert target_suite is not None

        self._check_release_file(target_suite, missing_config_msg)
        self._setup_architectures()

        # read the source and binary packages for the involved distributions.  Notes:
        # - Load testing last as some live-data tests have more complete information in
        #   unstable
        # - Load all sources before any of the binaries.
        for suite in suites:
            sources = self._read_sources(suite.path)
            suite.sources = sources
            (suite.binaries, suite.provides_table) = self._read_binaries(suite, self._architectures)

        return Suites(suites[0], suites[1:])

    def _setup_architectures(self):
        allarches = self._architectures
        # Re-order the architectures such as that the most important architectures are listed first
        # (this is to make the log easier to read as most important architectures will be listed
        #  first)
        arches = [x for x in allarches if x in self._nobreakall_arches]
        arches += [x for x in allarches if x not in arches and x not in self._outofsync_arches]
        arches += [x for x in allarches if x not in arches and x not in self._break_arches]
        arches += [x for x in allarches if x not in arches and x not in self._new_arches]
        arches += [x for x in allarches if x not in arches]

        # Intern architectures for efficiency; items in this list will be used for lookups and
        # building items/keys - by intern strings we reduce memory (considerably).
        self._architectures = [sys.intern(arch) for arch in allarches]

    def _check_release_file(self, target_suite, missing_config_msg):
        try:
            release_file = read_release_file(target_suite.path)
            self.logger.info("Found a Release file in %s - using that for defaults", target_suite.name)
        except FileNotFoundError:
            self.logger.info("The %s suite does not have a Release file.", target_suite.name)
            release_file = None

        if release_file is not None:
            self._components = release_file['Components'].split()
            self.logger.info("Using components listed in Release file: %s", ' '.join(self._components))

        if self._architectures is None:
            if release_file is None:
                self.logger.error("No configured architectures and there is no release file in the %s suite.",
                                  target_suite.name)
                self.logger.error("Please check if there is a \"Release\" file in %s",
                                  target_suite.path)
                self.logger.error("or if the config file contains a non-empty \"ARCHITECTURES\" field")
                raise MissingRequiredConfigurationError(missing_config_msg % "ARCHITECTURES")
            self._architectures = sorted(release_file['Architectures'].split())
            self.logger.info("Using architectures listed in Release file: %s", ' '.join(self._architectures))

    def _read_sources(self, basedir):
        """Read the list of source packages from the specified directory

        The source packages are read from the `Sources' file within the
        directory specified as `basedir' parameter. Considering the
        large amount of memory needed, not all the fields are loaded
        in memory. The available fields are Version, Maintainer and Section.

        The method returns a list where every item represents a source
        package as a dictionary.
        """

        if self._components:
            sources = {}
            for component in self._components:
                filename = os.path.join(basedir, component, "source", "Sources")
                filename = possibly_compressed(filename)
                self.logger.info("Loading source packages from %s", filename)
                read_sources_file(filename, sources)
        else:
            filename = os.path.join(basedir, "Sources")
            self.logger.info("Loading source packages from %s", filename)
            sources = read_sources_file(filename)

        return sources

    @staticmethod
    def merge_fields(get_field, *field_names, separator=', '):
        """Merge two or more fields (filtering out empty fields; returning None if all are empty)
        """
        return separator.join(filter(None, (get_field(x) for x in field_names))) or None

    def _read_packages_file(self, filename, arch, srcdist, packages=None, intern=sys.intern):
        self.logger.info("Loading binary packages from %s", filename)

        if packages is None:
            packages = {}

        all_binaries = self._all_binaries

        tag_file = apt_pkg.TagFile(filename)
        get_field = tag_file.section.get
        step = tag_file.step

        while step():
            pkg = get_field('Package')
            version = get_field('Version')

            # There may be multiple versions of any arch:all packages
            # (in unstable) if some architectures have out-of-date
            # binaries.  We only ever consider the package with the
            # largest version for migration.
            pkg = intern(pkg)
            version = intern(version)
            pkg_id = BinaryPackageId(pkg, version, arch)

            if pkg in packages:
                old_pkg_data = packages[pkg]
                if apt_pkg.version_compare(old_pkg_data.version, version) > 0:
                    continue
                old_pkg_id = old_pkg_data.pkg_id
                old_src_binaries = srcdist[old_pkg_data.source].binaries
                old_src_binaries.remove(old_pkg_id)
                # This may seem weird at first glance, but the current code rely
                # on this behaviour to avoid issues like #709460.  Admittedly it
                # is a special case, but Britney will attempt to remove the
                # arch:all packages without this.  Even then, this particular
                # stop-gap relies on the packages files being sorted by name
                # and the version, so it is not particularly resilient.
                if pkg_id not in old_src_binaries:
                    old_src_binaries.append(pkg_id)

            # Merge Pre-Depends with Depends and Conflicts with
            # Breaks. Britney is not interested in the "finer
            # semantic differences" of these fields anyway.
            deps = DebMirrorLikeSuiteContentLoader.merge_fields(get_field, 'Pre-Depends', 'Depends')
            conflicts = DebMirrorLikeSuiteContentLoader.merge_fields(get_field, 'Conflicts', 'Breaks')

            ess = False
            if get_field('Essential', 'no') == 'yes':
                ess = True

            source = pkg
            source_version = version
            # retrieve the name and the version of the source package
            source_raw = get_field('Source')
            if source_raw:
                source = intern(source_raw.split(" ")[0])
                if "(" in source_raw:
                    source_version = intern(source_raw[source_raw.find("(")+1:source_raw.find(")")])

            provides_raw = get_field('Provides')
            if provides_raw:
                provides = parse_provides(provides_raw, pkg_id=pkg_id, logger=self.logger)
            else:
                provides = []

            raw_arch = intern(get_field('Architecture'))
            if raw_arch not in {'all', arch}:  # pragma: no cover
                raise AssertionError("%s has wrong architecture (%s) - should be either %s or all" % (
                    str(pkg_id), raw_arch, arch))

            dpkg = BinaryPackage(version,
                                 intern(get_field('Section')),
                                 source,
                                 source_version,
                                 raw_arch,
                                 get_field('Multi-Arch'),
                                 deps,
                                 conflicts,
                                 provides,
                                 ess,
                                 pkg_id,
                                 )

            # if the source package is available in the distribution, then register this binary package
            if source in srcdist:
                # There may be multiple versions of any arch:all packages
                # (in unstable) if some architectures have out-of-date
                # binaries.  We only want to include the package in the
                # source -> binary mapping once. It doesn't matter which
                # of the versions we include as only the package name and
                # architecture are recorded.
                if pkg_id not in srcdist[source].binaries:
                    srcdist[source].binaries.append(pkg_id)
            # if the source package doesn't exist, create a fake one
            else:
                srcdist[source] = SourcePackage(source_version, 'faux', [pkg_id], None, True, None, None, [], [])

            # add the resulting dictionary to the package list
            packages[pkg] = dpkg
            if pkg_id in all_binaries:
                self._merge_pkg_entries(pkg, arch, all_binaries[pkg_id], dpkg)
            else:
                all_binaries[pkg_id] = dpkg

            # add the resulting dictionary to the package list
            packages[pkg] = dpkg

        return packages

    def _read_binaries(self, suite, architectures):
        """Read the list of binary packages from the specified directory

        This method reads all the binary packages for a given suite.

        If the "components" config parameter is set, the directory should
        be the "suite" directory of a local mirror (i.e. the one containing
        the "Release" file).  Otherwise, Britney will read the packages
        information from all the "Packages_${arch}" files referenced by
        the "architectures" parameter.

        Considering the
        large amount of memory needed, not all the fields are loaded
        in memory. The available fields are Version, Source, Multi-Arch,
        Depends, Conflicts, Provides and Architecture.

        The `Provides' field is used to populate the virtual packages list.

        The method returns a tuple of two dicts with architecture as key and
        another dict as value.  The value dicts of the first dict map
        from binary package name to "BinaryPackage" objects; the other second
        value dicts map a package name to the packages providing them.
        """
        binaries = {}
        provides_table = {}
        basedir = suite.path

        if self._components:
            release_file = read_release_file(basedir)
            listed_archs = set(release_file['Architectures'].split())
            for arch in architectures:
                packages = {}
                if arch not in listed_archs:
                    self.logger.info("Skipping arch %s for %s: It is not listed in the Release file",
                                     arch, suite.name)
                    binaries[arch] = {}
                    provides_table[arch] = {}
                    continue
                for component in self._components:
                    binary_dir = "binary-%s" % arch
                    filename = os.path.join(basedir,
                                            component,
                                            binary_dir,
                                            'Packages')
                    filename = possibly_compressed(filename)
                    udeb_filename = os.path.join(basedir,
                                                 component,
                                                 "debian-installer",
                                                 binary_dir,
                                                 "Packages")
                    # We assume the udeb Packages file is present if the
                    # regular one is present
                    udeb_filename = possibly_compressed(udeb_filename)
                    self._read_packages_file(filename,
                                             arch,
                                             suite.sources,
                                             packages)
                    self._read_packages_file(udeb_filename,
                                             arch,
                                             suite.sources,
                                             packages)
                # create provides
                provides = create_provides_map(packages)
                binaries[arch] = packages
                provides_table[arch] = provides
        else:
            for arch in architectures:
                filename = os.path.join(basedir, "Packages_%s" % arch)
                packages = self._read_packages_file(filename,
                                                    arch,
                                                    suite.sources)
                provides = create_provides_map(packages)
                binaries[arch] = packages
                provides_table[arch] = provides

        return (binaries, provides_table)

    def _merge_pkg_entries(self, package, parch, pkg_entry1, pkg_entry2):
        bad = []
        for f in self.CHECK_FIELDS:
            v1 = getattr(pkg_entry1, f)
            v2 = getattr(pkg_entry2, f)
            if v1 != v2:  # pragma: no cover
                bad.append((f, v1, v2))

        if bad:  # pragma: no cover
            self.logger.error("Mismatch found %s %s %s differs", package, pkg_entry1.version, parch)
            for f, v1, v2 in bad:
                self.logger.info(" ... %s %s != %s", f, v1, v2)
            raise ValueError("Inconsistent / Unsupported data set")

        # Merge ESSENTIAL if necessary
        assert pkg_entry1.is_essential or not pkg_entry2.is_essential
