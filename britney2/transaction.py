import contextlib


@contextlib.contextmanager
def start_transaction(suite_info, all_binaries, parent_transaction=None):
    tmts = MigrationTransactionState(suite_info, all_binaries, parent_transaction)
    try:
        yield tmts
    except Exception:
        if not tmts.is_committed and not tmts.is_rolled_back:
            tmts.rollback()
        raise
    assert tmts.is_rolled_back or tmts.is_committed


class MigrationTransactionState(object):

    def __init__(self, suite_info, all_binaries, parent=None):
        self._suite_info = suite_info
        self._all_binaries = all_binaries
        self.parent_transaction = parent
        self._is_rolled_back = False
        self._is_committed = False
        self._undo_items = []

    def add_undo_item(self, undo, item):
        self._assert_open_transaction()
        self._undo_items.append((undo, item))

    def _assert_open_transaction(self):
        assert not self._is_rolled_back and not self._is_committed
        p = self.parent_transaction
        if p:
            p._assert_open_transaction()

    @property
    def undo_items(self):
        """Only needed by a doop_source for the "hint"-hint case"""
        yield from self._undo_items

    def commit(self):
        """Commit the transaction

        After this call, it is not possible to roll these changes
        back (except if there is a parent transaction, which can
        still be rolled back).
        """
        self._assert_open_transaction()
        self._is_committed = True
        if self.parent_transaction:
            for undo_item in self._undo_items:
                self.parent_transaction.add_undo_item(*undo_item)

    def rollback(self):
        """Rollback all recorded changes by this transaction

        The parent transaction (if any) will remain unchanged
        """

        self._assert_open_transaction()

        self._is_rolled_back = True
        lundo = self._undo_items
        lundo.reverse()

        # We do the undo process in "4 steps" and each step must be
        # fully completed for each undo-item before starting on the
        # next.
        #
        # see commit:ef71f0e33a7c3d8ef223ec9ad5e9843777e68133 and
        # #624716 for the issues we had when we did not do this.

        all_binary_packages = self._all_binaries
        target_suite = self._suite_info.target_suite
        sources_t = target_suite.sources
        binaries_t = target_suite.binaries
        provides_t = target_suite.provides_table

        # STEP 1
        # undo all the changes for sources
        for (undo, item) in lundo:
            for k in undo['sources']:
                if k[0] == '-':
                    del sources_t[k[1:]]
                else:
                    sources_t[k] = undo['sources'][k]

        # STEP 2
        # undo all new binaries (consequence of the above)
        for (undo, item) in lundo:
            if not item.is_removal and item.package in item.suite.sources:
                source_data = item.suite.sources[item.package]
                for pkg_id in source_data.binaries:
                    binary, _, arch = pkg_id
                    if item.architecture in ['source', arch]:
                        try:
                            del binaries_t[arch][binary]
                        except KeyError:
                            # If this happens, pkg_id must be a cruft item that
                            # was *not* migrated.
                            assert source_data.version != all_binary_packages[pkg_id].version
                            assert not target_suite.is_pkg_in_the_suite(pkg_id)
                        target_suite.remove_binary(pkg_id)

        # STEP 3
        # undo all other binary package changes (except virtual packages)
        for (undo, item) in lundo:
            for p in undo['binaries']:
                binary, arch = p
                binaries_t_a = binaries_t[arch]
                assert binary not in binaries_t_a
                pkgdata = all_binary_packages[undo['binaries'][p]]
                binaries_t_a[binary] = pkgdata
                target_suite.add_binary(pkgdata.pkg_id)

        # STEP 4
        # undo all changes to virtual packages
        for (undo, item) in lundo:
            for provided_pkg, arch in undo['nvirtual']:
                del provides_t[arch][provided_pkg]
            for p in undo['virtual']:
                provided_pkg, arch = p
                provides_t[arch][provided_pkg] = undo['virtual'][p]

    @property
    def is_rolled_back(self):
        return self._is_rolled_back

    @property
    def is_committed(self):
        return self._is_committed
