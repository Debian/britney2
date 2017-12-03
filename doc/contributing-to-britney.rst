Contributing to the development of britney2
===========================================

If you are interested in improving britney, you can obtain the source
code via::

  git clone https://anonscm.debian.org/git/mirror/britney2.git
  # Additional tests
  git clone https://anonscm.debian.org/git/collab-maint/britney2-tests.git

You will need some packages to run britney and the test suites::

  # Runtime dependencies
  apt install python3 python3-apt python3-yaml
  # Test dependencies
  apt install python3-pytest libclass-accessor-perl rsync 
  # Documentation generator
  apt install python3-sphinx


Britney has some basic unit tests, which are handled by py.test.  It
also has some larger integration tests (from the `britney2-tests`
repo).  Running the tests are done via::

  cd britney2
  # Basic unit tests
  py.test-3
  # Integration tests
  rm -fr ./test-out/
  ../britney2-tests/bin/runtests ./britney.py ../britney2-tests/t ./test-out

The `runtests` command in `britney2-tests` supports running only a
subset of the tests.  Please see its `--help` output for more
information.

Finally, there is also some heavier tests based on some snapshots of
live data from Debian.  The data files for these are available in the
`live-data` submodule of the `britney2-tests` repo.  They consume
quite a bit of disk space and britney will need at least 1.3GB of RAM
to process them.
