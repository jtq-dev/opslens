import sqlite3
from typing import List, Dict, Any

def rolling_metric(conn: sqlite3.Connection, host: str, key: str, days: int = 30) -> List[Dict[str, Any]]:
    # Uses SQLite window function for 7-day rolling average
    cur = conn.cursor()
    cur.execute(
        """
        WITH daily AS (
          SELECT
            date(r.created_at) AS d,
            avg(m.value) AS v
          FROM runs r
          JOIN metrics m ON m.run_id = r.id
          WHERE r.host = ? AND m.key = ?
            AND r.created_at >= datetime('now', ?)
          GROUP BY date(r.created_at)
          ORDER BY date(r.created_at)
        )
        SELECT
          d,
          v,
          avg(v) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS rolling7
        FROM daily
        """,
        (host, key, f"-{days} days"),
    )
    return [dict(row) for row in cur.fetchall()]

def compare_runs(conn: sqlite3.Connection, run_a: str, run_b: str):
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM metrics WHERE run_id = ?", (run_a,))
    a = {r["key"]: r["value"] for r in cur.fetchall()}
    cur.execute("SELECT key, value FROM metrics WHERE run_id = ?", (run_b,))
    b = {r["key"]: r["value"] for r in cur.fetchall()}

    keys = sorted(set(a.keys()) | set(b.keys()))
    diff = []
    for k in keys:
        av = a.get(k)
        bv = b.get(k)
        if av is None or bv is None:
            diff.append({"key": k, "a": av, "b": bv, "delta": None})
        else:
            diff.append({"key": k, "a": av, "b": bv, "delta": round(bv - av, 3)})
    return diff
