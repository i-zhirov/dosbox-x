#!/bin/sh
# Run the fork self-tests: build the fixtures and run every test.
#
# The tests need RE_DOSBOXX set to the DOSBox-X binary.  The stop tests also
# need RE_GAME_DIR set to the game directory.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"

sh "$DIR/build_fixture.sh"

if [ -z "$RE_DOSBOXX" ]; then
    echo "RE_DOSBOXX is not set; the tests are skipped"
    exit 0
fi

cd "$ROOT"
python3 -m unittest discover -s tests/re -v
