#!/usr/bin/env python3
import argparse
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime


ANOMALY_PATTERNS = [
    r"\bERROR\b",
    r"\bWARNING\b",
    r"\bAPI_ERR\b",
    r"Traceback",
    r"Exception",
    r"timeout",
    r"failed",
    r"\b451\b",
]


def read_recent_lines(path: str, max_lines: int) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return lines[-max_lines:]


def extract_anomalies(lines: list[str]) -> tuple[list[str], Counter]:
    compiled = [re.compile(pat, re.IGNORECASE) for pat in ANOMALY_PATTERNS]
    anomalies = []
    buckets: Counter = Counter()
    for line in lines:
        for pat in compiled:
            if pat.search(line):
                anomalies.append(line.rstrip("\n"))
                buckets[pat.pattern] += 1
                break
    return anomalies, buckets


def db_scalar(cur: sqlite3.Cursor, sql: str) -> int | float:
    cur.execute(sql)
    row = cur.fetchone()
    if not row:
        return 0
    return row[0] if row[0] is not None else 0


def db_query_rows(cur: sqlite3.Cursor, sql: str, params: tuple = ()) -> list[tuple]:
    cur.execute(sql, params)
    return cur.fetchall()


def table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def summarize_db(db_path: str) -> str:
    if not os.path.exists(db_path):
        return f"- DB file missing: `{db_path}`\n"

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    out: list[str] = []

    tables = ["prices", "trades", "signal_events", "rl_events", "llm_usage"]
    out.append("### DB Snapshot")
    for table in tables:
        if table_exists(cur, table):
            count = db_scalar(cur, f"SELECT COUNT(*) FROM {table}")
            out.append(f"- `{table}` rows: {count}")
        else:
            out.append(f"- `{table}` missing")

    if table_exists(cur, "trades"):
        closed = db_scalar(cur, "SELECT COUNT(*) FROM trades WHERE status='CLOSED'")
        open_n = db_scalar(cur, "SELECT COUNT(*) FROM trades WHERE status='OPEN'")
        pnl_sum = db_scalar(cur, "SELECT COALESCE(SUM(pnl),0) FROM trades WHERE status='CLOSED'")
        out.append(f"- closed trades: {closed}, open trades: {open_n}, closed pnl sum: {pnl_sum:.4f}")

    if table_exists(cur, "rl_events"):
        mode_rows = db_query_rows(
            cur,
            "SELECT mode, COUNT(*) FROM rl_events GROUP BY mode ORDER BY mode",
        )
        out.append("- rl events by mode:")
        if mode_rows:
            for mode, n in mode_rows:
                out.append(f"  - {mode}: {n}")
        else:
            out.append("  - none")

        type_rows = db_query_rows(
            cur,
            "SELECT event_type, COUNT(*) FROM rl_events GROUP BY event_type ORDER BY event_type",
        )
        out.append("- rl events by type:")
        if type_rows:
            for event_type, n in type_rows:
                out.append(f"  - {event_type}: {n}")
        else:
            out.append("  - none")

    conn.close()
    return "\n".join(out) + "\n"


def _safe_json_load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def summarize_rl_training(db_path: str, rl_weights_path: str) -> str:
    out: list[str] = []
    out.append("### RL Training Snapshot")
    out.append(f"- weights source: `{rl_weights_path}`")

    payload = _safe_json_load(rl_weights_path)
    if not payload:
        out.append("- rl weights file missing or unreadable")
        return "\n".join(out) + "\n"

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    epsilon = meta.get("epsilon", "n/a")
    updated_at = meta.get("updated_at", "n/a")
    out.append(f"- epsilon: {epsilon}")
    out.append(f"- updated_at: {updated_at}")

    q_root = payload.get("q") if isinstance(payload.get("q"), dict) else {}
    n_root = payload.get("n") if isinstance(payload.get("n"), dict) else {}
    modes = sorted(set(q_root.keys()) | set(n_root.keys()))

    if not modes:
        out.append("- no RL mode data found in weights payload")
        return "\n".join(out) + "\n"

    for mode in modes:
        q_mode = q_root.get(mode) if isinstance(q_root.get(mode), dict) else {}
        n_mode = n_root.get(mode) if isinstance(n_root.get(mode), dict) else {}

        states = sorted(set(q_mode.keys()) | set(n_mode.keys()))
        visited_states = 0
        total_updates = 0
        profile_updates: dict[str, int] = {}
        profile_q_values: dict[str, list[float]] = {}

        for state_key in states:
            q_state = q_mode.get(state_key) if isinstance(q_mode.get(state_key), dict) else {}
            n_state = n_mode.get(state_key) if isinstance(n_mode.get(state_key), dict) else {}
            state_visits = 0
            for pid, visits in n_state.items():
                v = int(visits or 0)
                state_visits += v
                total_updates += v
                profile_updates[pid] = profile_updates.get(pid, 0) + v
            if state_visits > 0:
                visited_states += 1
            for pid, qv in q_state.items():
                try:
                    profile_q_values.setdefault(pid, []).append(float(qv or 0.0))
                except Exception:
                    continue

        out.append(f"- mode `{mode}`: states={len(states)} visited_states={visited_states} total_updates={total_updates}")

        if profile_updates:
            top_profiles = sorted(profile_updates.items(), key=lambda x: x[1], reverse=True)[:3]
            out.append("  - top profiles by updates:")
            for pid, n in top_profiles:
                out.append(f"    - {pid}: {n}")
        else:
            out.append("  - top profiles by updates: none")

        profile_avg_q: list[tuple[str, float]] = []
        for pid, values in profile_q_values.items():
            if values:
                profile_avg_q.append((pid, sum(values) / len(values)))

        if profile_avg_q:
            profile_avg_q.sort(key=lambda x: x[1], reverse=True)
            best_pid, best_q = profile_avg_q[0]
            worst_pid, worst_q = profile_avg_q[-1]
            out.append(f"  - avg Q best={best_pid}:{best_q:+.6f} worst={worst_pid}:{worst_q:+.6f}")
        else:
            out.append("  - avg Q: no values")

    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        if table_exists(cur, "rl_events"):
            rows = db_query_rows(
                cur,
                """
                SELECT mode, COUNT(*), ROUND(AVG(reward), 6), ROUND(SUM(reward), 6), MAX(timestamp)
                FROM rl_events
                GROUP BY mode
                ORDER BY mode
                """,
            )
            out.append("- rl_events reward summary:")
            if rows:
                for mode, n, avg_reward, sum_reward, max_ts in rows:
                    out.append(
                        f"  - {mode}: n={n}, avg_reward={avg_reward}, total_reward={sum_reward}, last_ts={max_ts}"
                    )
            else:
                out.append("  - none")
        conn.close()

    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build anomaly context from trading.log and sqlite DB.")
    parser.add_argument("--log", default="trading.log")
    parser.add_argument("--db", default="trading_data.db")
    parser.add_argument("--rl-weights", default="data/rl_weights.json")
    parser.add_argument("--max-lines", type=int, default=2000)
    parser.add_argument("--max-anomalies", type=int, default=160)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    lines = read_recent_lines(args.log, args.max_lines)
    anomalies, buckets = extract_anomalies(lines)
    anomalies = anomalies[-args.max_anomalies :]

    report: list[str] = []
    report.append(f"# Anomaly Context ({datetime.now().isoformat(timespec='seconds')})")
    report.append("")
    report.append("## Log Snapshot")
    report.append(f"- source: `{args.log}`")
    report.append(f"- scanned lines: {len(lines)}")
    report.append(f"- matched anomalies: {len(anomalies)}")
    report.append("")
    report.append("### Pattern Counts")
    if buckets:
        for pat, count in buckets.most_common():
            report.append(f"- `{pat}`: {count}")
    else:
        report.append("- none")
    report.append("")
    report.append("### Recent Anomaly Lines")
    if anomalies:
        report.append("```text")
        report.extend(anomalies)
        report.append("```")
    else:
        report.append("_No anomaly lines matched configured patterns._")
    report.append("")
    report.append(summarize_db(args.db))
    report.append(summarize_rl_training(args.db, args.rl_weights))

    payload = "\n".join(report).strip() + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(payload)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
