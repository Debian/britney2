from abc import abstractmethod
from enum import Enum, unique
import apt_pkg
import os
import time

from consts import VERSION, BINARIES


@unique
class PolicyVerdict(Enum):
    """"""
    """
    The migration item passed the policy.
    """
    PASS = 1
    """
    The policy was completely overruled by a hint.
    """
    PASS_HINTED = 2
    """
    The migration item did not pass the policy, but the failure is believed
    to be temporary
    """
    REJECTED_TEMPORARILY = 3
    """
    The migration item did not pass the policy and the failure is believed
    to be uncorrectable (i.e. a hint or a new version is needed)
    """
    REJECTED_PERMANENTLY = 4

    @property
    def is_rejected(self):
        return True if self.name.startswith('REJECTED') else False


class BasePolicy(object):

    def __init__(self, options, applicable_suites):
        self.options = options
        self.applicable_suites = applicable_suites
        self.hints = None

    # FIXME: use a proper logging framework
    def log(self, msg, type="I"):
        """Print info messages according to verbosity level

        An easy-and-simple log method which prints messages to the standard
        output. The type parameter controls the urgency of the message, and
        can be equal to `I' for `Information', `W' for `Warning' and `E' for
        `Error'. Warnings and errors are always printed, and information is
        printed only if verbose logging is enabled.
        """
        if self.options.verbose or type in ("E", "W"):
            print("%s: [%s] - %s" % (type, time.asctime(), msg))

    def initialise(self, britney):
        """Called once to make the policy initialise any data structures

        This is useful for e.g. parsing files or other "heavy do-once" work.
        """
        pass

    def save_state(self, britney):
        """Called once at the end of the run to make the policy save any persistent data

        Note this will *not* be called for "dry-runs" as such runs should not change
        the state.
        """
        pass

    @abstractmethod
    def apply_policy(self, policy_info, suite, source_name, source_data_tdist, source_data_srcdist):
        pass


class AgePolicy(BasePolicy):
    """Configurable Aging policy for source migrations

    The AgePolicy will let packages stay in the source suite for a pre-defined
    amount of days before letting migrate (based on their urgency, if any).

    The AgePolicy's decision is influenced by the following:

    State files:
     * ${TESTING}/Urgency: File containing urgencies for source packages.
       Note that urgencies are "sticky" and the most "urgent" urgency will be
       used (i.e. the one with lowest age-requirements).
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

    def __init__(self, options, mindays):
        super().__init__(options, {'unstable'})
        self._min_days = mindays
        if options.default_urgency not in mindays:
            raise ValueError("Missing age-requirement for default urgency (MINDAYS_%s)" % options.default_urgency)
        self._min_days_default = mindays[options.default_urgency]
        # britney's "day" begins at 3pm
        self._date_now = int(((time.time() / (60*60)) - 15) / 24)
        self._dates = {}
        self._urgencies = {}

    def initialise(self, britney):
        super().initialise(britney)
        self._read_dates_file()
        self._read_urgencies_file(britney)

    def save_state(self, britney):
        super().save_state(britney)
        self._write_dates_file()

    def apply_policy(self, policy_info, suite, source_name, source_data_tdist, source_data_srcdist):
        # retrieve the urgency for the upload, ignoring it if this is a NEW package (not present in testing)
        urgency = self._urgencies.get(source_name, self.options.default_urgency)
        if 'age' not in policy_info:
            policy_info['age'] = age_info = {}
        else:
            age_info = policy_info['age']

        if urgency not in self._min_days:
            age_info['unknown-urgency'] = urgency
            urgency = self.options.default_urgency

        if not source_data_tdist:
            if self._min_days[urgency] < self._min_days_default:
                age_info['urgency-reduced'] = {
                    'from': urgency,
                    'to': self.options.default_urgency,
                }
                urgency = self.options.default_urgency

        if source_name not in self._dates:
            self._dates[source_name] = (source_data_srcdist[VERSION], self._date_now)
        elif self._dates[source_name][0] != source_data_srcdist[VERSION]:
            self._dates[source_name] = (source_data_srcdist[VERSION], self._date_now)

        days_old = self._date_now - self._dates[source_name][1]
        min_days = self._min_days[urgency]
        age_info['age-requirement'] = min_days
        age_info['current-age'] = days_old

        for age_days_hint in [x for x in self.hints.search('age-days', package=source_name)
                              if source_data_srcdist[VERSION] == x.version]:
            new_req = int(age_days_hint.days)
            age_info['age-requirement-reduced'] = {
                'new-requirement': new_req,
                'changed-by': age_days_hint.user
            }
            min_days = new_req

        if days_old < min_days:
            urgent_hints = [x for x in self.hints.search('urgent', package=source_name)
                            if source_data_srcdist[VERSION] == x.version]
            if urgent_hints:
                age_info['age-requirement-reduced'] = {
                    'new-requirement': 0,
                    'changed-by': urgent_hints[0].user
                }
                return PolicyVerdict.PASS_HINTED
            else:
                return PolicyVerdict.REJECTED_TEMPORARILY

        return PolicyVerdict.PASS

    def _read_dates_file(self):
        """Parse the dates file"""
        dates = self._dates
        fallback_filename = os.path.join(self.options.testing, 'Dates')
        try:
            filename = os.path.join(self.options.state_dir, 'age-policy-dates')
            if not os.path.exists(filename) and os.path.exists(fallback_filename):
                filename = fallback_filename
        except AttributeError:
            filename = fallback_filename

        with open(filename, encoding='utf-8') as fd:
            for line in fd:
                # <source> <version> <date>
                l = line.split()
                if len(l) != 3:
                    continue
                try:
                    dates[l[0]] = (l[1], int(l[2]))
                except ValueError:
                    pass

    def _read_urgencies_file(self, britney):
        urgencies = self._urgencies
        filename = os.path.join(self.options.testing, 'Urgency')
        min_days_default = self._min_days_default
        with open(filename, errors='surrogateescape', encoding='ascii') as fd:
            for line in fd:
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

                # if the package exists in testing and it is more recent, do nothing
                tsrcv = britney.sources['testing'].get(l[0], None)
                if tsrcv and apt_pkg.version_compare(tsrcv[VERSION], l[1]) >= 0:
                    continue

                # if the package doesn't exist in unstable or it is older, do nothing
                usrcv = britney.sources['unstable'].get(l[0], None)
                if not usrcv or apt_pkg.version_compare(usrcv[VERSION], l[1]) < 0:
                    continue

                # update the urgency for the package
                urgencies[l[0]] = l[2]

    def _write_dates_file(self):
        dates = self._dates
        try:
            directory = self.options.state_dir
            basename = 'age-policy-dates'
            old_file = os.path.join(self.options.testing, 'Dates')
        except AttributeError:
            directory = self.options.testing
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
            self.log("Removing old age-policy-dates file %s" % old_file)
            os.unlink(old_file)


class RCBugPolicy(BasePolicy):
    """RC bug regression policy for source migrations

    The RCBugPolicy will read provided list of RC bugs and block any
    source upload that would introduce a *new* RC bug in the target
    suite.

    The RCBugPolicy's decision is influenced by the following:

    State files:
     * ${UNSTABLE}/BugsV: File containing RC bugs for packages in the
      source suite.
       - This file needs to be updated externally.
     * ${TESTING}/BugsV: File containing RC bugs for packages in the
       target suite.
       - This file needs to be updated externally.
    """

    def __init__(self, options):
        super().__init__(options, {'unstable'})
        self._bugs = {}

    def initialise(self, britney):
        super().initialise(britney)
        self._bugs['unstable'] = self._read_bugs(self.options.unstable)
        self._bugs['testing'] = self._read_bugs(self.options.testing)

    def apply_policy(self, policy_info, suite, source_name, source_data_tdist, source_data_srcdist):
        # retrieve the urgency for the upload, ignoring it if this is a NEW package (not present in testing)
        if 'rc-bugs' not in policy_info:
            policy_info['rc-bugs'] = rcbugs_info = {}
        else:
            rcbugs_info = policy_info['rc-bugs']

        bugs_t = set()
        bugs_u = set()

        for src_key in (source_name, 'src:%s' % source_name):
            if source_data_tdist and src_key in self._bugs['testing']:
                bugs_t.update(self._bugs['testing'][src_key])
            if src_key in self._bugs['unstable']:
                bugs_u.update(self._bugs['unstable'][src_key])

        for pkg, _, _ in source_data_srcdist[BINARIES]:
            if pkg in self._bugs['unstable']:
                bugs_u |= self._bugs['unstable'][pkg]
        if source_data_tdist:
            for pkg, _, _ in source_data_tdist[BINARIES]:
                if pkg in self._bugs['testing']:
                    bugs_t |= self._bugs['testing'][pkg]

        # If a package is not in testing, it has no RC bugs per
        # definition.  Unfortunately, it seems that the live-data is
        # not always accurate (e.g. live-2011-12-13 suggests that
        # obdgpslogger had the same bug in testing and unstable,
        # but obdgpslogger was not in testing at that time).
        # - For the curious, obdgpslogger was removed on that day
        #   and the BTS probably had not caught up with that fact.
        #   (https://tracker.debian.org/news/415935)
        assert not bugs_t or source_data_tdist, "%s had bugs in testing but is not in testing" % source_name

        rcbugs_info['shared-bugs'] = sorted(bugs_u & bugs_t)
        rcbugs_info['unique-source-bugs'] = sorted(bugs_u - bugs_t)
        rcbugs_info['unique-target-bugs'] = sorted(bugs_t - bugs_u)

        if not bugs_u or bugs_u <= bugs_t:
            return PolicyVerdict.PASS
        return PolicyVerdict.REJECTED_PERMANENTLY

    def _read_bugs(self, basedir):
        """Read the release critical bug summary from the specified directory

        The RC bug summaries are read from the `BugsV' file within the
        directory specified in the `basedir' parameter. The file contains
        rows with the format:

        <package-name> <bug number>[,<bug number>...]

        The method returns a dictionary where the key is the binary package
        name and the value is the list of open RC bugs for it.
        """
        bugs = {}
        filename = os.path.join(basedir, "BugsV")
        self.log("Loading RC bugs data from %s" % filename)
        for line in open(filename, encoding='ascii'):
            l = line.split()
            if len(l) != 2:
                self.log("Malformed line found in line %s" % (line), type='W')
                continue
            pkg = l[0]
            if pkg not in bugs:
                bugs[pkg] = set()
            bugs[pkg].update(l[1].split(","))
        return bugs
