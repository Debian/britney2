#! TITLE: Britney migration documentation
#! SUBTITLE: Understanding britney's workflow

# Migrations

This is a technical introduction to how britney
handles migrations.  Being an introduction, it deliberately
oversimplify certain things at the expense of accuracy.
It also covers common migration issues and how to fix
them.

The document is primarily aimed at contributors for
distributions that want to understand the basics of
britney and her migration rules.

The documentation also aspires to be a general purpose document
for britney that is applicable for multiple distributions.
However, it does reference distribution-specific practises in
some examples to prevent the documentation from becoming too
abstract.  Furthermore, the document assumes familiarity with
Debian-based distribution practises and terminology (such as
"suites" and "source package").

## A high level overview of britney and migrations

The purpose of britney is to (semi-)automatically select
a number of package groups from a series of source suites
(e.g. Debian unstable) that are ready to migrate to
the target suite (e.g. Debian testing).

The definition of "ready" can be summarized as satisfying all
of the following points:

 1. The package groups pass a number of policies for the target
    suite.  Most of these policies are basically that the
    package groups do not regress on selected QA checks.
    * A group satisfying this part is called a `valid candiate`.
 1. Installability will not regress as a result of
    migrating the package groups.
    * A group that (also) satisfy this will be selected for migration.

The keyword in both points being *regress*.  If a package
has an existing issue in the target suite, a group with the
new version is generally allowed to migrate if it has the
same issue (as it is not a regression).

This only leaves the definition of a package group.  In britney,
these groups are known as "migration items" and they come in
several variants.  These will be explained in the next section

## Migration items

Internally, britney groups packages into "migration items"
based on a few rules.  Every upload of a source package will
be associated with a *source migration item*.  As the binary
packages are built and uploaded, they will be included into
the migration item and various QA checks/policies will be
applied to the item.

Once britney deems the item ready, she will attempt to
migrate the item (i.e. source with its binaries) to the 
target suite.


There are several other migration types.  But they are
not covered in this document as the primary audience
of this document will generally not need to know about
them to begin with.

## Migration phase 1: Policies / Excuses

To begin with, britney will apply a number of policies to
all migration items.  Each policy will rate each migration
item and the combined results will be added into one of
britney's output documents known as the "excuses" (exists in
an HTML and a YAML variant).  A migration item that passes all
applicable policies will be labelled as a `valid candidate` in
the excuses and continue to the next phase.


The policies gives exactly one verdict to each item, some of
these verdicts are:

 * The item passes the policy.
 * The policy is waiting for test suites before providing a
   pass/fail result (temporary failure).
 * The item fails the policy and the failure is believed to
   be "permanent" (given no external changes).
 * The item does not pass the policy, but britney has
   insufficient information to determine if the failure is
   persistent or not.

It is important to note that all verdicts are based on the current
data that britney has access to.  This mean that without any change
to the items themselves:

 1. Items that passed originally may fail in a later britney run.
 1. Likewise, items may go from a "permanent failure" to a pass.

For the first case, a common example would be a new RC bug.  When the
package if first uploaded, no body filed an RC bug yet so britney may
flag it as "passing" the RC bug policy.  Then before it migrates, someone
files an RC bug.  Once britney becomes aware of this, she will change
the verdict from pass to a permanent failure.  If the bug is closed
without an upload, downgraded or it is determined that the bug is not 
a regression compared to the target suite, britney will update the
verdict again.

For the second case, there was a "hidden" example with the RC bug in
the previous paragraph. :)  But another example would be that piuparts
flags an item as having a regression due to a false positive.  The
false-positive is then found, fixed and the test is rerun.  Once the
updated test result reaches britney, she will update her verdict.

Finally, the people running the britney instance can overrule any
policy by applying a [britney hint](hints.html), if they deem it
necessary.  One caveat here is that not all policies can be overridden
directly and some will require the "ignore all policies"-hint (known
as the `force`-hint).

Since most policies are defined based on regressions,
a hinted migration generally implies that the problem will not
prevent future migrations for newer versions of the same source
package (assuming that the problem is deterministic).

## Migration phase 2: Installability regression testing

For the migration items that pass the previous phase, britney
will do a test migration to see if anything becomes uninstallable.
This is a more expensive test to ensure the migration does not cause
installability regressions.

The status of this phase is *not* included in the excuses.  To debug
problems here, the britney log file has to be examined.  This requires
a bit more technical insight as it has not been polished as much as
the excuses.

### Confirming a migration

To start with; if a migration is accepted and "committed" (i.e. it will not
be rolled back), britney will include in a line starting with `final:` a la
this example:

    Apparently successful
    final: -cwltool,-libtest-redisserver-perl,-pinfo,-webdis,hol88
    start: 41+0: a-4:i-27:a-1:a-1:a-1:m-0:m-3:m-1:p-1:s-2
     orig: 41+0: a-4:i-27:a-1:a-1:a-1:m-0:m-3:m-1:p-1:s-2
      end: 41+0: a-4:i-27:a-1:a-1:a-1:m-0:m-3:m-1:p-1:s-2
    SUCCESS (182/177)

The above example is a regular migration run where 4 source removal migration
items and one source migration item where accepted (those listed on the
`final:` line). The rest of the information are various statistical counters
which are useful for other purposes beyond the scope of this document.

When debugging a migration for an item that passed the previous phase, if the
item appears on a `final:` line like that, then it is migrated.  That is, the
problem is most likely that the britney run crashes later or the britney's
output is not committed to the archive (for reasons outside britney's control).

On the flip side, if the migration item of interest does *not* appear in a
final line, then the migration was rejected (or rolled back).

Reminder: Migration items generally use the name of the source package.  There
are exceptions to that "rule" (but they are not common cases covered by this
document).

### Debugging failed migration attempts

Start by confirming that the migration item was not accepted (as described
in the above section).  If the migration item does not appear on a `final:` line,
then we need to debug the actual migration attempts.  Migration attempts look
something like this:

    trying: -webdis
    accepted: -webdis
       ori: 41+0: a-4:i-27:a-1:a-1:a-1:m-0:m-3:m-1:p-1:s-2
       pre: 41+0: a-4:i-27:a-1:a-1:a-1:m-0:m-3:m-1:p-1:s-2
       now: 41+0: a-4:i-27:a-1:a-1:a-1:m-0:m-3:m-1:p-1:s-2
       all: -pinfo -webdis
    [...]
    trying: libaws
    skipped: libaws (0, 165, 11)
        got: 45+0: a-4:i-27:a-5:a-1:a-1:m-0:m-3:m-1:p-1:s-2
        * arm64: libaws-bin, libaws17.2.2017, libaws3.3.2.2-dev, liblog4ada3-dev
    [...]
    Trying easy from autohinter: asis/2017-1 dh-ada-library/6.12 [...]
    start: 41+0: a-4:i-27:a-1:a-1:a-1:m-0:m-3:m-1:p-1:s-2
    orig: 41+0: a-4:i-27:a-1:a-1:a-1:m-0:m-3:m-1:p-1:s-2
    easy: 261+0: a-26:i-49:a-23:a-23:a-23:m-22:m-25:m-23:p-23:s-24
        * amd64: asis-programs, libasis2017, libasis2017-dev, libaws-bin, [...]
        * i386: asis-programs, libasis2017, libasis2017-dev, libaws-bin, [...]
        * arm64: asis-programs, libasis2017, libasis2017-dev, libaws-bin, [...]
        * armel: asis-programs, libasis2017, libasis2017-dev, libaws-bin, [...]
    [...]
    FAILED

This example has one succeeding migration (`-webdis`) and one failing
(`libaws`) plus finally a failed `easy`-hint with several packages.
Both of the two first are "single item" migrations (i.e. the attempt only
includes a single item in isolation).  However, Britney can do multi-item
migrations (even outside hints).

Please keep in mind that items can attempted multiple times and accepted in a
later attempt.  It is not always immediately obvious, which attempt is better
for debugging.  When in doubt, it is *usually* easiest to look at the attempt
with the least amount of new uninstallable packages.

In the libaws example, a total of 4 binary packages become uninstallable on the
architecture `arm64`.  Here is the output again with this information high lighted:

    migration item(s) being attemped
            vvvvvv
    trying: libaws
    skipped: libaws (0, 165, 11)
        got: 45+0: a-4:i-27:a-5:a-1:a-1:m-0:m-3:m-1:p-1:s-2
        * arm64: libaws-bin, libaws17.2.2017, libaws3.3.2.2-dev, liblog4ada3-dev
          ^^^^^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
          |||||        The binary packages becoming uninstallable (here 4)
          Affected architecture (here "arm64")

Please note that britney is lazy and will often reject an item after proving
that there is a regression on a single architecture.  So in the above example,
we are not actually sure whether this problem is architecture specific.  For
`easy`-hints, the information is presented slightly different.

    Trying easy from autohinter: asis/2017-1 dh-ada-library/6.12 [...]
                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                    migration item(s) being attemped
    
    [... several lines of statistics from start, before and after ...]
        * amd64: asis-programs, libasis2017, libasis2017-dev, libaws-bin, [...]
          ^^^^^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
          |||||        The binary packages becoming uninstallable on amd64
          Affected architecture (here "amd64")
    
        * i386: asis-programs, libasis2017, libasis2017-dev, libaws-bin, [...]
          ^^^^^ ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
          |||||       The binary packages becoming uninstallable on i386
          Affected architecture (here "i386")
    [... more architectures with binary packages becoming uninstallable ...]


While this tells us what britney tried to migrate and what would break (become
uninstallable) as a result, it is not very helpful at explaining *why*
things break.  If there are few broken packages, it is often a question of
looking for `Breaks`-relations or `Depends`-relations with upper bounds on
versions / on old packages being removed.  Alternatively, there are also tools
like `dose-debcheck`, which attempts to analyse and explain problems like this.

# Common issues with policy decisions

## Britney complains about a fixed bug in the source suite (bug policy)

All decisions about bugs are related to data set extracted
from the bug tracker.  If britney says that the new version
introduces a bug, then it is because the data set from the bug
tracker lists that bug for *a* version in the source suite and
without it appearing for the version(s) in the target suite.

Please note that these data sets do not include versions, so
britney is unable to tell exactly which versions are affected.
The only thing, she can tell, is what suite the bug affects.

There is a number of common cases, where this is observed:

 * The metadata on the bug is wrong.  A known example is the
   Debian BTS, where if a bug has a `fixed` version equal to
   a `found` version, the bug is considered unfixed.

 * The bug is fixed, but the old version is still around in
   the source suite.  In this case, britney will generally
   mention a "missing build" or "old binaries".

If the metadata is wrong, the solution is to fix it in the bug
tracker and wait until britney receives a new data set.  In
the other case, the recommendation is to see the sections on
"missing builds" and "old binaries" below.  As long as they
are present, the package may be blocked by bugs in the older
versions of the binaries.

## Britney complains about "missing builds"

A "missing build" happens when britney detects that the binaries
for a given architecture are missing or is not up to date.  This
is detected by checking the "Packages" files in the archive, so
britney have no knowledge of *why* the build is missing.
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

## Britney complains about "old binaries"

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
   
   (Note: the bugs data is not versioned so britney cannot tell which
    versions the bug applies to.  Just which suite they affect)

 * Even if the migration item is a valid candidate (i.e. all policy
   checked have passed), it may cause installability regressions as
   britney will also attempt to keep the old binaries around as long
   as they are used.  The most often cause of this when the old
   binaries are not co-installable with the new ones.
   
   (Note: Britney generally only works with the highest version of a
    given binary.  If you have libfoo1 depends on libfoo-data v1 and
    then libfoo2 depends on libfoo-data v2, then libfoo1 will become
    uninstallable as libfoo-data v2 will "shadow" libfoo-data v1)

