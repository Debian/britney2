import json
import logging
import os
import re
import time
from enum import IntEnum, unique
from collections import defaultdict
from urllib.parse import quote

import apt_pkg

from britney2 import SuiteClass
from britney2.hints import Hint, split_into_one_hint_per_package
from britney2.inputs.suiteloader import SuiteContentLoader
from britney2.policies import PolicyVerdict, ApplySrcPolicy
from britney2.utils import get_dependency_solvers, compute_item_name
from britney2 import DependencyType


class PolicyEngine(object):
    def __init__(self):
        self._policies = []

    def add_policy(self, policy):
        self._policies.append(policy)

    def register_policy_hints(self, hint_parser):
        for policy in self._policies:
            policy.register_hints(hint_parser)

    def initialise(self, britney, hints):
        for policy in self._policies:
            policy.hints = hints
            policy.initialise(britney)

    def save_state(self, britney):
        for policy in self._policies:
            policy.save_state(britney)

    def apply_src_policies(self, source_suite, src, source_t, source_u, excuse):
        excuse_verdict = excuse.policy_verdict
        suite_name = source_suite.name
        suite_class = source_suite.suite_class
        for policy in self._policies:
            pinfo = {}
            policy_verdict = PolicyVerdict.NOT_APPLICABLE
            if suite_class in policy.applicable_suites:
                if policy.src_policy.run_arch:
                    for arch in policy.options.architectures:
                        v = policy.apply_srcarch_policy_impl(pinfo, suite_name, src, arch, source_t, source_u, excuse)
                        if v.value > policy_verdict.value:
                            policy_verdict = v
                if policy.src_policy.run_src:
                    v = policy.apply_src_policy_impl(pinfo, suite_name, src, source_t, source_u, excuse)
                    if v.value > policy_verdict.value:
                        policy_verdict = v
            # The base policy provides this field, so the subclass should leave it blank
            assert 'verdict' not in pinfo
            if policy_verdict != PolicyVerdict.NOT_APPLICABLE:
                excuse.policy_info[policy.policy_id] = pinfo
                pinfo['verdict'] = policy_verdict.name
                if policy_verdict.value > excuse_verdict.value:
                    excuse_verdict = policy_verdict
        excuse.policy_verdict = excuse_verdict

    def apply_srcarch_policies(self, source_suite, src, arch, source_t, source_u, excuse):
        excuse_verdict = excuse.policy_verdict
        suite_name = source_suite.name
        suite_class = source_suite.suite_class
        for policy in self._policies:
            pinfo = {}
            if suite_class in policy.applicable_suites:
                policy_verdict = policy.apply_srcarch_policy_impl(pinfo, suite_name, src, arch, source_t, source_u, excuse)
                if policy_verdict.value > excuse_verdict.value:
                    excuse_verdict = policy_verdict
                # The base policy provides this field, so the subclass should leave it blank
                assert 'verdict' not in pinfo
                if policy_verdict != PolicyVerdict.NOT_APPLICABLE:
                    excuse.policy_info[policy.policy_id] = pinfo
                    pinfo['verdict'] = policy_verdict.name
        excuse.policy_verdict = excuse_verdict


class BasePolicy(object):

    def __init__(self, policy_id, options, suite_info, applicable_suites, src_policy = ApplySrcPolicy.RUN_SRC):
        """The BasePolicy constructor

        :param policy_id An string identifying the policy.  It will
        determine the key used for the excuses.yaml etc.

        :param options The options member of Britney with all the
        config options.

        :param applicable_suites A set of suite classes where this
        policy applies.
        """
        self.policy_id = policy_id
        self.options = options
        self.suite_info = suite_info
        self.applicable_suites = applicable_suites
        self.src_policy = src_policy
        self.hints = None
        logger_name = ".".join((self.__class__.__module__, self.__class__.__name__))
        self.logger = logging.getLogger(logger_name)

    @property
    def state_dir(self):
        return self.options.state_dir

    def register_hints(self, hint_parser):  # pragma: no cover
        """Register new hints that this policy accepts

        :param hint_parser: An instance of HintParser (see HintParser.register_hint_type)
        """
        pass

    def initialise(self, britney):  # pragma: no cover
        """Called once to make the policy initialise any data structures

        This is useful for e.g. parsing files or other "heavy do-once" work.

        :param britney This is the instance of the "Britney" class.
        """
        pass

    def save_state(self, britney):  # pragma: no cover
        """Called once at the end of the run to make the policy save any persistent data

        Note this will *not* be called for "dry-runs" as such runs should not change
        the state.

        :param britney This is the instance of the "Britney" class.
        """
        pass

    def apply_src_policy_impl(self, policy_info, suite, source_name, source_data_tdist, source_data_srcdist, excuse):  # pragma: no cover
        """Apply a policy on a given source migration

        Britney will call this method on a given source package, when
        Britney is considering to migrate it from the given source
        suite to the target suite.  The policy will then evaluate the
        the migration and then return a verdict.

        :param policy_info A dictionary of all policy results.  The
        policy can add a value stored in a key related to its name.
        (e.g. policy_info['age'] = {...}).  This will go directly into
        the "excuses.yaml" output.

        :param suite The name of the suite from where the source is
        migrating from.

        :param source_data_tdist Information about the source package
        in the target distribution (e.g. "testing").  This is the
        data structure in source_suite.sources[source_name]

        :param source_data_srcdist Information about the source
        package in the source distribution (e.g. "unstable" or "tpu").
        This is the data structure in target_suite.sources[source_name]

        :return A Policy Verdict (e.g. PolicyVerdict.PASS)
        """
        return PolicyVerdict.NOT_APPLICABLE

    def apply_srcarch_policy_impl(self, policy_info, suite, source_name, arch, source_data_tdist, source_data_srcdist, excuse):
        """Apply a policy on a given binary migration

        Britney will call this method on binaries from a given source package
        on a given architecture, when Britney is considering to migrate them
        from the given source suite to the target suite.  The policy will then
        evaluate the the migration and then return a verdict.

        :param policy_info A dictionary of all policy results.  The
        policy can add a value stored in a key related to its name.
        (e.g. policy_info['age'] = {...}).  This will go directly into
        the "excuses.yaml" output.

        :param suite The name of the suite from where the source is
        migrating from.

        :param source_data_tdist Information about the source package
        in the target distribution (e.g. "testing").  This is the
        data structure in source_suite.sources[source_name]

        :param source_data_srcdist Information about the source
        package in the source distribution (e.g. "unstable" or "tpu").
        This is the data structure in target_suite.sources[source_name]

        :return A Policy Verdict (e.g. PolicyVerdict.PASS)
        """
        # if the policy doesn't implement this function, assume it's OK
        return PolicyVerdict.NOT_APPLICABLE


class SimplePolicyHint(Hint):

    def __init__(self, user, hint_type, policy_parameter, packages):
        super().__init__(user, hint_type, packages)
        self._policy_parameter = policy_parameter

    def __eq__(self, other):
        if self.type != other.type or self._policy_parameter != other._policy_parameter:
            return False
        return super().__eq__(other)

    def str(self):
        return '%s %s %s' % (self._type, str(self._policy_parameter), ' '.join(x.name for x in self._packages))


class AgeDayHint(SimplePolicyHint):

    @property
    def days(self):
        return self._policy_parameter


class IgnoreRCBugHint(SimplePolicyHint):

    @property
    def ignored_rcbugs(self):
        return self._policy_parameter


def simple_policy_hint_parser_function(class_name, converter):
    def f(mi_factory, hints, who, hint_name, policy_parameter, *args):
        for item in mi_factory.parse_items(*args):
            hints.add_hint(class_name(who, hint_name, converter(policy_parameter), [item]))
    return f


class AgePolicy(BasePolicy):
    """Configurable Aging policy for source migrations

    The AgePolicy will let packages stay in the source suite for a pre-defined
    amount of days before letting migrate (based on their urgency, if any).

    The AgePolicy's decision is influenced by the following:

    State files:
     * ${STATE_DIR}/age-policy-urgencies: File containing urgencies for source
       packages. Note that urgencies are "sticky" and the most "urgent" urgency
       will be used (i.e. the one with lowest age-requirements).
       - This file needs to be updated externally, if the policy should take
         urgencies into consideration.  If empty (or not updated), the policy
         will simply use the default urgency (see the "Config" section below)
       - In Debian, these values are taken from the .changes file, but that is
         not a requirement for Britney.
     * ${STATE_DIR}/age-policy-dates: File containing the age of all source
       packages.
       - The policy will automatically update this file.
    Config:
     * DEFAULT_URGENCY: Name of the urgency used for packages without an urgency
       (or for unknown urgencies).  Will also  be used to set the "minimum"
       aging requirements for packages not in the target suite.
     * MINDAYS_<URGENCY>: The age-requirements in days for packages with the
       given urgency.
       - Commonly used urgencies are: low, medium, high, emergency, critical
    Hints:
     * urgent <source>/<version>: Disregard the age requirements for a given
       source/version.
     * age-days X <source>/<version>: Set the age requirements for a given
       source/version to X days.  Note that X can exceed the highest
       age-requirement normally given.

    """

    def __init__(self, options, suite_info, mindays):
        super().__init__('age', options, suite_info, {SuiteClass.PRIMARY_SOURCE_SUITE})
        self._min_days = mindays
        self._min_days_default = None  # initialised later
        # britney's "day" begins at 7pm (we want aging to occur in the 22:00Z run and we run Britney 2-4 times a day)
        # NB: _date_now is used in tests
        time_now = time.time()
        if hasattr(self.options, 'fake_runtime'):
            time_now = int(self.options.fake_runtime)
            self.logger.info("overriding runtime with fake_runtime %d"%time_now)

        self._date_now = int(((time_now / (60*60)) - 19) / 24)
        self._dates = {}
        self._urgencies = {}
        self._default_urgency = self.options.default_urgency
        self._penalty_immune_urgencies = frozenset()
        if hasattr(self.options, 'no_penalties'):
            self._penalty_immune_urgencies = frozenset(x.strip() for x in self.options.no_penalties.split())
        self._bounty_min_age = None  # initialised later

    def register_hints(self, hint_parser):
        hint_parser.register_hint_type('age-days', simple_policy_hint_parser_function(AgeDayHint, int), min_args=2)
        hint_parser.register_hint_type('urgent', split_into_one_hint_per_package)

    def initialise(self, britney):
        super().initialise(britney)
        self._read_dates_file()
        self._read_urgencies_file()
        if self._default_urgency not in self._min_days:  # pragma: no cover
            raise ValueError("Missing age-requirement for default urgency (MINDAYS_%s)" % self._default_urgency)
        self._min_days_default = self._min_days[self._default_urgency]
        try:
            self._bounty_min_age = int(self.options.bounty_min_age)
        except ValueError:
            if self.options.bounty_min_age in self._min_days:
                self._bounty_min_age = self._min_days[self.options.bounty_min_age]
            else:  # pragma: no cover
                raise ValueError('Please fix BOUNTY_MIN_AGE in the britney configuration')
        except AttributeError:
            # The option wasn't defined in the configuration
            self._bounty_min_age = 0

    def save_state(self, britney):
        super().save_state(britney)
        self._write_dates_file()

    def apply_src_policy_impl(self, age_info, suite, source_name, source_data_tdist, source_data_srcdist, excuse):
        # retrieve the urgency for the upload, ignoring it if this is a NEW package
        # (not present in the target suite)
        urgency = self._urgencies.get(source_name, self._default_urgency)

        if urgency not in self._min_days:
            age_info['unknown-urgency'] = urgency
            urgency = self._default_urgency

        if not source_data_tdist:
            if self._min_days[urgency] < self._min_days_default:
                age_info['urgency-reduced'] = {
                    'from': urgency,
                    'to': self._default_urgency,
                }
                urgency = self._default_urgency

        if source_name not in self._dates:
            self._dates[source_name] = (source_data_srcdist.version, self._date_now)
        elif self._dates[source_name][0] != source_data_srcdist.version:
            self._dates[source_name] = (source_data_srcdist.version, self._date_now)

        days_old = self._date_now - self._dates[source_name][1]
        min_days = self._min_days[urgency]
        for bounty in excuse.bounty:
            self.logger.info('Applying bounty for %s granted by %s: %d days',
                             source_name, bounty, excuse.bounty[bounty])
            excuse.addhtml('Required age reduced by %d days because of %s' %
                         (excuse.bounty[bounty], bounty))
            min_days -= excuse.bounty[bounty]
        if urgency not in self._penalty_immune_urgencies:
            for penalty in excuse.penalty:
                self.logger.info('Applying penalty for %s given by %s: %d days',
                                 source_name, penalty, excuse.penalty[penalty])
                excuse.addhtml('Required age increased by %d days because of %s' %
                         (excuse.penalty[penalty], penalty))
                min_days += excuse.penalty[penalty]

        # the age in BOUNTY_MIN_AGE can be higher than the one associated with
        # the real urgency, so don't forget to take it into account
        bounty_min_age =  min(self._bounty_min_age, self._min_days[urgency])
        if min_days < bounty_min_age:
            min_days = bounty_min_age
            excuse.addhtml('Required age is not allowed to drop below %d days' % min_days)
        age_info['age-requirement'] = min_days
        age_info['current-age'] = days_old

        for age_days_hint in self.hints.search('age-days', package=source_name,
                                               version=source_data_srcdist.version):
            new_req = age_days_hint.days
            age_info['age-requirement-reduced'] = {
                'new-requirement': new_req,
                'changed-by': age_days_hint.user
            }
            min_days = new_req

        res = PolicyVerdict.PASS

        if days_old < min_days:
            urgent_hints = self.hints.search('urgent', package=source_name,
                                             version=source_data_srcdist.version)
            if urgent_hints:
                age_info['age-requirement-reduced'] = {
                    'new-requirement': 0,
                    'changed-by': urgent_hints[0].user
                }
                res = PolicyVerdict.PASS_HINTED
            else:
                res = PolicyVerdict.REJECTED_TEMPORARILY

        # update excuse
        age_hint = age_info.get('age-requirement-reduced', None)
        age_min_req = age_info['age-requirement']
        if age_hint:
            new_req = age_hint['new-requirement']
            who = age_hint['changed-by']
            if new_req:
                excuse.addhtml("Overriding age needed from %d days to %d by %s" % (
                    age_min_req, new_req, who))
                age_min_req = new_req
            else:
                excuse.addhtml("Too young, but urgency pushed by %s" % who)
        excuse.setdaysold(age_info['current-age'], age_min_req)

        return res

    def _read_dates_file(self):
        """Parse the dates file"""
        dates = self._dates
        fallback_filename = os.path.join(self.suite_info.target_suite.path, 'Dates')
        using_new_name = False
        try:
            filename = os.path.join(self.state_dir, 'age-policy-dates')
            if not os.path.exists(filename) and os.path.exists(fallback_filename):
                filename = fallback_filename
            else:
                using_new_name = True
        except AttributeError:
            if os.path.exists(fallback_filename):
                filename = fallback_filename
            else:
                raise RuntimeError("Please set STATE_DIR in the britney configuration")

        try:
            with open(filename, encoding='utf-8') as fd:
                for line in fd:
                    if line.startswith('#'):
                        # Ignore comment lines (mostly used for tests)
                        continue
                    # <source> <version> <date>)
                    l = line.split()
                    if len(l) != 3:  # pragma: no cover
                        continue
                    try:
                        dates[l[0]] = (l[1], int(l[2]))
                    except ValueError:  # pragma: no cover
                        pass
        except FileNotFoundError:
            if not using_new_name:
                # If we using the legacy name, then just give up
                raise
            self.logger.info("%s does not appear to exist.  Creating it", filename)
            with open(filename, mode='x', encoding='utf-8'):
                pass

    def _read_urgencies_file(self):
        urgencies = self._urgencies
        min_days_default = self._min_days_default
        fallback_filename = os.path.join(self.suite_info.target_suite.path, 'Urgency')
        try:
            filename = os.path.join(self.state_dir, 'age-policy-urgencies')
            if not os.path.exists(filename) and os.path.exists(fallback_filename):
                filename = fallback_filename
        except AttributeError:
            filename = fallback_filename

        sources_s = self.suite_info.primary_source_suite.sources
        sources_t = self.suite_info.target_suite.sources

        with open(filename, errors='surrogateescape', encoding='ascii') as fd:
            for line in fd:
                if line.startswith('#'):
                    # Ignore comment lines (mostly used for tests)
                    continue
                # <source> <version> <urgency>
                l = line.split()
                if len(l) != 3:
                    continue

                # read the minimum days associated with the urgencies
                urgency_old = urgencies.get(l[0], None)
                mindays_old = self._min_days.get(urgency_old, 1000)
                mindays_new = self._min_days.get(l[2], min_days_default)

                # if the new urgency is lower (so the min days are higher), do nothing
                if mindays_old <= mindays_new:
                    continue

                # if the package exists in the target suite and it is more recent, do nothing
                tsrcv = sources_t.get(l[0], None)
                if tsrcv and apt_pkg.version_compare(tsrcv.version, l[1]) >= 0:
                    continue

                # if the package doesn't exist in the primary source suite or it is older, do nothing
                usrcv = sources_s.get(l[0], None)
                if not usrcv or apt_pkg.version_compare(usrcv.version, l[1]) < 0:
                    continue

                # update the urgency for the package
                urgencies[l[0]] = l[2]

    def _write_dates_file(self):
        dates = self._dates
        try:
            directory = self.state_dir
            basename = 'age-policy-dates'
            old_file = os.path.join(self.suite_info.target_suite.path, 'Dates')
        except AttributeError:
            directory = self.suite_info.target_suite.path
            basename = 'Dates'
            old_file = None
        filename = os.path.join(directory, basename)
        filename_tmp = os.path.join(directory, '%s_new' % basename)
        with open(filename_tmp, 'w', encoding='utf-8') as fd:
            for pkg in sorted(dates):
                version, date = dates[pkg]
                fd.write("%s %s %d\n" % (pkg, version, date))
        os.rename(filename_tmp, filename)
        if old_file is not None and os.path.exists(old_file):
            self.logger.info("Removing old age-policy-dates file %s", old_file)
            os.unlink(old_file)


class RCBugPolicy(BasePolicy):
    """RC bug regression policy for source migrations

    The RCBugPolicy will read provided list of RC bugs and block any
    source upload that would introduce a *new* RC bug in the target
    suite.

    The RCBugPolicy's decision is influenced by the following:

    State files:
     * ${STATE_DIR}/rc-bugs-${SUITE_NAME}: File containing RC bugs for packages in
       the given suite (one for both primary source suite and the target sutie is
       needed).
       - These files need to be updated externally.
    """

    def __init__(self, options, suite_info):
        super().__init__('rc-bugs', options, suite_info, {SuiteClass.PRIMARY_SOURCE_SUITE})
        self._bugs = {}

    def register_hints(self, hint_parser):
        f = simple_policy_hint_parser_function(IgnoreRCBugHint, lambda x: frozenset(x.split(',')))
        hint_parser.register_hint_type('ignore-rc-bugs',
                                       f,
                                       min_args=2)

    def initialise(self, britney):
        super().initialise(britney)
        source_suite = self.suite_info.primary_source_suite
        target_suite = self.suite_info.target_suite
        fallback_unstable = os.path.join(source_suite.path, 'BugsV')
        fallback_testing = os.path.join(target_suite.path, 'BugsV')
        try:
            filename_unstable = os.path.join(self.state_dir, 'rc-bugs-%s' % source_suite.name)
            filename_testing = os.path.join(self.state_dir, 'rc-bugs-%s' % target_suite.name)
            if not os.path.exists(filename_unstable) and not os.path.exists(filename_testing) and \
               os.path.exists(fallback_unstable) and os.path.exists(fallback_testing):
                filename_unstable = fallback_unstable
                filename_testing = fallback_testing
        except AttributeError:
            filename_unstable = fallback_unstable
            filename_testing = fallback_testing
        self._bugs['source'] = self._read_bugs(filename_unstable)
        self._bugs['target'] = self._read_bugs(filename_testing)

    def apply_src_policy_impl(self, rcbugs_info, suite, source_name, source_data_tdist, source_data_srcdist, excuse):
        bugs_t = set()
        bugs_u = set()

        for src_key in (source_name, 'src:%s' % source_name):
            if source_data_tdist and src_key in self._bugs['target']:
                bugs_t.update(self._bugs['target'][src_key])
            if src_key in self._bugs['source']:
                bugs_u.update(self._bugs['source'][src_key])

        for pkg, _, _ in source_data_srcdist.binaries:
            if pkg in self._bugs['source']:
                bugs_u |= self._bugs['source'][pkg]
        if source_data_tdist:
            for pkg, _, _ in source_data_tdist.binaries:
                if pkg in self._bugs['target']:
                    bugs_t |= self._bugs['target'][pkg]

        # If a package is not in the target suite, it has no RC bugs per
        # definition.  Unfortunately, it seems that the live-data is
        # not always accurate (e.g. live-2011-12-13 suggests that
        # obdgpslogger had the same bug in testing and unstable,
        # but obdgpslogger was not in testing at that time).
        # - For the curious, obdgpslogger was removed on that day
        #   and the BTS probably had not caught up with that fact.
        #   (https://tracker.debian.org/news/415935)
        assert not bugs_t or source_data_tdist, "%s had bugs in the target suite but is not present" % source_name

        success_verdict = PolicyVerdict.PASS

        for ignore_hint in self.hints.search('ignore-rc-bugs', package=source_name,
                                             version=source_data_srcdist.version):
            ignored_bugs = ignore_hint.ignored_rcbugs

            # Only handle one hint for now
            if 'ignored-bugs' in rcbugs_info:
                self.logger.info("Ignoring ignore-rc-bugs hint from %s on %s due to another hint from %s",
                                 ignore_hint.user, source_name, rcbugs_info['ignored-bugs']['issued-by'])
                continue
            if not ignored_bugs.isdisjoint(bugs_u):
                bugs_u -= ignored_bugs
                bugs_t -= ignored_bugs
                rcbugs_info['ignored-bugs'] = {
                    'bugs': sorted(ignored_bugs),
                    'issued-by': ignore_hint.user
                }
                success_verdict = PolicyVerdict.PASS_HINTED
            else:
                self.logger.info("Ignoring ignore-rc-bugs hint from %s on %s as none of %s affect the package",
                                 ignore_hint.user, source_name, str(ignored_bugs))

        rcbugs_info['shared-bugs'] = sorted(bugs_u & bugs_t)
        rcbugs_info['unique-source-bugs'] = sorted(bugs_u - bugs_t)
        rcbugs_info['unique-target-bugs'] = sorted(bugs_t - bugs_u)

        # update excuse
        new_bugs = rcbugs_info['unique-source-bugs']
        old_bugs = rcbugs_info['unique-target-bugs']
        excuse.setbugs(old_bugs, new_bugs)
        if new_bugs:
            excuse.addhtml("Updating %s introduces new bugs: %s" % (source_name, ", ".join(
                ["<a href=\"https://bugs.debian.org/%s\">#%s</a>" % (quote(a), a) for a in new_bugs])))

        if old_bugs:
            excuse.addhtml("Updating %s fixes old bugs: %s" % (source_name, ", ".join(
                ["<a href=\"https://bugs.debian.org/%s\">#%s</a>" % (quote(a), a) for a in old_bugs])))
        if new_bugs and len(old_bugs) > len(new_bugs):
            excuse.addhtml("%s introduces new bugs, so still ignored (even "
                           "though it fixes more than it introduces, whine at debian-release)" % source_name)

        if not bugs_u or bugs_u <= bugs_t:
            return success_verdict
        return PolicyVerdict.REJECTED_PERMANENTLY

    def _read_bugs(self, filename):
        """Read the release critical bug summary from the specified file

        The file contains rows with the format:

        <package-name> <bug number>[,<bug number>...]

        The method returns a dictionary where the key is the binary package
        name and the value is the list of open RC bugs for it.
        """
        bugs = {}
        self.logger.info("Loading RC bugs data from %s", filename)
        for line in open(filename, encoding='ascii'):
            l = line.split()
            if len(l) != 2:  # pragma: no cover
                self.logger.warning("Malformed line found in line %s", line)
                continue
            pkg = l[0]
            if pkg not in bugs:
                bugs[pkg] = set()
            bugs[pkg].update(l[1].split(","))
        return bugs


class PiupartsPolicy(BasePolicy):

    def __init__(self, options, suite_info):
        super().__init__('piuparts', options, suite_info, {SuiteClass.PRIMARY_SOURCE_SUITE})
        self._piuparts = {
            'source': None,
            'target': None,
        }

    def register_hints(self, hint_parser):
        hint_parser.register_hint_type('ignore-piuparts', split_into_one_hint_per_package)

    def initialise(self, britney):
        super().initialise(britney)
        source_suite = self.suite_info.primary_source_suite
        target_suite = self.suite_info.target_suite
        try:
            filename_unstable = os.path.join(self.state_dir, 'piuparts-summary-%s.json' % source_suite.name)
            filename_testing = os.path.join(self.state_dir, 'piuparts-summary-%s.json' % target_suite.name)
        except AttributeError as e:  # pragma: no cover
            raise RuntimeError("Please set STATE_DIR in the britney configuration") from e
        self._piuparts['source'] = self._read_piuparts_summary(filename_unstable, keep_url=True)
        self._piuparts['target'] = self._read_piuparts_summary(filename_testing, keep_url=False)

    def apply_src_policy_impl(self, piuparts_info, suite, source_name, source_data_tdist, source_data_srcdist, excuse):
        if source_name in self._piuparts['target']:
            testing_state = self._piuparts['target'][source_name][0]
        else:
            testing_state = 'X'
        if source_name in self._piuparts['source']:
            unstable_state, url = self._piuparts['source'][source_name]
        else:
            unstable_state = 'X'
            url = None
        url_html = "(no link yet)"
        if url is not None:
            url_html = '<a href="{0}">{0}</a>'.format(url)

        if unstable_state == 'P':
            # Not a regression
            msg = 'Piuparts tested OK - {0}'.format(url_html)
            result = PolicyVerdict.PASS
            piuparts_info['test-results'] = 'pass'
        elif unstable_state == 'F':
            if testing_state != unstable_state:
                piuparts_info['test-results'] = 'regression'
                msg = 'Rejected due to piuparts regression - {0}'.format(url_html)
                result = PolicyVerdict.REJECTED_PERMANENTLY
            else:
                piuparts_info['test-results'] = 'failed'
                msg = 'Ignoring piuparts failure (Not a regression) - {0}'.format(url_html)
                result = PolicyVerdict.PASS
        elif unstable_state == 'W':
            msg = 'Waiting for piuparts test results (stalls migration) - {0}'.format(url_html)
            result = PolicyVerdict.REJECTED_TEMPORARILY
            piuparts_info['test-results'] = 'waiting-for-test-results'
        else:
            msg = 'Cannot be tested by piuparts (not a blocker) - {0}'.format(url_html)
            piuparts_info['test-results'] = 'cannot-be-tested'
            result = PolicyVerdict.PASS

        if url is not None:
            piuparts_info['piuparts-test-url'] = url
        excuse.addhtml(msg)

        if result.is_rejected:
            for ignore_hint in self.hints.search('ignore-piuparts',
                                                 package=source_name,
                                                 version=source_data_srcdist.version):
                piuparts_info['ignored-piuparts'] = {
                    'issued-by': ignore_hint.user
                }
                result = PolicyVerdict.PASS_HINTED
                excuse.addhtml("Ignoring piuparts issue as requested by {0}".format(ignore_hint.user))
                break

        return result

    def _read_piuparts_summary(self, filename, keep_url=True):
        summary = {}
        self.logger.info("Loading piuparts report from %s", filename)
        with open(filename) as fd:
            if os.fstat(fd.fileno()).st_size < 1:
                return summary
            data = json.load(fd)
        try:
            if data['_id'] != 'Piuparts Package Test Results Summary' or data['_version'] != '1.0':  # pragma: no cover
                raise ValueError('Piuparts results in {0} does not have the correct ID or version'.format(filename))
        except KeyError as e:  # pragma: no cover
            raise ValueError('Piuparts results in {0} is missing id or version field'.format(filename)) from e
        for source, suite_data in data['packages'].items():
            if len(suite_data) != 1:  # pragma: no cover
                raise ValueError('Piuparts results in {0}, the source {1} does not have exactly one result set'.format(
                    filename, source
                ))
            item = next(iter(suite_data.values()))
            state, _, url = item
            if not keep_url:
                url = None
            summary[source] = (state, url)

        return summary


@unique
class BuildDepResult(IntEnum):
    # relation is satisfied in target
    OK = 1
    # relation can be satisfied by other packages in source
    DEPENDS = 2
    # relation cannot be satisfied
    FAILED = 3

class BuildDependsPolicy(BasePolicy):

    def __init__(self, options, suite_info):
        super().__init__('build-depends', options, suite_info,
                         {SuiteClass.PRIMARY_SOURCE_SUITE, SuiteClass.ADDITIONAL_SOURCE_SUITE})
        self._britney = None
        self._all_buildarch = []

    def initialise(self, britney):
        super().initialise(britney)
        self._britney = britney
        if hasattr(self.options, 'all_buildarch'):
            self._all_buildarch = SuiteContentLoader.config_str_as_list(self.options.all_buildarch,[])

    def apply_src_policy_impl(self, build_deps_info, suite, source_name, source_data_tdist, source_data_srcdist, excuse,
                          get_dependency_solvers=get_dependency_solvers):
        verdict = PolicyVerdict.PASS

        # analyze the dependency fields (if present)
        deps = source_data_srcdist.build_deps_arch
        if deps:
            v = self._check_build_deps(deps, DependencyType.BUILD_DEPENDS, build_deps_info, suite, source_name, source_data_tdist, source_data_srcdist, excuse,
                          get_dependency_solvers=get_dependency_solvers)
            if verdict.value < v.value:
                verdict = v

        ideps = source_data_srcdist.build_deps_indep
        if ideps:
            v = self._check_build_deps(ideps, DependencyType.BUILD_DEPENDS_INDEP, build_deps_info, suite, source_name, source_data_tdist, source_data_srcdist, excuse,
                          get_dependency_solvers=get_dependency_solvers)
            if verdict.value < v.value:
                verdict = v

        return verdict

    def _get_check_archs(self, archs, dep_type):
        if dep_type == DependencyType.BUILD_DEPENDS:
            return [arch for arch in self.options.architectures if arch in archs]

        # first try the all buildarch
        checkarchs = self._all_buildarch
        # then try the architectures where this source has arch specific
        # binaries (in the order of the architecture config file)
        checkarchs.extend(arch for arch in self.options.architectures if arch in archs and arch not in checkarchs)
        # then try all other architectures
        checkarchs.extend(arch for arch in self.options.architectures if arch not in checkarchs)
        return checkarchs

    def _add_info_for_arch(self, arch, excuses_info, blockers, results, dep_type, target_suite, source_suite, excuse, verdict):
        if arch in excuses_info:
            for excuse_text in excuses_info[arch]:
                excuse.addhtml(excuse_text)

        if arch in blockers:
            packages = blockers[arch]

            sources_t = target_suite.sources
            sources_s = source_suite.sources

            # for the solving packages, update the excuse to add the dependencies
            for p in packages:
                if arch not in self.options.break_arches:
                    item_name = compute_item_name(sources_t, sources_s, p, arch)
                    excuse.add_dependency(dep_type, item_name, arch)

        if arch in results:
            if results[arch] == BuildDepResult.FAILED:
                if verdict.value < PolicyVerdict.REJECTED_PERMANENTLY.value:
                    verdict = PolicyVerdict.REJECTED_PERMANENTLY

        return verdict

    def _check_build_deps(self, deps, dep_type, build_deps_info, suite, source_name, source_data_tdist, source_data_srcdist, excuse,
                          get_dependency_solvers=get_dependency_solvers):
        verdict = PolicyVerdict.PASS
        any_arch_ok = dep_type == DependencyType.BUILD_DEPENDS_INDEP

        britney = self._britney

        # local copies for better performance
        parse_src_depends = apt_pkg.parse_src_depends

        source_suite = self.suite_info[suite]
        target_suite = self.suite_info.target_suite
        binaries_s = source_suite.binaries
        provides_s = source_suite.provides_table
        binaries_t = target_suite.binaries
        provides_t = target_suite.provides_table
        unsat_bd = {}
        relevant_archs = {binary.architecture for binary in source_data_srcdist.binaries
                          if britney.all_binaries[binary].architecture != 'all'}

        excuses_info = defaultdict(list)
        blockers = defaultdict(list)
        arch_results = {}
        result_archs = defaultdict(list)
        bestresult = BuildDepResult.FAILED
        check_archs = self._get_check_archs(relevant_archs,dep_type);
        if not check_archs:
            # when the arch list is empty, we check the b-d on any arch, instead of all archs
            # this happens for Build-Depens on a source package that only produces arch: all binaries
            any_arch_ok = True
            check_archs = self._get_check_archs(self.options.architectures,DependencyType.BUILD_DEPENDS_INDEP);

        for arch in check_archs:
            # retrieve the binary package from the specified suite and arch
            binaries_s_a = binaries_s[arch]
            provides_s_a = provides_s[arch]
            binaries_t_a = binaries_t[arch]
            provides_t_a = provides_t[arch]
            arch_results[arch] = BuildDepResult.OK
            # for every dependency block (formed as conjunction of disjunction)
            for block_txt in deps.split(','):
                block = parse_src_depends(block_txt, False, arch)
                # Unlike regular dependencies, some clauses of the Build-Depends(-Arch|-Indep) can be
                # filtered out by (e.g.) architecture restrictions.  We need to cope with this while
                # keeping block_txt and block aligned.
                if not block:
                    # Relation is not relevant for this architecture.
                    continue
                block = block[0]
                # if the block is satisfied in the target suite, then skip the block
                if get_dependency_solvers(block, binaries_t_a, provides_t_a, build_depends=True):
                    # Satisfied in the target suite; all ok.
                    continue

                # check if the block can be satisfied in the source suite, and list the solving packages
                packages = get_dependency_solvers(block, binaries_s_a, provides_s_a, build_depends=True)
                packages = sorted(p.source for p in packages)

                # if the dependency can be satisfied by the same source package, skip the block:
                # obviously both binary packages will enter the target suite together
                if source_name in packages:
                    continue

                # if no package can satisfy the dependency, add this information to the excuse
                if not packages:
                    excuses_info[arch].append("%s unsatisfiable %s on %s: %s" % (source_name, dep_type, arch, block_txt.strip()))
                    if arch not in unsat_bd:
                        unsat_bd[arch] = []
                    unsat_bd[arch].append(block_txt.strip())
                    arch_results[arch] = BuildDepResult.FAILED
                    continue

                blockers[arch] = packages
                if arch_results[arch] < BuildDepResult.DEPENDS:
                    arch_results[arch] = BuildDepResult.DEPENDS

            if any_arch_ok:
                if arch_results[arch] < bestresult:
                    bestresult = arch_results[arch]
                result_archs[arch_results[arch]].append(arch)
                if bestresult == BuildDepResult.OK:
                    # we found an architecture where the b-deps-indep are
                    # satisfied in the target suite, so we can stop
                    break

        if any_arch_ok:
            arch = result_archs[bestresult][0]
            excuse.addhtml("Checking %s on %s"%(dep_type.get_description(),arch))
            key = "check-%s-on-arch" % dep_type.get_reason()
            build_deps_info[key] = arch
            verdict = self._add_info_for_arch(arch, excuses_info, blockers, arch_results, dep_type, target_suite, source_suite, excuse, verdict)

        else:
            for arch in check_archs:
                verdict = self._add_info_for_arch(arch, excuses_info, blockers, arch_results, dep_type, target_suite, source_suite, excuse, verdict)

            if unsat_bd:
                build_deps_info['unsatisfiable-arch-build-depends'] = unsat_bd

        return verdict


class BuiltUsingPolicy(BasePolicy):
    """Built-Using policy

    Binaries that incorporate (part of) another source package must list these
    sources under 'Built-Using'.

    This policy checks if the corresponding sources are available in the
    target suite. If they are not, but they are candidates for migration, a
    dependency is added.

    If the binary incorporates a newer version of a source, that is not (yet)
    a candidate, we don't want to accept that binary. A rebuild later in the
    primary suite wouldn't fix the issue, because that would incorporate the
    newer version again.

    If the binary incorporates an older version of the source, a newer version
    will be accepted as a replacement. We assume that this can be fixed by
    rebuilding the binary at some point during the development cycle.

    Requiring exact version of the source would not be useful in practice. A
    newer upload of that source wouldn't be blocked by this policy, so the
    built-using would be outdated anyway.

    """

    def __init__(self, options, suite_info):
        super().__init__('built-using', options, suite_info,
                         {SuiteClass.PRIMARY_SOURCE_SUITE, SuiteClass.ADDITIONAL_SOURCE_SUITE},
                         ApplySrcPolicy.RUN_ON_EVERY_ARCH_ONLY)

    def initialise(self, britney):
        super().initialise(britney)

    def apply_srcarch_policy_impl(self, build_deps_info, suite, source_name, arch, source_data_tdist,
                                  source_data_srcdist, excuse):
        verdict = PolicyVerdict.PASS

        source_suite = self.suite_info[suite]
        target_suite = self.suite_info.target_suite
        binaries_s = source_suite.binaries

        sources_t = target_suite.sources

        def check_bu_in_suite(bu_source, bu_version, source_suite):
            found = False
            if bu_source not in source_suite.sources:
                return found
            s_source = source_suite.sources[bu_source]
            s_ver = s_source.version
            if apt_pkg.version_compare(s_ver, bu_version) >= 0:
                found = True
                item_name = compute_item_name(sources_t, source_suite.sources, bu_source, arch)
                if arch in self.options.break_arches:
                    excuse.addhtml("Ignoring Built-Using for %s/%s on %s" % (pkg_name, arch, item_name))
                else:
                    excuse.add_dependency(DependencyType.BUILT_USING, item_name, arch)
                    excuse.addhtml("%s/%s has Built-Using on %s" % (pkg_name, arch, item_name))

            return found

        for pkg_id in sorted(x for x in source_data_srcdist.binaries if x.architecture == arch):
            pkg_name = pkg_id.package_name

            # retrieve the testing (if present) and unstable corresponding binary packages
            binary_s = binaries_s[arch][pkg_name]

            for bu in binary_s.builtusing:
                bu_source = bu[0]
                bu_version = bu[1]
                found = False
                if bu_source in target_suite.sources:
                    t_source = target_suite.sources[bu_source]
                    t_ver = t_source.version
                    if apt_pkg.version_compare(t_ver, bu_version) >= 0:
                        found = True

                if not found:
                    found = check_bu_in_suite(bu_source, bu_version, source_suite)

                if not found and source_suite.suite_class.is_additional_source:
                    found = check_bu_in_suite(bu_source, bu_version, self.suite_info.primary_source_suite)

                if not found:
                    if arch in self.options.break_arches:
                        excuse.addhtml("Ignoring unsatisfiable Built-Using for %s/%s on %s %s" % (
                            pkg_name, arch, bu_source, bu_version))
                    else:
                        excuse.addhtml("%s/%s has unsatisfiable Built-Using on %s %s" % (
                            pkg_name, arch, bu_source, bu_version))
                        if verdict.value < PolicyVerdict.REJECTED_PERMANENTLY.value:
                            verdict = PolicyVerdict.REJECTED_PERMANENTLY

        return verdict


class BlockPolicy(BasePolicy):

    BLOCK_HINT_REGEX = re.compile('^(un)?(block-?.*)$')

    def __init__(self, options, suite_info):
        super().__init__('block', options, suite_info,
                         {SuiteClass.PRIMARY_SOURCE_SUITE, SuiteClass.ADDITIONAL_SOURCE_SUITE})
        self._britney = None
        self._blockall = {}

    def initialise(self, britney):
        super().initialise(britney)
        self._britney = britney
        for hint in self.hints.search(type='block-all'):
            self._blockall[hint.package] = hint

    def register_hints(self, hint_parser):
        # block related hints are currently defined in hint.py
        pass

    def _check_blocked(self, src, arch, version, suite_name, excuse):
        verdict = PolicyVerdict.PASS
        blocked = {}
        unblocked = {}
        source_suite = self.suite_info[suite_name]
        is_primary = source_suite.suite_class == SuiteClass.PRIMARY_SOURCE_SUITE

        if is_primary:
            if 'source' in self._blockall:
                blocked['block'] = self._blockall['source'].user
                excuse.add_hint(self._blockall['source'])
            elif 'new-source' in self._blockall and \
                    src not in self.suite_info.target_suite.sources:
                blocked['block'] = self._blockall['new-source'].user
                excuse.add_hint(self._blockall['new-source'])
        else:
            blocked['block'] = suite_name
            excuse.needs_approval = True

        shints = self.hints.search(package=src)
        mismatches = False
        r = self.BLOCK_HINT_REGEX
        for hint in shints:
            m = r.match(hint.type)
            if m:
                if m.group(1) == 'un':
                    if hint.version != version or hint.suite.name != suite_name or \
                            (hint.architecture != arch and hint.architecture != 'source'):
                        self.logger.info('hint mismatch: %s %s %s', version, arch, suite_name)
                        mismatches = True
                    else:
                        unblocked[m.group(2)] = hint.user
                        excuse.add_hint(hint)
                else:
                    # block(-*) hint: only accepts a source, so this will
                    # always match
                    blocked[m.group(2)] = hint.user
                    excuse.add_hint(hint)

        for block_cmd in blocked:
            unblock_cmd = 'un'+block_cmd
            if block_cmd in unblocked:
                if is_primary or block_cmd == 'block-udeb':
                    excuse.addhtml("Ignoring %s request by %s, due to %s request by %s" %
                                   (block_cmd, blocked[block_cmd], unblock_cmd, unblocked[block_cmd]))
                else:
                    excuse.addhtml("Approved by %s" % (unblocked[block_cmd]))
            else:
                if is_primary or block_cmd == 'block-udeb':
                    tooltip = "please contact debian-release if update is needed"
                    # redirect people to d-i RM for udeb things:
                    if block_cmd == 'block-udeb':
                        tooltip = "please contact the d-i release manager if an update is needed"
                    excuse.addhtml("Not touching package due to %s request by %s (%s)" %
                                   (block_cmd, blocked[block_cmd], tooltip))
                else:
                    excuse.addhtml("NEEDS APPROVAL BY RM")
                excuse.addreason("block")
                if mismatches:
                    excuse.addhtml("Some hints for %s do not match this item" % src)
                verdict = PolicyVerdict.REJECTED_NEEDS_APPROVAL
        return verdict

    def apply_src_policy_impl(self, block_info, suite, source_name, source_data_tdist, source_data_srcdist, excuse):
        return self._check_blocked(source_name, "source", source_data_srcdist.version, suite, excuse)

    def apply_srcarch_policy_impl(self, block_info, suite, source_name, arch, source_data_tdist, source_data_srcdist, excuse):
        return self._check_blocked(source_name, arch, source_data_srcdist.version, suite, excuse)

