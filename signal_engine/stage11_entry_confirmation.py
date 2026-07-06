"""
signal_engine/stage11_entry_confirmation.py
Candle pattern entry triggers and body quality checks.
"""

import io
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd
import numpy as np

from signal_engine.models import EntrySignal
from signal_engine.utils.indicators import ema, volume_zscore
from signal_engine.utils.logger import get_logger


@dataclass
class EntrySignalResult:
    symbol:              str
    direction:           str
    pattern_name:        Optional[str]
    body_quality:        str     # STRONG | NORMAL | WEAK
    body_quality_ratio:  float
    is_doji:             bool
    is_spinning_top:     bool
    is_confirmed:        bool
    confidence_modifier: int
    reject_reason:       Optional[str]

    def to_entry_signal(self, candle_status: str) -> EntrySignal:
        return EntrySignal(
            pattern_name       = self.pattern_name,
            direction          = self.direction,
            body_quality_score = self.body_quality_ratio,
            candle_status      = candle_status,
            is_valid           = self.is_confirmed,
            rejection_reason   = self.reject_reason,
        )


def _candle_metrics(row) -> Tuple[float, float, float, float]:
    """Returns (body, total_range, upper_wick, lower_wick)"""
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    body = abs(c - o)
    rng = h - l
    if rng == 0:
        rng = 1e-9  # avoid div by zero
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return body, rng, upper_wick, lower_wick


def _body_quality_check(df: pd.DataFrame, sig_idx: int) -> Tuple[str, float, bool, bool, Optional[str]]:
    """Returns (quality, ratio, is_doji, is_spinning, reject_reason)."""
    if sig_idx == -1:
        tail = df.tail(11)
    else:
        tail = df.iloc[sig_idx-10 : sig_idx+1]
        
    if len(tail) < 11:
        return "NORMAL", 1.0, False, False, None
        
    sig_row = tail.iloc[-1]
    hist_rows = tail.iloc[:-1]
    
    # 10-candle average body
    avg_body = np.mean([abs(row["close"] - row["open"]) for _, row in hist_rows.iterrows()])
    if avg_body == 0:
        avg_body = 1e-9
        
    c_body, c_rng, c_uwick, c_lwick = _candle_metrics(sig_row)
    
    ratio = c_body / avg_body
    
    if ratio > 1.2:
        quality = "STRONG"
    elif ratio >= 0.8:
        quality = "NORMAL"
    else:
        quality = "WEAK"
        
    # Doji check
    is_doji = c_body < (0.10 * c_rng)
    
    # Spinning top check
    is_spinning = (c_body < (0.20 * c_rng)) and (c_uwick > 0.30 * c_rng) and (c_lwick > 0.30 * c_rng)
    
    reason = None
    if is_doji:
        reason = "ENTRY_REJECT: Doji candle (body < 10% range)"
    elif is_spinning:
        reason = "ENTRY_REJECT: Spinning top candle"
        
    return quality, ratio, is_doji, is_spinning, reason


def _check_long_patterns(
    df: pd.DataFrame, 
    sig_idx: int, 
    quality: str, 
    regime: str, 
    res_levels: List[float]
) -> Optional[str]:
    """Check 4 long patterns."""
    if sig_idx == -1:
        subset = df.tail(5)
    else:
        subset = df.iloc[sig_idx-4 : sig_idx+1]
        
    if len(subset) < 4:
        return None
        
    c0 = subset.iloc[-1]  # current
    c1 = subset.iloc[-2]  # prev 1
    
    is_green = c0["close"] > c0["open"]
    if not is_green:
        return None
        
    body_ok = quality in ("STRONG", "NORMAL")
    
    # Pattern 1: Bullish Engulfing
    c1_is_red = c1["close"] < c1["open"]
    engulfing = (c0["open"] <= c1["close"]) and (c0["close"] >= c1["open"])
    if c1_is_red and engulfing and body_ok:
        return "Bullish Engulfing"
        
    # Pattern 2: Break and Retest (Long)
    # Price broke above res in last 3 candles, pulled back to within 0.3% of it
    if body_ok:
        for res in res_levels:
            # Did we break above in c1, c2, or c3?
            broke = False
            for i in range(-4, -1):
                if subset.iloc[i]["close"] > res and subset.iloc[i-1]["close"] <= res:
                    broke = True
                    break
            if broke:
                # Retest check on current candle
                pullback_dist = abs(c0["low"] - res) / res
                if pullback_dist <= 0.003 and c0["close"] > res:
                    return "Break & Retest (Long)"
                    
    # Pattern 3: Continuation Pullback
    # Regime TRENDING (we'll just check if it contains TRENDING), pullback to EMA20
    if "TRENDING" in regime and body_ok:
        ema20_s = ema(df, 20)
        e20 = ema20_s.iloc[sig_idx]
        if not pd.isna(e20):
            dist_to_ema = abs(c0["low"] - e20) / e20
            if dist_to_ema <= 0.005 and c0["close"] > e20:
                return "Continuation Pullback"
                
    # Pattern 4: Strong Breakout
    # Closes above nearest resistance, vol_z > 1.5, body > 60% range, quality STRONG
    if quality == "STRONG":
        if res_levels:
            nearest_res = min([r for r in res_levels if r > c1["close"]], default=None)
            if nearest_res and c0["close"] > nearest_res:
                body, rng, _, _ = _candle_metrics(c0)
                if body > 0.60 * rng:
                    vz_s = volume_zscore(df, 20)
                    vz = vz_s.iloc[sig_idx]
                    if vz > 1.5:
                        return "Strong Breakout"
                        
    return None


def _check_short_patterns(
    df: pd.DataFrame, 
    sig_idx: int, 
    quality: str, 
    regime: str, 
    sup_levels: List[float],
    res_levels: List[float]
) -> Optional[str]:
    """Check 4 short patterns."""
    if sig_idx == -1:
        subset = df.tail(5)
    else:
        subset = df.iloc[sig_idx-4 : sig_idx+1]
        
    if len(subset) < 4:
        return None
        
    c0 = subset.iloc[-1]
    c1 = subset.iloc[-2]
    
    is_red = c0["close"] < c0["open"]
    body, rng, uwick, lwick = _candle_metrics(c0)
    
    # Pattern 6: Rejection at Resistance (allow WEAK quality, can be red or green)
    if res_levels:
        nearest_res = min([r for r in res_levels if r >= c0["high"]], default=None)
        if nearest_res is None:  # Means high touched or exceeded a resistance
            touched = any(r <= c0["high"] and r >= c0["low"] for r in res_levels)
            if touched:
                if uwick > 0.60 * rng:
                    close_pct = (c0["close"] - c0["low"]) / rng
                    if close_pct < 0.30:
                        return "Rejection at Resistance"
                        
    if not is_red:
        return None
        
    body_ok = quality in ("STRONG", "NORMAL")
    
    # Pattern 5: Bearish Engulfing
    c1_is_green = c1["close"] > c1["open"]
    engulfing = (c0["open"] >= c1["close"]) and (c0["close"] <= c1["open"])
    if c1_is_green and engulfing and body_ok:
        return "Bearish Engulfing"
        
    # Pattern 7: Break and Retest (Short)
    if body_ok:
        for sup in sup_levels:
            broke = False
            for i in range(-4, -1):
                if subset.iloc[i]["close"] < sup and subset.iloc[i-1]["close"] >= sup:
                    broke = True
                    break
            if broke:
                pullback_dist = abs(c0["high"] - sup) / sup
                if pullback_dist <= 0.003 and c0["close"] < sup:
                    return "Break & Retest (Short)"
                    
    # Pattern 8: Strong Breakdown
    if quality == "STRONG":
        if sup_levels:
            nearest_sup = max([s for s in sup_levels if s < c1["close"]], default=None)
            if nearest_sup and c0["close"] < nearest_sup:
                if body > 0.60 * rng:
                    vz_s = volume_zscore(df, 20)
                    vz = vz_s.iloc[sig_idx]
                    if vz > 1.5:
                        return "Strong Breakdown"
                        
    return None


def analyze_entry_confirmation(
    df_15m: pd.DataFrame,
    symbol: str,
    direction: str,
    regime: str,
    res_levels: List[float],
    sup_levels: List[float],
) -> EntrySignalResult:
    slog = get_logger("STAGE11", symbol)
    slog.info(f"Running Entry Confirmation for {direction}...")
    
    sig_idx = df_15m.attrs.get("signal_idx", -1)
    
    quality, ratio, is_doji, is_spinning, reject = _body_quality_check(df_15m, sig_idx)
    slog.info(f"Body Quality: {quality} (Ratio: {ratio:.2f}) | Doji: {is_doji} | Spinning: {is_spinning}")
    
    if reject:
        slog.warning(reject)
        return EntrySignalResult(
            symbol=symbol, direction=direction, pattern_name="NONE",
            body_quality=quality, body_quality_ratio=ratio,
            is_doji=is_doji, is_spinning_top=is_spinning,
            is_confirmed=False, confidence_modifier=-5 if quality == "WEAK" else 0,
            reject_reason=reject
        )
        
    pattern = None
    if direction == "LONG":
        pattern = _check_long_patterns(df_15m, sig_idx, quality, regime, res_levels)
    elif direction == "SHORT":
        pattern = _check_short_patterns(df_15m, sig_idx, quality, regime, sup_levels, res_levels)
        
    mod = 0
    if pattern:
        mod += 5
        slog.info(f"Pattern Detected: {pattern} (+5 mod)")
    else:
        pattern = "NONE"
        slog.info("No entry pattern detected.")
        
    if quality == "STRONG":
        mod += 3
    elif quality == "WEAK":
        mod -= 5
        
    is_confirmed = (pattern != "NONE")
    
    return EntrySignalResult(
        symbol              = symbol,
        direction           = direction,
        pattern_name        = pattern,
        body_quality        = quality,
        body_quality_ratio  = ratio,
        is_doji             = is_doji,
        is_spinning_top     = is_spinning,
        is_confirmed        = is_confirmed,
        confidence_modifier = mod,
        reject_reason       = None,
    )


# ── Standalone test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    from signal_engine.stage00_data_fetcher import fetch_ohlcv
    from signal_engine.stage10_support_resistance import analyze_sr
    
    SEP = "=" * 80
    print(SEP)
    print("stage11_entry_confirmation.py -- Standalone Test")
    print(SEP)
    
    test_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XLMUSDT"]
    results = []
    
    for sym in test_symbols:
        df_15m = fetch_ohlcv(sym, "15m")
        df_4h = fetch_ohlcv(sym, "4h")
        
        if df_15m is not None and df_4h is not None:
            # Need S/R levels to test breakout/retest patterns
            price = float(df_4h["close"].iloc[-1])
            sr = analyze_sr(df_4h, sym, "LONG", price, price * 1.05, price * 0.95)
            
            # Simulate LONG
            res_long = analyze_entry_confirmation(df_15m, sym, "LONG", "TRENDING BULLISH", sr.resistance_levels, sr.support_levels)
            results.append(res_long)
            
            # Simulate SHORT
            res_short = analyze_entry_confirmation(df_15m, sym, "SHORT", "TRENDING BEARISH", sr.resistance_levels, sr.support_levels)
            results.append(res_short)
            
    print(f"\n{SEP}")
    print(f"{'Symbol':<10} {'Dir':<6} {'Quality':<8} {'Ratio':>5} {'Pattern':<25} {'Conf?':<6} {'Mod':>4} {'Reject'}")
    print("-" * 85)
    
    for r in results:
        rej = r.reject_reason or ""
        print(
            f"{r.symbol:<10} {r.direction:<6} {r.body_quality:<8} {r.body_quality_ratio:>5.2f} "
            f"{r.pattern_name:<25} {str(r.is_confirmed):<6} {r.confidence_modifier:>4d} {rej}"
        )

    print(f"\n{SEP}")
    print("[OK] Stage 11 entry confirmation test complete.")
    print(SEP)
