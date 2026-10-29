#!/usr/bin/env bash
# grimoire.sh: install, update and list every spell (skill) of hermes-grimoire in the current Hermes profile.
#
#   grimoire.sh list      -> remote spells and whether each one is installed here
#   grimoire.sh install   -> install the spells that are missing (installed ones are left untouched)
#   grimoire.sh update    -> update the installed spells to the latest version (locally edited ones are skipped)
#
# Every install goes through `hermes skills install`, so Hermes' security scan runs on each spell.
# Target another profile with HERMES_HOME=... (or run it as `hermes -p <profile> ...` yourself).
set -uo pipefail

REPO="${GRIMOIRE_REPO:-silviomoreto/hermes-grimoire}"
BRANCH="${GRIMOIRE_BRANCH:-main}"
cmd="${1:-list}"

command -v hermes >/dev/null 2>&1 || { echo "hermes CLI not found in PATH" >&2; exit 1; }

remote=$(curl -fsSL "https://api.github.com/repos/${REPO}/contents/skills?ref=${BRANCH}" \
  | grep -oE '"path": *"skills/[^"/]+"' | cut -d'"' -f4 | cut -d/ -f2 | sort -u)
[ -z "${remote}" ] && { echo "Could not list spells from GitHub (rate limit?). Try again in a minute." >&2; exit 1; }

installed=$(hermes skills list --source hub 2>/dev/null | grep -oE '│ [a-z0-9][a-z0-9_-]+ ' | tr -d '│ ' | sort -u)
is_installed() { grep -qxF "$1" <<< "${installed}"; }

case "${cmd}" in
  list)
    for s in ${remote}; do
      if is_installed "$s"; then echo "✓ ${s}"; else echo "· ${s} (not installed)"; fi
    done
    ;;
  install)
    ok=0; skip=0; fail=0
    for s in ${remote}; do
      if is_installed "$s"; then skip=$((skip + 1)); continue; fi
      echo "==> installing ${s}"
      if hermes skills install "${REPO}/skills/${s}" --yes >/dev/null 2>&1; then
        ok=$((ok + 1)); echo "    installed"
      else
        fail=$((fail + 1)); echo "    FAILED (run: hermes skills install ${REPO}/skills/${s})" >&2
      fi
    done
    echo "Done: ${ok} installed, ${skip} already there, ${fail} failed."
    [ "${fail}" -eq 0 ]
    ;;
  update)
    for s in ${remote}; do
      is_installed "$s" || continue
      echo "==> ${s}"
      hermes skills update "$s" 2>&1 | grep -vE '^\s*$' | tail -2
    done
    ;;
  *)
    echo "usage: grimoire.sh [list|install|update]" >&2; exit 2
    ;;
esac
