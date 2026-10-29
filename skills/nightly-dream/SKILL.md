---
name: nightly-dream
description: Use when setting up a nightly self-review cron for Hermes.
---

# Nightly dream: the agent consolidates the day while you sleep

## When to Use
- You want the agent to learn from the day's corrections without anyone saying "save this as a skill".
- Conversations restart from zero (`/new`, compression) and you want a written thread to pick up from.
- Set it up once per Hermes profile. Each profile dreams about its own conversations.

## What it does
A cron runs every night (e.g. 3:30 am), silently, on a strong model (e.g. Opus). It:

1. **Rereads the day.**
   - `scripts/day_transcript.py` dumps the last ~26h of user and agent messages, without tool output, so reading is cheap.
   - It also checks the cron outputs (`<HERMES_HOME>/cron/output/*/`) for errors and failed deliveries.
2. **Updates skills.** Every user correction, agent mistake, rework or new procedure that worked becomes a short imperative rule, with its "why", in the skill for that task (`skill_manage patch`). It reads the skill first, never duplicates, and makes at most 5 patches per night.
3. **Updates the task list:** done items, promises (with dates) and dropped items. It only changes what the history shows.
4. **Writes a diary** at `<data dir>/diary/YYYY-MM-DD.md`: at most 40 lines, mode 600, with these sections:
   - Decisions
   - Deliveries
   - Open items
   - Promises with dates
   - Mistakes and lessons
   - Memory suggestions
5. **Stays silent.** It answers `[SILENT]`, except when the user must know something today: a broken promise, a routine failing for 2+ days, an expired token. Then it sends up to 3 lines.

## Setup
1. Copy `scripts/day_transcript.py` to `<HERMES_HOME>/scripts/` and test it: `python3 day_transcript.py 26 --out /tmp/day.txt`.
2. Adapt `references/prompt.md`: paths, the user's main skills and the confidentiality rules.
3. Create the cron, pinned to a strong model:

   ```bash
   hermes cron create "30 3 * * *" "$(cat prompt.md)" --name "Dream · consolidate the day" --deliver <origin|telegram:<chat_id>> --model <strong model> --provider <provider>
   ```

4. Optional: `hermes config set curator.consolidate true`. The weekly cleanup then merges duplicate skills.
5. Several profiles on one machine: stagger the times (e.g. 3:00 and 3:30) so they don't compete for the same quota.

## Rules that matter
- **Don't let the dream write memory** if memory writes need approval (`memory.write_approval`) or memory is nearly full. Otherwise the user wakes up to a pile of approvals. Suggestions go in the diary.
- **Confidentiality:**
  - Anything the user asked not to keep goes nowhere.
  - People and HR topics go in only as a neutral theme, without names.
  - No secrets or tokens.
  - Confidential numbers go only in the private diary.
- **Limits:**
  - The dream does not create, edit or remove crons.
  - It does not send messages, post or touch the calendar.
  - It reports broken routines; it doesn't fix them.
- **Never invent anything that is not in the history.**
- **When a conversation restarts from zero,** the agent reads the latest diary before answering about open items. Put this rule in the agent's main skill.

## Files
- `scripts/day_transcript.py`: transcript of the last N hours from `<HERMES_HOME>/state.db`, opened read-only.
- `references/prompt.md`: the cron prompt template.
