"""
signal_engine/utils/alerts.py
──────────────────────────────────────────────────────────────────────────────
Discord-only alert sender for the Signal Engine.

Supports 5 alert types with distinct embed colours:
  SIGNAL        → Green   (0x2ECC71)  — trade signals
  WARNING       → Orange  (0xF39C12)  — geo-block, squeeze watch
  CRITICAL      → Red     (0xE74C3C)  — loss limits, engine errors
  DAILY_SUMMARY → Blue    (0x3498DB)  — paper trading daily report
  PAPER_FILL    → Grey    (0x95A5A6)  — simulated paper trade fills

Rules:
  • Every alert includes UTC timestamp and symbol (if applicable)
  • Webhook failures are logged locally — engine NEVER crashes
  • All convenience functions return True on success, False on failure

Usage:
  from signal_engine.utils.alerts import alert_signal, alert_futures_blocked
  alert_futures_blocked()
  alert_signal(symbol="SOLUSDT", direction="LONG", ...)
──────────────────────────────────────────────────────────────────────────────
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from signal_engine.utils.logger import get_logger

_log = get_logger("ALERTS", "DISCORD")

# ── Embed colour palette ───────────────────────────────────────────────────

EMBED_COLORS: Dict[str, int] = {
    "SIGNAL":        0x2ECC71,   # Green
    "WARNING":       0xF39C12,   # Orange/Yellow
    "CRITICAL":      0xE74C3C,   # Red
    "DAILY_SUMMARY": 0x3498DB,   # Blue
    "PAPER_FILL":    0x95A5A6,   # Grey
}


# ── Internal helpers ───────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def get_webhook_for_grade(grade):
    from signal_engine.config import cfg
    if grade == 'A+':
        return cfg.discord_webhook_a_plus
    elif grade == 'A':
        return cfg.discord_webhook_a
    elif grade == 'B':
        return cfg.discord_webhook_b
    else:
        return None

def _get_webhook() -> Optional[str]:
    from signal_engine.config import cfg
    url = cfg.discord_webhook_system
    if not url:
        _log.error("SYSTEM webhook is not set in .env — alert skipped")
        return None
    return url


def _build_embed(
    alert_type: str,
    title: str,
    description: str,
    fields: Optional[List[Dict[str, Any]]] = None,
    symbol: Optional[str] = None,
    footer_text: Optional[str] = None,
) -> Dict[str, Any]:
    color = EMBED_COLORS.get(alert_type, 0x7F8C8D)
    ts    = _utc_now()

    embed: Dict[str, Any] = {
        "title":       title,
        "description": description,
        "color":       color,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "footer":      {"text": footer_text or f"Signal Engine • {ts}"},
    }

    if symbol:
        embed["author"] = {"name": f"⬡ {symbol}"}

    if fields:
        embed["fields"] = fields

    return embed


def _post_embed(
    alert_type: str,
    title: str,
    description: str,
    fields: Optional[List[Dict[str, Any]]] = None,
    symbol: Optional[str] = None,
    footer_text: Optional[str] = None,
    webhook_url: Optional[str] = None,
    content: Optional[str] = None,
) -> bool:
    """
    Core sender. Returns True on success, False on any failure.
    NEVER raises — all exceptions are caught and logged.
    """
    from signal_engine.config import cfg
    if getattr(cfg, 'mode', None) == 'backtest':
        return False
    url = webhook_url or _get_webhook()
    if not url:
        return False

    embed   = _build_embed(alert_type, title, description, fields, symbol, footer_text)
    payload_dict = {"embeds": [embed]}
    if content:
        payload_dict["content"] = content
    payload = json.dumps(payload_dict)

    try:
        _log.info(f"[DEBUG] About to call requests.post to Discord webhook {url[:40]}... for [{alert_type}]")
        resp = requests.post(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        _log.info(f"[DEBUG] Discord response status: {resp.status_code}, body: {resp.text}")
        if resp.status_code in (200, 204):
            _log.info(f"Sent [{alert_type}] '{title}'")
            return True

        _log.error(
            f"Discord returned HTTP {resp.status_code} for [{alert_type}] '{title}' "
            f"— body: {resp.text[:300]}"
        )
        return False

    except requests.exceptions.Timeout:
        _log.error(f"Discord webhook timed out (10 s) for [{alert_type}] '{title}' to {url[:40]}... — continuing")
        return False
    except requests.exceptions.ConnectionError as exc:
        _log.error(f"Discord connection error for [{alert_type}] '{title}' to {url[:40]}...: {exc} — continuing")
        return False
    except Exception as exc:  # pylint: disable=broad-except
        import traceback
        _log.error(f"Unexpected error sending Discord alert [{alert_type}] '{title}' to {url[:40]}...: {exc} — continuing")
        _log.error(traceback.format_exc())
        return False


# ── Public convenience functions ───────────────────────────────────────────

def alert_signal(
    symbol: str,
    direction: str,         # "LONG" or "SHORT"
    grade: str,             # "A+", "A", "B", "C"
    confidence: float,
    entry: float,
    stop: float,
    target1: float,
    target2: float,
    rr: float,
    position_size_pct: float,
    narrative: str,
    risks: str,
    regime: str = "",
    btc_trend: str = "",
    rs_label: str = "",
) -> bool:
    """Green embed — fired trade signal."""
    emoji = "🟢" if direction == "LONG" else "🔴"
    fields = [
        {"name": "Direction",        "value": f"{emoji} {direction}",               "inline": True},
        {"name": "Grade",            "value": grade,                                 "inline": True},
        {"name": "Confidence",       "value": f"{confidence:.1f} / 100",            "inline": True},
        {"name": "Entry",            "value": f"`${entry:,.4f}`",                   "inline": True},
        {"name": "Stop Loss",        "value": f"`${stop:,.4f}`",                    "inline": True},
        {"name": "R:R",              "value": f"{rr:.1f} : 1",                      "inline": True},
        {"name": "Target 1 (1R)",    "value": f"`${target1:,.4f}`",                 "inline": True},
        {"name": "Target 2 (2R)",    "value": f"`${target2:,.4f}`",                 "inline": True},
        {"name": "Position Size",    "value": f"{position_size_pct:.2f}% of acct", "inline": True},
        {"name": "Market Regime",    "value": regime   or "—",                      "inline": True},
        {"name": "BTC Trend",        "value": btc_trend or "—",                     "inline": True},
        {"name": "Relative Strength","value": rs_label  or "—",                     "inline": True},
        {"name": "💡 Why This Trade", "value": narrative,                            "inline": False},
        {"name": "⚠️ Risks",          "value": risks,                                "inline": False},
    ]
    return _post_embed(
        "SIGNAL",
        f"{emoji} {symbol}  ·  {direction}  ·  Grade {grade}",
        f"Signal fired at `{_utc_now()}`",
        fields=fields,
        symbol=symbol,
    )


def alert_futures_blocked(symbol: Optional[str] = None) -> bool:
    """Orange embed — 451 geo-block detected."""
    return _post_embed(
        "WARNING",
        "⚠️ Futures API Blocked — Running Spot-Only Mode",
        (
            "Binance Futures (`fapi.binance.com`) returned a **451** geo-block error.\n\n"
            "The engine is now running in **Spot-only mode**.\n"
            "• Open Interest, Funding Rate, L/S Ratio → **UNAVAILABLE**\n"
            "• Confidence scores **capped at 75**\n\n"
            f"Detected at `{_utc_now()}`"
        ),
        symbol=symbol,
    )


def alert_squeeze_watch(symbol: str, timeframe: str, bbwidth_pct: float) -> bool:
    """Orange embed — low-vol squeeze detected, no trade."""
    return _post_embed(
        "WARNING",
        f"🔔 Squeeze Watch — {symbol}",
        (
            f"**{symbol}** on `{timeframe}` has entered a **LOW_VOL_SQUEEZE**.\n"
            f"BBWidth is at the **{bbwidth_pct:.0f}th percentile** of the last 30 days.\n\n"
            "No trade. Monitoring for breakout."
        ),
        symbol=symbol,
    )


def alert_daily_loss_limit(current_loss_pct: float, account_usd: float) -> bool:
    """Red embed — daily loss limit breached, signals halted."""
    return _post_embed(
        "CRITICAL",
        "🛑 Daily Loss Limit Hit — Signals Halted",
        (
            f"Portfolio drawdown today: **−{abs(current_loss_pct):.2f}%**\n"
            f"Daily limit: **−3.00%**\n"
            f"Virtual account: **${account_usd:,.2f}**\n\n"
            "All signals halted for the rest of this UTC day.\n"
            "Signals resume automatically at **00:00 UTC**."
        ),
        content="@here"
    )


def alert_weekly_loss_limit(current_loss_pct: float, account_usd: float) -> bool:
    """Red embed — weekly loss limit breached, manual reset required."""
    return _post_embed(
        "CRITICAL",
        "🚨 Weekly Loss Limit Hit — Manual Reset Required",
        (
            f"Portfolio drawdown this week: **−{abs(current_loss_pct):.2f}%**\n"
            f"Weekly limit: **−8.00%**\n"
            f"Virtual account: **${account_usd:,.2f}**\n\n"
            "All signals **permanently halted** until manual reset.\n"
            "To resume: delete or reset the `weekly_halted` flag in `engine_state.json`."
        ),
        content="@here"
    )


def alert_paper_fill(
    symbol: str,
    direction: str,
    fill_price: float,
    stop: float,
    target1: float,
    target2: float,
    position_size_pct: float,
    slippage_pct: float = 0.05,
) -> bool:
    """Grey embed — paper trade simulated fill."""
    emoji = "🟢" if direction == "LONG" else "🔴"
    fields = [
        {"name": "Direction",   "value": f"{emoji} {direction}",                      "inline": True},
        {"name": "Fill Price",  "value": f"`${fill_price:,.4f}` (+{slippage_pct:.2f}% slip)", "inline": True},
        {"name": "Stop Loss",   "value": f"`${stop:,.4f}`",                            "inline": True},
        {"name": "Target 1",    "value": f"`${target1:,.4f}`",                         "inline": True},
        {"name": "Target 2",    "value": f"`${target2:,.4f}`",                         "inline": True},
        {"name": "Size",        "value": f"{position_size_pct:.2f}% of account",       "inline": True},
    ]
    return _post_embed(
        "PAPER_FILL",
        f"📝 Paper Fill — {symbol}",
        f"Simulated {direction} fill at `{_utc_now()}`",
        fields=fields,
        symbol=symbol,
    )


def alert_paper_exit(
    symbol: str,
    direction: str,
    exit_price: float,
    exit_reason: str,       # STOP_LOSS | TARGET_1 | TARGET_2
    pnl_usd: float,
    pnl_r: float,
    new_balance: float,
) -> bool:
    """Coloured embed — paper trade closed (WIN green / LOSS red)."""
    is_win = pnl_usd >= 0
    color = EMBED_COLORS["SIGNAL"] if is_win else EMBED_COLORS["CRITICAL"]
    result_label = "WIN ✅" if is_win else "LOSS ❌"
    emoji = "🟢" if direction == "LONG" else "🔴"
    reason_emoji = {
        "STOP_LOSS":  "🛑 Stop Loss",
        "TARGET_1":   "🎯 Target 1 (partial)",
        "TARGET_2":   "🏆 Target 2 (full close)",
    }.get(exit_reason, exit_reason)

    fields = [
        {"name": "Direction",    "value": f"{emoji} {direction}",          "inline": True},
        {"name": "Result",       "value": result_label,                     "inline": True},
        {"name": "Exit Reason",  "value": reason_emoji,                     "inline": True},
        {"name": "Exit Price",   "value": f"`${exit_price:,.4f}`",          "inline": True},
        {"name": "PnL",          "value": f"`${pnl_usd:+,.2f}` ({pnl_r:+.2f}R)", "inline": True},
        {"name": "New Balance",  "value": f"`${new_balance:,.2f}`",         "inline": True},
    ]
    return _post_embed(
        "SIGNAL" if is_win else "CRITICAL",
        f"📤 Paper Exit — {symbol}",
        f"{result_label} · {direction} closed at `{_utc_now()}`",
        fields=fields,
        symbol=symbol,
    )


def alert_daily_paper_summary(
    date_str: str,
    signals_fired: int,
    wins: int,
    losses: int,
    open_positions: int,
    net_r: float,
    virtual_balance: float,
    start_balance: float,
    paper_start_date: str,
) -> bool:
    """Blue embed — end-of-day paper trading performance summary."""
    day_pct   = ((virtual_balance - start_balance) / start_balance) * 100
    total_pct = ((virtual_balance - 1000.0) / 1000.0) * 100
    r_emoji   = "📈" if net_r >= 0 else "📉"

    fields = [
        {"name": "Signals Fired",    "value": str(signals_fired),                              "inline": True},
        {"name": "✅ Winners",        "value": str(wins),                                        "inline": True},
        {"name": "❌ Losers",         "value": str(losses),                                      "inline": True},
        {"name": "🔄 Open",           "value": str(open_positions),                              "inline": True},
        {"name": f"{r_emoji} Net R",  "value": f"{net_r:+.2f}R",                                "inline": True},
        {"name": "Balance",           "value": f"${virtual_balance:,.2f} ({day_pct:+.1f}% today)", "inline": True},
        {"name": "Total Since Start", "value": f"{total_pct:+.1f}% from {paper_start_date}",    "inline": False},
    ]
    return _post_embed(
        "DAILY_SUMMARY",
        f"📊 Paper Trading Daily Summary — {date_str}",
        f"End-of-day report for **{date_str}**",
        fields=fields,
    )


def alert_matrix_stale(age_hours: float) -> bool:
    """Orange embed — correlation matrix is stale, conservative defaults applied."""
    return _post_embed(
        "WARNING",
        "⚠️ Correlation Matrix Stale",
        (
            f"The 7-day rolling correlation matrix has not been updated in "
            f"**{age_hours:.1f} hours** (limit: 24 h).\n\n"
            "Portfolio risk (cluster limits) is now using **conservative defaults** "
            "— all altcoins treated as correlated.\n"
            "The matrix will be recalculated on the next scheduled cycle."
        ),
    )


# ── Standalone test block ──────────────────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()   # loads DISCORD_WEBHOOK_URL from .env

    print("=" * 70)
    print("alerts.py — Standalone Test")
    print("Sending 6 test embeds to Discord. Check your channel.")
    print("=" * 70)
    print()

    # 1. Futures blocked warning
    print("[1/6] Sending FUTURES_BLOCKED warning...")
    ok = alert_futures_blocked(symbol="BTCUSDT")
    print(f"      Result: {'✅ Sent' if ok else '❌ Failed (check DISCORD_WEBHOOK_URL in .env)'}")
    print()

    # 2. Squeeze watch
    print("[2/6] Sending SQUEEZE_WATCH warning...")
    ok = alert_squeeze_watch("SOLUSDT", "4h", bbwidth_pct=8.3)
    print(f"      Result: {'✅ Sent' if ok else '❌ Failed'}")
    print()

    # 3. Simulated signal
    print("[3/6] Sending SIGNAL embed (LONG SOLUSDT)...")
    ok = alert_signal(
        symbol="SOLUSDT",
        direction="LONG",
        grade="A",
        confidence=83.5,
        entry=145.20,
        stop=141.80,
        target1=148.60,
        target2=152.00,
        rr=2.2,
        position_size_pct=1.0,
        narrative=(
            "SOL reclaimed the 1h EMA50 after a clean pullback, with volume spiking to 2.1× average "
            "confirming real buyer interest. BTC's BULLISH backdrop provides a tailwind. "
            "Clear room to Target 1 at $148.60 before the next resistance cluster."
        ),
        risks="BTC breakdown below $60K invalidates macro thesis. Funding rate elevated at +0.08%.",
        regime="TRENDING (1h)",
        btc_trend="BULLISH",
        rs_label="LEADER (+3.2%)",
    )
    print(f"      Result: {'✅ Sent' if ok else '❌ Failed'}")
    print()

    # 4. Daily loss limit
    print("[4/6] Sending DAILY_LOSS_LIMIT critical alert...")
    ok = alert_daily_loss_limit(current_loss_pct=3.21, account_usd=968.00)
    print(f"      Result: {'✅ Sent' if ok else '❌ Failed'}")
    print()

    # 5. Paper fill
    print("[5/6] Sending PAPER_FILL grey embed...")
    ok = alert_paper_fill(
        symbol="ETHUSDT",
        direction="SHORT",
        fill_price=3489.75,
        stop=3532.00,
        target1=3447.50,
        target2=3405.25,
        position_size_pct=0.5,
    )
    print(f"      Result: {'✅ Sent' if ok else '❌ Failed'}")
    print()

    # 6. Daily paper summary
    print("[6/6] Sending DAILY_PAPER_SUMMARY blue embed...")
    ok = alert_daily_paper_summary(
        date_str="2026-07-04",
        signals_fired=3,
        wins=2,
        losses=1,
        open_positions=1,
        net_r=1.4,
        virtual_balance=1014.20,
        start_balance=1000.00,
        paper_start_date="2026-07-04",
    )
    print(f"      Result: {'✅ Sent' if ok else '❌ Failed'}")
    print()

    print("=" * 70)
    print("✅ All 6 embeds attempted. Verify in your Discord channel.")
    print("   Each type should have a distinct colour:")
    print("   GREEN=SIGNAL  ORANGE=WARNING  RED=CRITICAL  BLUE=SUMMARY  GREY=FILL")
    print("=" * 70)
