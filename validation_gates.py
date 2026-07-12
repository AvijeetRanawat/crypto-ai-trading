"""
Validation gate checker for rollout readiness.

Outputs a hard decision:
  GO     -> ready for next stage
  NO_GO  -> keep iterating / keep in simulation

Usage:
  python3 validation_gates.py
  python3 validation_gates.py --session 20260227T134331
  python3 validation_gates.py --json-out evaluation_report.json
"""
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from config import config
from database import DB_PATH


def _gate(label: str, ok: bool, detail: str):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}: {detail}")


def _parse_args():
    parser = argparse.ArgumentParser(description="Run project evaluation gates (GO/NO_GO).")
    parser.add_argument(
        "--session",
        default="latest",
        help="Session id to evaluate (default: latest). Use 'all' for all rows.",
    )
    parser.add_argument(
        "--json-out",
        default="evaluation_report.json",
        help="Path to write JSON report (set empty string to disable).",
    )
    return parser.parse_args()


def _latest_session_id(cur) -> str:
    cur.execute(
        """
        SELECT session_id
        FROM (
            SELECT session_id FROM trades WHERE session_id IS NOT NULL AND session_id != ''
            UNION ALL
            SELECT session_id FROM signal_events WHERE session_id IS NOT NULL AND session_id != ''
            UNION ALL
            SELECT session_id FROM llm_usage WHERE session_id IS NOT NULL AND session_id != ''
        )
        GROUP BY session_id
        ORDER BY session_id DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    return row[0] if row else None


def _session_clause(session_id: str):
    if not session_id:
        return "", ()
    return " AND session_id = ?", (session_id,)


def _parse_iso(ts: str):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _parse_session_start(session_id: str):
    if not session_id:
        return None
    try:
        return datetime.strptime(session_id, "%Y%m%dT%H%M%S")
    except Exception:
        return None


def _runtime_hours(cur, session_id: str):
    times = []
    where, args = _session_clause(session_id)

    # trades uses entry/exit timestamps, other tables use `timestamp`.
    cur.execute(
        f"SELECT MIN(entry_time), MAX(entry_time), MAX(exit_time) FROM trades WHERE 1=1 {where}",
        args,
    )
    mn_entry, mx_entry, mx_exit = cur.fetchone()
    if mn_entry:
        times.append(_parse_iso(mn_entry))
    if mx_entry:
        times.append(_parse_iso(mx_entry))
    if mx_exit:
        times.append(_parse_iso(mx_exit))

    for table in ("signal_events", "llm_usage"):
        cur.execute(f"SELECT MIN(timestamp), MAX(timestamp) FROM {table} WHERE 1=1 {where}", args)
        mn, mx = cur.fetchone()
        if mn:
            times.append(_parse_iso(mn))
        if mx:
            times.append(_parse_iso(mx))

    # Fallback for fresh sessions with sparse rows.
    log_path = Path("trading.log")
    if log_path.exists():
        try:
            first = log_path.read_text().splitlines()[0].strip()
            marker = "=== Session started "
            if first.startswith(marker) and first.endswith(" ==="):
                dt = datetime.strptime(first[len(marker):-4], "%Y-%m-%d %H:%M:%S")
                times.append(dt)
                times.append(datetime.now())
        except Exception:
            pass

    clean = [t for t in times if t is not None]
    if len(clean) < 2:
        return 0.0
    return max(0.0, (max(clean) - min(clean)).total_seconds() / 3600.0)


def _engine_errors():
    log_path = Path("trading.log")
    if not log_path.exists():
        return 0
    log_text = log_path.read_text()
    return (
        log_text.count("Engine error:")
        + log_text.count("Unexpected error in main loop:")
    )


def _maybe_write_json(path: str, payload: dict):
    if not path:
        return
    Path(path).write_text(json.dumps(payload, indent=2))


def main():
    args = _parse_args()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    chosen_session = None
    if args.session == "latest":
        chosen_session = _latest_session_id(cur)
    elif args.session == "all":
        chosen_session = None
    else:
        chosen_session = args.session

    where, where_args = _session_clause(chosen_session)
    runtime_hours = _runtime_hours(cur, chosen_session)

    print(f"Evaluation scope: session={chosen_session or 'ALL'}")
    print(
        f"Thresholds: runtime>={config.EVAL_MIN_RUNTIME_HOURS:.1f}h | "
        f"errors<={config.EVAL_MAX_ENGINE_ERRORS} | "
        f"llm/gross+<={config.EVAL_MAX_LLM_TO_GROSS_POS_PNL_PCT:.2f}% | "
        f"closed_trades>={config.EVAL_MIN_CLOSED_TRADES} | "
        f"avg_pnl>{config.EVAL_MIN_AVG_PNL_PER_TRADE:.6f} | "
        f"drawdown<={config.MAX_DAILY_DRAWDOWN_USD:.2f}"
    )

    # Gate 1: stability over runtime window
    err_count = _engine_errors()
    stability_ok = runtime_hours >= config.EVAL_MIN_RUNTIME_HOURS and err_count <= config.EVAL_MAX_ENGINE_ERRORS
    _gate(
        "Stability",
        stability_ok,
        (
            f"runtime={runtime_hours:.2f}h, errors={err_count} "
            f"(need runtime>={config.EVAL_MIN_RUNTIME_HOURS:.1f}h and errors<={config.EVAL_MAX_ENGINE_ERRORS})"
        ),
    )

    # Gate 2: cost discipline (LLM spend as % of gross positive PnL)
    cur.execute(
        f"""
        SELECT COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0)
        FROM trades
        WHERE status='CLOSED' {where}
        """,
        where_args,
    )
    gross_positive_pnl = float(cur.fetchone()[0] or 0.0)

    cur.execute(
        f"SELECT COALESCE(SUM(estimated_cost_usd),0) FROM llm_usage WHERE 1=1 {where}",
        where_args,
    )
    llm_cost = float(cur.fetchone()[0] or 0.0)
    ratio = (llm_cost / gross_positive_pnl * 100.0) if gross_positive_pnl > 0 else None
    cost_ok = ratio is not None and ratio <= config.EVAL_MAX_LLM_TO_GROSS_POS_PNL_PCT
    ratio_label = f"{ratio:.2f}%" if ratio is not None else "N/A (gross+PnL=0)"
    _gate(
        "Cost discipline",
        cost_ok,
        (
            f"LLM/Gross+PnL={ratio_label} (llm=${llm_cost:.4f}, gross+=${gross_positive_pnl:.2f}, "
            f"limit<={config.EVAL_MAX_LLM_TO_GROSS_POS_PNL_PCT:.2f}%)"
        ),
    )

    # Gate 3: quality sample size + expectancy
    cur.execute(
        f"""
        SELECT COUNT(*), COALESCE(AVG(pnl),0), COALESCE(SUM(pnl),0)
        FROM trades
        WHERE status='CLOSED' {where}
        """,
        where_args,
    )
    closed_n, avg_pnl, net_pnl = cur.fetchone()
    sample_ok = int(closed_n) >= config.EVAL_MIN_CLOSED_TRADES
    expectancy_ok = float(avg_pnl) > config.EVAL_MIN_AVG_PNL_PER_TRADE
    _gate("Quality sample size", sample_ok, f"closed trades={closed_n} (need>={config.EVAL_MIN_CLOSED_TRADES})")
    _gate(
        "Net expectancy",
        expectancy_ok,
        f"avg pnl/trade={float(avg_pnl):.6f}, net pnl=${float(net_pnl):.2f}",
    )

    # Gate 4: drawdown cap
    # portfolio has no session_id; derive session window from session id when available.
    session_start = _parse_session_start(chosen_session)
    if session_start:
        cur.execute(
            "SELECT COALESCE(MAX(balance_usdt),0), COALESCE(MIN(balance_usdt),0) FROM portfolio WHERE timestamp >= ?",
            (session_start.isoformat(),),
        )
    else:
        cur.execute("SELECT COALESCE(MAX(balance_usdt),0), COALESCE(MIN(balance_usdt),0) FROM portfolio")
    max_bal, min_bal = cur.fetchone()
    drawdown = max(0.0, float(max_bal or 0.0) - float(min_bal or 0.0))
    drawdown_ok = drawdown <= config.MAX_DAILY_DRAWDOWN_USD
    _gate(
        "Drawdown cap",
        drawdown_ok,
        f"observed drawdown=${drawdown:.2f}, cap=${config.MAX_DAILY_DRAWDOWN_USD:.2f}",
    )

    all_ok = all([stability_ok, cost_ok, sample_ok, expectancy_ok, drawdown_ok])
    final = "GO" if all_ok else "NO_GO"
    print()
    print("=" * 72)
    print(f"FINAL DECISION: {final}")
    if final == "GO":
        print("Ready for next stage (micro-live rollout gate passed).")
    else:
        print("Keep in simulation and continue data collection / tuning.")
    print("=" * 72)

    report = {
        "generated_at": datetime.now().isoformat(),
        "session_id": chosen_session,
        "decision": final,
        "metrics": {
            "runtime_hours": runtime_hours,
            "engine_errors": err_count,
            "llm_cost_usd": llm_cost,
            "gross_positive_pnl_usd": gross_positive_pnl,
            "llm_to_gross_positive_pnl_pct": ratio,
            "closed_trades": int(closed_n),
            "avg_pnl_per_trade": float(avg_pnl),
            "net_pnl_usd": float(net_pnl),
            "drawdown_usd": drawdown,
        },
        "thresholds": {
            "min_runtime_hours": config.EVAL_MIN_RUNTIME_HOURS,
            "max_engine_errors": config.EVAL_MAX_ENGINE_ERRORS,
            "max_llm_to_gross_positive_pnl_pct": config.EVAL_MAX_LLM_TO_GROSS_POS_PNL_PCT,
            "min_closed_trades": config.EVAL_MIN_CLOSED_TRADES,
            "min_avg_pnl_per_trade": config.EVAL_MIN_AVG_PNL_PER_TRADE,
            "max_daily_drawdown_usd": config.MAX_DAILY_DRAWDOWN_USD,
        },
        "gates": {
            "stability": stability_ok,
            "cost_discipline": cost_ok,
            "quality_sample_size": sample_ok,
            "net_expectancy": expectancy_ok,
            "drawdown_cap": drawdown_ok,
        },
    }
    _maybe_write_json(args.json_out, report)

    conn.close()
    raise SystemExit(0 if final == "GO" else 1)


if __name__ == "__main__":
    main()
