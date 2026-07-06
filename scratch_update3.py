import sys

with open(r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\utils\narrative.py", "r", encoding="utf-8") as f:
    nar = f.read()

old_btc = '''def btc_driven_lift(
    symbol: str,
    btc_move_pct: float,
    rs_pct: float,
    target1: float,
) -> str:
    direction = "higher" if btc_move_pct > 0 else "lower"
    outperform = f"outpacing BTC by {abs(rs_pct):.1f}%" if rs_pct > 0 else f"lagging BTC by {abs(rs_pct):.1f}%"
    quality = "showing genuine demand rather than just being dragged passively" if rs_pct > 0 else "trailing the macro move"
    return (
        f"BTC moved {abs(btc_move_pct):.1f}% {direction} and {symbol} is rising in sympathy — "
        f"but more importantly, the coin is {outperform}, {quality}. "
        f"When an altcoin leads BTC on a macro move, the follow-through tends to be stronger "
        f"and more sustained than a passive correlation trade. "
        f"The setup targets {_fmt(target1)} on the assumption that BTC holds its current tone."
    )'''

new_btc = '''def btc_driven_lift(
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
    )'''

nar = nar.replace(old_btc, new_btc)

nar = nar.replace(
'''    # Priority 6 — BTC-driven lift (strong BTC move + positive correlation)
    if abs(btc_move) >= 1.5 and not s.get("is_counter_trend", False):
        return btc_driven_lift(symbol, btc_move, rs_pct, target1)''',
'''    # Priority 6 — BTC-driven lift (strong BTC move + positive correlation)
    if abs(btc_move) >= 1.5 and not s.get("is_counter_trend", False):
        return btc_driven_lift(symbol, btc_move, rs_pct, target1, direction)'''
)

with open(r"c:\Users\Nirankush\Desktop\FYP\Binance Trading\signal_engine\utils\narrative.py", "w", encoding="utf-8") as f:
    f.write(nar)

print("BTC-driven lift updated.")
