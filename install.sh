#!/usr/bin/env bash
# Install every spell (skill) in hermes-grimoire into the current Hermes profile.
#
#   curl -fsSL https://raw.githubusercontent.com/silviomoreto/hermes-grimoire/main/install.sh | bash
#
# Each skill goes through `hermes skills install`, so Hermes' own security scan still runs on every one.
# Target a profile with HERMES_HOME=... or pass extra flags, e.g.: ... | bash -s -- --category productivity
set -euo pipefail

REPO="silviomoreto/hermes-grimoire"
BRANCH="main"

command -v hermes >/dev/null 2>&1 || { echo "hermes CLI not found in PATH" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "curl not found" >&2; exit 1; }

# List skill folders straight from GitHub, so new spells are picked up automatically.
skills=$(curl -fsSL "https://api.github.com/repos/${REPO}/contents/skills?ref=${BRANCH}" \
  | grep -oE '"path": *"skills/[^"/]+"' | cut -d'"' -f4 | cut -d/ -f2 | sort -u || true)

if [ -z "${skills}" ]; then
  echo "Could not list skills from GitHub (rate limit?). Try again in a minute." >&2
  exit 1
fi

ok=0; failed=0
for s in ${skills}; do
  echo "==> ${s}"
  if hermes skills install "${REPO}/skills/${s}" --yes "$@"; then
    ok=$((ok + 1))
  else
    failed=$((failed + 1))
    echo "    (failed: ${s})" >&2
  fi
done

echo "Done: ${ok} installed, ${failed} failed."
[ "${failed}" -eq 0 ]
