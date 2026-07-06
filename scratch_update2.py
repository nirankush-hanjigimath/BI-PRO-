import sys

# 1. Update stage13_signal_output.py
with open(r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\stage13_signal_output.py", "r", encoding="utf-8") as f:
    s13 = f.read()

s13 = s13.replace(
'''def _post_discord(embed: dict) -> bool:
    """Sends the embed to the Discord webhook."""''',
'''def _post_discord(embed: dict) -> bool:
    """Sends the embed to the Discord webhook."""
    from signal_engine.config import cfg
    if getattr(cfg, 'mode', None) == 'backtest':
        return False'''
)
with open(r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\stage13_signal_output.py", "w", encoding="utf-8") as f:
    f.write(s13)


# 2. Update alerts.py
with open(r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\utils\alerts.py", "r", encoding="utf-8") as f:
    alerts = f.read()

alerts = alerts.replace(
'''def _post_embed(
    alert_type: str,
    title: str,
    description: str,
    fields: Optional[List[Dict[str, Any]]] = None,
    symbol: Optional[str] = None,
    footer_text: Optional[str] = None,
    webhook_url: Optional[str] = None,
) -> bool:
    """
    Core sender. Returns True on success, False on any failure.
    NEVER raises — all exceptions are caught and logged.
    """''',
'''def _post_embed(
    alert_type: str,
    title: str,
    description: str,
    fields: Optional[List[Dict[str, Any]]] = None,
    symbol: Optional[str] = None,
    footer_text: Optional[str] = None,
    webhook_url: Optional[str] = None,
) -> bool:
    """
    Core sender. Returns True on success, False on any failure.
    NEVER raises — all exceptions are caught and logged.
    """
    from signal_engine.config import cfg
    if getattr(cfg, 'mode', None) == 'backtest':
        return False'''
)
with open(r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\utils\alerts.py", "w", encoding="utf-8") as f:
    f.write(alerts)


# 3. Fix narrative.py
with open(r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\utils\narrative.py", "r", encoding="utf-8") as f:
    nar = f.read()

# Fix momentum_continuation
old_mc = '''def momentum_continuation(
    symbol: str,
    timeframe: str,
    ema: float,
    volume_z: float,
    btc_trend: str,
    target1: float,
) -> str:
    btc = _btc_context(btc_trend)
    vol = _vol_text(volume_z)
    return (
        f"{symbol} is continuing a clean uptrend on the {timeframe}, "
        f"with the {_fmt(ema)} moving average acting as a dynamic floor that has held "
        f"through multiple tests — a sign that buyers are defending the level with conviction. "
        f"This session's candle resumed the trend with {vol}, "
        f"suggesting accumulation rather than distribution. "
        f"{btc}, and the first meaningful target sits at {_fmt(target1)}."
    )'''

new_mc = '''def momentum_continuation(
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
    )'''
nar = nar.replace(old_mc, new_mc)


# Fix pullback_to_ema
old_pte = '''def pullback_to_ema(
    symbol: str,
    ema_period: int,
    ema_price: float,
    volume_z: float,
    btc_trend: str,
    target1: float,
) -> str:
    btc = _btc_context(btc_trend)
    vol = _vol_text(volume_z)
    return (
        f"{symbol} extended above its {ema_period}-period moving average before pulling "
        f"back cleanly to {_fmt(ema_price)}, where buyers stepped in exactly where they should "
        f"in a healthy uptrend. "
        f"The confirmation candle absorbed the dip with {vol}, "
        f"a signal that dip buyers are active rather than passive. "
        f"{btc}, and the structure points toward {_fmt(target1)} as the next target."
    )'''

new_pte = '''def pullback_to_ema(
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
    )'''
nar = nar.replace(old_pte, new_pte)


# Fix rs_leader_breakout
old_rs = '''def rs_leader_breakout(
    symbol: str,
    rs_pct: float,
    volume_z: float,
    btc_trend: str,
    target1: float,
) -> str:
    btc = _btc_context(btc_trend)
    vol = _vol_text(volume_z)
    return (
        f"{symbol} is outperforming BTC by {abs(rs_pct):.1f}% — "
        f"a spread of that magnitude typically reflects a specific rotation or catalyst "
        f"into the coin rather than broad market momentum carrying it along. "
        f"The move is backed by {vol}, adding conviction that this is "
        f"purposeful buying rather than thin-market noise. "
        f"{btc}, and the relative strength leader breakout points to "
        f"{_fmt(target1)} as the first objective."
    )'''

new_rs = '''def rs_leader_breakout(
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
    )'''
nar = nar.replace(old_rs, new_rs)


# Update select_template to pass direction
nar = nar.replace(
'''    # Priority 5 — RS leader (coin outperforming BTC by >3%)
    if rs_pct >= 3.0:
        return rs_leader_breakout(symbol, rs_pct, volume_z, btc_trend, target1)

    # Priority 6 — BTC-driven lift (strong BTC move + positive correlation)
    if abs(btc_move) >= 1.5 and not s.get("is_counter_trend", False):
        return btc_driven_lift(symbol, btc_move, rs_pct, target1)

    # Priority 7 — Pullback to EMA
    if "pullback" in pattern or "retest" in pattern:
        return pullback_to_ema(symbol, ema_period, ema_price, volume_z, btc_trend, target1)

    # Default — Momentum continuation
    return momentum_continuation(symbol, timeframe, ema_price, volume_z, btc_trend, target1)''',
'''    # Priority 5 — RS leader (coin outperforming BTC by >3%)
    if rs_pct >= 3.0:
        return rs_leader_breakout(symbol, rs_pct, volume_z, btc_trend, target1, direction)

    # Priority 6 — BTC-driven lift (strong BTC move + positive correlation)
    if abs(btc_move) >= 1.5 and not s.get("is_counter_trend", False):
        return btc_driven_lift(symbol, btc_move, rs_pct, target1)

    # Priority 7 — Pullback to EMA
    if "pullback" in pattern or "retest" in pattern:
        return pullback_to_ema(symbol, ema_period, ema_price, volume_z, btc_trend, target1, direction)

    # Default — Momentum continuation
    return momentum_continuation(symbol, timeframe, ema_price, volume_z, btc_trend, target1, direction)'''
)

with open(r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\utils\narrative.py", "w", encoding="utf-8") as f:
    f.write(nar)

print("Updates applied successfully.")
