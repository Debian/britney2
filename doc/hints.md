#! TITLE: Britney hints documentation
#! SUBTITLE: How to override the britney policies

# Britney hints

This document describes the "britney hints".  These are basically
small instructions to britney.  The vast majority of them involve
overriding a quality gating policy in britney.  However, there are a
few hints that assist britney into finding solutions that it cannot
compute itself.


## Related configuration

The configuration `HINTSDIR` determines which directory contains the
so called "hints files".  This is complimented with the `HINTS_<NAME>`
configurations that defines a "hint file" and the related hint
permissions for it.

For each `HINTS_<NAME>` configuration, britney will attempt to read
`<HINTSDIR>/<name>`.  Note that it lowercases `<NAME>` when looking
for the file.


Configuration example:

    HINTSDIR = /etc/britney2/hints
    HINTS_ANNA = ALL
    HINTS_JOHN = STANDARD
    HINTS_FREEZE = block block-all block-udeb
    HINTS_AUTO-REMOVALS = remove

There is no fixed rules for how to use hints files.  Though usually,
each person with permissions to give hints to britney will have their
own hint file along with write permissions for that file.  It can also
make sense to create hint files for "roles".  Like in the above
example there are two human hints (anna and john) plus two non-human
hinters (freeze and auto-removals).


## Format of the hint file

The hint file is a plain text file with line-based content.  Empty and
whitespace-only lines are ignored.  If the first (non-whitespace)
character is a `#`, then britney considers it a comment and ignores
it.  However, other tooling may interpret these comments (as is the
case for e.g. some parts of the Debian infrastructure).

The remaining lines are considered space-separated lists, where the
first element must be a known hint.  The remaining elements will be
interpreted as its arguments.  Britney generally warns on and then
discards unknown hints or hints with invalid arguments.

The following are common types of arguments for hints:

 * Unversioned item, format: `<item name>`
 * Versioned item, format: `<item name>/<version>`
 * Architecture-qualified versioned item: `<item name>/<version>/<architecture>`

(The above-mentioned types correspond to britney migration item types)

Generally, for hints, all item names will be names of source packages.
Furthermore, some hints also accept a `-` before the item name.  This
generally refers to the removal of said item rather than the migration
of the hint.


# Hints

There are the following type of hints:

 * Policy overrides
 * Migration selections (with or without overrides)
 * Other


## Policy override hints

The policy override hints are used to disable or tweak various
policies in britney.  Their effects are generally very precise ways of
accepting specific regressions or disabling various checks.

Some of these items are built-in while others are related to specific
policies.  In the latter case, they are only valid if the given policy
is enabled (as the policy registers them when it is enabled).

### block-all `<type>`

Usually used during freezes to prevent migrations by default.

The `<type>` can be one of:

 * `source`: Blocks all source migrations.  This is a superset of
   `new-source`.
 * `new-source`: Block source migrations if the given source is not
    already in the target suite.  (Side-effect: Removed packages will
    not re-enter the taget suite automatically).

All variants of these can be overruled by a valid `unblock`-hint.

Note that this does not and cannot restrict architecture specific
migrations (e.g. binNMUs or first time builds for architectures).

### block `<action list>`, block-udeb `<action list>`

Prevent the items in the `<action list>` from migrating until the hint
is removed or overruled by the equivalent unblock hint (or a
`remove`-hint).  All items in the `<action list>` must be unversioned
items and can be prefixed with `-` to prevent removal by built-in
policies.  However, it will not prevent removals requested by a
`removal`-hint.

The `block-udeb` is mainly intended for preventing accidental
migration of installer-related packages during the later stages of the
release cycle.

Note that this does not and cannot restrict architecture specific
migrations (e.g. binNMUs or first time builds for architectures).

### unblock `<action list>`, unblock-udeb `<action list>`

Enable the items in `<action list>` to migrate by overriding `block`-,
`block-all`- or `block-udeb`-hints.  The `unblock`-hint (often under
its synonym `approve`) is also used to approve migrations from source
suites that require approval.

The items in `<action list>` must all be versioned items.

The `unblock-udeb` is mainly intended for preventing accidental
migration of installer-related packages during the later stages of the
release cycle.

The two types of block hint must be paired with their corresponding
unblock hint - i.e. an `unblock-udeb` does not override a `block`.

### approve `<action list>`

A synonym of `unblock`.  The variant is generally used for approving
migrations from suites that require approvals.

Aside from the tab-completion in the hint testing interface, which
will give different suggestions to `approve` and `unblock`, the rest
of britney will consider them identical.

### age-days `<days>` `<action list>`

Set the length of time which the listed action items must have been in
unstable before they can be considered candidates.  This may be used
to either lengthen or reduce the default time period.  All items in
`<action list>` must be versioned items.

If multiple `age-days` hints for a single package are available,
whichever is encountered first during parsing overrides the others.

Provided by the `age` policy.

### urgent `<action list>`

Approximately equivalent to `age-days 0 <action list>`, with the
distinction that an "urgent" hint overrides any "age-days" hint for
the same action item.

Provided by the `age` policy.

### ignore-rc-bugs `<bugs>` `<action list>`

The `<bugs>` argument is a comma separated list <bugs> of bugs that
affect the items in `<action list>`.  Britney will ignore these bugs
when determining whether the migration items have regressed compared
to the target suite.  All items in `<action list>` must be versioned
items.

Currently britney supports at most one active `ignore-rc-bugs` per
migration item.

Provided by the `bugs` policy

### ignore-piuparts `<action list>`

The items in `<action list>` will not be blocked by regressions in
results from piuparts tests.  All items in `<action list>` must be
versioned items.

Provided by the `piuparts` policy

### force `<action list>`

Override all policies that claim the items in `<action list>` have
regressions or are otherwise not ready to migrate.  All items in the
`<action list>` must be versioned items or architecture qualified
versioned items.

This hint does not guarantee that they will migrate.  To ensure that,
you will have to combine it with a `force-hint`.  However, please read
the warning in the documentation for `force-hint` before you do this.

## Migration selection hints

All migration selection hints work on an "action list".  This consists
of at least 1 or more of the following (in any combination):

 * Versioned item (e.g. `coreutils/8.27`)
 * Architecture qualified versioned item (e.g. `coreutils/8.27-1/amd64`)
 * The removal of either of the above (e.g. `-coreutils/8.27-1` or `-coreutils/8.27-1/amd64`)

All elements in the action list must be valid at the time the hint is
attempted.  Notably, if one action has already been completed, the
entire hint is rejected as invalid.

### easy `<action list>`

Perform all the migrations and removals denoted by `<action list>` as if
it were a single migration group.  If the end result is equal or better
compared to the original situation, the action is committed.

This hint is primarily useful if britney fails to compute a valid
solution for a concrete problem with a valid solution.  Although, in
many cases, Britney will generally figure out the solution on its own.

Note that for `easy` the `<action list>` must have at least two
elements.  There is no use-case where a single element for easy will
make sense (as britney always tries those).

### hint `<action list>`

Perform all the migrations and removals denoted by `<action list>` as if
it were a single migration group.  After that, process all remaining
(unmigrated) items and accept any that can now be processed.  If the
end result is equal or better compared to the original situation, the
result is committed.  Otherwise, all actions triggered by the hint are
rolled back.

The primary difference between `easy` and `hint` is who carries the
burden of finding the solution.  In an `easy` hint, the hinter must
provide a full valid and self-contained solution.  Whereas with a
`hint`, the hinter can basically say "I want X to migrate, try to
figure out a solution for it".  For the same reason, `hint`-hints are
rather expensive and should be used sparingly.

This hint is primarily useful if britney fails to compute a valid
solution for a concrete problem with a valid solution.  Although, in
many cases, Britney will generally figure out the solution on its own.

*Caveat*: Due to "uninstallability trading", this hint may cause
undesireable changes to the target suite.  In practise, this is rather
rare but the hinter is letting britney decide what "repairs" the
situation.

### force-hint `<action list>`

The provided `<action list>` is migrated as-is regardless of what is
broken by said migration.  This often needs to be paired with a
`force`-hint to ensure that the actions are considered as valid
candidates.

This hint is generally useful when the provided `<action list>` is more
desirable than the resulting breakage.

*Caveat*: Be sure to test the outcome of these hints.  A last minute
change can have long lasting undesireable consequences on the end
result.

## Other hints

This section cover hints that have no other grouping.

### remove `<action list>`

Britney should attempt to remove all items in the `<action list>` from
the target suite.  The `<action list>` must consist entirely of
versioned items (note the items should *not* be prefixed with "-").

If an item in `<action list>` is not in the target suite that item is
silently ignored.

Note: It is not possible to do architecture specific removals via
`remove`-hints.
