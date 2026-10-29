#!/bin/sh
set -eu
profile=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for git in /opt/homebrew/bin/git /usr/bin/git; do
    TEST_GIT="$git" /opt/homebrew/bin/python3 -I -m unittest discover -s "$profile" -p test_guard.py -q
done
