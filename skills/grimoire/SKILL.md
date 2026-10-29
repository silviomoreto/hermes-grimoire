---
name: grimoire
description: Use when installing or updating every hermes-grimoire spell.
---

# Grimoire: install and update every spell at once

This skill knows the whole [hermes-grimoire](https://github.com/silviomoreto/hermes-grimoire). Install it once and ask your agent things like "install the whole grimoire", "any new spells?" or "update the grimoire".

```bash
hermes skills install silviomoreto/hermes-grimoire/skills/grimoire
```

## When to Use
- The user asks to install all grimoire spells, or the ones that are missing.
- The user asks what's new in the grimoire, or to update the installed spells.

## How
The script is `scripts/grimoire.sh` inside this skill's folder (find it with `skill_view grimoire` or under `$HERMES_HOME/skills/`). It reads the spell list straight from GitHub, so new spells show up without updating this skill.

1. **See what exists:** `bash scripts/grimoire.sh list`. Each spell shows ✓ if installed here, · if not.
2. **Install what is missing:** `bash scripts/grimoire.sh install`. It runs `hermes skills install <repo>/skills/<name> --yes` for each missing spell, so Hermes' security scan runs on every one. Spells already installed are left alone.
3. **Update:** `bash scripts/grimoire.sh update`. It runs `hermes skills update <name>` for each installed spell. Spells the user edited locally are skipped; use `hermes skills update <name> --force` only if the user agrees to lose their edits.
4. **Report to the user** in a few lines: what was installed, updated or failed.
5. **Then offer setup, don't do it silently.** Some spells only work after setup: crons (`nightly-dream`, `hermes-railway-savings`) or a WhatsApp login (`whatsapp-web`). Read each new spell's `SKILL.md`, list what it needs, and ask before creating crons or logging into anything.

## Pitfalls
- **GitHub API rate limit** (60 requests/hour without a token): if `list` fails, wait a minute and retry.
- **Another profile:** prefix with `HERMES_HOME=<profile dir>` so the spells land in the right profile.
- **One spell only:** `hermes skills install silviomoreto/hermes-grimoire/skills/<name>`.
