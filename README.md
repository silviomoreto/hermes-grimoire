# hermes-grimoire 🌙

[![skills.sh](https://skills.sh/b/silviomoreto/hermes-grimoire)](https://skills.sh/silviomoreto/hermes-grimoire) [![License: MIT](https://img.shields.io/badge/license-MIT-black.svg)](LICENSE)

A spell book for [Hermes Agent](https://hermes-agent.nousresearch.com/docs): **skills battle-tested on a real, always-on Hermes**, ready to drop into yours.

Each skill is a spell: a folder with a `SKILL.md` (when to use it and how), plus optional `scripts/` and `references/`.

## Spells

| # | Skill | What it does |
|---|-------|--------------|
| 0 | [`grimoire`](skills/grimoire) | The book itself: installs every spell, tells you what's new and updates them. Start here. |
| 1 | [`hermes-railway-savings`](skills/hermes-railway-savings) | Run Hermes on Railway on a diet: RAM, disk and routine tokens. Ships with a memory watcher and a daily scratch cleanup. |
| 2 | [`nightly-dream`](skills/nightly-dream) | A nightly routine where the agent rereads the day, turns your corrections into skill rules and writes a diary. |
| 3 | [`whatsapp-web`](skills/whatsapp-web) | Your agent reads and sends on your own WhatsApp (text, images, reply watchers), always with your approval. |

## Install

**The whole grimoire, the easy way.** Install the `grimoire` skill, then just ask your agent:

```bash
hermes skills install silviomoreto/hermes-grimoire/skills/grimoire
```

> "Install the whole grimoire" · "Any new spells?" · "Update the grimoire"

The agent installs what is missing, updates what you have, and asks before setting up crons or logins.

**Or from the terminal, in one line:**

```bash
curl -fsSL https://raw.githubusercontent.com/silviomoreto/hermes-grimoire/main/install.sh | bash
```

**Or one spell at a time:**

```bash
hermes skills install silviomoreto/hermes-grimoire/skills/nightly-dream
hermes skills install silviomoreto/hermes-grimoire/skills/hermes-railway-savings
hermes skills install silviomoreto/hermes-grimoire/skills/whatsapp-web
```

Every path goes through `hermes skills install`, so Hermes runs its security scan on each spell (they show up as `community` trust). Preview first with `hermes skills inspect <same identifier>`. Target another profile with `HERMES_HOME=...`.

Then read each spell's `SKILL.md`: it says what to adjust (paths, ports, cron).

## Contribute a spell

1. **Generic only.** It must help any Hermes. Personal context (addresses, contacts, calendars, preferences) stays in your local copy.
2. **No secrets.** No tokens, passwords, cookies, API keys or personal IDs. Scripts read secrets from the environment and never print them.
3. **No personal or customer data.**
4. **`description` up to 60 characters**, starting with "Use when ..." (it is what the agent reads to decide whether to load the skill).
5. **Tested for real.** Say in the PR where it ran and what you checked.

Before opening a PR: `grep -rniE "token|password|secret|@gmail" skills/<name>`.

## License

[MIT](LICENSE). Use, fork and remix freely.
