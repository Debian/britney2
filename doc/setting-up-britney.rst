How to setup britney
====================

This document describes how to install, configure and run britney in
your infrastructure.

Installing britney
------------------

TODO

Configuring britney
-------------------

TODO

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


Using the results from britney
------------------------------

TODO

