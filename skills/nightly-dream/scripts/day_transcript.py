#!/usr/bin/env python3
"""Dump the last N hours of the agent conversations (current HERMES_HOME) as a compact transcript.

Used by the nightly "dream" cron. Keeps only user messages and assistant text replies
(no tool calls / tool outputs), so the dream reads the day cheaply.

Usage: day_transcript.py [hours=26] [--out FILE]
"""
import datetime, os, sqlite3, sys
from zoneinfo import ZoneInfo

try:
    TZ = ZoneInfo(os.environ.get("TZ") or "UTC")  # set TZ=America/Sao_Paulo (etc.) for local times
except Exception:
    TZ = datetime.timezone.utc
DB = os.path.join(os.environ.get("HERMES_HOME", "/data/.hermes"), "state.db")


def main():
    argv = sys.argv[1:]
    out = None
    if "--out" in argv:
        i = argv.index("--out")
        out = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    hours = float(argv[0]) if argv else 26
    since = datetime.datetime.now(datetime.timezone.utc).timestamp() - hours * 3600
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        """select s.id, s.source, coalesce(s.title,''), m.role, m.content, m.timestamp
             from messages m join sessions s on s.id = m.session_id
            where m.timestamp >= ? and m.role in ('user','assistant')
              and coalesce(m._compressed_summary,0) = 0
              and m.content is not null and trim(m.content) != ''
            order by m.timestamp""", (since,)).fetchall()
    lines, last_sid = [], None
    for sid, source, title, role, content, ts in rows:
        text = content.strip()
        if role == "user" and text.startswith("[CONTEXT COMPACTION"):
            continue
        if sid != last_sid:
            lines.append(f"\n=== session {sid[:28]} · {source} · {title[:70]}")
            last_sid = sid
        when = datetime.datetime.fromtimestamp(ts, TZ).strftime("%d/%m %H:%M")
        who = "USER/PROMPT" if role == "user" else "AGENT"
        if len(text) > 2500:
            text = text[:2500] + " […]"
        lines.append(f"[{when}] {who}: {text}")
    body = "\n".join(lines) or "(no conversations in this period)"
    if out:
        with open(out, "w") as f:
            f.write(body)
        print(f"{len(rows)} messages -> {out}")
    else:
        print(body)


if __name__ == "__main__":
    main()
