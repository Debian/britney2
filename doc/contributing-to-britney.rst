Contributing to the development of britney2
===========================================

If you are interested in improving britney, you can obtain the source
code via::

  git clone https://salsa.debian.org/release-team/britney2.git
  # Additional tests
  git clone https://salsa.debian.org/debian/britney2-tests.git

You will need some packages to run britney and the test suites::

  # Runtime dependencies
  apt install python3 python3-apt python3-yaml
  # Test dependencies
  apt install python3-pytest libclass-accessor-perl rsync
  # Documentation generator
  apt install python3-sphinx
  # AMQP integration for autopkgtest policy (optional runtime dependency)
  apt install python3-amqplib

Britney has some basic unit tests, which are handled by py.test.  It
also has some larger integration tests (from the ``britney2-tests``
repo).  Running the tests are done via::

  cd britney2
  # Basic unit tests
  py.test-3
  # Integration tests
  rm -fr ./test-out/
  ../britney2-tests/bin/runtests ./britney.py ../britney2-tests/t ./test-out

The ``runtests`` command in ``britney2-tests`` supports running only a
subset of the tests.  Please see its ``--help`` output for more
information.

There are also some heavier tests based on some snapshots of
live data from Debian.  The data files for these are available in the
``live-data`` submodule of the ``britney2-tests`` repo.  They consume
quite a bit of disk space and britney will need at least 1.3GB of RAM
to process them.


Documentation is handled by sphinx and can be built via::

    make html
