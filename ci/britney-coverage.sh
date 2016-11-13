#!/bin/sh

# This script is used on (e.g.) Travis CI to collect coverage

dir=$(dirname "$(dirname "$0")")
exec python3-coverage run --omit '*/yaml/*.py' --branch --append "$dir/britney.py" "$@"
