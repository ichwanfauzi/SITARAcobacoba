#!/usr/bin/env sh
set -eu
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
git config core.hooksPath .githooks
printf '%s\n' "Git hooks installed: .githooks"
