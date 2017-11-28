import unittest
import os

from britney2 import SuiteInfo, SourcePackage
from britney2.excuse import Excuse
from britney2.hints import HintParser
from britney2.policies.policy import AgePolicy, RCBugPolicy, PiupartsPolicy, PolicyVerdict

from . import MockObject, TEST_HINTER, HINTS_ALL, DEFAULT_URGENCY

POLICY_DATA_BASE_DIR = os.path.join(os.path.dirname(__file__), 'policy-test-data')


def initialize_policy(test_name, policy_class, *args, **kwargs):
    test_dir = os.path.join(POLICY_DATA_BASE_DIR, test_name)
    hints = []
    if 'hints' in kwargs:
        hints = kwargs['hints']
        del kwargs['hints']
    options = MockObject(state_dir=test_dir, verbose=0, default_urgency=DEFAULT_URGENCY, **kwargs)
    suite_info = {
        'testing': SuiteInfo('testing', os.path.join(test_dir, 'testing'), ''),
        'unstable': SuiteInfo('unstable', os.path.join(test_dir, 'unstable'), ''),
    }
    policy = policy_class(options, suite_info, *args)
    fake_britney = MockObject(log=lambda x, y='I': None)
    hint_parser = HintParser(fake_britney)
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
    return SourcePackage(version, section, binaries, 'Random tester', False, None, '', '')


def create_policy_objects(source_name, target_version, source_version):
    return (
        create_source_package(target_version),
        create_source_package(source_version),
        create_excuse(source_name),
        {},
    )


def apply_policy(policy, expected_verdict, src_name, *, suite='unstable', source_version='1.0', target_version='2.0'):
    src_t, src_u, excuse, policy_info = create_policy_objects(src_name, source_version, target_version)
    verdict = policy.apply_policy(policy_info, suite, src_name, src_t, src_u, excuse)
    pinfo = policy_info[policy.policy_id]
    assert verdict == expected_verdict
    assert pinfo['verdict'] == expected_verdict.name
    return pinfo


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

if __name__ == '__main__':
    unittest.main()
