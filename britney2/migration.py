import apt_pkg

from britney2.utils import MigrationConstraintException, find_smooth_updateable_binaries


class MigrationManager(object):

    def __init__(self, options, suite_info, all_binaries, pkg_universe):
        self.options = options
        self.suite_info = suite_info
        self.all_binaries = all_binaries
        self.pkg_universe = pkg_universe

    def _compute_groups(self,
                        item,
                        allow_smooth_updates=True,
                        removals=frozenset()):
        """Compute the groups of binaries being migrated by item

        This method will compute the binaries that will be added to,
        replaced in or removed from the target suite and which of
        the removals are smooth updatable.

        Parameters:
        * "item" is a MigrationItem
        * "allow_smooth_updates" is a boolean determining whether smooth-
          updates are permitted in this migration.  When set to False,
          the "smoothbins" return value will always be the empty set.
          Any value that would have been there will now be in "rms"
          instead. (defaults: True)
        * "removals" is a set of binaries that is assumed to be
          removed at the same time as this migration (e.g. in the same
          "easy"-hint).  This may affect what if some binaries are
          smooth updated or not. (defaults: empty-set)
          - Binaries must be given as ("package-name", "version",
            "architecture") tuples.

        Returns a tuple (adds, rms, smoothbins).  "adds" is a set of
        binaries that will updated in or appear after the migration.
        "rms" is a set of binaries that are not smooth-updatable (or
        binaries that could be, but there is no reason to let them be
        smooth updated).  "smoothbins" is set of binaries that are to
        be smooth-updated.

        Each "binary" in "adds", "rms" and "smoothbins" will be a
        tuple of ("package-name", "version", "architecture") and are
        thus tuples suitable for passing on to the
        InstallabilityTester.


        Unlike doop_source, this will not modify any data structure.
        """
        # local copies for better performances
        source_name = item.package
        source_suite = item.suite
        target_suite = self.suite_info.target_suite
        binaries_s = source_suite.binaries
        binaries_t = target_suite.binaries
        pkg_universe = self.pkg_universe

        adds = set()
        rms = set()
        smoothbins = set()

        # remove all binary packages (if the source already exists)
        if item.architecture == 'source' or not item.is_removal:
            sources_t = target_suite.sources
            if source_name in sources_t:
                source_data = sources_t[source_name]

                bins = []
                # remove all the binaries

                # first, build a list of eligible binaries
                for pkg_id in source_data.binaries:
                    binary, _, parch = pkg_id
                    if item.architecture != 'source' and parch != item.architecture:
                        continue

                    # Work around #815995
                    if item.architecture == 'source' and item.is_removal and binary not in binaries_t[parch]:
                        continue

                    # Do not include hijacked binaries
                    if binaries_t[parch][binary].source != source_name:
                        continue
                    bins.append(pkg_id)

                if allow_smooth_updates and source_suite.suite_class.is_primary_source:
                    smoothbins = find_smooth_updateable_binaries(bins,
                                                                 source_suite.sources[source_name],
                                                                 pkg_universe,
                                                                 target_suite,
                                                                 binaries_t,
                                                                 binaries_s,
                                                                 removals,
                                                                 self.options.smooth_updates)

                # remove all the binaries which aren't being smooth updated
                if item.architecture != 'source' and source_suite.suite_class.is_additional_source:
                    # Special-case for pu/tpu:
                    # if this is a binary migration from *pu, only the arch:any
                    # packages will be present. ideally dak would also populate
                    # the arch-indep packages, but as that's not the case we
                    # must keep them around; they will not be re-added by the
                    # migration so will end up missing from testing
                    all_binaries = self.all_binaries
                    rms = {pkg_id for pkg_id in bins
                           if pkg_id not in smoothbins and all_binaries[pkg_id].architecture != 'all'}
                else:
                    rms = {pkg_id for pkg_id in bins if pkg_id not in smoothbins}

        # single binary removal; used for clearing up after smooth
        # updates but not supported as a manual hint
        else:
            assert source_name in binaries_t[item.architecture]
            pkg_id = binaries_t[item.architecture][source_name].pkg_id
            rms.add(pkg_id)

        # add the new binary packages (if we are not removing)
        if not item.is_removal:
            source_data = source_suite.sources[source_name]
            source_ver_new = source_data.version
            if source_name in sources_t:
                source_data_old = sources_t[source_name]
                source_ver_old = source_data_old.version
                if apt_pkg.version_compare(source_ver_old, source_ver_new) > 0:
                    raise MigrationConstraintException("trying src:%s %s, while %s has %s" % (
                        source_name, source_ver_new, target_suite.name, source_ver_old))

            for pkg_id in source_data.binaries:
                binary, ver, parch = pkg_id
                if item.architecture not in ['source', parch]:
                    continue

                if binaries_s[parch][binary].source != source_name:
                    # This binary package has been hijacked by some other source.
                    # So don't add it as part of this update.
                    #
                    # Also, if this isn't a source update, don't remove
                    # the package that's been hijacked if it's present.
                    if item.architecture != 'source':
                        for rm_b, rm_v, rm_p in list(rms):
                            if (rm_b, rm_p) == (binary, parch):
                                rms.remove((rm_b, rm_v, rm_p))
                    continue

                # Don't add the binary if it is cruft; smooth updates will keep it if possible
                if (parch not in self.options.outofsync_arches and
                        source_data.version != binaries_s[parch][binary].source_version):
                    continue

                if binary in binaries_t[parch]:
                    oldver = binaries_t[parch][binary].version
                    if apt_pkg.version_compare(oldver, ver) > 0:
                        raise MigrationConstraintException("trying %s %s from src:%s %s, while %s has %s" % (
                            binary, ver, source_name, source_ver_new, target_suite.name, oldver))

                adds.add(pkg_id)

        return (adds, rms, smoothbins)
