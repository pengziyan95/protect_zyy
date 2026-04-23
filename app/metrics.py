from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text


@dataclass(frozen=True)
class DailyPoint:
    day: str
    comments: int
    actions: dict[str, int]
    severities: dict[str, int]
    llm_calls: int
    llm_ok: int


def _dashes(days: int) -> str:
    return ",".join(["?"] * days)


def daily_metrics(engine: Engine, days: int = 7) -> list[dict[str, Any]]:
    """
    Lightweight SQLite metrics for a demo (no complex retention modeling yet).
    """
    if days < 1 or days > 90:
        raise ValueError("days must be 1..90")

    today = dt.date.today()
    start = today - dt.timedelta(days=days - 1)
    day_list = [start + dt.timedelta(days=i) for i in range(days)]
    day_keys = [d.isoformat() for d in day_list]
    day_set = set(day_keys)

    with engine.connect() as conn:
        # comments per day
        comment_rows = conn.execute(
            text(
                f"""
                SELECT strftime('%Y-%m-%d', created_at) AS d, COUNT(*) AS c
                FROM comments
                WHERE date(created_at) >= date(:start)
                GROUP BY d
                """
            ),
            {"start": start.isoformat()},
        ).fetchall()

        # moderation actions/severities per day
        mod_rows = conn.execute(
            text(
                f"""
                SELECT
                  strftime('%Y-%m-%d', mr.created_at) AS d,
                  mr.action,
                  IFNULL(mr.severity, 'MED') AS sev,
                  COUNT(*) AS c
                FROM moderation_results mr
                WHERE date(mr.created_at) >= date(:start)
                GROUP BY d, mr.action, sev
                """
            ),
            {"start": start.isoformat()},
        ).fetchall()

        llm_rows = conn.execute(
            text(
                f"""
                SELECT strftime('%Y-%m-%d', created_at) AS d, COUNT(*) AS c, SUM(CASE WHEN ok = 1 THEN 1 ELSE 0 END) AS okc
                FROM llm_call_logs
                WHERE date(created_at) >= date(:start)
                GROUP BY d
                """
            ),
            {"start": start.isoformat()},
        ).fetchall()

    comment_map = {r[0]: int(r[1]) for r in comment_rows if r[0]}

    mod_action: dict[str, dict[str, int]] = {k: {} for k in day_keys}
    mod_sev: dict[str, dict[str, int]] = {k: {} for k in day_keys}
    for d, action, sev, c in mod_rows:
        if d not in day_set:
            continue
        mod_action[d][str(action)] = mod_action[d].get(str(action), 0) + int(c)
        mod_sev[d][str(sev)] = mod_sev[d].get(str(sev), 0) + int(c)

    llm_map = {r[0]: (int(r[1]), int(r[2] or 0)) for r in llm_rows if r[0]}

    out: list[dict[str, Any]] = []
    for k in day_keys:
        total, ok = llm_map.get(k, (0, 0))
        out.append(
            {
                "day": k,
                "comments": int(comment_map.get(k, 0)),
                "actions": mod_action.get(k, {}),
                "severities": mod_sev.get(k, {}),
                "llm_calls": total,
                "llm_ok": ok,
            }
        )

    return out
