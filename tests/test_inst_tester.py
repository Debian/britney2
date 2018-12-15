import sys
import unittest

from collections import OrderedDict

from . import new_pkg_universe_builder
from britney2.installability.solver import compute_scc, InstallabilitySolver


class TestInstTester(unittest.TestCase):

    def test_basic_inst_test(self):
        builder = new_pkg_universe_builder()
        universe, inst_tester = builder.new_package('lintian').depends_on('perl').depends_on_any_of('awk', 'mawk').\
            new_package('perl-base').is_essential().\
            new_package('dpkg').is_essential(). \
            new_package('perl').\
            new_package('awk').not_in_testing().\
            new_package('mawk').\
            build()
        pkg_lintian = builder.pkg_id('lintian')
        pkg_awk = builder.pkg_id('awk')
        pkg_mawk = builder.pkg_id('mawk')
        pkg_perl = builder.pkg_id('perl')
        pkg_perl_base = builder.pkg_id('perl-base')
        assert inst_tester.is_installable(pkg_lintian)
        assert inst_tester.is_installable(pkg_perl)
        assert inst_tester.any_of_these_are_in_testing((pkg_lintian, pkg_perl))
        assert not inst_tester.is_installable(pkg_awk)
        assert not inst_tester.any_of_these_are_in_testing((pkg_awk,))
        inst_tester.remove_binary(pkg_perl)
        assert not inst_tester.any_of_these_are_in_testing((pkg_perl,))
        assert inst_tester.any_of_these_are_in_testing((pkg_lintian,))
        assert not inst_tester.is_pkg_in_testing(pkg_perl)
        assert inst_tester.is_pkg_in_testing(pkg_lintian)
        assert not inst_tester.is_installable(pkg_lintian)
        assert not inst_tester.is_installable(pkg_perl)
        inst_tester.add_binary(pkg_perl)
        assert inst_tester.is_installable(pkg_lintian)
        assert inst_tester.is_installable(pkg_perl)

        assert universe.reverse_dependencies_of(pkg_perl) == {pkg_lintian}
        assert universe.reverse_dependencies_of(pkg_lintian) == frozenset()

        # awk and mawk are equivalent, but nothing else is eqv.
        assert universe.are_equivalent(pkg_awk, pkg_mawk)
        assert not universe.are_equivalent(pkg_lintian, pkg_mawk)
        assert not universe.are_equivalent(pkg_lintian, pkg_perl)
        assert not universe.are_equivalent(pkg_mawk, pkg_perl)

        # Trivial test of the special case for adding and removing an essential package
        inst_tester.remove_binary(pkg_perl_base)
        inst_tester.add_binary(pkg_perl_base)

        inst_tester.add_binary(pkg_awk)
        assert inst_tester.is_installable(pkg_lintian)

    def test_basic_essential_conflict(self):
        builder = new_pkg_universe_builder()
        pseudo_ess1 = builder.new_package('pseudo-essential1')
        pseudo_ess2 = builder.new_package('pseudo-essential2')
        essential_simple = builder.new_package('essential-simple').is_essential()
        essential_with_deps = builder.new_package('essential-with-deps').is_essential().\
            depends_on_any_of(pseudo_ess1, pseudo_ess2)
        conflict1 = builder.new_package('conflict1').conflicts_with(essential_simple)
        conflict2 = builder.new_package('conflict2').conflicts_with(pseudo_ess1, pseudo_ess2)
        conflict_installable1 = builder.new_package('conflict-inst1').conflicts_with(pseudo_ess1)
        conflict_installable2 = builder.new_package('conflict-inst2').conflicts_with(pseudo_ess2)

        universe, inst_tester = builder.build()

        assert inst_tester.is_installable(essential_simple.pkg_id)
        assert inst_tester.is_installable(essential_with_deps.pkg_id)
        assert inst_tester.is_installable(conflict_installable1.pkg_id)
        assert inst_tester.is_installable(conflict_installable2.pkg_id)
        assert not inst_tester.is_installable(conflict1.pkg_id)
        assert not inst_tester.is_installable(conflict2.pkg_id)

        for line in inst_tester.stats.stats():
            print(line)
        assert inst_tester.stats.conflicts_essential == 1

    def test_basic_simple_choice(self):
        builder = new_pkg_universe_builder()
        root_pkg = builder.new_package('root')
        conflicting1 = builder.new_package('conflict1')
        conflicting2 = builder.new_package('conflict2')
        bottom1_pkg = builder.new_package('bottom1').conflicts_with(conflicting1)
        bottom2_pkg = builder.new_package('bottom2').conflicts_with(conflicting2)

        pkg1 = builder.new_package('pkg1').depends_on(bottom1_pkg)
        pkg2 = builder.new_package('pkg2').depends_on(bottom2_pkg)

        root_pkg.depends_on_any_of(pkg1, pkg2)

        universe, inst_tester = builder.build()

        # The dependencies of "root" are not equivalent (if they were, we would trigger
        # an optimization, which takes another code path)
        assert not universe.are_equivalent(pkg1.pkg_id, pkg2.pkg_id)

        assert inst_tester.is_installable(root_pkg.pkg_id)
        for line in inst_tester.stats.stats():
            print(line)
        assert inst_tester.stats.eqv_table_times_used == 0
        assert inst_tester.stats.eqv_table_total_number_of_alternatives_eliminated == 0
        assert inst_tester.stats.eqv_table_reduced_to_one == 0
        assert inst_tester.stats.eqv_table_reduced_by_zero == 0

    def test_basic_simple_choice_deadend(self):
        builder = new_pkg_universe_builder()
        root_pkg = builder.new_package('root')
        bottom1_pkg = builder.new_package('bottom1').conflicts_with(root_pkg)
        bottom2_pkg = builder.new_package('bottom2').conflicts_with(root_pkg)

        pkg1 = builder.new_package('pkg1').depends_on(bottom1_pkg)
        pkg2 = builder.new_package('pkg2').depends_on(bottom2_pkg)

        root_pkg.depends_on_any_of(pkg1, pkg2)

        universe, inst_tester = builder.build()

        # The dependencies of "root" are not equivalent (if they were, we would trigger
        # an optimization, which takes another code path)
        assert not universe.are_equivalent(pkg1.pkg_id, pkg2.pkg_id)

        assert not inst_tester.is_installable(root_pkg.pkg_id)
        for line in inst_tester.stats.stats():
            print(line)
        assert inst_tester.stats.eqv_table_times_used == 0
        assert inst_tester.stats.eqv_table_total_number_of_alternatives_eliminated == 0
        assert inst_tester.stats.eqv_table_reduced_to_one == 0
        assert inst_tester.stats.eqv_table_reduced_by_zero == 0
        # This case is simple enough that the installability tester will assert it does not
        # need to recurse to reject the first option
        assert inst_tester.stats.backtrace_restore_point_used == 0
        assert inst_tester.stats.backtrace_last_option == 1

    def test_basic_simple_choice_opt_no_restore_needed(self):
        builder = new_pkg_universe_builder()
        conflicting = builder.new_package('conflict')
        root_pkg = builder.new_package('root').conflicts_with(conflicting)
        bottom1_pkg = builder.new_package('bottom1').conflicts_with(conflicting)
        bottom2_pkg = builder.new_package('bottom2').conflicts_with(conflicting)

        # These two packages have (indirect) conflicts, so they cannot trigger the
        # safe set optimization.  However, since "root" already have the same conflict
        # it can use the "no restore point needed" optimization.
        pkg1 = builder.new_package('pkg1').depends_on(bottom1_pkg)
        pkg2 = builder.new_package('pkg2').depends_on(bottom2_pkg)

        root_pkg.depends_on_any_of(pkg1, pkg2)

        universe, inst_tester = builder.build()

        # The dependencies of "root" are not equivalent (if they were, we would trigger
        # an optimization, which takes another code path)
        assert not universe.are_equivalent(pkg1.pkg_id, pkg2.pkg_id)

        assert inst_tester.is_installable(root_pkg.pkg_id)
        for line in inst_tester.stats.stats():
            print(line)
        assert inst_tester.stats.eqv_table_times_used == 0
        assert inst_tester.stats.eqv_table_total_number_of_alternatives_eliminated == 0
        assert inst_tester.stats.eqv_table_reduced_to_one == 0
        assert inst_tester.stats.eqv_table_reduced_by_zero == 0
        assert inst_tester.stats.backtrace_restore_point_used == 0
        assert inst_tester.stats.backtrace_last_option == 0
        assert inst_tester.stats.choice_resolved_without_restore_point == 1

    def test_basic_simple_choice_opt_no_restore_needed_deadend(self):
        builder = new_pkg_universe_builder()
        conflicting1 = builder.new_package('conflict1').conflicts_with('conflict2')
        conflicting2 = builder.new_package('conflict2').conflicts_with('conflict1')
        root_pkg = builder.new_package('root')
        bottom_pkg = builder.new_package('bottom').depends_on(conflicting1).depends_on(conflicting2)
        mid1_pkg = builder.new_package('mid1').depends_on(bottom_pkg)
        mid2_pkg = builder.new_package('mid2').depends_on(bottom_pkg)

        # These two packages have (indirect) conflicts, so they cannot trigger the
        # safe set optimization.  However, since "root" already have the same conflict
        # it can use the "no restore point needed" optimization.
        pkg1 = builder.new_package('pkg1').depends_on(mid1_pkg)
        pkg2 = builder.new_package('pkg2').depends_on(mid2_pkg)

        root_pkg.depends_on_any_of(pkg1, pkg2)

        universe, inst_tester = builder.build()

        # The dependencies of "root" are not equivalent (if they were, we would trigger
        # an optimization, which takes another code path)
        assert not universe.are_equivalent(pkg1.pkg_id, pkg2.pkg_id)

        assert not inst_tester.is_installable(root_pkg.pkg_id)
        for line in inst_tester.stats.stats():
            print(line)
        assert inst_tester.stats.eqv_table_times_used == 0
        assert inst_tester.stats.eqv_table_total_number_of_alternatives_eliminated == 0
        assert inst_tester.stats.eqv_table_reduced_to_one == 0
        assert inst_tester.stats.eqv_table_reduced_by_zero == 0
        assert inst_tester.stats.backtrace_restore_point_used == 0
        assert inst_tester.stats.choice_resolved_without_restore_point == 0
        assert inst_tester.stats.backtrace_last_option == 1

    def test_basic_choice_deadend_restore_point_needed(self):
        builder = new_pkg_universe_builder()
        root_pkg = builder.new_package('root')
        bottom1_pkg = builder.new_package('bottom1').depends_on_any_of('bottom2', 'bottom3')
        bottom2_pkg = builder.new_package('bottom2').conflicts_with(root_pkg)
        bottom3_pkg = builder.new_package('bottom3').depends_on_any_of('bottom1', 'bottom2')

        pkg1 = builder.new_package('pkg1').depends_on_any_of(bottom1_pkg, bottom2_pkg).conflicts_with('bottom3')
        pkg2 = builder.new_package('pkg2').depends_on_any_of(bottom2_pkg, bottom3_pkg).conflicts_with('bottom1')

        root_pkg.depends_on_any_of(pkg1, pkg2)

        universe, inst_tester = builder.build()

        # The dependencies of "root" are not equivalent (if they were, we would trigger
        # an optimization, which takes another code path)
        assert not universe.are_equivalent(pkg1.pkg_id, pkg2.pkg_id)

        assert not inst_tester.is_installable(root_pkg.pkg_id)
        for line in inst_tester.stats.stats():
            print(line)
        assert inst_tester.stats.eqv_table_times_used == 0
        assert inst_tester.stats.eqv_table_total_number_of_alternatives_eliminated == 0
        assert inst_tester.stats.eqv_table_reduced_to_one == 0
        assert inst_tester.stats.eqv_table_reduced_by_zero == 0
        # This case is simple enough that the installability tester will assert it does not
        # need to recurse to reject the first option
        assert inst_tester.stats.backtrace_restore_point_used == 1
        assert inst_tester.stats.backtrace_last_option == 1

    def test_corner_case_dependencies_inter_conflict(self):
        builder = new_pkg_universe_builder()
        root_pkg = builder.new_package('root').depends_on('conflict1').depends_on('conflict2')
        conflicting1 = builder.new_package('conflict1').conflicts_with('conflict2')
        conflicting2 = builder.new_package('conflict2').conflicts_with('conflict1')

        universe, inst_tester = builder.build()

        # They should not be eqv.
        assert not universe.are_equivalent(conflicting1.pkg_id, conflicting2.pkg_id)

        # "root" should not be installable and we should trigger a special code path where
        # the installability tester has both conflicting packages in its "check" set
        # Technically, we cannot assert we hit that path with this test, but we can at least
        # check it does not regress
        assert not inst_tester.is_installable(root_pkg.pkg_id)

    def test_basic_choice_deadend_pre_solvable(self):
        builder = new_pkg_universe_builder()
        # This test is complicated by the fact that the inst-tester has a non-deterministic ordering.
        # To ensure that it becomes predictable, we have to force it to see the choice before
        # the part that eliminates it.  In practise, this is easiest to do by creating a symmetric
        # graph where one solving one choice eliminates the other.

        root_pkg = builder.new_package('root')

        # These two packages are used to make options distinct; otherwise the eqv. optimisation will just
        # collapse the choices.
        nodep1 = builder.new_package('nodep1')
        nodep2 = builder.new_package('nodep2')

        path1a = builder.new_package('path1a').depends_on(nodep1).depends_on('end1')
        path1b = builder.new_package('path1b').depends_on(nodep2).depends_on('end1')

        path2a = builder.new_package('path2a').depends_on(nodep1).depends_on('end2')
        path2b = builder.new_package('path2b').depends_on(nodep2).depends_on('end2')

        builder.new_package('end1').conflicts_with(path2a, path2b)
        builder.new_package('end2').conflicts_with(path1a, path1b)

        root_pkg.depends_on_any_of(path1a, path1b).depends_on_any_of(path2a, path2b)

        _, inst_tester = builder.build()

        assert not inst_tester.is_installable(root_pkg.pkg_id)
        for line in inst_tester.stats.stats():
            print(line)
        assert inst_tester.stats.eqv_table_times_used == 0
        assert inst_tester.stats.eqv_table_total_number_of_alternatives_eliminated == 0
        assert inst_tester.stats.eqv_table_reduced_to_one == 0
        assert inst_tester.stats.eqv_table_reduced_by_zero == 0

        # The following numbers are observed due to:
        #   * Pick an option from (pathXa | pathXb)
        #   * First option -> obviously unsolvable
        #   * Undo and do "last option" on the remaining
        #   * "last option" -> obviously unsolvable
        #   * unsolvable
        assert inst_tester.stats.backtrace_restore_point_used == 1
        assert inst_tester.stats.backtrace_last_option == 1
        assert inst_tester.stats.choice_presolved == 2

    def test_basic_choice_pre_solvable(self):
        builder = new_pkg_universe_builder()
        # This test is complicated by the fact that the inst-tester has a non-deterministic ordering.
        # To ensure that it becomes predictable, we have to force it to see the choice before
        # the part that eliminates it.  In practise, this is easiest to do by creating a symmetric
        # graph where one solving one choice eliminates the other.

        root_pkg = builder.new_package('root')

        nodep1 = builder.new_package('nodep1').conflicts_with('path1b', 'path2b')
        nodep2 = builder.new_package('nodep2').conflicts_with('path1b', 'path2b')
        end1 = builder.new_package('end1')
        end2 = builder.new_package('end2')

        path1a = builder.new_package('path1a').depends_on(nodep1).depends_on(end1)
        path1b = builder.new_package('path1b').depends_on(nodep2).depends_on(end1)

        path2a = builder.new_package('path2a').depends_on(nodep1).depends_on(end2)
        path2b = builder.new_package('path2b').depends_on(nodep2).depends_on(end2)

        root_pkg.depends_on_any_of(path1a, path1b).depends_on_any_of(path2a, path2b)

        _, inst_tester = builder.build()

        assert inst_tester.is_installable(root_pkg.pkg_id)
        for line in inst_tester.stats.stats():
            print(line)
        assert inst_tester.stats.eqv_table_times_used == 0
        assert inst_tester.stats.eqv_table_total_number_of_alternatives_eliminated == 0
        assert inst_tester.stats.eqv_table_reduced_to_one == 0
        assert inst_tester.stats.eqv_table_reduced_by_zero == 0

        # After its first guess, the tester can pre-solve remaining choice
        assert inst_tester.stats.backtrace_restore_point_used == 0
        assert inst_tester.stats.choice_presolved == 1

    def test_optimisation_simple_full_eqv_reduction(self):
        builder = new_pkg_universe_builder()
        root_pkg = builder.new_package('root')
        conflicting = builder.new_package('conflict')
        bottom1_pkg = builder.new_package('bottom1').conflicts_with(conflicting)
        # Row 1 is simple enough that it collapse into a single option immediately
        # (Ergo eqv_table_reduced_to_one == 1)
        row1 = ['pkg-%s' % x for x in range(1000)]

        root_pkg.depends_on_any_of(*row1)
        for pkg in row1:
            builder.new_package(pkg).depends_on(bottom1_pkg)
        universe, inst_tester = builder.build()

        pkg_row1 = builder.pkg_id(row1[0])

        # all items in a row are eqv.
        for pkg in row1:
            assert universe.are_equivalent(builder.pkg_id(pkg), pkg_row1)

        assert inst_tester.is_installable(root_pkg.pkg_id)
        for line in inst_tester.stats.stats():
            print(line)
        assert inst_tester.stats.eqv_table_times_used == 1
        assert inst_tester.stats.eqv_table_total_number_of_alternatives_eliminated == 999
        assert inst_tester.stats.eqv_table_reduced_to_one == 1

    def test_optimisation_simple_partial_eqv_reduction(self):
        builder = new_pkg_universe_builder()
        root_pkg = builder.new_package('root')
        conflicting = builder.new_package('conflict')
        another_pkg = builder.new_package('another-pkg')
        bottom1_pkg = builder.new_package('bottom1').conflicts_with(conflicting)
        # Row 1 is simple enough that it collapse into a single option immediately
        # but due to "another_pkg" the entire choice is only reduced into two
        row1 = ['pkg-%s' % x for x in range(1000)]

        root_pkg.depends_on_any_of(another_pkg, *row1)
        for pkg in row1:
            builder.new_package(pkg).depends_on(bottom1_pkg)
        universe, inst_tester = builder.build()

        pkg_row1 = builder.pkg_id(row1[0])

        # all items in a row are eqv.
        for pkg in row1:
            assert universe.are_equivalent(builder.pkg_id(pkg), pkg_row1)

        assert inst_tester.is_installable(root_pkg.pkg_id)
        for line in inst_tester.stats.stats():
            print(line)
        assert inst_tester.stats.eqv_table_times_used == 1
        assert inst_tester.stats.eqv_table_total_number_of_alternatives_eliminated == 999
        assert inst_tester.stats.eqv_table_reduced_to_one == 0

    def test_optimisation_simple_zero_eqv_reduction(self):
        builder = new_pkg_universe_builder()
        root_pkg = builder.new_package('root')
        conflicting1 = builder.new_package('conflict1')
        conflicting2 = builder.new_package('conflict2')
        bottom1_pkg = builder.new_package('bottom1').conflicts_with(conflicting1)
        bottom2_pkg = builder.new_package('bottom2').conflicts_with(conflicting2)

        # To trigger a failed reduction, we have to create eqv. packages and ensure that only one
        # of them are in testing.  Furthermore, the choice has to remain, so we create two pairs
        # of them
        pkg1_v1 = builder.new_package('pkg1', version='1.0-1').depends_on(bottom1_pkg)
        pkg1_v2 = builder.new_package('pkg1', version='2.0-1').depends_on(bottom1_pkg).not_in_testing()
        pkg2_v1 = builder.new_package('pkg2', version='1.0-1').depends_on(bottom2_pkg)
        pkg2_v2 = builder.new_package('pkg2', version='2.0-1').depends_on(bottom2_pkg).not_in_testing()

        root_pkg.depends_on_any_of(pkg1_v1, pkg1_v2, pkg2_v1, pkg2_v2)

        universe, inst_tester = builder.build()

        # The packages in the pairs are equivalent, but the two pairs are not
        assert universe.are_equivalent(pkg1_v1.pkg_id, pkg1_v2.pkg_id)
        assert universe.are_equivalent(pkg2_v1.pkg_id, pkg2_v2.pkg_id)
        assert not universe.are_equivalent(pkg1_v1.pkg_id, pkg2_v1.pkg_id)

        assert inst_tester.is_installable(root_pkg.pkg_id)
        for line in inst_tester.stats.stats():
            print(line)
        assert inst_tester.stats.eqv_table_times_used == 1
        assert inst_tester.stats.eqv_table_total_number_of_alternatives_eliminated == 0
        assert inst_tester.stats.eqv_table_reduced_to_one == 0
        assert inst_tester.stats.eqv_table_reduced_by_zero == 1

    def test_solver_recursion_limit(self):
        builder = new_pkg_universe_builder()
        recursion_limit = 200
        pkg_limit = recursion_limit + 20
        orig_limit = sys.getrecursionlimit()
        pkgs = [builder.new_package('pkg-%d' % i) for i in range(pkg_limit)]

        for i, pkg in enumerate(pkgs):
            # Intentionally -1 for the first package (wrap-around)
            ni = i - 1
            pkg.not_in_testing()
            pkg.depends_on(pkgs[ni])

        try:
            sys.setrecursionlimit(recursion_limit)
            universe, inst_tester = builder.build()
            solver = InstallabilitySolver(universe, inst_tester)
            groups = []

            for pkg in pkgs:
                group = (pkg.pkg_id.package_name, {pkg.pkg_id}, set())
                groups.append(group)

            expected = {g[0] for g in groups}
            actual = solver.solve_groups(groups)
            assert actual
            assert expected == set(actual[0])
            assert len(actual) == 1
        finally:
            sys.setrecursionlimit(orig_limit)

    def test_solver_simple_scc(self):
        builder = new_pkg_universe_builder()

        # SCC 1
        pkga = builder.new_package('pkg-a').not_in_testing()
        pkgb = builder.new_package('pkg-b').not_in_testing()
        pkgc = builder.new_package('pkg-c').not_in_testing()

        # SSC 2
        pkgd = builder.new_package('pkg-d').not_in_testing()
        pkge = builder.new_package('pkg-e').not_in_testing()
        pkgf = builder.new_package('pkg-f').not_in_testing()
        pkgg = builder.new_package('pkg-g').not_in_testing()
        pkgh = builder.new_package('pkg-h').not_in_testing()

        # SSC 3
        pkgi = builder.new_package('pkg-i').not_in_testing()

        # SSC 1 dependencies
        pkga.depends_on(pkgb)
        pkgb.depends_on(pkgc).depends_on(pkgd)
        pkgc.depends_on(pkga).depends_on(pkge)

        # SSC 2 dependencies
        pkgd.depends_on(pkgf)
        pkge.depends_on(pkgg).depends_on(pkgd)
        pkgf.depends_on(pkgh)
        pkgg.depends_on(pkgh)
        pkgh.depends_on(pkge).depends_on(pkgi)

        universe, inst_tester = builder.build()
        solver = InstallabilitySolver(universe, inst_tester)
        expected = [
            # SSC 3 first
            {pkgi.pkg_id.package_name},
            # Then SSC 2
            {pkgd.pkg_id.package_name, pkge.pkg_id.package_name, pkgf.pkg_id.package_name,
             pkgg.pkg_id.package_name, pkgh.pkg_id.package_name},
            # Finally SSC 1
            {pkga.pkg_id.package_name, pkgb.pkg_id.package_name, pkgc.pkg_id.package_name},
        ]
        groups = []
        for ssc in expected:
            for node in ssc:
                groups.append((node, {builder.pkg_id(node)}, {}))

        actual = [set(x) for x in solver.solve_groups(groups)]
        print("EXPECTED: %s" % str(expected))
        print("ACTUAL  : %s" % str(actual))
        assert expected == actual

    def test_solver_no_scc_stack_bug(self):
        """
        This whitebox test is designed to trigger a bug in Tarjan's algorithm
        if you omit the "w is on stack of points" check from the pseudo code
        (or it is wrong).  It makes tons of assumptions about how compute_scc
        works, so it is very sensitive to even minor tweaks.

        There is no strongly-connected component in this test, but if we
        trigger the bug, the algorithm will think there is one.
        """

        graph = OrderedDict()

        graph['A'] = {
            'before': ['C', 'B'],
            'after': ['A0'],
        }
        graph['B'] = {
            'before': ['F'],
            'after': ['A'],
        }
        graph['C'] = {
            'before': ['E', 'D'],
            'after': ['A'],
        }
        graph['D'] = {
            'before': [],
            'after': ['C']
        }
        graph['E'] = {
            'before': ['B'],
            'after': ['C']
        }
        graph['F'] = {
            'before': [],
            'after': ['B']
        }
        graph['A0'] = {
            'before': ['A0'],
            'after': []
        }

        # We also assert that the order is correct to ensure that
        # nodes were visited in the order we expected (the bug is
        # visit order sensitive).
        expected = [
            ('F',),
            ('B',),
            ('D',),
            ('E',),
            ('C',),
            ('A',),
            ('A0',)
        ]

        actual = compute_scc(graph)
        print("EXPECTED: %s" % str(expected))
        print("ACTUAL  : %s" % str(actual))
        assert expected == actual


if __name__ == '__main__':
    unittest.main()

