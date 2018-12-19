import apt_pkg
import contextlib

from britney2.transaction import MigrationTransactionState
from britney2.utils import (
    MigrationConstraintException, compute_reverse_tree, check_installability, clone_nuninst,
    find_smooth_updateable_binaries,
)


def compute_eqv_set(pkg_universe, updates, rms):
    eqv_set = set()
    # If we are removing *and* updating packages, then check for eqv. packages
    if rms and updates:
        eqv_table = {(x.package_name, x.architecture): x for x in rms}

        for new_pkg_id in updates:
            binary, _, parch = new_pkg_id
            key = (binary, parch)
            old_pkg_id = eqv_table.get(key)
            if old_pkg_id is not None:
                if pkg_universe.are_equivalent(new_pkg_id, old_pkg_id):
                    eqv_set.add(key)
    return eqv_set


def is_nuninst_worse(must_be_installable, nuninst_now_arch, nuninst_after_arch):
    if len(nuninst_after_arch) > len(nuninst_now_arch):
        return True

    regression = nuninst_after_arch - nuninst_now_arch
    if not regression.isdisjoint(must_be_installable):
        return True
    return False


class MigrationManager(object):

    def __init__(self, options, suite_info, all_binaries, pkg_universe, constraints):
        self.options = options
        self.suite_info = suite_info
        self.all_binaries = all_binaries
        self.pkg_universe = pkg_universe
        self.constraints = constraints
        self._transactions = []
        self._all_architectures = frozenset(self.options.architectures)

    @property
    def current_transaction(self):
        return self._transactions[0] if self._transactions else None

    def compute_groups(self,
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
        target_suite = self.suite_info.target_suite
        binaries_t = target_suite.binaries

        adds = set()

        # remove all binary packages (if the source already exists)
        if item.architecture == 'source' or not item.is_removal:
            if source_name in target_suite.sources:
                rms, smoothbins = self._compute_removals(item, allow_smooth_updates, removals)
            else:
                rms = set()
                smoothbins = set()

        # single binary removal; used for clearing up after smooth
        # updates but not supported as a manual hint
        else:
            assert source_name in binaries_t[item.architecture]
            pkg_id = binaries_t[item.architecture][source_name].pkg_id
            rms = {pkg_id}
            smoothbins = set()

        # add the new binary packages (if we are not removing)
        if not item.is_removal:
            source_suite = item.suite
            binaries_s = source_suite.binaries
            source_data = source_suite.sources[source_name]
            source_ver_new = source_data.version
            sources_t = target_suite.sources
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

    def _compute_removals(self, item, allow_smooth_updates, removals):
        pkg_universe = self.pkg_universe
        source_suite = item.suite
        target_suite = self.suite_info.target_suite
        binaries_s = source_suite.binaries
        binaries_t = target_suite.binaries
        source_name = item.package
        source_data = target_suite.sources[source_name]

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
        else:
            smoothbins = set()

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

        return rms, smoothbins

    def _apply_item_to_target_suite(self, item, removals=frozenset()):
        """Apply a change to the target suite as requested by `item`

        An optional set of binaries may be passed in "removals". Binaries listed
        in this set will be assumed to be removed at the same time as the "item"
        will migrate.  This may change what binaries will be smooth-updated.
        - Binaries in this set must be instances of BinaryPackageId.

        This method applies the changes required by the action `item` tracking
        them so it will be possible to revert them.

        The method returns a tuple containing a set of packages
        affected by the change (as (name, arch)-tuples) and the
        dictionary undo which can be used to rollback the changes.
        """
        undo = {'binaries': {}, 'sources': {}, 'virtual': {}}

        affected_direct = set()
        updated_binaries = set()

        # local copies for better performance
        source_suite = item.suite
        target_suite = self.suite_info.target_suite
        packages_t = target_suite.binaries
        provides_t = target_suite.provides_table
        pkg_universe = self.pkg_universe
        transaction = self.current_transaction

        updates, rms, _ = self.compute_groups(item, removals=removals)

        # Handle the source package
        if item.architecture == 'source':
            sources_t = target_suite.sources
            if item.package in sources_t:
                source = sources_t[item.package]
                undo['sources'][item.package] = source
                del sources_t[item.package]
            else:
                # the package didn't exist, so we mark it as to-be-removed in case of undo
                undo['sources']['-' + item.package] = True

            # add/update the source package
            if not item.is_removal:
                sources_t[item.package] = source_suite.sources[item.package]

        eqv_set = compute_eqv_set(pkg_universe, updates, rms)

        # remove all the binaries which aren't being smooth updated
        for rm_pkg_id in rms:
            binary, version, parch = rm_pkg_id
            pkey = (binary, parch)
            binaries_t_a = packages_t[parch]
            provides_t_a = provides_t[parch]

            pkg_data = binaries_t_a[binary]
            # save the old binary for undo
            undo['binaries'][pkey] = rm_pkg_id
            if pkey not in eqv_set:
                # all the reverse dependencies are affected by
                # the change
                affected_direct.update(pkg_universe.reverse_dependencies_of(rm_pkg_id))
                affected_direct.update(pkg_universe.negative_dependencies_of(rm_pkg_id))

            # remove the provided virtual packages
            for provided_pkg, prov_version, _ in pkg_data.provides:
                key = (provided_pkg, parch)
                if key not in undo['virtual']:
                    undo['virtual'][key] = provides_t_a[provided_pkg].copy()
                provides_t_a[provided_pkg].remove((binary, prov_version))
                if not provides_t_a[provided_pkg]:
                    del provides_t_a[provided_pkg]
            # finally, remove the binary package
            del binaries_t_a[binary]
            target_suite.remove_binary(rm_pkg_id)

        # Add/Update binary packages in testing
        if updates:
            packages_s = source_suite.binaries

            for updated_pkg_id in updates:
                binary, new_version, parch = updated_pkg_id
                key = (binary, parch)
                binaries_t_a = packages_t[parch]
                provides_t_a = provides_t[parch]
                equivalent_replacement = key in eqv_set

                # obviously, added/modified packages are affected
                if not equivalent_replacement:
                    affected_direct.add(updated_pkg_id)
                # if the binary already exists in testing, it is currently
                # built by another source package. we therefore remove the
                # version built by the other source package, after marking
                # all of its reverse dependencies as affected
                if binary in binaries_t_a:
                    old_pkg_data = binaries_t_a[binary]
                    old_pkg_id = old_pkg_data.pkg_id
                    # save the old binary package
                    undo['binaries'][key] = old_pkg_id
                    if not equivalent_replacement:
                        # all the reverse conflicts
                        affected_direct.update(pkg_universe.reverse_dependencies_of(old_pkg_id))
                    target_suite.remove_binary(old_pkg_id)
                elif transaction and transaction.parent_transaction:
                    # the binary isn't in the target suite, but it may have been at
                    # the start of the current hint and have been removed
                    # by an earlier migration. if that's the case then we
                    # will have a record of the older instance of the binary
                    # in the undo information. we can use that to ensure
                    # that the reverse dependencies of the older binary
                    # package are also checked.
                    # reverse dependencies built from this source can be
                    # ignored as their reverse trees are already handled
                    # by this function
                    for (tundo, tpkg) in transaction.parent_transaction.undo_items:
                        if key in tundo['binaries']:
                            tpkg_id = tundo['binaries'][key]
                            affected_direct.update(pkg_universe.reverse_dependencies_of(tpkg_id))

                # add/update the binary package from the source suite
                new_pkg_data = packages_s[parch][binary]
                binaries_t_a[binary] = new_pkg_data
                target_suite.add_binary(updated_pkg_id)
                updated_binaries.add(updated_pkg_id)
                # register new provided packages
                for provided_pkg, prov_version, _ in new_pkg_data.provides:
                    key = (provided_pkg, parch)
                    if key not in undo['virtual']:
                        restore_as = provides_t_a[provided_pkg].copy() if provided_pkg in provides_t_a else None
                        undo['virtual'][key] = restore_as
                    provides_t_a[provided_pkg].add((binary, prov_version))
                if not equivalent_replacement:
                    # all the reverse dependencies are affected by the change
                    affected_direct.add(updated_pkg_id)
                    affected_direct.update(pkg_universe.negative_dependencies_of(updated_pkg_id))

        # Also include the transitive rdeps of the packages found so far
        affected_all = affected_direct.copy()
        compute_reverse_tree(pkg_universe, affected_all)
        if transaction:
            transaction.add_undo_item(undo, updated_binaries)
        # return the affected packages (direct and than all)
        return (affected_direct, affected_all)

    def _apply_multiple_items_to_target_suite(self, items):
        is_source_migration = False
        if len(items) == 1:
            item = items[0]
            # apply the changes
            affected_direct, affected_all = self._apply_item_to_target_suite(item)
            if item.architecture == 'source':
                affected_architectures = self._all_architectures
                is_source_migration = True
            else:
                affected_architectures = {item.architecture}
        else:
            affected_architectures = set()
            removals = set()
            affected_direct = set()
            affected_all = set()
            for item in items:
                _, rms, _ = self.compute_groups(item, allow_smooth_updates=False)
                removals.update(rms)
                affected_architectures.add(item.architecture)

            if 'source' in affected_architectures:
                affected_architectures = self._all_architectures
                is_source_migration = True

            for item in items:
                item_affected_direct, item_affected_all = self._apply_item_to_target_suite(item,
                                                                                           removals=removals)
                affected_direct.update(item_affected_direct)
                affected_all.update(item_affected_all)

        return is_source_migration, affected_architectures, affected_direct, affected_all

    def migrate_item_to_target_suite(self, items, nuninst_now, stop_on_first_regression=True):
        is_accepted = True
        target_suite = self.suite_info.target_suite
        packages_t = target_suite.binaries

        nobreakall_arches = self.options.nobreakall_arches
        new_arches = self.options.new_arches
        break_arches = self.options.break_arches
        arch = None

        is_source_migration, affected_architectures, affected_direct, affected_all = \
            self._apply_multiple_items_to_target_suite(items)

        # Optimise the test if we may revert directly.
        # - The automatic-revert is needed since some callers (notably via hints) may
        #   accept the outcome of this migration and expect nuninst to be updated.
        #   (e.g. "force-hint" or "hint")
        if stop_on_first_regression:
            affected_all -= affected_direct
        else:
            affected_direct = set()

        # Copy nuninst_comp - we have to deep clone affected
        # architectures.

        # NB: We do this *after* updating testing as we have to filter out
        # removed binaries.  Otherwise, uninstallable binaries that were
        # removed by the item would still be counted.

        nuninst_after = clone_nuninst(nuninst_now, packages_s=packages_t, architectures=affected_architectures)
        must_be_installable = self.constraints['keep-installable']

        # check the affected packages on all the architectures
        for arch in affected_architectures:
            check_archall = arch in nobreakall_arches

            check_installability(target_suite, packages_t, arch, affected_direct, affected_all,
                                 check_archall, nuninst_after)

            # if the uninstallability counter is worse than before, break the loop
            if stop_on_first_regression:
                worse = is_nuninst_worse(must_be_installable, nuninst_now[arch], nuninst_after[arch])

                # ... except for a few special cases
                if worse and ((not is_source_migration and arch not in new_arches) or
                              (arch not in break_arches)):
                    is_accepted = False
                    break

        return (is_accepted, nuninst_after, arch)

    @contextlib.contextmanager
    def start_transaction(self):
        tmts = MigrationTransactionState(self.suite_info, self.all_binaries, self.current_transaction)
        self._transactions.append(tmts)
        try:
            yield tmts
        except Exception:
            if not tmts.is_committed and not tmts.is_rolled_back:
                tmts.rollback()
            raise
        finally:
            self._transactions.pop()
        assert tmts.is_rolled_back or tmts.is_committed
