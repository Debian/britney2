#!/bin/bash

set -e

err=0

nosetests3 -v --with-coverage || err=$?
echo
echo
britney2-tests/bin/runtests ./ci/britney-coverage.sh britney2-tests/t test-out || err=$?
echo
britney2-tests/bin/runtests ./britney.py britney2-tests/live-data test-out-live-data-1 live-2011-12-13 || err=$?
echo
britney2-tests/bin/runtests ./britney.py britney2-tests/live-data test-out-live-data-2 live-2011-12-20 || err=$?
echo
if [ -n "$CI" ] ; then
    echo skipping live-2012-01-04 to prevent time out on Travis of the whole test suite
else
    britney2-tests/bin/runtests ./britney.py britney2-tests/live-data test-out-live-data-3 live-2012-01-04 || err=$?
fi
echo
britney2-tests/bin/runtests ./britney.py britney2-tests/live-data test-out-live-data-4 live-2012-05-09 || err=$?
echo
britney2-tests/bin/runtests ./britney.py britney2-tests/live-data test-out-live-data-5 live-2016-04-11 || err=$?
echo

if [ $err = 0 ] ; then
    python3-coverage report || true
    echo
    python3-coverage report -m || true
    echo
    python3-coverage xml -i || true
    echo
    mv .coverage shared
fi

exit $err
