from collections import namedtuple
from operator import attrgetter

from britney2.installability.solver import InstallabilitySolver
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


class PartialOrderSolverProgress(object):

    def __init__(self, rescheduled_packages, maybe_rescheduled_packages, worklist):
        self.rescheduled_packages = rescheduled_packages
        self.maybe_rescheduled_packages = maybe_rescheduled_packages
        self.worklist = worklist

    def __str__(self):
        return '%d, %d, %d' % (
            len(self.rescheduled_packages),
            len(self.maybe_rescheduled_packages),
            len(self.worklist)
        )


class PartialOrderSolver(object):

    def __init__(self, solver_helper, target_suite, pkg_universe, output_logger):
        self.output_logger = output_logger
        self._target_suite = target_suite
        self._pkg_universe = pkg_universe
        self._solver_helper = solver_helper

    def solve_as_many_as_possible(self, mm, considered_items):
        group_info = {}
        rescheduled_packages = considered_items
        maybe_rescheduled_packages = []
        output_logger = self.output_logger
        solver = InstallabilitySolver(self._pkg_universe, self._target_suite)
        solver_helper = self._solver_helper

        for y in sorted((y for y in considered_items), key=attrgetter('uvname')):
            try:
                _, updates, rms, _ = mm.compute_groups(y)
                result = (y, frozenset(updates), frozenset(rms))
                group_info[y] = result
            except MigrationConstraintException as e:
                rescheduled_packages.remove(y)
                output_logger.info("not adding package to list: %s", y.package)
                output_logger.info("    got exception: %s", repr(e))

        while rescheduled_packages:
            groups = {group_info[x] for x in rescheduled_packages}
            worklist = solver.solve_groups(groups)
            rescheduled_packages = []

            # Relies on the parameters being mutable/updated for providing accurate feedback
            progress = PartialOrderSolverProgress(rescheduled_packages, maybe_rescheduled_packages, worklist)

            worklist.reverse()

            while worklist:
                comp = worklist.pop()

                accepted, new_cruft = solver_helper.try_migrating_items(comp, progress)

                if accepted:
                    for cruft_item in new_cruft:
                        _, updates, rms, _ = mm.compute_groups(cruft_item)
                        result = (cruft_item, frozenset(updates), frozenset(rms))
                        group_info[cruft_item] = result
                    worklist.extend([x] for x in new_cruft)
                    rescheduled_packages.extend(maybe_rescheduled_packages)
                    maybe_rescheduled_packages.clear()

                else:
                    if len(comp) > 1:
                        output_logger.info("    - splitting the component into single items and retrying them")
                        worklist.extend([item] for item in comp)
                    else:
                        maybe_rescheduled_packages.append(comp[0])

        return MigrationSolverResult(committed_items=solver_helper.selected,
                                     unsolved_items=maybe_rescheduled_packages,
                                     original_baseline=solver_helper.baseline_original,
                                     new_baseline=solver_helper.baseline_current,
                                     )
