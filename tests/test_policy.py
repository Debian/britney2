import apt_pkg
import os
import tempfile
import unittest

from britney2 import Suites, Suite, SuiteClass, SourcePackage, BinaryPackageId, BinaryPackage
from britney2.excuse import Excuse
from britney2.hints import HintParser
from britney2.migrationitem import MigrationItem
from britney2.policies.policy import AgePolicy, RCBugPolicy, PiupartsPolicy, PolicyVerdict
from britney2.policies.autopkgtest import AutopkgtestPolicy

from . import MockObject, TEST_HINTER, HINTS_ALL, DEFAULT_URGENCY, new_pkg_universe_builder

POLICY_DATA_BASE_DIR = os.path.join(os.path.dirname(__file__), 'policy-test-data')
ARCH = 'amd64'


def initialize_policy(test_name, policy_class, *args, **kwargs):
    test_dir = os.path.join(POLICY_DATA_BASE_DIR, test_name)
    debci_data = os.path.join(test_dir, 'debci.json')
    target = 'testing'
    hints = []
    if 'hints' in kwargs:
        hints = kwargs['hints']
        del kwargs['hints']
    options = MockObject(
        state_dir=test_dir,
        verbose=0,
        default_urgency=DEFAULT_URGENCY,
        dry_run = False,
        adt_shared_results_cache = False,
        series = target,
        adt_arches = ARCH,
        architectures = ARCH,
        adt_swift_url = 'file://' + debci_data,
        adt_ci_url = '',
        adt_success_bounty = 3,
        adt_regression_penalty = False,
        adt_retry_url_mech = 'run_id',
        **kwargs)
    suite_info = Suites(
        Suite(SuiteClass.TARGET_SUITE, target, os.path.join(test_dir, target), ''),
        [Suite(SuiteClass.PRIMARY_SOURCE_SUITE, 'unstable', os.path.join(test_dir, 'unstable'), '')],
    )
    MigrationItem.set_suites(suite_info)
    policy = policy_class(options, suite_info, *args)
    fake_britney = MockObject(log=lambda x, y='I': None)
    hint_parser = HintParser()
    policy.initialise(fake_britney)
    policy.register_hints(hint_parser)
    hint_parser.parse_hints(TEST_HINTER, HINTS_ALL, 'test-%s' % test_name, hints)
    policy.hints = hint_parser.hints
    return policy


def create_excuse(name):
    return Excuse(name)


def create_source_package(version, section='devel', binaries=None):
    if binaries is None:
        binaries = []
    return SourcePackage(version, section, binaries, 'Random tester', False, None, None, ['autopkgtest'], [])


def create_bin_package(pkg_id, source_name=None, depends=None, conflicts=None):
    name = pkg_id.package_name
    version = pkg_id.version
    source_version = version
    if source_name is None:
        source_name = name
    return BinaryPackage(
        version,
        'main',
        source_name,
        source_version,
        ARCH,
        None,
        depends,
        conflicts,
        None,
        False,
        pkg_id,
        )


def create_policy_objects(source_name, target_version='1.0', source_version='2.0'):
    return (
        create_source_package(target_version),
        create_source_package(source_version),
        create_excuse(source_name),
        {},
    )


def apply_policy(policy, expected_verdict, src_name, *, suite='unstable', target_version='1.0', source_version='2.0'):
    suite_info = policy.suite_info
    if src_name in suite_info[suite].sources:
        src_u = suite_info[suite].sources[src_name]
        src_t = suite_info.target_suite.sources.get(src_name)
        _, _, excuse, policy_info = create_policy_objects(src_name)
    else:
        src_t, src_u, excuse, policy_info = create_policy_objects(src_name, target_version, source_version)
    suite_info.target_suite.sources[src_name] = src_t
    suite_info[suite].sources[src_name] = src_u
    verdict = policy.apply_policy(policy_info, suite, src_name, src_t, src_u, excuse)
    pinfo = policy_info[policy.policy_id]
    assert verdict == expected_verdict
    assert pinfo['verdict'] == expected_verdict.name
    return pinfo


def build_sources_from_universe_and_inst_tester(policy, pkg_universe, inst_tester, suite='unstable'):
    suite_info = policy.suite_info
    policy.britney._inst_tester = inst_tester
    policy.britney.pkg_universe = pkg_universe
    src_universe = {}
    bin_universe = {}
    src_source = {}
    binaries_t = {}
    binaries_s = {}
    for pkg_id in pkg_universe:
        pkg_name = pkg_id.package_name
        src_universe[pkg_id] = create_source_package(pkg_id.version, binaries=[pkg_id])
        bin_universe[pkg_id] = create_bin_package(pkg_id)
        if inst_tester.is_pkg_in_testing(pkg_id):
            if pkg_name in suite_info.target_suite.sources:
                # sanity check, this shouldn't happen
                raise(KeyError)
            suite_info.target_suite.sources[pkg_name] = src_universe[pkg_id]
            binaries_t.setdefault(ARCH, {}).setdefault(pkg_name, bin_universe[pkg_id])
        # We need to find the highest version of a package to add it to the
        # sources of the source suite
        if pkg_name not in src_source or \
          apt_pkg.version_compare(src_source[pkg_name].version, pkg_id.version) < 0:
            src_source[pkg_name] = pkg_id
    suite_info.target_suite.binaries = binaries_t
    for pkg_id in src_source.values():
        pkg_name = pkg_id.package_name
        suite_info[suite].sources[pkg_name] = src_universe[pkg_id]
        binaries_s.setdefault(ARCH, {}).setdefault(pkg_name, bin_universe[pkg_id])
    suite_info[suite].binaries = binaries_s


class TestRCBugsPolicy(unittest.TestCase):

    def test_no_bugs(self):
        src_name = 'has-no-bugs'
        policy = initialize_policy('rc-bugs/basic', RCBugPolicy)
        bug_policy_info = apply_policy(policy, PolicyVerdict.PASS, src_name)
        assert set(bug_policy_info['unique-source-bugs']) == set()
        assert set(bug_policy_info['unique-target-bugs']) == set()
        assert set(bug_policy_info['shared-bugs']) == set()

    def test_regression(self):
        src_name = 'regression'
        policy = initialize_policy('rc-bugs/basic', RCBugPolicy)
        bug_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_PERMANENTLY, src_name)
        assert set(bug_policy_info['unique-source-bugs']) == {'123458'}
        assert set(bug_policy_info['unique-target-bugs']) == set()
        assert set(bug_policy_info['shared-bugs']) == set()

    def test_regression_but_fixes_more_bugs(self):
        src_name = 'regression-but-fixes-more-bugs'
        policy = initialize_policy('rc-bugs/basic', RCBugPolicy)
        bug_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_PERMANENTLY, src_name)
        assert set(bug_policy_info['unique-source-bugs']) == {'100003'}
        assert set(bug_policy_info['unique-target-bugs']) == {'100001', '100002'}
        assert set(bug_policy_info['shared-bugs']) == {'100000'}

    def test_not_a_regression(self):
        src_name = 'not-a-regression'
        policy = initialize_policy('rc-bugs/basic', RCBugPolicy)
        bug_policy_info = apply_policy(policy, PolicyVerdict.PASS, src_name)
        assert set(bug_policy_info['unique-source-bugs']) == set()
        assert set(bug_policy_info['unique-target-bugs']) == set()
        assert set(bug_policy_info['shared-bugs']) == {'123457'}

    def test_improvement(self):
        src_name = 'fixes-bug'
        policy = initialize_policy('rc-bugs/basic', RCBugPolicy)
        bug_policy_info = apply_policy(policy, PolicyVerdict.PASS, src_name)
        assert set(bug_policy_info['unique-source-bugs']) == set()
        assert set(bug_policy_info['unique-target-bugs']) == {'123456'}
        assert set(bug_policy_info['shared-bugs']) == set()

    def test_regression_with_hint(self):
        src_name = 'regression'
        hints = ['ignore-rc-bugs 123458 regression/2.0']
        policy = initialize_policy('rc-bugs/basic', RCBugPolicy, hints=hints)
        bug_policy_info = apply_policy(policy, PolicyVerdict.PASS_HINTED, src_name)
        assert set(bug_policy_info['ignored-bugs']['bugs']) == {'123458'}
        assert bug_policy_info['ignored-bugs']['issued-by'] == TEST_HINTER
        assert set(bug_policy_info['unique-source-bugs']) == set()
        assert set(bug_policy_info['unique-target-bugs']) == set()
        assert set(bug_policy_info['shared-bugs']) == set()

    def test_regression_but_fixes_more_bugs_bad_hint(self):
        src_name = 'regression-but-fixes-more-bugs'
        hints = ['ignore-rc-bugs 100000 regression-but-fixes-more-bugs/2.0']
        policy = initialize_policy('rc-bugs/basic', RCBugPolicy, hints=hints)
        bug_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_PERMANENTLY, src_name)
        assert set(bug_policy_info['unique-source-bugs']) == {'100003'}
        assert set(bug_policy_info['unique-target-bugs']) == {'100001', '100002'}
        assert set(bug_policy_info['ignored-bugs']['bugs']) == {'100000'}
        assert bug_policy_info['ignored-bugs']['issued-by'] == TEST_HINTER
        assert set(bug_policy_info['shared-bugs']) == set()


class TestAgePolicy(unittest.TestCase):

    DEFAULT_MIN_DAYS = {
        'emergency': 0,
        'critical': 0,
        'high': 2,
        'medium': 5,
        'low': 10,
    }

    @classmethod
    def reset_age(cls, policy, effective_date=10):
        policy._date_now = effective_date

    def test_missing_age_file(self):
        age_file = os.path.join(POLICY_DATA_BASE_DIR, 'age', 'missing-age-file', 'age-policy-dates')
        assert not os.path.exists(age_file)

        try:
            src_name = 'unlisted-source-package'
            policy = initialize_policy('age/missing-age-file', AgePolicy, TestAgePolicy.DEFAULT_MIN_DAYS)
            age_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_TEMPORARILY, src_name)
            assert os.path.exists(age_file)
            assert age_policy_info['age-requirement'] == TestAgePolicy.DEFAULT_MIN_DAYS[DEFAULT_URGENCY]
            assert age_policy_info['current-age'] == 0
        finally:
            if os.path.exists(age_file):
                os.unlink(age_file)

    def test_age_new(self):
        src_name = 'unlisted-source-package'
        policy = initialize_policy('age/basic', AgePolicy, TestAgePolicy.DEFAULT_MIN_DAYS)
        age_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_TEMPORARILY, src_name)
        assert age_policy_info['age-requirement'] == TestAgePolicy.DEFAULT_MIN_DAYS[DEFAULT_URGENCY]
        assert age_policy_info['current-age'] == 0

    def test_age_urgented(self):
        src_name = 'unlisted-source-package'
        policy = initialize_policy('age/basic', AgePolicy, TestAgePolicy.DEFAULT_MIN_DAYS,
                                   hints=['urgent unlisted-source-package/2.0'])
        age_policy_info = apply_policy(policy, PolicyVerdict.PASS_HINTED, src_name)
        assert age_policy_info['age-requirement'] == TestAgePolicy.DEFAULT_MIN_DAYS[DEFAULT_URGENCY]
        assert age_policy_info['current-age'] == 0
        assert age_policy_info['age-requirement-reduced']['new-requirement'] == 0
        assert age_policy_info['age-requirement-reduced']['changed-by'] == TEST_HINTER

    def test_age_old_version_aged(self):
        src_name = 'out-of-date-version'
        policy = initialize_policy('age/basic', AgePolicy, TestAgePolicy.DEFAULT_MIN_DAYS)
        self.reset_age(policy)
        age_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_TEMPORARILY, src_name)
        assert age_policy_info['age-requirement'] == TestAgePolicy.DEFAULT_MIN_DAYS[DEFAULT_URGENCY]
        assert age_policy_info['current-age'] == 0

    def test_age_almost_aged(self):
        src_name = 'almost-aged-properly'
        policy = initialize_policy('age/basic', AgePolicy, TestAgePolicy.DEFAULT_MIN_DAYS)
        self.reset_age(policy)
        age_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_TEMPORARILY, src_name)
        assert age_policy_info['age-requirement'] == TestAgePolicy.DEFAULT_MIN_DAYS[DEFAULT_URGENCY]
        assert age_policy_info['current-age'] == 4

    def test_age_aged_properly(self):
        src_name = 'aged-properly'
        policy = initialize_policy('age/basic', AgePolicy, TestAgePolicy.DEFAULT_MIN_DAYS)
        self.reset_age(policy)
        age_policy_info = apply_policy(policy, PolicyVerdict.PASS, src_name)
        assert age_policy_info['age-requirement'] == TestAgePolicy.DEFAULT_MIN_DAYS[DEFAULT_URGENCY]
        assert age_policy_info['current-age'] == 5


class TestPiupartsPolicy(unittest.TestCase):

    def test_passes(self):
        src_name = 'pass'
        policy = initialize_policy('piuparts/basic', PiupartsPolicy)
        piu_policy_info = apply_policy(policy, PolicyVerdict.PASS, src_name)
        assert piu_policy_info['test-results'] == 'pass'
        assert piu_policy_info['piuparts-test-url'] == 'https://piuparts.debian.org/sid/source/p/pass.html'

    def test_regression(self):
        src_name = 'regression'
        policy = initialize_policy('piuparts/basic', PiupartsPolicy)
        piu_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_PERMANENTLY, src_name)
        assert piu_policy_info['test-results'] == 'regression'
        assert piu_policy_info['piuparts-test-url'] == 'https://piuparts.debian.org/sid/source/r/regression.html'

    def test_regression_hinted(self):
        src_name = 'regression'
        hints = ['ignore-piuparts regression/2.0']
        policy = initialize_policy('piuparts/basic', PiupartsPolicy, hints=hints)
        piu_policy_info = apply_policy(policy, PolicyVerdict.PASS_HINTED, src_name)
        assert piu_policy_info['test-results'] == 'regression'
        assert piu_policy_info['piuparts-test-url'] == 'https://piuparts.debian.org/sid/source/r/regression.html'
        assert piu_policy_info['ignored-piuparts']['issued-by'] == TEST_HINTER

    def test_not_tested_yet(self):
        src_name = 'not-tested-yet'
        policy = initialize_policy('piuparts/basic', PiupartsPolicy)
        piu_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_TEMPORARILY, src_name)
        assert piu_policy_info['test-results'] == 'waiting-for-test-results'
        assert piu_policy_info['piuparts-test-url'] == 'https://piuparts.debian.org/sid/source/n/not-tested-yet.html'

    def test_failed_not_regression(self):
        src_name = 'failed-not-regression'
        policy = initialize_policy('piuparts/basic', PiupartsPolicy)
        piu_policy_info = apply_policy(policy, PolicyVerdict.PASS, src_name)
        assert piu_policy_info['test-results'] == 'failed'
        assert piu_policy_info['piuparts-test-url'] == 'https://piuparts.debian.org/sid/source/f/failed-not-regression.html'


pkg1 = BinaryPackageId('pkg', '1.0', ARCH)
pkg2 = BinaryPackageId('pkg', '2.0', ARCH)
inter =  BinaryPackageId('inter', '1.0', ARCH)
broken1 = BinaryPackageId('broken', '1.0', ARCH)
broken2 = BinaryPackageId('broken', '2.0', ARCH)
dummy = BinaryPackageId('dummy', '1', ARCH)

builder = new_pkg_universe_builder()
builder.new_package(pkg1).in_testing()
builder.new_package(pkg2).not_in_testing()
simple_universe, simple_inst_tester = builder.build()

builder_breaks = new_pkg_universe_builder()
builder_breaks.new_package(broken1).in_testing()
builder_breaks.new_package(broken2).not_in_testing()
builder_breaks.new_package(inter).in_testing().depends_on_any_of(broken1, broken2)
builder_breaks.new_package(pkg1).depends_on(inter).in_testing()
builder_breaks.new_package(pkg2).depends_on(inter).not_in_testing().conflicts_with(broken1)
breaks_universe, breaks_inst_tester = builder_breaks.build()

class TestAutopkgtestPolicy(unittest.TestCase):
    import apt_pkg
    apt_pkg.init()

    def read_amqp(self):
        with open(self.amqp.replace('file://', ''), 'r+') as f:
            amqp = f.read()
        return amqp

    def setUp(self):
        self.amqp = 'file://' + tempfile.NamedTemporaryFile(mode='w', delete=False).name

    def tearDown(self):
        os.unlink(self.amqp.replace('file://', ''))

    def test_pass_to_pass(self):
        src_name = 'pkg'
        policy = initialize_policy('autopkgtest/pass-to-pass', AutopkgtestPolicy, adt_amqp=self.amqp)
        build_sources_from_universe_and_inst_tester(policy, simple_universe, simple_inst_tester)
        autopkgtest_policy_info = apply_policy(policy, PolicyVerdict.PASS, src_name)
        assert autopkgtest_policy_info[src_name + '/2.0'][ARCH][0] == 'PASS'
        assert autopkgtest_policy_info[src_name + '/2.0'][ARCH][1] == 'data/autopkgtest/testing/amd64/' + src_name[0] + '/' + src_name + '/2/log.gz'
        assert autopkgtest_policy_info[src_name + '/2.0'][ARCH][2] == 'packages/' + src_name[0] + '/' + src_name + '/testing/amd64'
        amqp = self.read_amqp()
        assert len(amqp) == 0

    def test_pass_to_fail(self):
        src_name = 'pkg'
        policy = initialize_policy('autopkgtest/pass-to-fail', AutopkgtestPolicy, adt_amqp=self.amqp, adt_retry_older_than=1)
        build_sources_from_universe_and_inst_tester(policy, simple_universe, simple_inst_tester)
        autopkgtest_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_PERMANENTLY, src_name)
        assert autopkgtest_policy_info[src_name + '/2.0'][ARCH][0] == 'REGRESSION'
        assert autopkgtest_policy_info[src_name + '/2.0'][ARCH][1] == 'data/autopkgtest/testing/amd64/' + src_name[0] + '/' + src_name + '/2/log.gz'
        assert autopkgtest_policy_info[src_name + '/2.0'][ARCH][2] == 'packages/' + src_name[0] + '/' + src_name + '/testing/amd64'
        amqp = self.read_amqp()
        assert len(amqp) == 0

    def test_pass_to_neutral(self):
        src_name = 'pkg'
        policy = initialize_policy('autopkgtest/pass-to-neutral', AutopkgtestPolicy, adt_amqp=self.amqp)
        build_sources_from_universe_and_inst_tester(policy, simple_universe, simple_inst_tester)
        autopkgtest_policy_info = apply_policy(policy, PolicyVerdict.PASS, src_name)
        assert autopkgtest_policy_info[src_name + '/2.0'][ARCH][0] == 'NEUTRAL'
        assert autopkgtest_policy_info[src_name + '/2.0'][ARCH][1] == 'data/autopkgtest/testing/amd64/' + src_name[0] + '/' + src_name + '/2/log.gz'
        assert autopkgtest_policy_info[src_name + '/2.0'][ARCH][2] == 'packages/' + src_name[0] + '/' + src_name + '/testing/amd64'
        amqp = self.read_amqp()
        assert len(amqp) == 0

    def test_new(self):
        src_name = 'pkg'
        builder_new = new_pkg_universe_builder()
        builder_new.new_package(pkg2).not_in_testing()
        builder_new.new_package(dummy).in_testing()
        new_universe, new_inst_tester = builder_new.build()
        policy = initialize_policy('autopkgtest/new', AutopkgtestPolicy, adt_amqp=self.amqp)
        build_sources_from_universe_and_inst_tester(policy, new_universe, new_inst_tester)
        autopkgtest_policy_info = apply_policy(policy, PolicyVerdict.PASS, src_name)
        assert autopkgtest_policy_info[src_name][ARCH][0] == 'RUNNING-ALWAYSFAIL'
        assert autopkgtest_policy_info[src_name][ARCH][1] == 'status/pending'
        assert autopkgtest_policy_info[src_name][ARCH][2] == 'packages/' + src_name[0] + '/' + src_name + '/testing/amd64'
        amqp = self.read_amqp()
        assert amqp[0:-1] == 'debci-testing-amd64:' + src_name + ' {"triggers": ["' + src_name + '/2.0"]}'

    def test_pass_to_new(self):
        src_name = 'pkg'
        policy = initialize_policy('autopkgtest/pass-to-new', AutopkgtestPolicy, adt_amqp=self.amqp)
        build_sources_from_universe_and_inst_tester(policy, simple_universe, simple_inst_tester)
        autopkgtest_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_TEMPORARILY, src_name)
        assert autopkgtest_policy_info[src_name][ARCH][0] == 'RUNNING'
        assert autopkgtest_policy_info[src_name][ARCH][1] == 'status/pending'
        assert autopkgtest_policy_info[src_name][ARCH][2] == 'packages/' + src_name[0] + '/' + src_name + '/testing/amd64'
        amqp = self.read_amqp()
        assert amqp[0:-1] == 'debci-testing-amd64:' + src_name + ' {"triggers": ["' + src_name + '/2.0"]}'

    def test_fail_to_new(self):
        src_name = 'pkg'
        policy = initialize_policy('autopkgtest/fail-to-new', AutopkgtestPolicy, adt_amqp=self.amqp)
        build_sources_from_universe_and_inst_tester(policy, simple_universe, simple_inst_tester)
        autopkgtest_policy_info = apply_policy(policy, PolicyVerdict.PASS, src_name)
        assert autopkgtest_policy_info[src_name][ARCH][0] == 'RUNNING-ALWAYSFAIL'
        assert autopkgtest_policy_info[src_name][ARCH][1] == 'status/pending'
        assert autopkgtest_policy_info[src_name][ARCH][2] == 'packages/' + src_name[0] + '/' + src_name + '/testing/amd64'
        amqp = self.read_amqp()
        assert amqp[0:-1] == 'debci-testing-amd64:' + src_name + ' {"triggers": ["' + src_name + '/2.0"]}'

    def test_neutral_to_new(self):
        src_name = 'pkg'
        policy = initialize_policy('autopkgtest/neutral-to-new', AutopkgtestPolicy, adt_amqp=self.amqp)
        build_sources_from_universe_and_inst_tester(policy, simple_universe, simple_inst_tester)
        autopkgtest_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_TEMPORARILY, src_name)
        assert autopkgtest_policy_info[src_name][ARCH][0] == 'RUNNING'
        assert autopkgtest_policy_info[src_name][ARCH][1] == 'status/pending'
        assert autopkgtest_policy_info[src_name][ARCH][2] == 'packages/' + src_name[0] + '/' + src_name + '/testing/amd64'
        amqp = self.read_amqp()
        assert amqp[0:-1] == 'debci-testing-amd64:' + src_name + ' {"triggers": ["' + src_name + '/2.0"]}'

    def test_neutral_to_fail(self):
        src_name = 'pkg'
        policy = initialize_policy('autopkgtest/neutral-to-fail', AutopkgtestPolicy, adt_amqp=self.amqp, adt_retry_older_than=1)
        build_sources_from_universe_and_inst_tester(policy, simple_universe, simple_inst_tester)
        autopkgtest_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_PERMANENTLY, src_name)
        assert autopkgtest_policy_info[src_name + '/2.0'][ARCH][0] == 'REGRESSION'
        assert autopkgtest_policy_info[src_name + '/2.0'][ARCH][1] == 'data/autopkgtest/testing/amd64/' + src_name[0] + '/' + src_name + '/2/log.gz'
        assert autopkgtest_policy_info[src_name + '/2.0'][ARCH][2] == 'packages/' + src_name[0] + '/' + src_name + '/testing/amd64'
        amqp = self.read_amqp()
        assert len(amqp) == 0

    def test_pass_to_new_with_breaks(self):
        src_name = 'pkg'
        policy = initialize_policy('autopkgtest/pass-to-new-with-breaks', AutopkgtestPolicy, adt_amqp=self.amqp)
        build_sources_from_universe_and_inst_tester(policy, breaks_universe, breaks_inst_tester)
        autopkgtest_policy_info = apply_policy(policy, PolicyVerdict.REJECTED_TEMPORARILY, src_name)
        assert autopkgtest_policy_info[src_name][ARCH][0] == 'RUNNING'
        assert autopkgtest_policy_info[src_name][ARCH][1] == 'status/pending'
        assert autopkgtest_policy_info[src_name][ARCH][2] == 'packages/' + src_name[0] + '/' + src_name + '/testing/amd64'
        amqp = self.read_amqp()
        assert amqp[0:-1] == 'debci-testing-amd64:' + src_name + ' {"triggers": ["' + src_name + '/2.0 broken/2.0"]}'


if __name__ == '__main__':
    unittest.main()
