A short introduction to migrations
==================================

This is a technical introduction to how britney
handles migrations.  Being an introduction, it deliberately
oversimplifies certain things at the expense of accuracy.
It also covers common migration issues and how to fix
them in :doc:`solutions-to-common-policy-issues`.

The document is primarily aimed at contributors for
distributions that want to understand the basics of
britney and its migration rules.

The documentation also aspires to be a general purpose document
for britney that is applicable for multiple distributions.
However, it does reference distribution-specific practises in
some examples to prevent the documentation from becoming too
abstract.  Furthermore, the document assumes familiarity with
Debian-based distribution practises and terminology (such as
"suites" and "source package").

A high level overview of britney and migrations
-----------------------------------------------

The purpose of britney is to (semi-)automatically select
a number of migration items from a series of source suites
(e.g. Debian unstable) that are ready to migrate to
the target suite (e.g. Debian testing).

The definition of "ready" can be summarized as satisfying all
of the following points:

 1. The migration items pass a number of policies for the target
    suite.  Most of these policies are basically that the
    migration items do not regress on selected QA checks.
    
    * An item satisfying this part is called a `valid candiate`.

 2. Installability will not regress as a result of
    migrating the migration items.

    * An item that (also) satisfies this part will be selected
      for migration.

The keyword in both points being *regress*.  If a package has an
existing issue in the target suite, the item including a new version
of that package is generally allowed to migrate if it has the same
issue (as it is not a regression).

This only leaves the definition of a migration items.  They come
in several variants defined in the next section.

Migration items
---------------

Internally, britney groups packages into migration items based on a
few rules.  There are several kinds of migration items and this
document will only describe the source migration item.

   A source migration item is one upload of a source package, with
   associated binary packages once built.

Once a new version of a source package appears in the source suite,
britney will create track it with a source migration item.  As the
binary packages are built and uploaded, they will be included into the
migration item and various QA checks/policies will be applied to the
item.

Once britney deems the item ready, it will attempt to
migrate the item (i.e. source with its binaries) to the 
target suite.


As implied earlier, there are several other migration types.  But they
are not covered in this document.  They deal with cases like removals,
rebuilds of existing binaries, etc.

Migration phase 1: Policies / Excuses
-------------------------------------

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

 2. Likewise, items may go from a "permanent failure" to a pass.

This can be seen in the following example case:

 1. A new version of package is uploaded.

    * Britney processes the package and concludes that there no blocking bugs,
      so the package passes the bug policy.

 2. Then before it migrates, someone files a blocking bug against
    the new version.

    * Britney reprocesses the package and now concludes it has a regression in
      the bug policy (i.e. the policy verdict goes from "pass" to "permanent fail").

 3. The bug is examined and it is determined that the bug also affects the
    version in the target suite.  The bug tracker is updated to reflect this.

    * Britney reprocesses the package again and now concludes there is a blocking
      bug, but it is not a regression (since it also affects the target suite).
      This means the policy verdict now go from "fail" to "pass".

This is also applicable to e.g. the piuparts policy, where if the test is
rescheduled on the piuparts side and the result changes as a result of that.

Finally, the people running the britney instance can overrule any
policy by applying a [britney hint](hints.html), if they deem it
necessary.  One caveat here is that not all policies can be overridden
directly and some will require the "ignore all policies"-hint (known
as the `force`-hint).

Since most policies are defined based on regressions,
a hinted migration generally implies that the problem will not
prevent future migrations for newer versions of the same source
package (assuming that the problem is deterministic).

Migration phase 2: Installability regression testing
----------------------------------------------------

For the migration items that pass the previous phase, britney
will do a test migration to see if anything becomes uninstallable.
This is a more expensive test to ensure the migration does not cause
installability regressions.

The status of this phase is *not* included in the excuses.  To debug
problems here, the britney log file has to be examined.  This requires
a bit more technical insight as it has not been polished as much as
the excuses.

Confirming a migration
^^^^^^^^^^^^^^^^^^^^^^

To start with; if a migration is accepted and "committed" (i.e. it will not
be rolled back), britney will include in a line starting with `final:` like
in this example::

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

Debugging failed migration attempts
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Start by confirming that the migration item was not accepted (as described
in the above section).  If the migration item does not appear on a `final:` line,
then we need to debug the actual migration attempts.  Migration attempts look
something like this::

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

In the libaws example, a total of 4 binary packages become
uninstallable on the architecture `arm64`.  Here is the output again
with this information high lighted::

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
`easy`-hints, the information is presented slightly different::

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
