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

