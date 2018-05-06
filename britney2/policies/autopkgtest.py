# -*- coding: utf-8 -*-

# Copyright (C) 2013 - 2016 Canonical Ltd.
# Authors:
#   Colin Watson <cjwatson@ubuntu.com>
#   Jean-Baptiste Lallement <jean-baptiste.lallement@canonical.com>
#   Martin Pitt <martin.pitt@ubuntu.com>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

import collections
import os
import json
import tarfile
import io
import re
import sys
import urllib.parse
from urllib.request import urlopen

import apt_pkg

import britney2.hints
from britney2.policies.policy import BasePolicy, PolicyVerdict


EXCUSES_LABELS = {
    "PASS": '<span style="background:#87d96c">Pass</span>',
    "FAIL": '<span style="background:#ff6666">Failed</span>',
    "ALWAYSFAIL": '<span style="background:#e5c545">Always failed</span>',
    "REGRESSION": '<span style="background:#ff6666">Regression</span>',
    "IGNORE-FAIL": '<span style="background:#e5c545">Ignored failure</span>',
    "RUNNING": '<span style="background:#99ddff">Test in progress</span>',
    "RUNNING-ALWAYSFAIL": '<span style="background:#99ddff">Test in progress (always failed)</span>',
}

REF_TRIG = 'migration-reference/0'

def srchash(src):
    '''archive hash prefix for source package'''

    if src.startswith('lib'):
        return src[:4]
    else:
        return src[0]


class AutopkgtestPolicy(BasePolicy):
    """autopkgtest regression policy for source migrations

    Run autopkgtests for the excuse and all of its reverse dependencies, and
    reject the upload if any of those regress.
    """

    def __init__(self, options, suite_info):
        super().__init__('autopkgtest', options, suite_info, {'unstable'})
        # tests requested in this and previous runs
        # trigger -> src -> [arch]
        self.pending_tests = None
        self.pending_tests_file = os.path.join(self.options.state_dir, 'autopkgtest-pending.json')

        # results map: trigger -> src -> arch -> [passed, version, run_id]
        # - trigger is "source/version" of an unstable package that triggered
        #   this test run.
        # - "passed" is a bool
        # - "version" is the package version  of "src" of that test
        # - "run_id" is an opaque ID that identifies a particular test run for
        #   a given src/arch. It's usually a time stamp like "20150120_125959".
        #   This is also used for tracking the latest seen time stamp for
        #   requesting only newer results.
        self.test_results = {}
        if self.options.adt_shared_results_cache:
            self.results_cache_file = self.options.adt_shared_results_cache
        else:
            self.results_cache_file = os.path.join(self.options.state_dir, 'autopkgtest-results.cache')

        try:
            self.options.adt_ppas = self.options.adt_ppas.strip().split()
        except AttributeError:
            self.options.adt_ppas = []

        self.swift_container = 'autopkgtest-' + options.series
        if self.options.adt_ppas:
            self.swift_container += '-' + options.adt_ppas[-1].replace('/', '-')

        # restrict adt_arches to architectures we actually run for
        self.adt_arches = []
        for arch in self.options.adt_arches.split():
            if arch in self.options.architectures:
                self.adt_arches.append(arch)
            else:
                self.logger.info("Ignoring ADT_ARCHES %s as it is not in architectures list", arch)

    def register_hints(self, hint_parser):
        hint_parser.register_hint_type('force-badtest', britney2.hints.split_into_one_hint_per_package)
        hint_parser.register_hint_type('force-skiptest', britney2.hints.split_into_one_hint_per_package)

    def initialise(self, britney):
        super().initialise(britney)
        os.makedirs(self.options.state_dir, exist_ok=True)
        self.read_pending_tests()

        if not hasattr(self.options, 'adt_baseline'):
            # Make adt_baseline optional
            setattr(self.options, 'adt_baseline', None)

        # read the cached results that we collected so far
        if os.path.exists(self.results_cache_file):
            with open(self.results_cache_file) as f:
                self.test_results = json.load(f)
            self.logger.info('Read previous results from %s', self.results_cache_file)
        else:
            self.logger.info('%s does not exist, re-downloading all results from swift', self.results_cache_file)

        # read in the new results
        if self.options.adt_swift_url.startswith('file://'):
            debci_file = self.options.adt_swift_url[7:]
            if os.path.exists(debci_file):
                with open(debci_file) as f:
                    test_results = json.load(f)
                self.logger.info('Read new results from %s', debci_file)
                # With debci, pending tests are determined from the debci file
                self.pending_tests = {}
                for res in test_results['results']:
                    # Blacklisted tests don't get a version
                    if res['version'] is None:
                        res['version'] = 'blacklisted'
                    (trigger, src, arch, ver, status, stamp) = ([res['trigger'], res['package'], res['arch'], res['version'], res['status'], str(res['run_id'])])
                    if trigger is None:
                        # not requested for this policy, so ignore
                        continue
                    if status is None:
                        # still running => pending
                        arch_list = self.pending_tests.setdefault(trigger, {}).setdefault(src, [])
                        if arch not in arch_list:
                            self.logger.info('Pending autopkgtest %s on %s to verify %s',src, arch, trigger)
                            arch_list.append(arch)
                            arch_list.sort()
                    elif status == 'tmpfail':
                        # let's see if we still need it
                        continue
                    else:
                        self.logger.info('Results %s %s %s added', src, trigger, status)
                        self.add_trigger_to_results(trigger, src, ver, arch, stamp, status == 'pass')
            else:
                self.logger.info('%s does not exist, no new data will be processed', debci_file)

        # we need sources, binaries, and installability tester, so for now
        # remember the whole britney object
        self.britney = britney

        # Initialize AMQP connection
        self.amqp_channel = None
        self.amqp_file = None
        if self.options.dry_run:
            return

        amqp_url = self.options.adt_amqp

        if amqp_url.startswith('amqp://'):
            import amqplib.client_0_8 as amqp
            # depending on the setup we connect to a AMQP server
            creds = urllib.parse.urlsplit(amqp_url, allow_fragments=False)
            self.amqp_con = amqp.Connection(creds.hostname, userid=creds.username,
                                            password=creds.password)
            self.amqp_channel = self.amqp_con.channel()
            self.logger.info('Connected to AMQP server')
        elif amqp_url.startswith('file://'):
            # or in Debian and in testing mode, adt_amqp will be a file:// URL
            self.amqp_file = amqp_url[7:]
        else:
            raise RuntimeError('Unknown ADT_AMQP schema %s' % amqp_url.split(':', 1)[0])

    def save_state(self, britney):
        super().save_state(britney)

        # update the results on-disk cache, unless we are using a r/o shared one
        if not self.options.adt_shared_results_cache:
            self.logger.info('Updating results cache')
            with open(self.results_cache_file + '.new', 'w') as f:
                json.dump(self.test_results, f, indent=2)
            os.rename(self.results_cache_file + '.new', self.results_cache_file)

        # update the pending tests on-disk cache
        self.logger.info('Updating pending requested tests in %s', self.pending_tests_file)
        with open(self.pending_tests_file + '.new', 'w') as f:
            json.dump(self.pending_tests, f, indent=2)
        os.rename(self.pending_tests_file + '.new', self.pending_tests_file)

    def apply_policy_impl(self, tests_info, suite, source_name, source_data_tdist, source_data_srcdist, excuse):
        # initialize
        verdict = PolicyVerdict.PASS
        elegible_for_bounty = False

        # skip/delay autopkgtests until new package is built somewhere
        binaries_info = self.britney.sources[suite][source_name]
        if not binaries_info.binaries:
            self.logger.info('%s hasn''t been built anywhere, skipping autopkgtest policy', excuse.name)
            verdict = PolicyVerdict.REJECTED_TEMPORARILY

        if 'all' in excuse.missing_builds:
            self.logger.info('%s hasn''t been built for arch:all, skipping autopkgtest policy', source_name)
            verdict = PolicyVerdict.REJECTED_TEMPORARILY

        if verdict == PolicyVerdict.PASS:
            self.logger.info('Checking autopkgtests for %s', source_name)
            trigger = source_name + '/' + source_data_srcdist.version

            # build a (testsrc, testver) → arch → (status, log_url) map; we trigger/check test
            # results per architecture for technical/efficiency reasons, but we
            # want to evaluate and present the results by tested source package
            # first
            pkg_arch_result = collections.defaultdict(dict)
            for arch in self.adt_arches:
                if arch in excuse.missing_builds:
                    verdict = PolicyVerdict.REJECTED_TEMPORARILY
                    self.logger.info('%s hasn''t been built on arch %s, delay autopkgtest there', source_name, arch)
                elif arch in excuse.unsatisfiable_on_archs:
                    verdict = PolicyVerdict.REJECTED_TEMPORARILY
                    self.logger.info('%s is uninstallable on arch %s, delay autopkgtest there', source_name, arch)
                else:
                    # request tests (unless they were already requested earlier or have a result)
                    tests = self.tests_for_source(source_name, source_data_srcdist.version, arch)
                    is_huge = False
                    try:
                        is_huge = len(tests) > int(self.options.adt_huge)
                    except AttributeError:
                        pass
                    for (testsrc, testver) in tests:
                        self.pkg_test_request(testsrc, arch, trigger, huge=is_huge)
                        (result, real_ver, run_id, url) = self.pkg_test_result(testsrc, testver, arch, trigger)
                        pkg_arch_result[(testsrc, real_ver)][arch] = (result, run_id, url)

            # add test result details to Excuse
            cloud_url = self.options.adt_ci_url + "packages/%(h)s/%(s)s/%(r)s/%(a)s"
            for (testsrc, testver) in sorted(pkg_arch_result):
                arch_results = pkg_arch_result[(testsrc, testver)]
                r = {v[0] for v in arch_results.values()}
                if 'REGRESSION' in r:
                    verdict = PolicyVerdict.REJECTED_PERMANENTLY
                elif 'RUNNING' in r and verdict == PolicyVerdict.PASS:
                    verdict = PolicyVerdict.REJECTED_TEMPORARILY
                # skip version if still running on all arches
                if not r - {'RUNNING', 'RUNNING-ALWAYSFAIL'}:
                    testver = None

                # A source package is elegible for the bounty if it has tests
                # of its own that pass on all tested architectures.
                if testsrc == source_name and r == {'PASS'}:
                    elegible_for_bounty = True

                if testver:
                    testname = '%s/%s' % (testsrc, testver)
                else:
                    testname = testsrc

                html_archmsg = []
                for arch in sorted(arch_results):
                    (status, run_id, log_url) = arch_results[arch]
                    artifact_url = None
                    retry_url = None
                    history_url = None
                    if self.options.adt_ppas:
                        if log_url.endswith('log.gz'):
                            artifact_url = log_url.replace('log.gz', 'artifacts.tar.gz')
                    else:
                        history_url = cloud_url % {
                            'h': srchash(testsrc), 's': testsrc,
                            'r': self.options.series, 'a': arch}
                    if status == 'REGRESSION':
                        if self.options.adt_retry_url_mech == 'run_id':
                            retry_url = self.options.adt_ci_url + 'api/v1/retry/' + run_id
                        else:
                            retry_url = self.options.adt_ci_url + 'request.cgi?' + \
                                    urllib.parse.urlencode([('release', self.options.series),
                                                            ('arch', arch),
                                                            ('package', testsrc),
                                                            ('trigger', trigger)] +
                                                           [('ppa', p) for p in self.options.adt_ppas])

                    tests_info.setdefault(testname, {})[arch] = \
                            [status, log_url, history_url, artifact_url, retry_url]

                    # render HTML snippet for testsrc entry for current arch
                    if history_url:
                        message = '<a href="%s">%s</a>' % (history_url, arch)
                    else:
                        message = arch
                    message += ': <a href="%s">%s</a>' % (log_url, EXCUSES_LABELS[status])
                    if retry_url:
                        message += ' <a href="%s" style="text-decoration: none;">♻ </a> ' % retry_url
                    if artifact_url:
                        message += ' <a href="%s">[artifacts]</a>' % artifact_url
                    html_archmsg.append(message)

                # render HTML line for testsrc entry
                excuse.addhtml("autopkgtest for %s: %s" % (testname, ', '.join(html_archmsg)))

        if verdict != PolicyVerdict.PASS:
            # check for force-skiptest hint
            hints = self.hints.search('force-skiptest', package=source_name, version=source_data_srcdist.version)
            if hints:
                excuse.addreason('skiptest')
                excuse.addhtml("Should wait for tests relating to %s %s, but forced by %s" %
                               (source_name, source_data_srcdist.version, hints[0].user))
                verdict = PolicyVerdict.PASS_HINTED
            else:
                excuse.addreason('autopkgtest')

        if self.options.adt_success_bounty and verdict == PolicyVerdict.PASS and elegible_for_bounty:
            excuse.add_bounty('autopkgtest', int(self.options.adt_success_bounty))
        if self.options.adt_regression_penalty and \
           verdict in {PolicyVerdict.REJECTED_PERMANENTLY, PolicyVerdict.REJECTED_TEMPORARILY}:
            excuse.add_penalty('autopkgtest', int(self.options.adt_regression_penalty))
            # In case we give penalties instead of blocking, we must always pass
            verdict = PolicyVerdict.PASS

        return verdict

    #
    # helper functions
    #

    @classmethod
    def has_autodep8(kls, srcinfo, binaries):
        '''Check if package  is covered by autodep8

        srcinfo is an item from self.britney.sources
        binaries is self.britney.binaries['unstable'][arch][0]
        '''
        # autodep8?
        for t in srcinfo.testsuite:
            if t.startswith('autopkgtest-pkg'):
                return True

        # DKMS: some binary depends on "dkms"
        for pkg_id in srcinfo.binaries:
            try:
                bininfo = binaries[pkg_id.package_name]
            except KeyError:
                continue
            if 'dkms' in (bininfo.depends or ''):
                return True
        return False

    def tests_for_source(self, src, ver, arch):
        '''Iterate over all tests that should be run for given source and arch'''

        sources_info = self.britney.sources['testing']
        binaries_info = self.britney.binaries['testing'][arch][0]

        reported_pkgs = set()

        tests = []

        # gcc-N triggers tons of tests via libgcc1, but this is mostly in vain:
        # gcc already tests itself during build, and it is being used from
        # -proposed, so holding it back on a dozen unrelated test failures
        # serves no purpose. Just check some key packages which actually use
        # gcc during the test, and libreoffice as an example for a libgcc user.
        if src.startswith('gcc-'):
            if re.match('gcc-\d$', src):
                for test in ['binutils', 'fglrx-installer', 'libreoffice', 'linux']:
                    try:
                        tests.append((test, sources_info[test].version))
                    except KeyError:
                        # no package in that series? *shrug*, then not (mostly for testing)
                        pass
                return tests
            else:
                # for other compilers such as gcc-snapshot etc. we don't need
                # to trigger anything
                return []

        # Debian doesn't have linux-meta, but Ubuntu does
        # for linux themselves we don't want to trigger tests -- these should
        # all come from linux-meta*. A new kernel ABI without a corresponding
        # -meta won't be installed and thus we can't sensibly run tests against
        # it.
        if src.startswith('linux') and src.replace('linux', 'linux-meta') in sources_info:
            return []

        # we want to test the package itself, if it still has a test in unstable
        srcinfo = self.britney.sources['unstable'][src]
        if 'autopkgtest' in srcinfo.testsuite or self.has_autodep8(srcinfo, binaries_info):
            reported_pkgs.add(src)
            tests.append((src, ver))

        extra_bins = []
        # Debian doesn't have linux-meta, but Ubuntu does
        # Hack: For new kernels trigger all DKMS packages by pretending that
        # linux-meta* builds a "dkms" binary as well. With that we ensure that we
        # don't regress DKMS drivers with new kernel versions.
        if src.startswith('linux-meta'):
            # does this have any image on this arch?
            for pkg_id in srcinfo.binaries:
                if pkg_id.architecture == arch and '-image' in pkg_id.package_name:
                    try:
                        extra_bins.append(binaries_info['dkms'].pkg_id)
                    except KeyError:
                        pass

        # plus all direct reverse dependencies and test triggers of its
        # binaries which have an autopkgtest
        for binary in srcinfo.binaries + extra_bins:
            rdeps = self.britney._inst_tester.reverse_dependencies_of(binary)
            for rdep in rdeps:
                try:
                    rdep_src = binaries_info[rdep.package_name].source
                    # Don't re-trigger the package itself here; this should
                    # have been done above if the package still continues to
                    # have an autopkgtest in unstable.
                    if rdep_src == src:
                        continue
                except KeyError:
                    continue

                rdep_src_info = sources_info[rdep_src]
                if 'autopkgtest' in rdep_src_info.testsuite or self.has_autodep8(rdep_src_info, binaries_info):
                    if rdep_src not in reported_pkgs:
                        tests.append((rdep_src, rdep_src_info.version))
                        reported_pkgs.add(rdep_src)

            for tdep_src in self.britney.testsuite_triggers.get(binary.package_name, set()):
                if tdep_src not in reported_pkgs:
                    try:
                        tdep_src_info = sources_info[tdep_src]
                    except KeyError:
                        continue
                    if 'autopkgtest' in tdep_src_info.testsuite or self.has_autodep8(tdep_src_info, binaries_info):
                        for pkg_id in tdep_src_info.binaries:
                            if pkg_id.architecture == arch:
                                tests.append((tdep_src, tdep_src_info.version))
                                reported_pkgs.add(tdep_src)
                                break

        tests.sort(key=lambda s_v: s_v[0])
        return tests

    def read_pending_tests(self):
        '''Read pending test requests from previous britney runs

        Initialize self.pending_tests with that data.
        '''
        assert self.pending_tests is None, 'already initialized'
        if not os.path.exists(self.pending_tests_file):
            self.logger.info('No %s, starting with no pending tests', self.pending_tests_file)
            self.pending_tests = {}
            return
        with open(self.pending_tests_file) as f:
            self.pending_tests = json.load(f)
        self.logger.info('Read pending requested tests from %s: %s', self.pending_tests_file, self.pending_tests)

    def latest_run_for_package(self, src, arch):
        '''Return latest run ID for src on arch'''

        # this requires iterating over all triggers and thus is expensive;
        # cache the results
        try:
            return self.latest_run_for_package._cache[src][arch]
        except KeyError:
            pass

        latest_run_id = ''
        for srcmap in self.test_results.values():
            try:
                run_id = srcmap[src][arch][2]
            except KeyError:
                continue
            if run_id > latest_run_id:
                latest_run_id = run_id
        self.latest_run_for_package._cache[arch] = latest_run_id
        return latest_run_id

    latest_run_for_package._cache = collections.defaultdict(dict)

    def fetch_swift_results(self, swift_url, src, arch):
        '''Download new results for source package/arch from swift'''

        # Download results for one particular src/arch at most once in every
        # run, as this is expensive
        done_entry = src + '/' + arch
        if done_entry in self.fetch_swift_results._done:
            return
        self.fetch_swift_results._done.add(done_entry)

        # prepare query: get all runs with a timestamp later than the latest
        # run_id for this package/arch; '@' is at the end of each run id, to
        # mark the end of a test run directory path
        # example: <autopkgtest-wily>wily/amd64/libp/libpng/20150630_054517@/result.tar
        query = {'delimiter': '@',
                 'prefix': '%s/%s/%s/%s/' % (self.options.series, arch, srchash(src), src)}

        # determine latest run_id from results
        if not self.options.adt_shared_results_cache:
            latest_run_id = self.latest_run_for_package(src, arch)
            if latest_run_id:
                query['marker'] = query['prefix'] + latest_run_id

        # request new results from swift
        url = os.path.join(swift_url, self.swift_container)
        url += '?' + urllib.parse.urlencode(query)
        f = None
        try:
            f = urlopen(url, timeout=30)
            if f.getcode() == 200:
                result_paths = f.read().decode().strip().splitlines()
            elif f.getcode() == 204:  # No content
                result_paths = []
            else:
                # we should not ever end up here as we expect a HTTPError in
                # other cases; e. g. 3XX is something that tells us to adjust
                # our URLS, so fail hard on those
                raise NotImplementedError('fetch_swift_results(%s): cannot handle HTTP code %i' %
                                          (url, f.getcode()))
        except IOError as e:
            # 401 "Unauthorized" is swift's way of saying "container does not exist"
            if hasattr(e, 'code') and e.code == 401:
                self.logger.info('fetch_swift_results: %s does not exist yet or is inaccessible', url)
                return
            # Other status codes are usually a transient
            # network/infrastructure failure. Ignoring this can lead to
            # re-requesting tests which we already have results for, so
            # fail hard on this and let the next run retry.
            self.logger.error('Failure to fetch swift results from %s: %s', url, str(e))
            sys.exit(1)
        finally:
            if f is not None:
                f.close()

        for p in result_paths:
            self.fetch_one_result(
                os.path.join(swift_url, self.swift_container, p, 'result.tar'), src, arch)

    fetch_swift_results._done = set()

    def fetch_one_result(self, url, src, arch):
        '''Download one result URL for source/arch

        Remove matching pending_tests entries.
        '''
        f = None
        try:
            f = urlopen(url, timeout=30)
            if f.getcode() == 200:
                tar_bytes = io.BytesIO(f.read())
            else:
                raise NotImplementedError('fetch_one_result(%s): cannot handle HTTP code %i' %
                                          (url, f.getcode()))
        except IOError as e:
            self.logger.error('Failure to fetch %s: %s', url, str(e))
            # we tolerate "not found" (something went wrong on uploading the
            # result), but other things indicate infrastructure problems
            if hasattr(e, 'code') and e.code == 404:
                return
            sys.exit(1)
        finally:
            if f is not None:
                f.close()
        try:
            with tarfile.open(None, 'r', tar_bytes) as tar:
                exitcode = int(tar.extractfile('exitcode').read().strip())
                srcver = tar.extractfile('testpkg-version').read().decode().strip()
                (ressrc, ver) = srcver.split()
                testinfo = json.loads(tar.extractfile('testinfo.json').read().decode())
        except (KeyError, ValueError, tarfile.TarError) as e:
            self.logger.error('%s is damaged, ignoring: %s', url, str(e))
            # ignore this; this will leave an orphaned request in autopkgtest-pending.json
            # and thus require manual retries after fixing the tmpfail, but we
            # can't just blindly attribute it to some pending test.
            return

        if src != ressrc:
            self.logger.error('%s is a result for package %s, but expected package %s', url, ressrc, src)
            return

        # parse recorded triggers in test result
        for e in testinfo.get('custom_environment', []):
            if e.startswith('ADT_TEST_TRIGGERS='):
                result_triggers = [i for i in e.split('=', 1)[1].split() if '/' in i]
                break
        else:
            self.logger.error('%s result has no ADT_TEST_TRIGGERS, ignoring')
            return

        stamp = os.path.basename(os.path.dirname(url))
        # allow some skipped tests, but nothing else
        passed = exitcode in [0, 2]

        self.logger.info('Fetched test result for %s/%s/%s %s (triggers: %s): %s',
                 src, ver, arch, stamp, result_triggers, passed and 'pass' or 'fail')

        # remove matching test requests
        for trigger in result_triggers:
            self.remove_from_pending(trigger, src, arch)

        # add this result
        for trigger in result_triggers:
            self.add_trigger_to_results(trigger, src, ver, arch, stamp, passed)

    def remove_from_pending(self, trigger, src, arch):
        try:
            arch_list = self.pending_tests[trigger][src]
            arch_list.remove(arch)
            if not arch_list:
                del self.pending_tests[trigger][src]
            if not self.pending_tests[trigger]:
                del self.pending_tests[trigger]
            self.logger.info('-> matches pending request %s/%s for trigger %s', src, arch, trigger)
        except (KeyError, ValueError):
            self.logger.info('-> does not match any pending request for %s/%s', src, arch)

    def add_trigger_to_results(self, trigger, src, ver, arch, stamp, passed):
        # If a test runs because of its own package (newer version), ensure
        # that we got a new enough version; FIXME: this should be done more
        # generically by matching against testpkg-versions
        (trigsrc, trigver) = trigger.split('/', 1)
        if trigsrc == src and apt_pkg.version_compare(ver, trigver) < 0:
            self.logger.error('test trigger %s, but run for older version %s, ignoring', trigger, ver)
            return
    
        result = self.test_results.setdefault(trigger, {}).setdefault(
            src, {}).setdefault(arch, [False, None, ''])
    
        # don't clobber existing passed results with failures from re-runs
        # except for reference updates
        if passed or not result[0] or (self.options.adt_baseline == 'reference' and trigger == REF_TRIG):
            result[0] = passed
            result[1] = ver
            result[2] = stamp

            if self.options.adt_baseline == 'reference' and trigsrc != src:
                self.test_results.setdefault(REF_TRIG, {}).setdefault(
                    src, {}).setdefault(arch, [passed, ver, stamp])

    def send_test_request(self, src, arch, trigger, huge=False):
        '''Send out AMQP request for testing src/arch for trigger

        If huge is true, then the request will be put into the -huge instead of
        normal queue.
        '''
        if self.options.dry_run:
            return

        params = {'triggers': [trigger]}
        if self.options.adt_ppas:
            params['ppas'] = self.options.adt_ppas
            qname = 'debci-ppa-%s-%s' % (self.options.series, arch)
        elif huge:
            qname = 'debci-huge-%s-%s' % (self.options.series, arch)
        else:
            qname = 'debci-%s-%s' % (self.options.series, arch)
        params = json.dumps(params)

        if self.amqp_channel:
            self.amqp_channel.basic_publish(amqp.Message(src + '\n' + params), routing_key=qname)
        else:
            assert self.amqp_file
            with open(self.amqp_file, 'a') as f:
                f.write('%s:%s %s\n' % (qname, src, params))

    def pkg_test_request(self, src, arch, trigger, huge=False):
        '''Request one package test for one particular trigger

        trigger is "pkgname/version" of the package that triggers the testing
        of src. If huge is true, then the request will be put into the -huge
        instead of normal queue.

        This will only be done if that test wasn't already requested in a
        previous run (i. e. not already in self.pending_tests) or there already
        is a result for it. This ensures to download current results for this
        package before requesting any test.
        '''
        # Don't re-request if we already have a result
        try:
            passed = self.test_results[trigger][src][arch][0]
            if self.options.adt_swift_url.startswith('file://'):
                return
            if passed:
                self.logger.info('%s/%s triggered by %s already passed', src, arch, trigger)
                return
            self.logger.info('Checking for new results for failed %s/%s for trigger %s', src, arch, trigger)
            raise KeyError  # fall through
        except KeyError:
            # Without swift we don't expect new results
            if not self.options.adt_swift_url.startswith('file://'):
                self.fetch_swift_results(self.options.adt_swift_url, src, arch)
                # do we have one now?
                try:
                    self.test_results[trigger][src][arch]
                    return
                except KeyError:
                    pass

        # Don't re-request if it's already pending
        arch_list = self.pending_tests.setdefault(trigger, {}).setdefault(src, [])
        if arch in arch_list:
            self.logger.info('Test %s/%s for %s is already pending, not queueing', src, arch, trigger)
        else:
            self.logger.info('Requesting %s autopkgtest on %s to verify %s', src, arch, trigger)
            arch_list.append(arch)
            arch_list.sort()
            self.send_test_request(src, arch, trigger, huge=huge)
            if self.options.adt_baseline == 'reference':
                # Check if we already have a reference for this src on this
                # arch (or pending).
                try:
                    self.test_results[REF_TRIG][src][arch]
                except KeyError:
                    try:
                        arch_list = self.pending_tests[REF_TRIG][src]
                        if arch not in arch_list:
                            raise KeyError # fall through
                    except KeyError:
                        self.logger.info('Requesting %s autopkgtest on %s to set a reference',
                                             src, arch)
                        self.send_test_request(src, arch, REF_TRIG, huge=huge)

    def passed_in_baseline(self, src, arch):
        '''Check if tests for src passed on arch in the baseline

        The baseline is optionally all data or a reference set)
        '''

        # this requires iterating over all cached results and thus is expensive;
        # cache the results
        try:
            return self.passed_in_baseline._cache[src][arch]
        except KeyError:
            pass

        passed_reference = False
        if self.options.adt_baseline == 'reference':
            try:
                passed_reference = self.test_results[REF_TRIG][src][arch][0]
                self.logger.info('Found result for src %s in reference: pass=%s', src, passed_reference)
            except KeyError:
                self.logger.info('Found NO result for src %s in reference: pass=%s', src, passed_reference)
                pass
            self.passed_in_baseline._cache[arch] = passed_reference
            return passed_reference

        passed_ever = False
        for srcmap in self.test_results.values():
            try:
                if srcmap[src][arch][0]:
                    passed_ever = True
                    break
            except KeyError:
                pass

        self.passed_in_baseline._cache[arch] = passed_ever
        self.logger.info('Result for src %s ever: pass=%s', src, passed_ever)
        return passed_ever

    passed_in_baseline._cache = collections.defaultdict(dict)

    def pkg_test_result(self, src, ver, arch, trigger):
        '''Get current test status of a particular package

        Return (status, real_version, run_id, log_url) tuple; status is a key in
        EXCUSES_LABELS. run_id is None if the test is still running.
        '''
        # determine current test result status
        ever_passed = self.passed_in_baseline(src, arch)
        url = None
        run_id = None
        try:
            r = self.test_results[trigger][src][arch]
            ver = r[1]
            run_id = r[2]
            if r[0]:
                result = 'PASS'
            else:
                # Special-case triggers from linux-meta*: we cannot compare
                # results against different kernels, as e. g. a DKMS module
                # might work against the default kernel but fail against a
                # different flavor; so for those, ignore the "ever
                # passed" check; FIXME: check against trigsrc only
                if trigger.startswith('linux-meta') or trigger.startswith('linux/'):
                    ever_passed = False

                if ever_passed:
                    if self.has_force_badtest(src, ver, arch):
                        result = 'IGNORE-FAIL'
                    else:
                        result = 'REGRESSION'
                else:
                    result = 'ALWAYSFAIL'

            if self.options.adt_swift_url.startswith('file://'):
                url = os.path.join(self.options.adt_ci_url,
                                   'data',
                                   'autopkgtest',
                                   self.options.series,
                                   arch,
                                   srchash(src),
                                   src,
                                   run_id,
                                   'log.gz')
            else:
                url = os.path.join(self.options.adt_swift_url,
                                   self.swift_container,
                                   self.options.series,
                                   arch,
                                   srchash(src),
                                   src,
                                   run_id,
                                   'log.gz')
        except KeyError:
            # no result for src/arch; still running?
            if arch in self.pending_tests.get(trigger, {}).get(src, []):
                if ever_passed and not self.has_force_badtest(src, ver, arch):
                    result = 'RUNNING'
                else:
                    result = 'RUNNING-ALWAYSFAIL'
                url = self.options.adt_ci_url + 'status/pending'
            else:
                raise RuntimeError('Result for %s/%s/%s (triggered by %s) is neither known nor pending!' %
                                   (src, ver, arch, trigger))

        return (result, ver, run_id, url)

    def has_force_badtest(self, src, ver, arch):
        '''Check if src/ver/arch has a force-badtest hint'''

        hints = self.hints.search('force-badtest', package=src)
        if hints:
            self.logger.info('Checking hints for %s/%s/%s: %s', src, ver, arch, [str(h) for h in hints])
            for hint in hints:
                if [mi for mi in hint.packages if mi.architecture in ['source', arch] and
                        (mi.version == 'all' or apt_pkg.version_compare(ver, mi.version) <= 0)]:
                    return True

        return False

