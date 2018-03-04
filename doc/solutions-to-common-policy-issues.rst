Solutions to common policy decisions
====================================

.. contents::

Britney complains about a fixed bug in the source suite (bug policy)
--------------------------------------------------------------------

All decisions about bugs are related to data set extracted
from the bug tracker.  If britney says that the new version
introduces a bug, then it is because the data set from the bug
tracker lists that bug for *a* version in the source suite,
without it appearing for the version(s) in the target suite.

Please note that these data sets do not include versions, so
britney is unable to tell exactly which versions are affected.
The only thing, it can tell, is what suite the bug affects.

There is a number of common cases, where this is observed:

 * The metadata on the bug is wrong.  A known example is the
   Debian BTS, where if a bug has a `fixed` version equal to
   a `found` version, the bug is considered unfixed.

 * The bug is fixed, but the old version is still around in
   the source suite.  In this case, britney will generally
   also mention a "missing build" or "old binaries".

If the metadata is wrong, the solution is to fix it in the bug
tracker and wait until britney receives a new data set.  In
the other case, the recommendation is to see the sections on
"missing builds" and "old binaries" below.  As long as they
are present, the package may be blocked by bugs in the older
versions of the binaries.

Britney complains about "missing builds"
----------------------------------------

A "missing build" happens when britney detects that the binaries
for a given architecture are missing or not up to date.  This
is detected by checking the "Packages" files in the archive, so
britney has no knowledge of *why* the build is missing.
Accordingly, this kind of issue is flagged as a "possibly permanent"
issue.

If the omission is deliberate (e.g. the new version no longer
supports that architecture), then please have the old binaries
for that architecture removed from the *source* suite.  Once
those are removed, britney will no longer see that as a problem.

Otherwise, please check the build services for any issues with
building or uploading the package to the archive.

**Common misconceptions**: If the architecture is no longer
supported, the removal of the old binaries should happen in
the *source* suite (e.g. Debian unstable).  However, many
people mistakenly request a removal from the *target* suite
(e.g. Debian testing).  Unfortunately, this is not the proper
solution (and, britney does not support architecture
specific removals so it may be difficult to do anyhow).

Britney complains about "old binaries"
--------------------------------------

Depending on the configuration of the britney instance, this may
or may not be a blocker.  If the distribution has chosen to enable
the "ignore_cruft" option, this is merely a warning/note.  That
said, even in this mode it can block a package from migration.

This appears when britney detects that there are older versions of
the binary packages around, which was built by (an older version of)
the same source package.

This is common with distributions where their archive management
software is capable of keeping old binaries as long as something
depends on them (e.g. DAK as used by Debian).  Therefore, the
most common solution is to ensure all reverse dependencies are
updated to use the new binaries and then have the old ones
removed (the latter commonly known as "decrufting").  Technically,
this is also solvable by "decrufting" without updating/rebuilding
other packages.  Though whether this is an acceptable practise
depends on the distribution.

Alternatively, if the distribution uses the "ignore_cruft" option,
this (in itself) is not a blocker.  However, it commonly triggers
non-obvious issues:

 * If the bugs policy is enabled, an bug in the old binaries that
   is fixed in the new version will still be a blocker.  Here, the
   best solution is to get rid of the old binaries.
   
   * Note: the bugs data is not versioned so britney cannot tell which
     versions the bug applies to.  Just which suite they affect.

 * Even if the migration item is a valid candidate (i.e. all policy
   checked have passed), it may cause installability regressions as
   britney will also attempt to keep the old binaries around as long
   as they are used.  The most often cause of this when the old
   binaries are not co-installable with the new ones.
   
   * Note: Britney generally only works with the highest version of a
     given binary.  If you have libfoo1 depends on libfoo-data v1 and
     then libfoo2 depends on libfoo-data v2, then libfoo1 will become
     uninstallable as libfoo-data v2 will "shadow" libfoo-data v1.

Britney complains about "Piupart"
---------------------------------

Britney can be configured to take the results of piuparts (package
installation, upgrading and removal testing suite) into account. Currently this
policy is only taking into account the piuparts result for installing and
purging the package in the source suite and the target suite (so no upgrade
test). As with the other policies, a regression means that the package passes
in the target suite, but fails in the source suite. Unless this is a bug in
piuparts, the package needs to be fixed first to install and purge cleanly in
the non-interactive debconf state. An URL to the relevant piuparts results is
provided in the excuses.

Britney complains about "autopkgtest"
-------------------------------------

Maintainers can add autopkgtest test cases to their packages. Britney can be
configured to request a test runner instance (in the case of Debian, this is
debci) to run relevant tests. The idea is that a package that is candidate for
migration is updated in the target suite to its candidate version and that the
autopkgtest cases of the package (if it has one or more) *and* those of all
reverse dependencies are run. Regression in the results with respect to the
current situation in the target suite can influence migration in the following
ways, depending on britney's configuration:

 * migration is blocked

 * regression adds to the time a package needs to be in the source suite before
   migration is considered (via the age policy)

Regression in the autopkgtest of the candidate package just needs to be fixed
in the package itself. However, due to the addition of test cases from reverse
dependencies, regression in this policy may come from a test case that the
package does not control. If that is the case, the maintainers of the package
and the maintainers of the regressing test case typically need to discuss and
solve the issue together. The maintainers of the package have the knowledge of
what changed, while the maintainers of the reverse dependency with the failing
test case know what and how the test is actually testing. After all, a
regression in a reverse dependency can come due to one of the following reasons
(of course not complete):

 * new bug in the candidate package (fix the package)

 * bug in the test case that only gets triggered due to the update (fix the
   reverse dependency, but see below)

 * out-of-date reference date in the test case that captures a former bug in
   the candidate package (fix the reverse dependency, but see below)

 * deprecation of functionality that is used in the reverse dependency and/or
   its test case (discussion needed)

Unfortunately sometimes a regression is only intermittent. Ideally this should
be fixed, but it may be OK to just have the autopkgtest retried (how this is to
be achieved depends on the setup that is being used).

There are cases where it is required to have multiple packages migrate together
to have the test cases pass, e.g. when there was a bug in a regressing test
case of a reverse dependency and that got fixed. In that case the test cases
need to be triggered with both packages from the source suite in the target
suite (again, how this is done depends on the setup).

If britney is configured to add time to the age policy in case of regression, a
test case that hasn't been run (but ran successfully in the past) will also
cause the penalty to be added. This is harmless, because once the results come
in, the penalty will no longer be effective. Similarly, a missing build will
also cause the (harmless) penalty.

A failing test that has never succeeded in britney's memory will be treated as
if the test case doesn't exist.

On top of the penalties for regressions, britney can be configured to reward
bounties for packages that have a successful test case.

