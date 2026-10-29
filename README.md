# hermes-grimoire 🌙

A spell book for [Hermes Agent](https://hermes-agent.nousresearch.com/docs): **skills battle-tested on a real, always-on Hermes**, ready to drop into yours.

Each skill is a spell: a folder with a `SKILL.md` (when to use it and how), plus optional `scripts/` and `references/`.

## Spells

| # | Skill | What it does |
|---|-------|--------------|
| 1 | [`hermes-railway-savings`](skills/hermes-railway-savings) | Run Hermes on Railway on a diet: RAM, disk and routine tokens. Ships with a memory watcher and a daily scratch cleanup. |
| 2 | [`nightly-dream`](skills/nightly-dream) | A nightly routine where the agent rereads the day, turns your corrections into skill rules and writes a diary. |
| 3 | [`whatsapp-web`](skills/whatsapp-web) | Your agent reads and sends on your own WhatsApp (text, images, reply watchers), always with your approval. |

## Install a skill

All spells at once:

```bash
curl -fsSL https://raw.githubusercontent.com/silviomoreto/hermes-grimoire/main/install.sh | bash
```

It lists the folders in `skills/` and runs `hermes skills install` on each one, so new spells come along automatically. Target another profile with `HERMES_HOME=...`.

Or one at a time, from any Hermes:

```bash
hermes skills install silviomoreto/hermes-grimoire/skills/nightly-dream
hermes skills install silviomoreto/hermes-grimoire/skills/hermes-railway-savings
hermes skills install silviomoreto/hermes-grimoire/skills/whatsapp-web
```

Hermes runs its security scan before installing (these show up as `community` trust). Preview first with `hermes skills inspect <same identifier>`.

Or copy it by hand:

```bash
git clone https://github.com/silviomoreto/hermes-grimoire.git /tmp/hermes-grimoire
cp -r /tmp/hermes-grimoire/skills/<name> "$HERMES_HOME/skills/<category>/"
```

Then read its `SKILL.md`: each skill says what to adjust (paths, ports, cron).

## Contribute a spell

1. **Generic only.** It must help any Hermes. Personal context (addresses, contacts, calendars, preferences) stays in your local copy.
2. **No secrets.** No tokens, passwords, cookies, API keys or personal IDs. Scripts read secrets from the environment and never print them.
3. **No personal or customer data.**
4. **`description` up to 60 characters**, starting with "Use when ..." (it is what the agent reads to decide whether to load the skill).
5. **Tested for real.** Say in the PR where it ran and what you checked.

Before opening a PR: `grep -rniE "token|password|secret|@gmail" skills/<name>`.
