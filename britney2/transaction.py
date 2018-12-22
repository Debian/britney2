class MigrationTransactionState(object):

    def __init__(self, suite_info, all_binaries, parent=None):
        self._suite_info = suite_info
        self._all_binaries = all_binaries
        self.parent_transaction = parent
        self._is_rolled_back = False
        self._is_committed = False
        self._undo_items = []
        self._pending_child = False
        if self.parent_transaction:
            # Transactions can only support one child transaction at a time
            assert not self.parent_transaction._pending_child
            self.parent_transaction._pending_child = True

    def add_undo_item(self, undo, updated_binaries):
        # We do not accept any changes to this transaction while it has a child transaction
        # (the undo code does not handle that case correctly)
        assert not self._pending_child
        self._assert_open_transaction()
        self._undo_items.append((undo, updated_binaries))

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
            self.parent_transaction._pending_child = False
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

        all_binary_packages = self._all_binaries
        target_suite = self._suite_info.target_suite
        sources_t = target_suite.sources
        binaries_t = target_suite.binaries
        provides_t = target_suite.provides_table

        # Historically, we have done the undo process in "4 steps"
        # with the rule that each step must be fully completed for
        # each undo-item before starting on the next.
        #
        # see commit:ef71f0e33a7c3d8ef223ec9ad5e9843777e68133 and
        # #624716 for the issues we had when we did not do this.
        #
        # Today, only STEP 2 and STEP 3 are known to potentially
        # clash.  If there is a point in merging the loops/steps,
        # then it is now feasible.

        # STEP 1
        # undo all the changes for sources
        for (undo, updated_binaries) in lundo:
            for (k, v) in undo['sources'].items():
                if v is None:
                    del sources_t[k]
                else:
                    sources_t[k] = v

        # STEP 2
        # undo all new/updated binaries
        # Note this must be completed fully before starting STEP 3
        # as it potentially breaks STEP 3 if the two are interleaved.
        for (_, updated_binaries) in lundo:
            for pkg_id in updated_binaries:
                pkg_name, _, pkg_arch = pkg_id
                try:
                    del binaries_t[pkg_arch][pkg_name]
                except KeyError:
                    continue

                target_suite.remove_binary(pkg_id)

        # STEP 3
        # undo all other binary package changes (except virtual packages)
        for (undo, updated_binaries) in lundo:
            for p in undo['binaries']:
                binary, arch = p
                binaries_t_a = binaries_t[arch]
                pkgdata = all_binary_packages[undo['binaries'][p]]
                binaries_t_a[binary] = pkgdata
                target_suite.add_binary(pkgdata.pkg_id)

        # STEP 4
        # undo all changes to virtual packages
        for (undo, _) in lundo:
            for p, value in undo['virtual'].items():
                provided_pkg, arch = p
                if value is None:
                    del provides_t[arch][provided_pkg]
                else:
                    provides_t[arch][provided_pkg] = undo['virtual'][p]

        if self.parent_transaction:
            self.parent_transaction._pending_child = False

    @property
    def is_rolled_back(self):
        return self._is_rolled_back

    @property
    def is_committed(self):
        return self._is_committed
