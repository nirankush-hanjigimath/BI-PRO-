"""
signal_engine/utils/narrative.py
8 trader-grade narrative templates + automatic template selector.
Output: 2-3 sentence plain-English explanation. No indicator names visible.
"""

from typing import Any, Dict


# ── Internal helpers ───────────────────────────────────────────────────────

def _vol_text(z: float) -> str:
    """Convert volume Z-score to natural-language description."""
    if z >= 2.5:
        return "volume surging over 3× the recent baseline"
    elif z >= 2.0:
        return "volume running well over double its recent average"
    elif z >= 1.5:
        return f"volume running roughly {1.0 + z * 0.45:.1f}× the recent average"
    elif z >= 1.0:
        return "volume notably above recent norms"
    elif z >= 0.0:
        return "volume near its recent baseline"
    else:
        return "volume below recent averages — watch for follow-through"


def _btc_context(btc_trend: str) -> str:
    """Convert BTC state to a short contextual phrase."""
    mapping = {
        "STRONGLY_BULLISH": "BTC's strongly bullish backdrop provides a clear macro tailwind",
        "BULLISH":          "BTC's constructive posture supports the long-side bias",
        "NEUTRAL":          "BTC is treading water, so this is a coin-specific setup",
        "BEARISH":          "BTC remains under pressure, so risk management is critical here",
        "STRONGLY_BEARISH": "BTC is in a firm downtrend — size accordingly and stay disciplined",
    }
    return mapping.get(btc_trend, "the macro backdrop is mixed")


def _fmt(price: float) -> str:
    """Smart price formatter: 2dp >= $1, 4dp $0.01-$1, 6dp below $0.01."""
    if price >= 1.0:
        return f"${price:,.2f}"
    elif price >= 0.01:
        return f"${price:.4f}"
    else:
        return f"${price:.6f}"


# ── Template 1: Momentum Continuation ─────────────────────────────────────

def momentum_continuation(
    symbol: str,
    timeframe: str,
    ema: float,
    volume_z: float,
    btc_trend: str,
    target1: float,
    direction: str = "LONG",
) -> str:
    btc = _btc_context(btc_trend)
    vol = _vol_text(volume_z)
    trend = "clean uptrend" if direction == "LONG" else "clean downtrend"
    level = "dynamic floor" if direction == "LONG" else "dynamic ceiling"
    actor = "buyers" if direction == "LONG" else "sellers"
    action = "accumulation" if direction == "LONG" else "distribution"
    opp_action = "distribution" if direction == "LONG" else "accumulation"
    return (
        f"{symbol} is continuing a {trend} on the {timeframe}, "
        f"with the {_fmt(ema)} moving average acting as a {level} that has held "
        f"through multiple tests — a sign that {actor} are defending the level with conviction. "
        f"This session's candle resumed the trend with {vol}, "
        f"suggesting {action} rather than {opp_action}. "
        f"{btc}, and the first meaningful target sits at {_fmt(target1)}."
    )


# ── Template 2: Pullback to EMA ────────────────────────────────────────────

def pullback_to_ema(
    symbol: str,
    ema_period: int,
    ema_price: float,
    volume_z: float,
    btc_trend: str,
    target1: float,
    direction: str = "LONG",
) -> str:
    btc = _btc_context(btc_trend)
    vol = _vol_text(volume_z)
    move = "extended above" if direction == "LONG" else "extended below"
    action = "pulling back" if direction == "LONG" else "rallying"
    actor = "buyers" if direction == "LONG" else "sellers"
    trend = "healthy uptrend" if direction == "LONG" else "healthy downtrend"
    dip = "dip" if direction == "LONG" else "rally"
    dip_buyers = "dip buyers" if direction == "LONG" else "short sellers"
    return (
        f"{symbol} {move} its {ema_period}-period moving average before {action} "
        f"cleanly to {_fmt(ema_price)}, where {actor} stepped in exactly where they should "
        f"in a {trend}. "
        f"The confirmation candle absorbed the {dip} with {vol}, "
        f"a signal that {dip_buyers} are active rather than passive. "
        f"{btc}, and the structure points toward {_fmt(target1)} as the next target."
    )


# ── Template 3: Breakout With Volume ──────────────────────────────────────

def breakout_with_volume(
    symbol: str,
    broken_level: float,
    volume_z: float,
    oi_status: str,
    target1: float,
) -> str:
    vol = _vol_text(volume_z)
    oi_phrase = {
        "REAL_DEMAND":   "Open interest rose alongside price, confirming new money entered rather than shorts covering",
        "SHORT_COVER":   "Some of the move was fuelled by short covering, so expect a potential pause after the initial burst",
        "NEW_SHORTS":    "Aggressive new short positions are building, which adds squeeze potential if price holds above the level",
        "UNAVAILABLE":   "Futures positioning data is unavailable, so lean on the price and volume evidence alone",
    }.get(oi_status, "positioning data is neutral")
    return (
        f"{symbol} had been testing the {_fmt(broken_level)} level repeatedly "
        f"before finally printing a decisive close above it on {vol} — "
        f"a sign that sellers at that level have been absorbed and the balance of power has shifted. "
        f"{oi_phrase}. "
        f"The breakout targets {_fmt(target1)} as the first measured objective."
    )


# ── Template 4: Counter-Trend Caution ─────────────────────────────────────

def counter_trend_caution(
    symbol: str,
    direction: str,
    higher_tf_trend: str,
    confidence: float,
) -> str:
    opp = "bearish" if direction == "LONG" else "bullish"
    action = "bounce" if direction == "LONG" else "pullback"
    manage = "stop to breakeven quickly" if direction == "LONG" else "trail the stop aggressively"
    return (
        f"This is a counter-trend setup on {symbol} — the larger {higher_tf_trend} timeframe "
        f"remains {opp}, but short-term conditions have reached an extreme that historically "
        f"produces a brief {action} before the primary trend reasserts itself. "
        f"Confidence sits at {confidence:.0f}/100 given the against-trend nature of this trade, "
        f"so position size is reduced and you should {manage} if the setup delivers. "
        f"Treat any initial gain as a bonus rather than an expectation — "
        f"this is a precision trade with a tighter leash than a trend-following entry."
    )


# ── Template 5: Squeeze Breakout ──────────────────────────────────────────

def squeeze_breakout(
    symbol: str,
    bbwidth_percentile: float,
    direction: str,
    volume_z: float,
    target1: float,
) -> str:
    dir_word = "upward" if direction == "LONG" else "downward"
    vol = _vol_text(volume_z)
    days_str = f"bottom {bbwidth_percentile:.0f}th percentile of the past 30 days"
    return (
        f"{symbol} has been coiling for an extended period, "
        f"with price range compressing to the {days_str} — "
        f"a textbook pre-breakout structure where energy builds until it must release. "
        f"That release is materialising now, with price breaking {dir_word} on {vol}, "
        f"confirming this is a genuine expansion rather than a low-conviction drift. "
        f"Post-squeeze moves tend to be sustained; the first target is {_fmt(target1)}."
    )


# ── Template 6: BTC-Driven Altcoin Lift ───────────────────────────────────

def btc_driven_lift(
    symbol: str,
    btc_move_pct: float,
    rs_pct: float,
    target1: float,
    direction: str = "LONG",
) -> str:
    btc_dir = "higher" if btc_move_pct > 0 else "lower"
    outperform = f"outpacing BTC by {abs(rs_pct):.1f}%" if rs_pct > 0 else f"lagging BTC by {abs(rs_pct):.1f}%"
    action = "rising" if direction == "LONG" else "falling"
    demand = "demand" if direction == "LONG" else "selling"
    quality = f"showing genuine {demand} rather than just being dragged passively" if (rs_pct > 0 and direction == "LONG") or (rs_pct < 0 and direction == "SHORT") else "trailing the macro move"
    return (
        f"BTC moved {abs(btc_move_pct):.1f}% {btc_dir} and {symbol} is {action} in sympathy — "
        f"but more importantly, the coin is {outperform}, {quality}. "
        f"When an altcoin leads BTC on a macro move, the follow-through tends to be stronger "
        f"and more sustained than a passive correlation trade. "
        f"The setup targets {_fmt(target1)} on the assumption that BTC holds its current tone."
    )


# ── Template 7: Relative Strength Leader Breakout ─────────────────────────

def rs_leader_breakout(
    symbol: str,
    rs_pct: float,
    volume_z: float,
    btc_trend: str,
    target1: float,
    direction: str = "LONG",
) -> str:
    btc = _btc_context(btc_trend)
    vol = _vol_text(volume_z)
    action = "buying" if direction == "LONG" else "selling"
    break_type = "breakout" if direction == "LONG" else "breakdown"
    return (
        f"{symbol} is outperforming BTC by {abs(rs_pct):.1f}% — "
        f"a spread of that magnitude typically reflects a specific rotation or catalyst "
        f"into the coin rather than broad market momentum carrying it along. "
        f"The move is backed by {vol}, adding conviction that this is "
        f"purposeful {action} rather than thin-market noise. "
        f"{btc}, and the relative strength leader {break_type} points to "
        f"{_fmt(target1)} as the first objective."
    )


# ── Template 8: Range Boundary Rejection ──────────────────────────────────

def range_boundary_rejection(
    symbol: str,
    boundary_type: str,
    boundary_price: float,
    volume_z: float,
    target1: float,
) -> str:
    vol = _vol_text(volume_z)
    if boundary_type.upper() in ("RESISTANCE", "TOP", "UPPER"):
        touch = "upper boundary"
        action = "rejection candle — a long upper wick with price closing near the session low"
        thesis = "what sells at the top of an established range tends to reach the midpoint"
    else:
        touch = "lower boundary"
        action = "reversal candle — a long lower wick with price closing near the session high"
        thesis = "what bounces at the bottom of an established range tends to reach the midpoint"
    return (
        f"{symbol} tagged its {touch} at {_fmt(boundary_price)} and immediately "
        f"printed a {action}, on {vol} — "
        f"one of the cleanest range-fade signals available when the boundary is well-established. "
        f"The thesis is straightforward: {thesis}. "
        f"Target {_fmt(target1)} aligns with that midpoint."
    )


# ── Automatic Template Selector ────────────────────────────────────────────

def select_template(signal_data: Dict[str, Any]) -> str:
    """
    Automatically picks and renders the most appropriate narrative template
    based on signal characteristics.

    Required keys in signal_data:
      symbol, direction, timeframe, btc_trend, volume_z, target1
      + optional: is_counter_trend, entry_pattern, rs_pct, btc_move_pct,
                  ema_period, ema_price, broken_level, oi_status,
                  bbwidth_percentile, boundary_type, boundary_price, confidence
    """
    s           = signal_data
    symbol      = s["symbol"]
    direction   = s.get("direction", "LONG")
    timeframe   = s.get("timeframe", "4h")
    btc_trend   = s.get("btc_trend", "NEUTRAL")
    volume_z    = float(s.get("volume_z", 0.0))
    target1     = float(s["target1"])
    rs_pct      = float(s.get("rs_pct", 0.0))
    btc_move    = float(s.get("btc_move_pct", 0.0))
    ema_period  = int(s.get("ema_period", 50))
    ema_price   = float(s.get("ema_price", 0.0))
    pattern     = s.get("entry_pattern", "").lower()
    confidence  = float(s.get("confidence", 70.0))
    oi_status   = s.get("oi_status", "UNAVAILABLE")
    bw_pct      = float(s.get("bbwidth_percentile", 50.0))
    boundary    = s.get("boundary_type", "RESISTANCE")
    b_price     = float(s.get("boundary_price", 0.0))
    broken_lvl  = float(s.get("broken_level", 0.0))
    htf_trend   = s.get("higher_tf_trend", "4h")

    # Priority 1 — Counter-trend (always flagged explicitly)
    if s.get("is_counter_trend", False):
        return counter_trend_caution(symbol, direction, htf_trend, confidence)

    # Priority 2 — Squeeze breakout (regime recently exited LOW_VOL_SQUEEZE)
    if s.get("squeeze_breakout", False) or bw_pct <= 15.0:
        return squeeze_breakout(symbol, bw_pct, direction, volume_z, target1)

    # Priority 3 — Range boundary rejection pattern
    if "rejection" in pattern or "range" in pattern or s.get("range_rejection", False):
        return range_boundary_rejection(symbol, boundary, b_price, volume_z, target1)

    # Priority 4 — Breakout with volume
    if "breakout" in pattern or "breakdown" in pattern:
        return breakout_with_volume(symbol, broken_lvl, volume_z, oi_status, target1)

    # Priority 5 — RS leader (coin outperforming BTC by >3%)
    if rs_pct >= 3.0:
        return rs_leader_breakout(symbol, rs_pct, volume_z, btc_trend, target1, direction)

    # Priority 6 — BTC-driven lift (strong BTC move + positive correlation)
    if abs(btc_move) >= 1.5 and not s.get("is_counter_trend", False):
        return btc_driven_lift(symbol, btc_move, rs_pct, target1, direction)

    # Priority 7 — Pullback to EMA
    if "pullback" in pattern or "retest" in pattern:
        return pullback_to_ema(symbol, ema_period, ema_price, volume_z, btc_trend, target1, direction)

    # Default — Momentum continuation
    return momentum_continuation(symbol, timeframe, ema_price, volume_z, btc_trend, target1, direction)


# ── Standalone test block ──────────────────────────────────────────────────

if __name__ == "__main__":
    import io, sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    SEP = "-" * 70

    print("=" * 70)
    print("narrative.py -- All 8 Templates")
    print("=" * 70)

    # T1 — Momentum Continuation
    print(f"\n[T1] MOMENTUM CONTINUATION\n{SEP}")
    print(momentum_continuation(
        symbol="SOLUSDT", timeframe="1h", ema=143.20,
        volume_z=1.8, btc_trend="BULLISH", target1=148.60,
    ))

    # T2 — Pullback to EMA
    print(f"\n[T2] PULLBACK TO EMA\n{SEP}")
    print(pullback_to_ema(
        symbol="BTCUSDT", ema_period=50, ema_price=61200.00,
        volume_z=1.6, btc_trend="BULLISH", target1=63500.00,
    ))

    # T3 — Breakout With Volume
    print(f"\n[T3] BREAKOUT WITH VOLUME\n{SEP}")
    print(breakout_with_volume(
        symbol="ETHUSDT", broken_level=3450.00,
        volume_z=2.4, oi_status="REAL_DEMAND", target1=3620.00,
    ))

    # T4 — Counter-Trend Caution
    print(f"\n[T4] COUNTER-TREND CAUTION\n{SEP}")
    print(counter_trend_caution(
        symbol="XLMUSDT", direction="LONG",
        higher_tf_trend="4h", confidence=63.0,
    ))

    # T5 — Squeeze Breakout
    print(f"\n[T5] SQUEEZE BREAKOUT\n{SEP}")
    print(squeeze_breakout(
        symbol="SOLUSDT", bbwidth_percentile=8.0,
        direction="LONG", volume_z=3.1, target1=158.00,
    ))

    # T6 — BTC-Driven Altcoin Lift
    print(f"\n[T6] BTC-DRIVEN ALTCOIN LIFT\n{SEP}")
    print(btc_driven_lift(
        symbol="ETHUSDT", btc_move_pct=3.2,
        rs_pct=1.8, target1=3580.00,
    ))

    # T7 — RS Leader Breakout
    print(f"\n[T7] RELATIVE STRENGTH LEADER\n{SEP}")
    print(rs_leader_breakout(
        symbol="SOLUSDT", rs_pct=4.7,
        volume_z=2.8, btc_trend="NEUTRAL", target1=158.00,
    ))

    # T8 — Range Boundary Rejection
    print(f"\n[T8] RANGE BOUNDARY REJECTION\n{SEP}")
    print(range_boundary_rejection(
        symbol="XLMUSDT", boundary_type="RESISTANCE",
        boundary_price=0.2900, volume_z=1.9, target1=0.2650,
    ))

    # Auto-selector demo
    print(f"\n{'='*70}")
    print("AUTO-SELECTOR DEMO (select_template)")
    print(f"{'='*70}")

    test_signals = [
        {
            "label": "Squeeze signal",
            "symbol": "BTCUSDT", "direction": "LONG", "timeframe": "4h",
            "btc_trend": "BULLISH", "volume_z": 2.9, "target1": 65000,
            "bbwidth_percentile": 9.0, "squeeze_breakout": True,
            "ema_price": 61000, "rs_pct": 1.2, "btc_move_pct": 0.8,
        },
        {
            "label": "RS leader signal",
            "symbol": "SOLUSDT", "direction": "LONG", "timeframe": "1h",
            "btc_trend": "NEUTRAL", "volume_z": 2.3, "target1": 155.00,
            "rs_pct": 4.2, "btc_move_pct": 0.5, "ema_price": 143.0,
            "bbwidth_percentile": 55.0,
        },
        {
            "label": "Counter-trend signal",
            "symbol": "XLMUSDT", "direction": "LONG", "timeframe": "4h",
            "btc_trend": "BEARISH", "volume_z": 0.8, "target1": 0.28,
            "is_counter_trend": True, "confidence": 62.0,
            "higher_tf_trend": "4h", "ema_price": 0.245,
        },
    ]

    for sig in test_signals:
        label = sig.pop("label")
        print(f"\n--- {label} ---")
        print(select_template(sig))

    print(f"\n{'='*70}")
    print("[OK] Review all 8 outputs above for natural, professional tone.")
    print("=" * 70)
