"""
signal_engine/stage06_trend_quality.py
Trend quality analysis combining EMA slopes, market structure, and overextension checks.

EMA Slopes: RISING, FALLING, or FLAT (abs(slope) < 0.05% of current price).
Structure: BULLISH (last 3 HH/HL), BEARISH (last 3 LH/LL), MIXED.
Overextension: Distance from EMA50 > 3 ATR (-8 mod), > 5 ATR (-15 mod).
"""

import io
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

import pandas as pd

from signal_engine.utils.indicators import atr, ema, ema_slope
from signal_engine.utils.logger import get_logger
from signal_engine.utils.swing_points import find_swing_highs, find_swing_lows, classify_swing_structure

_EMA_SLOPE_LOOKBACK = 10
_FLAT_THRESHOLD_PCT = 0.0005  # 0.05%


# ── Result dataclass ───────────────────────────────────────────────────────

@dataclass
class TrendQualityResult:
    symbol:                   str
    trend_quality:            str    # STRONG_TREND | MODERATE_TREND | WEAK_TREND | NO_TREND
    direction:                str    # BULLISH | BEARISH | MIXED
    ema50_slope_4h:           float
    ema200_slope_4h:          float
    ema50_slope_1h:           float
    ema200_slope_1h:          float
    swing_structure:          str    # BULLISH | BEARISH | MIXED
    distance_from_ema50_atr:  float
    trend_persistence_candles:int
    overextension_tag:        Optional[str]
    confidence_modifier:      int


# ── Internal logic ─────────────────────────────────────────────────────────

def _classify_slope(slope: float, current_price: float) -> str:
    """Classify a slope as RISING, FALLING, or FLAT based on % of price."""
    if abs(slope) < (current_price * _FLAT_THRESHOLD_PCT):
        return "FLAT"
    return "RISING" if slope > 0 else "FALLING"


def _calc_persistence(df: pd.DataFrame, ema50_s: pd.Series) -> int:
    """
    Count consecutive candles closing on the same side of EMA50 as the signal candle.
    Returns the count (int).
    """
    if len(df) == 0 or len(ema50_s) == 0:
        return 0

    sig_idx = df.attrs.get("signal_idx", -1)
    # Get subset up to sig_idx to ensure we only look at closed/current data correctly
    if sig_idx == -1:
        closes = df["close"]
        emas = ema50_s
    else:
        # e.g., sig_idx = -2 means skip the last row
        closes = df["close"].iloc[:sig_idx+1]
        emas = ema50_s.iloc[:sig_idx+1]

    if len(closes) == 0:
        return 0

    # side: True if close > ema, False if close < ema
    # For exact equals, we can count it as the current side
    current_side = closes.iloc[-1] >= emas.iloc[-1]
    
    count = 0
    # Walk backwards
    for c, e in zip(closes.values[::-1], emas.values[::-1]):
        if pd.isna(e):
            break
        if (c >= e) == current_side:
            count += 1
        else:
            break
            
    return count


def _classify_trend_quality(
    ema50_cls: str,
    ema200_cls: str,
    structure: str,
    overextended: bool
) -> Tuple[str, str]:
    """
    Returns (trend_quality, direction).
    
    STRONG_TREND: EMAs both rising/falling in agreement AND structure BULLISH/BEARISH AND not overextended
    MODERATE_TREND: EMAs agree but structure MIXED, or structure clear but one EMA flat
    WEAK_TREND: EMAs disagreeing or structure MIXED and EMAs flat
    NO_TREND: all flat, no structure
    """
    # Base direction from EMAs and structure
    if ema50_cls == "RISING" and ema200_cls == "RISING":
        direction = "BULLISH"
    elif ema50_cls == "FALLING" and ema200_cls == "FALLING":
        direction = "BEARISH"
    elif structure == "BULLISH" and ema50_cls != "FALLING" and ema200_cls != "FALLING":
        direction = "BULLISH"
    elif structure == "BEARISH" and ema50_cls != "RISING" and ema200_cls != "RISING":
        direction = "BEARISH"
    else:
        direction = "MIXED"

    emas_agree = (ema50_cls == "RISING" and ema200_cls == "RISING") or \
                 (ema50_cls == "FALLING" and ema200_cls == "FALLING")
    
    one_flat = (ema50_cls == "FLAT" and ema200_cls != "FLAT") or \
               (ema50_cls != "FLAT" and ema200_cls == "FLAT")
               
    all_flat = (ema50_cls == "FLAT" and ema200_cls == "FLAT")
    struct_clear = (structure in ("BULLISH", "BEARISH"))
    struct_matches_ema = (emas_agree and ((direction == "BULLISH" and structure == "BULLISH") or 
                                          (direction == "BEARISH" and structure == "BEARISH")))

    if all_flat and not struct_clear:
        return "NO_TREND", direction
        
    if emas_agree and struct_matches_ema and not overextended:
        return "STRONG_TREND", direction
        
    if (emas_agree and structure == "MIXED") or (struct_clear and one_flat):
        return "MODERATE_TREND", direction
        
    if (ema50_cls == "RISING" and ema200_cls == "FALLING") or \
       (ema50_cls == "FALLING" and ema200_cls == "RISING") or \
       (structure == "MIXED" and all_flat):
        return "WEAK_TREND", direction
        
    # Default fallback
    return "WEAK_TREND", direction


# ── Main analyzer ──────────────────────────────────────────────────────────

def analyze_trend_quality(
    df_4h: pd.DataFrame,
    df_1h: pd.DataFrame,
    symbol: str,
) -> TrendQualityResult:
    """Analyze trend quality based on 4h (primary) and 1h EMAs + market structure."""
    slog = get_logger("STAGE06", symbol)
    slog.info("Running trend quality analysis...")
    
    sig_idx_4h = df_4h.attrs.get("signal_idx", -1)
    current_price_4h = float(df_4h["close"].iloc[sig_idx_4h])
    
    # ── EMA Slopes (4h and 1h) ─────────────────────────────────────────────
    # 4h EMAs
    e50_4h = ema(df_4h, 50)
    e200_4h = ema(df_4h, 200)
    slope50_4h = float(ema_slope(e50_4h, _EMA_SLOPE_LOOKBACK).iloc[sig_idx_4h])
    slope200_4h = float(ema_slope(e200_4h, _EMA_SLOPE_LOOKBACK).iloc[sig_idx_4h])
    cls50_4h = _classify_slope(slope50_4h, current_price_4h)
    cls200_4h = _classify_slope(slope200_4h, current_price_4h)
    
    # 1h EMAs
    sig_idx_1h = df_1h.attrs.get("signal_idx", -1)
    current_price_1h = float(df_1h["close"].iloc[sig_idx_1h])
    
    e50_1h = ema(df_1h, 50)
    e200_1h = ema(df_1h, 200)
    slope50_1h = float(ema_slope(e50_1h, _EMA_SLOPE_LOOKBACK).iloc[sig_idx_1h])
    slope200_1h = float(ema_slope(e200_1h, _EMA_SLOPE_LOOKBACK).iloc[sig_idx_1h])
    
    # ── Market Structure (4h) ──────────────────────────────────────────────
    highs = find_swing_highs(df_4h, lookback=5)
    lows = find_swing_lows(df_4h, lookback=5)
    structure_obj = classify_swing_structure(highs, lows, n=3)
    structure = structure_obj.label
    
    # ── Overextension Check (4h) ───────────────────────────────────────────
    atr14 = float(atr(df_4h, 14).iloc[sig_idx_4h])
    ema50_val = float(e50_4h.iloc[sig_idx_4h])
    dist_atr = (current_price_4h - ema50_val) / atr14 if atr14 > 0 else 0.0
    abs_dist = abs(dist_atr)
    
    over_tag = None
    mod = 0
    
    if abs_dist > 5.0:
        over_tag = "SEVERELY_OVEREXTENDED"
        mod = -15
    elif abs_dist > 3.0:
        over_tag = "OVEREXTENDED"
        mod = -8
        
    # ── Trend Persistence (4h) ─────────────────────────────────────────────
    persistence = _calc_persistence(df_4h, e50_4h)
    
    # ── Overall Quality ────────────────────────────────────────────────────
    quality, direction = _classify_trend_quality(
        cls50_4h, cls200_4h, structure, overextended=(over_tag is not None)
    )
    
    # Logging
    slog.info(
        f"4h EMAs: 50={cls50_4h} ({slope50_4h:+.4f}), 200={cls200_4h} ({slope200_4h:+.4f}) | "
        f"Structure: {structure}"
    )
    if over_tag:
        slog.warning(f"Price is {over_tag} ({abs_dist:.1f} ATRs from EMA50) → Mod {mod}")
    slog.info(f"Trend Persistence: {persistence} candles (side of EMA50)")
    slog.info(f"Result: {quality} ({direction})")

    return TrendQualityResult(
        symbol                    = symbol,
        trend_quality             = quality,
        direction                 = direction,
        ema50_slope_4h            = slope50_4h,
        ema200_slope_4h           = slope200_4h,
        ema50_slope_1h            = slope50_1h,
        ema200_slope_1h           = slope200_1h,
        swing_structure           = structure,
        distance_from_ema50_atr   = dist_atr,
        trend_persistence_candles = persistence,
        overextension_tag         = over_tag,
        confidence_modifier       = mod,
    )


# ── Standalone test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    from signal_engine.stage00_data_fetcher import fetch_ohlcv
    
    SEP = "=" * 70
    print(SEP)
    print("stage06_trend_quality.py -- Standalone Test")
    print(SEP)
    
    test_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XLMUSDT"]
    results = []
    
    for sym in test_symbols:
        df_1h = fetch_ohlcv(sym, "1h")
        df_4h = fetch_ohlcv(sym, "4h")
        
        if df_1h is not None and df_4h is not None:
            res = analyze_trend_quality(df_4h, df_1h, sym)
            results.append(res)
            
    print(f"\n{SEP}")
    print(f"{'Symbol':<10} {'Quality':<16} {'Direction':<10} {'Struct':<10} {'Dist(ATR)':>10} {'Persist':>8} {'Mod':>4} {'Tag'}")
    print("-" * 90)
    for r in results:
        tag = r.overextension_tag or "NONE"
        print(
            f"{r.symbol:<10} {r.trend_quality:<16} {r.direction:<10} {r.swing_structure:<10} "
            f"{r.distance_from_ema50_atr:>10.2f} {r.trend_persistence_candles:>8} {r.confidence_modifier:>4d} {tag}"
        )
        
    print(f"\n{SEP}")
    print("Detailed Slopes (Price/Candle)")
    print("-" * 90)
    for r in results:
        print(f"  {r.symbol:<10} 4h: EMA50={r.ema50_slope_4h:>+8.4f} EMA200={r.ema200_slope_4h:>+8.4f}")
        print(f"             1h: EMA50={r.ema50_slope_1h:>+8.4f} EMA200={r.ema200_slope_1h:>+8.4f}")
        print()

    print(f"{SEP}")
    print("[OK] Stage 06 trend quality test complete.")
    print(SEP)
