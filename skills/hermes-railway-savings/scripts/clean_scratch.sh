#!/bin/bash
# Daily scratch cleanup (no AI). Agents in cron cannot `rm -rf`, so repo clones (with node_modules,
# ~650 MB each) pile up in the scratch dir. This removes anything untouched for 1+ day, after saving
# a git bundle + diff of git repos, and drops node_modules of idle worktrees.
# Cron: hermes [-p <profile>] cron create "0 4 * * *" --script limpa_scratch.sh --no-agent
set -u
HOME_DIR=${HERMES_HOME:-/data/.hermes}          # or /data/.hermes/profiles/<profile>
SCRATCH=$HOME_DIR/cache/scratch
BK=$HOME_DIR/workspace/backups/scratch-clones
REPOS=""                                          # canonical checkouts with worktrees, e.g. "/data/projects/app"
mkdir -p "$BK"
freed=0
stale() { [ -z "$(find "$1" -xdev -newermt '-1 day' -print -quit 2>/dev/null)" ]; }
for d in "$SCRATCH"/*/; do
  d=${d%/}; [ -d "$d" ] || continue
  stale "$d" || continue
  kb=$(du -xsk "$d" 2>/dev/null | cut -f1)
  if [ -e "$d/.git" ]; then
    name=$(basename "$d")
    git -C "$d" bundle create "$BK/$name.bundle" --all >/dev/null 2>&1
    git -C "$d" diff > "$BK/$name.diff" 2>/dev/null; [ -s "$BK/$name.diff" ] || rm -f "$BK/$name.diff"
  fi
  rm -rf "$d" && freed=$((freed + kb))
done
for repo in $REPOS; do
  [ -d "$repo/.git" ] || continue
  git -C "$repo" worktree prune >/dev/null 2>&1
  git -C "$repo" worktree list --porcelain | awk '/^worktree /{print $2}' | while read -r wt; do
    [ "$wt" = "$repo" ] && continue
    stale "$wt" || continue
    [ -z "$(git -C "$wt" status --porcelain 2>/dev/null)" ] || continue
    [ -d "$wt/node_modules" ] && [ ! -L "$wt/node_modules" ] && rm -rf "$wt/node_modules"
  done
done
find "$BK" -xdev -type f -mtime +14 -delete 2>/dev/null
[ "$freed" -gt 1048576 ] && echo "🧹 Cleanup: freed $((freed / 1048576)) GB of stale copies from disk."
exit 0
