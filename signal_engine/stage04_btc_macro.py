"""
signal_engine/stage04_btc_macro.py
Bitcoin macro classification — acts as a filter for all altcoin signals downstream.

Scoring per timeframe (max 4 pts bullish OR 4 pts bearish):
  EMA slopes:   both positive → +2 bull | both negative → +2 bear
                diverging → +1 bull or +1 bear
  RSI(14):      > 60 → +1 bull | < 40 → +1 bear
  Vol Z-Score:  > 1.5 on bullish candle → +1 bull | on bearish candle → +1 bear

Combined score (both TFs, max ±8):
  +6 to +8 → STRONGLY_BULLISH
  +3 to +5 → BULLISH
  -2 to +2 → NEUTRAL
  -3 to -5 → BEARISH
  -6 to -8 → STRONGLY_BEARISH
"""

import io
import sys
from dataclasses import dataclass
from typing import Tuple

import numpy as np
import pandas as pd

from signal_engine.models import BTCMacro
from signal_engine.utils.indicators import ema, ema_slope, rsi, volume_zscore
from signal_engine.utils.logger import get_logger

_EMA_SLOPE_LOOKBACK = 10


# ── Extended result (richer than models.BTCMacro) ─────────────────────────

@dataclass
class BTCMacroResult:
    """Full BTCMacro result with per-timeframe breakdown and scoring detail."""
    classification:      str   # STRONGLY_BULLISH | BULLISH | NEUTRAL | BEARISH | STRONGLY_BEARISH
    bullish_score:       int   # 0–8
    bearish_score:       int   # 0–8
    net_score:           int   # bullish_score - bearish_score

    # 1h indicators
    ema50_slope_1h:      float
    ema200_slope_1h:     float
    rsi_1h:              float
    volume_zscore_1h:    float
    bull_pts_1h:         int
    bear_pts_1h:         int

    # 4h indicators
    ema50_slope_4h:      float
    ema200_slope_4h:     float
    rsi_4h:              float
    volume_zscore_4h:    float
    bull_pts_4h:         int
    bear_pts_4h:         int

    # Downstream flags
    confidence_modifier: int   # base modifier for LONG signals
    hard_reject_long:    bool  # True when STRONGLY_BEARISH

    def to_btc_macro(self) -> BTCMacro:
        """Produce the slim BTCMacro model used inside the Signal dataclass."""
        return BTCMacro(
            classification      = self.classification,
            ema50_slope         = self.ema50_slope_4h,
            ema200_slope        = self.ema200_slope_4h,
            rsi                 = self.rsi_4h,
            volume_zscore       = self.volume_zscore_4h,
            confidence_modifier = self.confidence_modifier,
        )


# ── Per-timeframe scorer ───────────────────────────────────────────────────

def _score_timeframe(df: pd.DataFrame, label: str, symbol: str) -> Tuple[int, int, dict]:
    """
    Score one timeframe. Returns (bull_pts, bear_pts, indicator_snapshot).
    Max 4 bull pts or 4 bear pts.
    """
    slog     = get_logger("STAGE04", symbol)
    bull     = 0
    bear     = 0
    snapshot = {}

    # ── EMA slopes ─────────────────────────────────────────────────────────
    ema50_s  = ema(df, 50)
    ema200_s = ema(df, 200)
    slope50  = ema_slope(ema50_s,  _EMA_SLOPE_LOOKBACK)
    slope200 = ema_slope(ema200_s, _EMA_SLOPE_LOOKBACK)

    s50  = float(slope50.iloc[-1])  if not slope50.isna().all()  else 0.0
    s200 = float(slope200.iloc[-1]) if not slope200.isna().all() else 0.0
    snapshot["ema50_slope"]  = s50
    snapshot["ema200_slope"] = s200

    if s50 > 0 and s200 > 0:
        bull += 2
        slog.info(f"{label} EMA: both positive → +2 bull")
    elif s50 > 0 and s200 <= 0:
        bull += 1
        slog.info(f"{label} EMA: recovering (50 pos, 200 neg) → +1 bull")
    elif s50 <= 0 and s200 <= 0:
        bear += 2
        slog.info(f"{label} EMA: both negative → +2 bear")
    elif s50 <= 0 and s200 > 0:
        bear += 1
        slog.info(f"{label} EMA: weakening (50 neg, 200 pos) → +1 bear")

    # ── RSI ────────────────────────────────────────────────────────────────
    rsi_s   = rsi(df, 14)
    rsi_val = float(rsi_s.iloc[-1]) if not rsi_s.isna().all() else 50.0
    snapshot["rsi"] = rsi_val

    if rsi_val > 60:
        bull += 1
        slog.info(f"{label} RSI={rsi_val:.1f} > 60 → +1 bull")
    elif rsi_val < 40:
        bear += 1
        slog.info(f"{label} RSI={rsi_val:.1f} < 40 → +1 bear")
    else:
        slog.info(f"{label} RSI={rsi_val:.1f} → neutral")

    # ── Volume Z-Score ─────────────────────────────────────────────────────
    vz_s    = volume_zscore(df, 20)
    vz_val  = float(vz_s.iloc[-1]) if not vz_s.isna().all() else 0.0
    snapshot["volume_zscore"] = vz_val

    # Determine candle direction (close vs open of signal row)
    sig_idx     = df.attrs.get("signal_idx", -1)
    sig_row     = df.iloc[sig_idx]
    candle_bull = float(sig_row["close"]) > float(sig_row["open"])

    if abs(vz_val) > 1.5:
        if candle_bull:
            bull += 1
            slog.info(f"{label} Vol Z={vz_val:.2f} on bullish candle → +1 bull")
        else:
            bear += 1
            slog.info(f"{label} Vol Z={vz_val:.2f} on bearish candle → +1 bear")
    else:
        slog.info(f"{label} Vol Z={vz_val:.2f} < 1.5 → neutral")

    return bull, bear, snapshot


# ── Classification from net score ─────────────────────────────────────────

def _classify(net: int) -> str:
    if net >= 6:
        return "STRONGLY_BULLISH"
    if net >= 3:
        return "BULLISH"
    if net <= -6:
        return "STRONGLY_BEARISH"
    if net <= -3:
        return "BEARISH"
    return "NEUTRAL"


# ── Confidence modifier lookup ─────────────────────────────────────────────

_LONG_BASE_MODIFIER = {
    "STRONGLY_BULLISH": +10,
    "BULLISH":          +5,
    "NEUTRAL":          0,
    "BEARISH":          -10,
    "STRONGLY_BEARISH": -10,   # hard_reject handles complete block
}


def get_btc_confidence_modifier(
    btc_macro:        BTCMacroResult,
    signal_direction: str,    # "LONG" or "SHORT"
) -> Tuple[int, bool]:
    """
    Returns (modifier, hard_reject).

    modifier    : confidence points to add/subtract
    hard_reject : True if the BTC state means the signal must be dropped entirely
                  (STRONGLY_BEARISH + LONG, or STRONGLY_BULLISH + SHORT with no RS edge)
    """
    cls = btc_macro.classification

    # Hard reject: STRONGLY_BEARISH + LONG
    if cls == "STRONGLY_BEARISH" and signal_direction == "LONG":
        return (-30, True)

    # Base modifier for direction
    if signal_direction == "LONG":
        base = _LONG_BASE_MODIFIER.get(cls, 0)
    else:   # SHORT — inverse
        base = -_LONG_BASE_MODIFIER.get(cls, 0)

    # Opposing-direction penalty
    bullish_cls = cls in ("STRONGLY_BULLISH", "BULLISH")
    bearish_cls = cls in ("STRONGLY_BEARISH", "BEARISH")

    opposing = (signal_direction == "SHORT" and bullish_cls) or \
               (signal_direction == "LONG"  and bearish_cls)

    penalty = -20 if opposing else 0

    return (base + penalty, False)


# ── Main function ──────────────────────────────────────────────────────────

def analyze_btc_macro(
    df_1h:  pd.DataFrame,
    df_4h:  pd.DataFrame,
    symbol: str = "BTCUSDT",
) -> BTCMacroResult:
    """
    Run BTC macro analysis on 1h and 4h candles.
    Returns BTCMacroResult with full breakdown.
    """
    slog = get_logger("STAGE04", symbol)
    slog.info("Running BTC macro analysis...")

    bull_1h, bear_1h, snap_1h = _score_timeframe(df_1h, "1h", symbol)
    bull_4h, bear_4h, snap_4h = _score_timeframe(df_4h, "4h", symbol)

    total_bull = bull_1h + bull_4h
    total_bear = bear_1h + bear_4h
    net        = total_bull - total_bear
    cls        = _classify(net)

    base_mod   = _LONG_BASE_MODIFIER.get(cls, 0)
    hard_rej   = (cls == "STRONGLY_BEARISH")

    slog.info(
        f"Score: bull={total_bull} bear={total_bear} net={net:+d} → {cls} "
        f"| base_modifier={base_mod:+d} | hard_reject_long={hard_rej}"
    )

    return BTCMacroResult(
        classification      = cls,
        bullish_score       = total_bull,
        bearish_score       = total_bear,
        net_score           = net,
        ema50_slope_1h      = snap_1h["ema50_slope"],
        ema200_slope_1h     = snap_1h["ema200_slope"],
        rsi_1h              = snap_1h["rsi"],
        volume_zscore_1h    = snap_1h["volume_zscore"],
        bull_pts_1h         = bull_1h,
        bear_pts_1h         = bear_1h,
        ema50_slope_4h      = snap_4h["ema50_slope"],
        ema200_slope_4h     = snap_4h["ema200_slope"],
        rsi_4h              = snap_4h["rsi"],
        volume_zscore_4h    = snap_4h["volume_zscore"],
        bull_pts_4h         = bull_4h,
        bear_pts_4h         = bear_4h,
        confidence_modifier = base_mod,
        hard_reject_long    = hard_rej,
    )


# ── Standalone test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    from signal_engine.stage00_data_fetcher import fetch_ohlcv, _refresh_daily_volume_cache
    from signal_engine.config import cfg

    SEP = "=" * 70
    print(SEP)
    print("stage04_btc_macro.py -- Standalone Test (BTCUSDT)")
    print(SEP)

    _refresh_daily_volume_cache(cfg.symbols)
    df_1h = fetch_ohlcv("BTCUSDT", "1h")
    df_4h = fetch_ohlcv("BTCUSDT", "4h")

    if df_1h is None or df_4h is None:
        print("ERROR: failed to fetch BTCUSDT candles")
        sys.exit(1)

    result = analyze_btc_macro(df_1h, df_4h, "BTCUSDT")

    print(f"\n{'─'*70}")
    print("  SCORING BREAKDOWN")
    print(f"{'─'*70}")
    print(f"  {'Metric':<28} {'1h':>10} {'4h':>10}")
    print(f"  {'-'*50}")
    print(f"  {'EMA50 slope':<28} {result.ema50_slope_1h:>+10.4f} {result.ema50_slope_4h:>+10.4f}")
    print(f"  {'EMA200 slope':<28} {result.ema200_slope_1h:>+10.4f} {result.ema200_slope_4h:>+10.4f}")
    print(f"  {'RSI(14)':<28} {result.rsi_1h:>10.2f} {result.rsi_4h:>10.2f}")
    print(f"  {'Volume Z-Score':<28} {result.volume_zscore_1h:>+10.3f} {result.volume_zscore_4h:>+10.3f}")
    print(f"  {'-'*50}")
    print(f"  {'Bull pts':<28} {result.bull_pts_1h:>10} {result.bull_pts_4h:>10}")
    print(f"  {'Bear pts':<28} {result.bear_pts_1h:>10} {result.bear_pts_4h:>10}")

    print(f"\n{'─'*70}")
    print("  COMBINED RESULT")
    print(f"{'─'*70}")
    print(f"  Total bull score   : {result.bullish_score} / 8")
    print(f"  Total bear score   : {result.bearish_score} / 8")
    print(f"  Net score          : {result.net_score:+d}")
    print(f"  Classification     : {result.classification}")
    print(f"  Hard reject LONG   : {result.hard_reject_long}")
    print(f"  Base modifier      : {result.confidence_modifier:+d}")

    print(f"\n{'─'*70}")
    print("  MODIFIER APPLIED TO HYPOTHETICAL SIGNALS")
    print(f"{'─'*70}")
    for direction in ("LONG", "SHORT"):
        mod, reject = get_btc_confidence_modifier(result, direction)
        print(f"  {direction:<6} signal → modifier={mod:+d}  hard_reject={reject}")

    # Also show slim BTCMacro model
    slim = result.to_btc_macro()
    print(f"\n{'─'*70}")
    print("  BTCMacro (slim model for Signal dataclass)")
    print(f"{'─'*70}")
    print(f"  classification      : {slim.classification}")
    print(f"  confidence_modifier : {slim.confidence_modifier:+d}")
    print(f"  ema50_slope (4h)    : {slim.ema50_slope:+.4f}")
    print(f"  ema200_slope (4h)   : {slim.ema200_slope:+.4f}")
    print(f"  rsi (4h)            : {slim.rsi:.2f}")
    print(f"  volume_zscore (4h)  : {slim.volume_zscore:+.3f}")

    print(f"\n{SEP}")
    print("[OK] Stage 04 BTC macro analysis complete.")
    print(SEP)
