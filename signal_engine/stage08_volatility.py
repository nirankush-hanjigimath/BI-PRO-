"""
signal_engine/stage08_volatility.py
Volatility analysis, stop loss sizing, and position sizing.
"""

import io
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from signal_engine.config import cfg
from signal_engine.utils.indicators import atr
from signal_engine.utils.logger import get_logger
from signal_engine.utils.swing_points import find_swing_highs, find_swing_lows, nearest_resistance, nearest_support


@dataclass
class VolatilityResult:
    symbol:               str
    atr_14_15m:           float
    realized_vol_7d:      float
    realized_vol_30d:     float
    high_vol_environment: bool
    base_stop_distance:   float
    swing_stop_distance:  float
    final_stop_distance:  float
    final_stop_pct:       float
    risk_amount_usd:      float
    position_size_usd:    float
    position_size_pct:    float
    size_modifier:        float
    data_quality:         str    # FULL_DATA | PARTIAL_DATA


def _calc_realized_vol(df: pd.DataFrame, candles_needed: int, annualize_factor: float) -> Tuple[float, bool]:
    """Calculate annualized realized volatility using log returns."""
    if len(df) < 2:
        return 0.0, False
        
    closes = df["close"]
    log_returns = np.log(closes / closes.shift(1)).dropna()
    
    available = len(log_returns)
    has_full_data = available >= candles_needed
    
    # Use as many candles as we need or what's available
    window = min(available, candles_needed)
    slice_returns = log_returns.iloc[-window:]
    
    std_dev = slice_returns.std()
    vol = std_dev * np.sqrt(annualize_factor)
    
    return float(vol * 100.0), has_full_data  # return as percentage


def analyze_volatility(
    df_15m: pd.DataFrame,
    symbol: str,
    direction: str = "LONG",  # LONG or SHORT
) -> VolatilityResult:
    slog = get_logger("STAGE08", symbol)
    slog.info(f"Running volatility analysis for {direction}...")

    sig_idx = df_15m.attrs.get("signal_idx", -1)
    
    # ── ATR Calculation ────────────────────────────────────────────────────
    atr_s = atr(df_15m, 14)
    current_atr = float(atr_s.iloc[sig_idx]) if not atr_s.isna().all() else 0.0
    
    # ── Realized Volatility ────────────────────────────────────────────────
    # 15m candles: 96 per day. 365 days = 35040
    annualize_factor = 365 * 24 * 4
    
    vol_7d, full_7d = _calc_realized_vol(df_15m, 7 * 24 * 4, annualize_factor)
    vol_30d, full_30d = _calc_realized_vol(df_15m, 30 * 24 * 4, annualize_factor)
    
    data_quality = "FULL_DATA" if full_7d and full_30d else "PARTIAL_DATA"
    
    # ── High Vol Environment ───────────────────────────────────────────────
    # We require vol_30d > 0 to avoid division by zero
    high_vol_env = False
    if vol_30d > 0 and vol_7d > (2.0 * vol_30d):
        high_vol_env = True
        
    # ── Stop Loss Calculation ──────────────────────────────────────────────
    current_price = float(df_15m["close"].iloc[sig_idx])
    base_stop = 1.5 * current_atr
    
    if high_vol_env:
        base_stop *= 1.20   # widen stop by 20%
        
    swing_stop_dist = 0.0
    if direction == "LONG":
        lows = find_swing_lows(df_15m, lookback=5)
        sup_price, _ = nearest_support(lows, current_price)
        if not np.isnan(sup_price) and sup_price < current_price:
            swing_stop_dist = current_price - sup_price
    else:
        highs = find_swing_highs(df_15m, lookback=5)
        res_price, _ = nearest_resistance(highs, current_price)
        if not np.isnan(res_price) and res_price > current_price:
            swing_stop_dist = res_price - current_price
            
    final_stop = max(base_stop, swing_stop_dist)
    final_stop_pct = (final_stop / current_price) * 100.0 if current_price > 0 else 0.0
    
    # ── Position Sizing ────────────────────────────────────────────────────
    account_size = 1000.0
    risk_pct = 0.01  # 1%
    risk_amount = account_size * risk_pct
    
    size_modifier = 1.0
    if high_vol_env:
        risk_amount *= 0.70  # reduce position size by 30% (by reducing risk)
        size_modifier = 0.70
        
    if final_stop_pct > 0:
        # USD size = Risk USD / (Stop Loss %)
        position_size_usd = risk_amount / (final_stop_pct / 100.0)
    else:
        position_size_usd = 0.0
        
    # Cap at 10% of account maximum
    max_position = account_size * 0.10
    if position_size_usd > max_position:
        position_size_usd = max_position
        
    pos_size_pct = (position_size_usd / account_size) * 100.0
    
    v7 = f"{vol_7d:.1f}" if vol_7d is not None else "N/A"
    v30 = f"{vol_30d:.1f}" if vol_30d is not None else "N/A"
    slog.info(
        f"Vol 7d={v7}% 30d={v30}% | High Vol Env={high_vol_env} ({data_quality})"
    )
    sb = f"{base_stop:.4f}" if base_stop is not None else "N/A"
    ss = f"{swing_stop_dist:.4f}" if swing_stop_dist is not None else "N/A"
    sf = f"{final_stop_pct:.2f}" if final_stop_pct is not None else "N/A"
    slog.info(
        f"Stop Base={sb} Swing={ss} → Final={sf}%"
    )
    ra = f"{risk_amount:.2f}" if risk_amount is not None else "N/A"
    psu = f"{position_size_usd:.2f}" if position_size_usd is not None else "N/A"
    psp = f"{pos_size_pct:.1f}" if pos_size_pct is not None else "N/A"
    slog.info(
        f"Risk=${ra} → Pos Size=${psu} ({psp}%)"
    )

    return VolatilityResult(
        symbol               = symbol,
        atr_14_15m           = current_atr,
        realized_vol_7d      = vol_7d,
        realized_vol_30d     = vol_30d,
        high_vol_environment = high_vol_env,
        base_stop_distance   = base_stop,
        swing_stop_distance  = swing_stop_dist,
        final_stop_distance  = final_stop,
        final_stop_pct       = final_stop_pct,
        risk_amount_usd      = risk_amount,
        position_size_usd    = position_size_usd,
        position_size_pct    = pos_size_pct,
        size_modifier        = size_modifier,
        data_quality         = data_quality,
    )


# ── Standalone test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    from signal_engine.stage00_data_fetcher import fetch_ohlcv
    
    SEP = "=" * 70
    print(SEP)
    print("stage08_volatility.py -- Standalone Test (Hypothetical LONG)")
    print(SEP)
    
    test_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XLMUSDT"]
    results = []
    
    for sym in test_symbols:
        df_15m = fetch_ohlcv(sym, "15m")
        if df_15m is not None:
            results.append(analyze_volatility(df_15m, sym, direction="LONG"))
            
    print(f"\n{SEP}")
    print(f"{'Symbol':<10} {'ATR14':>8} {'7d RV':>8} {'30d RV':>8} {'High Vol?':<10} {'Stop %':>8} {'Pos($)':>8} {'Pos(%)':>8}")
    print("-" * 80)
    for r in results:
        print(
            f"{r.symbol:<10} {r.atr_14_15m:>8.2f} {r.realized_vol_7d:>7.1f}% {r.realized_vol_30d:>7.1f}% "
            f"{str(r.high_vol_environment):<10} {r.final_stop_pct:>7.2f}% "
            f"${r.position_size_usd:>7.2f} {r.position_size_pct:>7.1f}%"
        )
        
    print(f"\n{SEP}")
    print("Detailed Stop Distance Breakdown")
    print("-" * 80)
    for r in results:
        print(f"  {r.symbol:<10} Base={r.base_stop_distance:>8.4f}  Swing={r.swing_stop_distance:>8.4f}  →  Final={r.final_stop_distance:>8.4f}  ({r.data_quality})")

    print(f"\n{SEP}")
    print("[OK] Stage 08 volatility test complete.")
    print(SEP)
