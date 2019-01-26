from collections import namedtuple

from britney2.utils import MigrationConstraintException

MigrationSolverResult = namedtuple('MigrationSolverResult', [
    'committed_items',
    'unsolved_items',
    'original_baseline',
    'new_baseline',
])


class SolverStateHelper(object):

    def __init__(self, options, target_suite, migration_manager, nuninst_baseline, selected, output_logger):
        self.options = options
        self.output_logger = output_logger
        self.target_suite = target_suite
        self.selected = selected
        self.migration_manager = migration_manager
        self.baseline_original = nuninst_baseline
        self.baseline_current = nuninst_baseline

    def try_migrating_items(self, items, progress):
        mm = self.migration_manager
        baseline_current = self.baseline_current
        output_logger = self.output_logger
        comp_name = ' '.join(item.uvname for item in items)
        output_logger.info("trying: %s" % comp_name)
        new_cruft = None
        accepted = False
        with mm.start_transaction() as transaction:
            try:
                accepted, baseline_after, failed_arch, new_cruft = mm.migrate_items_to_target_suite(
                    items,
                    baseline_current
                )
                if accepted:
                    selected = self.selected
                    selected.extend(items)
                    transaction.commit()
                    output_logger.info("accepted: %s", comp_name)
                    output_logger.info("   ori: %s", self.eval_nuninst(self.baseline_original))
                    output_logger.info("   pre: %s", self.eval_nuninst(baseline_current))
                    output_logger.info("   now: %s", self.eval_nuninst(baseline_after))
                    if len(selected) <= 20:
                        output_logger.info("   all: %s", " ".join(x.uvname for x in selected))
                    else:
                        output_logger.info("  most: (%d) .. %s",
                                           len(selected),
                                           " ".join(x.uvname for x in selected[-20:]))
                    if self.options.check_consistency_level >= 3:
                        self.target_suite.check_suite_source_pkg_consistency('iter_packages after commit')
                    self.baseline_current = baseline_after
                else:
                    transaction.rollback()
                    broken = sorted(b for b in baseline_after[failed_arch]
                                    if b not in baseline_current[failed_arch])
                    compare_baseline = None
                    if any(item for item in items if item.architecture != 'source'):
                        compare_baseline = baseline_current
                    # NB: try_migration already reverted this for us, so just print the results and move on
                    output_logger.info("skipped: %s (%s)", comp_name, progress)
                    output_logger.info("    got: %s", self.eval_nuninst(baseline_after, compare_baseline))
                    output_logger.info("    * %s: %s", failed_arch, ", ".join(broken))
                    if self.options.check_consistency_level >= 3:
                        self.target_suite.check_suite_source_pkg_consistency(
                            'iter_package after rollback (not accepted)')

            except MigrationConstraintException as e:
                transaction.rollback()
                output_logger.info("skipped: %s (%s)", comp_name, progress)
                output_logger.info("    got exception: %s", repr(e))
                if self.options.check_consistency_level >= 3:
                    self.target_suite.check_suite_source_pkg_consistency(
                        'iter_package after rollback (MigrationConstraintException)')

        return accepted, new_cruft

    def eval_nuninst(self, nuninst, original=None):
        """Return a string which represents the uninstallability counters

        This method returns a string which represents the uninstallability
        counters reading the uninstallability statistics `nuninst` and, if
        present, merging the results with the `original` one.

        An example of the output string is:
        1+2: i-0:a-0:a-0:h-0:i-1:m-0:m-0:p-0:a-0:m-0:s-2:s-0

        where the first part is the number of broken packages in non-break
        architectures + the total number of broken packages for all the
        architectures.
        """
        res = []
        total = 0
        totalbreak = 0
        for arch in self.options.architectures:
            if arch in nuninst:
                n = len(nuninst[arch])
            elif original and arch in original:
                n = len(original[arch])
            else:
                continue
            if arch in self.options.break_arches:
                totalbreak = totalbreak + n
            else:
                total = total + n
            res.append("%s-%d" % (arch[0], n))
        return "%d+%d: %s" % (total, totalbreak, ":".join(res))
