#!/usr/bin/env bash
# Weekly no-AI disk sweep for a Hermes install on a small persistent volume.
# Only touches caches that rebuild themselves on demand. Silent unless the
# volume is still above DISK_WARN_PCT after the sweep (cron no_agent stays quiet
# on empty output). Safe to run while agents are working.
set -u
HERMES_HOME="${HERMES_HOME:-/data/.hermes}"
DATA_DIR="${DATA_DIR:-/data}"
BROWSER_DIRS="${BROWSER_DIRS:-$DATA_DIR/browser/*}"
NPX_MAX_DAYS="${NPX_MAX_DAYS:-7}"
DISK_WARN_PCT="${DISK_WARN_PCT:-70}"

before=$(df -P "$DATA_DIR" | awk 'NR==2{print $3}')

# 1. uv cache: drop unreferenced wheels/sources.
UV=$(ls -d /opt/hermes/tools/uv-*/uv 2>/dev/null | head -1)
[ -n "$UV" ] && [ -d "$HERMES_HOME/cache/uv" ] && UV_CACHE_DIR="$HERMES_HOME/cache/uv" "$UV" cache prune >/dev/null 2>&1

# 2. Per-home caches (main home + every profile home).
for h in "$HERMES_HOME/home" "$HERMES_HOME"/profiles/*/home; do
  [ -d "$h" ] || continue
  rm -rf "$h/.cache/pip/http" "$h/.cache/pip/http-v2" "$h/.npm/_cacache" 2>/dev/null
  [ -d "$h/.npm/_npx" ] && find "$h/.npm/_npx" -mindepth 1 -maxdepth 1 -type d -mtime +"$NPX_MAX_DAYS" -exec rm -rf {} + 2>/dev/null
done

# 3. Chrome caches, only for profiles whose Chrome is NOT running (logins live elsewhere).
for d in $BROWSER_DIRS; do
  [ -d "$d" ] || continue
  pgrep -f -- "--user-data-dir=$d( |$)" >/dev/null && continue
  for c in Cache "Code Cache" GPUCache DawnGraphiteCache DawnWebGPUCache GrShaderCache ShaderCache; do
    find "$d" -maxdepth 3 -type d -name "$c" -prune -exec rm -rf {} + 2>/dev/null
  done
done

after=$(df -P "$DATA_DIR" | awk 'NR==2{print $3}')
pct=$(df -P "$DATA_DIR" | awk 'NR==2{gsub("%","",$5); print $5}')
if [ "$pct" -ge "$DISK_WARN_PCT" ]; then
  echo "Disk still at ${pct}% after the weekly sweep (freed $(( (before-after)/1024 )) MB). Look at old Hermes generations, model caches and repo clones."
fi
exit 0
