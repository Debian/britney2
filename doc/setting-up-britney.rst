How to setup britney
====================

This document describes how to install, configure and run britney in
your infrastructure.

Installing britney
------------------

At the moment, the preferred way to install britney is to clone the
source repo and run britney directly from the git checkout.

Configuring britney
-------------------

This is a very brief intro to the steps required to setup a Britney
instance.

 * Copy ``britney.conf.template`` and edit it to suit your purpose
    - If you want Britney to bootstrap your target suite, you
      probably want to add all architectures to ``NEW_ARCHES`` and
      ``BREAK_ARCHES`` for a few runs

 * Create the following files (they can be empty):

    * ``$STATE_DIR/age-policy-dates``
    * ``$STATE_DIR/age-policy-urgencies``
    * ``$STATE_DIR/rc-bugs-unstable``
    * ``$STATE_DIR/rc-bugs-testing``
    * ``$STATE_DIR/piuparts-summary-testing.json``
    * ``$STATE_DIR/piuparts-summary-unstable.json``

 * Run ``./britney.py -c $BRITNEY_CONF -v [--dry-run]`` to test the run

 * Setup a cron-/batch-job that:

    * (Optionally) Updates the rc-bugs files
    * (Optionally) Updates the $STATE_DIR/age-policy-urgencies
    * (Optionally) Updates the piuparts summary files
    * Runs Britney
    * Consume the results from Britney (See
      :ref:`using-the-results-from-britney` for more information)

hints - Configuring who can provide which hints
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Britney reads all hints from a set of `hints` files.  These files must
be placed in the directory denoted by the `HINTSDIR` configuration.
This is complimented with the `HINTS_<NAME>` configurations that
defines a "hint file" and the related hint permissions for it.

For each `HINTS_<NAME>` configuration, britney will attempt to read
`<HINTSDIR>/<name>`.  Note that it lowercases `<NAME>` when looking
for the file.


Configuration example::

    HINTSDIR = /etc/britney2/hints
    HINTS_ANNA = ALL
    HINTS_JOHN = STANDARD
    HINTS_FREEZE = block block-all block-udeb
    HINTS_AUTO-REMOVALS = remove

In the above example, we have defined 4 hints files named `anna`,
`john`, `freeze` and `auto-removals`.  These must be placed in
`/etc/britney2/hints` and be readable by britney.  Furthermore, they
must be writable by (only) the people that are allowed to use the
particular hints file (apply `chown`, `chmod` and `setfacl` as
neccesary).

The values on the right hand side of the `=` decides which hints are
permitted in the files.  With the above definitions:

 * The file `anna` may use any known hint (including potentially
   dangerous ones like `force` and `force-hint`)

 * The file `john` may use most of the known hints.  The set called STANDARD
   includes a lot of hints for overriding most policies when it
   can be done without (additional) side-effects.  However, it
   excludes `force` and `force-hint` as they can cause unintentional
   results.

 * The file `freeze` can use any of the hints `block`, `block-all`
   and `block-udeb`.

 * The file `auto-removals` can only use the hint called `remove`.

There are no fixed rules for how to use hints files.  Though usually,
each person with permissions to give hints to britney will have their
own hint file along with write permissions for that file.  It can also
make sense to create hint files for "roles".  Like in the above
example there are two human hinters (`anna` and `john`) plus two
non-human hinters (`freeze` and `auto-removals`).

Please see :doc:`hints` for which hints are available and what they
can do.


.. _using-the-results-from-britney:

Using the results from Britney
------------------------------

Britney optionally generates a number of files that may be useful for
further processing.

 * ``HEIDI_OUTPUT`` can be used with ``dak control-suite``.  Example::

     cut -d" " -f1-3 < ${HEIDI_OUTPUT} | dak control-suite --set ${TARGET_SUITE} [--britney]

 * ``HEIDI_DELTA_OUTPUT`` is a variant of ``HEIDI_OUTPUT`` that
   represent the result as a delta rather than a full selection.

 * ``EXCUSES_YAML_OUTPUT`` provides a machine-readable output about
   which packages comply with the active policies and which does not.

