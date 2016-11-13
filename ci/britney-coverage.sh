#!/bin/sh

# This script is used on (e.g.) Travis CI to collect coverage

dir=$(dirname "$(dirname "$0")")
exec python3-coverage run --rcfile "$dir/.coveragerc" --append "$dir/britney.py" "$@"
