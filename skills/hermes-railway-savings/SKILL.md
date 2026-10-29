---
name: hermes-railway-savings
description: "Use when a Hermes on Railway must cut RAM, disk or tokens."
---

# Hermes on Railway: cut RAM, disk and tokens

A checklist tested on a production Hermes (Railway template, volume mounted at `/data`, one or more profiles).

Railway prices, roughly ([pricing](https://railway.com/pricing)):
- RAM: ~US$ 10/GB/month.
- vCPU: ~US$ 20/month.
- Disk: ~US$ 0.15/GB/month.

**RAM and tokens are what cost money. Disk only matters so it doesn't fill up.**

## 1. Measure before changing anything
- **Container RAM:** `cat /sys/fs/cgroup/memory.current` and `grep -E '^(anon|file) ' /sys/fs/cgroup/memory.stat`.
- **Per process:** `ps -eo rss,args --sort=-rss | head`.
- **Disk:** `df -h /data` and `du -xsh /data/* /data/.hermes/* | sort -rh | head`, then drill into the biggest ones.
- **Routine noise:** for each job, count the outputs from the last 3 days in `cron/output/<id>/` whose Response section is not `[SILENT]`.
- **Leave a logger running.** `scripts/mem_watch.sh` (below) writes RAM and the top consumers to `logs/mem_watch.log` every 15 min. Without that history you can't prove a change worked.

## 2. RAM
- **A dedicated Chrome** (WhatsApp Web, logged-in sites) eats 1.5–2 GB while open. Close it after 30 min and reopen it on demand. The login survives because it lives in the profile on disk (a fixed `--user-data-dir` on the volume). `mem_watch.sh` does this.
- **Orphan `browser_harness.daemon` processes** (~40 MB each) stay alive after their browser closes. `mem_watch.sh` kills the ones older than 30 min whose CDP port (`BU_CDP_WS` in the process environ) no longer answers. The first cleanup found 11 of them (~400 MB).
- **The gateway grows** from ~0.4 GB at boot to ~1.7 GB after 5 days, even with `agent_cache.memory_high_mb` set. This is Python malloc fragmentation.
  - Under test: set the Railway Variable `MALLOC_ARENA_MAX=2` and redeploy.
  - Check it applied with `tr '\0' '\n' < /proc/<gateway pid>/environ | grep MALLOC`.
  - Compare 3 days of growth in the log.

## 3. Disk
- **The usual villain is repo clones with `node_modules`** (~650 MB each). In cron the agent can't `rm -rf`, so every task left a fresh clone behind: 8 clones = 5.3 GB. Rules:
  - Keep one canonical checkout per repo.
  - Per task, run `git worktree add -b <branch> <dir> FETCH_HEAD`.
  - Symlink `node_modules` from the canonical checkout.
  - Run `git worktree remove --force` when done.
  - Run a daily no-AI cleanup: `scripts/clean_scratch.sh` deletes anything in scratch untouched for 1+ day, after saving a `git bundle` + `git diff` of whatever isn't on the remote.
  - Before deleting a clone by hand, run `git status` and `git log --branches --not --remotes`.
- **Old Hermes generations** in `/data/.hermes/installs/*/environments/` take ~2 GB each after an update. Remove them with:

  ```bash
  cd /opt/hermes && HERMES_HOME=/data/.hermes /opt/hermes/.venv/bin/python -c "from pathlib import Path; from hermes_cli.runtime_state import collect_generations as c; print(c(Path('/opt/hermes')))"
  ```

  It only removes generations that are neither selected nor leased.
- **Caches:**
  - `UV_CACHE_DIR=/data/.hermes/cache/uv /opt/hermes/tools/uv-*/uv cache prune` freed 1.2 GB.
  - Delete `~/.cache/pip` of each profile.
- **Raw media already published** (edited video, audio) can go once its owner confirms.
- **Result:** the volume went from 47% to 28% in one afternoon.

## 4. Tokens and CPU of routines (cron)
- **Watchers should be no-AI scripts.** Run `hermes cron create "every 5m" --script <s> --no-agent`.
  - Empty output means silent. Any output goes straight to the chat.
  - Each run costs milliseconds of CPU and zero tokens.
  - Good for: WhatsApp reply watchers, an SSH alarm, post-deploy checks, cleanups.
- **Monitor mode:** the script prints one stable line only when something changes (e.g. a meeting entering the 20–50 min window), so the AI only wakes up then.
- **`[SILENT]` by default.** A routine that talks to the user only writes when it has something concrete. Merge a profile's daily routines into ONE daily message.
- **Remove one-shot jobs that already ran** (`state: completed`). They only clutter the list. Run `hermes [-p profile] cron remove <id>`; the output stays in `cron/output`.
- **Pick the model by routine type:**
  - Plain reminder: Haiku.
  - Scoreboard or relay: Sonnet.
  - Text for other people, or anything that needs judgment: Opus.
  - An expensive model with a bad brief just writes nicer nonsense. Fix the prompt before upgrading the model.
- **Lower the frequency** of a routine whose suggestions the user keeps rejecting.

## 5. Pitfalls
- **WhatsApp Web watchers:** a reopened chat only renders its last ~4 rows. Filter replies by time (HH:MM ≥ request time), never by using your own message as an anchor. That message scrolls out and the watcher goes silent.
- **A watcher that fails 2 runs in a row** should say so, not stay quiet.
- **A new Railway Variable only applies after the deploy finishes.** Check the gateway uptime (`ps -o etime= -p <pid>`) before claiming it applied.
- **`pkill -f <pattern>`** in the agent's terminal can kill its own shell. Use `pgrep` + `kill <pid>`.

## Scripts
- **`scripts/mem_watch.sh`:** RAM logger, closes idle dedicated Chromes and kills orphan browser daemons. Cron: `hermes cron create "every 15m" --script mem_watch.sh --no-agent`.
- **`scripts/clean_scratch.sh`:** daily scratch cleanup with a git backup. Cron: `hermes cron create "0 4 * * *" --script clean_scratch.sh --no-agent`.
- **Setup:** copy them to `<HERMES_HOME>/scripts/` (or `profiles/<profile>/scripts/`) and adjust the variables at the top.
