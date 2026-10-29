#!/bin/bash
# Silent RAM logger + idle-closer for dedicated Chromes + orphan browser daemon killer.
# Cron (no AI): hermes cron create "every 15m" --script mem_watch.sh --no-agent   (empty output = silent)
# Adjust PROFILES: names of dedicated Chrome profiles under BROWSER_DIR (each started with --user-data-dir=$BROWSER_DIR/<name>).
LOG=${HERMES_HOME:-/data/.hermes}/logs/mem_watch.log
BROWSER_DIR=/data/browser
PROFILES="whatsapp"          # e.g. "whatsapp grok"
IDLE_SECONDS=1800
ts=$(date '+%d/%m %H:%M')
cur=$(awk '{printf "%.2f",$1/1e9}' /sys/fs/cgroup/memory.current 2>/dev/null)
anon=$(awk '$1=="anon"{printf "%.2f",$2/1e9}' /sys/fs/cgroup/memory.stat 2>/dev/null)
top=$(ps -eo rss,args --sort=-rss | awk 'NR>1{a=$0; sub(/^ *[0-9]+ /,"",a); k="outro"; if(a~/chrom/)k="chrome"; else if(a~/python -P -c/)k="gateway"; else if(a~/browser_harness/)k="bh-daemon"; else if(a~/python/)k="python"; else if(a~/node/)k="node"; s[k]+=$1} END{for(k in s) printf "%s=%.2f ",k,s[k]/1048576}')
echo "$ts total=${cur}GB anon=${anon} | $top" >> "$LOG"
# 1) close dedicated Chromes open longer than IDLE_SECONDS (login persists in the profile dir)
for prof in $PROFILES; do
  pid=$(pgrep -o -f "user-data-dir=$BROWSER_DIR/$prof( |$)")
  [ -z "$pid" ] && continue
  age=$(( $(date +%s) - $(stat -c %Y /proc/$pid) ))
  [ $age -gt $IDLE_SECONDS ] && kill $pid 2>/dev/null && echo "$ts closed chrome-$prof (open for $((age/60)) min)" >> "$LOG"
done
# 2) kill orphan browser_harness daemons whose CDP port no longer answers
for p in $(pgrep -f browser_harness.daemon); do
  [ "$(ps -o etimes= -p $p 2>/dev/null | tr -d ' ')" -gt $IDLE_SECONDS ] 2>/dev/null || continue
  port=$(tr '\0' '\n' < /proc/$p/environ 2>/dev/null | grep -E "^BU_CDP_WS=" | grep -oE ":[0-9]{4,5}/" | tr -d ':/' | head -1)
  [ -z "$port" ] && continue
  (exec 3<>/dev/tcp/127.0.0.1/$port) 2>/dev/null && continue
  kill $p 2>/dev/null && echo "$ts killed orphan browser daemon (pid $p, port $port)" >> "$LOG"
done
exit 0
