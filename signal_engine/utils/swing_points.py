"""
signal_engine/utils/swing_points.py
Swing point detection, market structure classification, and liquidity zone clustering.
Input: DataFrame with high/low columns. No mutation of input DataFrame.
"""

from typing import List, NamedTuple, Tuple
import numpy as np
import pandas as pd


# ── Named return types ─────────────────────────────────────────────────────

class SwingPoint(NamedTuple):
    timestamp: pd.Timestamp
    price:     float
    kind:      str   # "HIGH" or "LOW"

class LiquidityZone(NamedTuple):
    price:     float  # representative price (mean of cluster)
    count:     int    # number of swing points in cluster
    kind:      str    # "HIGH" or "LOW"

class SwingStructure(NamedTuple):
    label:    str    # "HH_HL" | "LH_LL" | "HH_LL" | "MIXED" | "INSUFFICIENT"
    bullish:  bool
    bearish:  bool


# ── Swing High Detection ───────────────────────────────────────────────────

def find_swing_highs(df: pd.DataFrame, lookback: int = 5) -> List[SwingPoint]:
    """
    A swing high is a candle whose high is strictly greater than
    `lookback` candles on each side.

    Note: last `lookback` candles cannot be swing highs (no right-side context).
    """
    highs   = df["high"].values
    idx     = df.index
    result  = []
    n       = len(highs)

    for i in range(lookback, n - lookback):
        left  = highs[i - lookback : i]
        right = highs[i + 1 : i + lookback + 1]
        if highs[i] > left.max() and highs[i] > right.max():
            result.append(SwingPoint(timestamp=idx[i], price=float(highs[i]), kind="HIGH"))

    return result


# ── Swing Low Detection ────────────────────────────────────────────────────

def find_swing_lows(df: pd.DataFrame, lookback: int = 5) -> List[SwingPoint]:
    """
    A swing low is a candle whose low is strictly less than
    `lookback` candles on each side.
    """
    lows   = df["low"].values
    idx    = df.index
    result = []
    n      = len(lows)

    for i in range(lookback, n - lookback):
        left  = lows[i - lookback : i]
        right = lows[i + 1 : i + lookback + 1]
        if lows[i] < left.min() and lows[i] < right.min():
            result.append(SwingPoint(timestamp=idx[i], price=float(lows[i]), kind="LOW"))

    return result


# ── Market Structure Classification ───────────────────────────────────────

def classify_swing_structure(
    swing_highs: List[SwingPoint],
    swing_lows:  List[SwingPoint],
    n:           int = 3,
) -> SwingStructure:
    """
    Classify market structure from last `n` swing highs and lows.

    HH_HL  → Higher Highs + Higher Lows  (bullish)
    LH_LL  → Lower Highs  + Lower Lows   (bearish)
    HH_LL  → Mixed (expanding range or transition)
    MIXED  → No clear structure
    INSUFFICIENT → Not enough swing points
    """
    if len(swing_highs) < n or len(swing_lows) < n:
        return SwingStructure(label="INSUFFICIENT", bullish=False, bearish=False)

    recent_highs = [sp.price for sp in swing_highs[-n:]]
    recent_lows  = [sp.price for sp in swing_lows[-n:]]

    hh = all(recent_highs[i] > recent_highs[i - 1] for i in range(1, len(recent_highs)))
    hl = all(recent_lows[i]  > recent_lows[i - 1]  for i in range(1, len(recent_lows)))
    lh = all(recent_highs[i] < recent_highs[i - 1] for i in range(1, len(recent_highs)))
    ll = all(recent_lows[i]  < recent_lows[i - 1]  for i in range(1, len(recent_lows)))

    if hh and hl:
        return SwingStructure(label="HH_HL", bullish=True,  bearish=False)
    if lh and ll:
        return SwingStructure(label="LH_LL", bullish=False, bearish=True)
    if hh and ll:
        return SwingStructure(label="HH_LL", bullish=False, bearish=False)
    return SwingStructure(label="MIXED",  bullish=False, bearish=False)


# ── Liquidity Zone Clustering ──────────────────────────────────────────────

def cluster_liquidity_zones(
    points:        List[SwingPoint],
    threshold_pct: float = 0.5,
) -> List[LiquidityZone]:
    """
    Group swing points within `threshold_pct`% of each other into zones.
    Each zone has a representative price (mean) and a count.
    Returns zones sorted by price ascending.
    """
    if not points:
        return []

    sorted_pts = sorted(points, key=lambda sp: sp.price)
    zones: List[LiquidityZone] = []
    cluster_prices: List[float] = [sorted_pts[0].price]
    cluster_kind:   str          = sorted_pts[0].kind

    for sp in sorted_pts[1:]:
        zone_center = float(np.mean(cluster_prices))
        diff_pct    = abs(sp.price - zone_center) / zone_center * 100.0

        if diff_pct <= threshold_pct:
            cluster_prices.append(sp.price)
        else:
            zones.append(LiquidityZone(
                price=round(float(np.mean(cluster_prices)), 6),
                count=len(cluster_prices),
                kind=cluster_kind,
            ))
            cluster_prices = [sp.price]
            cluster_kind   = sp.kind

    # Flush last cluster
    zones.append(LiquidityZone(
        price=round(float(np.mean(cluster_prices)), 6),
        count=len(cluster_prices),
        kind=cluster_kind,
    ))

    return zones


# ── Convenience: nearest S/R levels ───────────────────────────────────────

def nearest_resistance(
    swing_highs: List[SwingPoint],
    current_price: float,
) -> Tuple[float, float]:
    """
    Returns (resistance_price, distance_pct) of the nearest swing high ABOVE current price.
    Returns (nan, nan) if none found.
    """
    above = [sp.price for sp in swing_highs if sp.price > current_price]
    if not above:
        return (np.nan, np.nan)
    res = min(above)
    dist_pct = (res - current_price) / current_price * 100.0
    return (res, dist_pct)


def nearest_support(
    swing_lows: List[SwingPoint],
    current_price: float,
) -> Tuple[float, float]:
    """
    Returns (support_price, distance_pct) of the nearest swing low BELOW current price.
    Returns (nan, nan) if none found.
    """
    below = [sp.price for sp in swing_lows if sp.price < current_price]
    if not below:
        return (np.nan, np.nan)
    sup = max(below)
    dist_pct = (current_price - sup) / current_price * 100.0
    return (sup, dist_pct)


# ── Standalone test block ──────────────────────────────────────────────────

if __name__ == "__main__":
    import io, sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    import requests

    print("=" * 70)
    print("swing_points.py -- Standalone Test (BTCUSDT 4h, last 300 candles)")
    print("=" * 70)

    resp = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={"symbol": "BTCUSDT", "interval": "4h", "limit": 300},
        timeout=10,
    )
    resp.raise_for_status()
    cols = ["open_time","open","high","low","close","volume",
            "close_time","quote_vol","trades","tbv","tbq","ignore"]
    df = pd.DataFrame(resp.json(), columns=cols)
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.set_index("open_time", inplace=True)

    current_price = float(df["close"].iloc[-1])
    print(f"\nCurrent BTCUSDT price: ${current_price:,.2f}")

    # Swing detection (lookback=5 candles each side)
    highs = find_swing_highs(df, lookback=5)
    lows  = find_swing_lows(df,  lookback=5)

    print(f"\nTotal swing highs detected: {len(highs)}")
    print(f"Total swing lows  detected: {len(lows)}")

    print(f"\nLast 5 Swing HIGHS:")
    for sp in highs[-5:]:
        print(f"  {sp.timestamp}  HIGH = ${sp.price:,.2f}")

    print(f"\nLast 5 Swing LOWS:")
    for sp in lows[-5:]:
        print(f"  {sp.timestamp}  LOW  = ${sp.price:,.2f}")

    # Market structure
    structure = classify_swing_structure(highs, lows, n=3)
    print(f"\nMarket Structure (last 3 swings): {structure.label}")
    print(f"  Bullish: {structure.bullish}  |  Bearish: {structure.bearish}")

    # Nearest S/R
    res_price, res_dist = nearest_resistance(highs, current_price)
    sup_price, sup_dist = nearest_support(lows,  current_price)
    print(f"\nNearest Resistance: ${res_price:,.2f}  ({res_dist:.2f}% above)")
    print(f"Nearest Support:    ${sup_price:,.2f}  ({sup_dist:.2f}% below)")

    # Liquidity zones — combine all swing points
    all_points = highs + lows
    zones = cluster_liquidity_zones(all_points, threshold_pct=0.5)
    strong_zones = [z for z in zones if z.count >= 2]

    print(f"\nLiquidity Zones (>= 2 swing points, within 0.5%):")
    if strong_zones:
        for z in sorted(strong_zones, key=lambda z: z.price):
            marker = " <-- current" if abs(z.price - current_price) / current_price < 0.02 else ""
            print(f"  ${z.price:,.2f}  [{z.kind}]  hits={z.count}{marker}")
    else:
        print("  No multi-touch zones detected in this window.")

    print("\n" + "=" * 70)
    print("[OK] Swing point detection complete.")
    print("=" * 70)
