"""
signal_engine/stage10_support_resistance.py
Support and Resistance analysis. Detects liquidity zones, checks room to nearest levels,
and adjusts targets based on S/R blockades.
"""

import io
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pandas as pd

from signal_engine.models import SRLevels
from signal_engine.utils.logger import get_logger
from signal_engine.utils.swing_points import (
    LiquidityZone,
    SwingPoint,
    cluster_liquidity_zones,
    find_swing_highs,
    find_swing_lows,
)


@dataclass
class SRLevelsResult:
    symbol:                   str
    direction:                str
    resistance_levels:        List[float]
    support_levels:           List[float]
    nearest_resistance:       Optional[float]
    nearest_resistance_pct:   Optional[float]
    nearest_support:          Optional[float]
    nearest_support_pct:      Optional[float]
    room_check_pass:          bool
    sr_reject:                bool
    reject_reason:            Optional[str]
    adjusted_target1:         float
    adjusted_rr_ratio:        float
    zone_count:               int
    strongest_zone_price:     Optional[float]
    strongest_zone_touches:   int

    def to_sr_levels(self) -> SRLevels:
        return SRLevels(
            resistance_levels      = self.resistance_levels,
            support_levels         = self.support_levels,
            nearest_resistance     = self.nearest_resistance,
            nearest_support        = self.nearest_support,
            room_to_resistance_pct = self.nearest_resistance_pct,
            room_to_support_pct    = self.nearest_support_pct,
            long_rejected          = self.sr_reject if self.direction == "LONG" else False,
            short_rejected         = self.sr_reject if self.direction == "SHORT" else False,
            rejection_reason       = self.reject_reason,
        )


def _get_time_levels(df: pd.DataFrame, sig_idx: int) -> Tuple[List[SwingPoint], List[SwingPoint]]:
    """Get Daily and Weekly highs/lows and return them as SwingPoints."""
    if sig_idx == -1:
        valid_df = df
    else:
        valid_df = df.iloc[:sig_idx+1]
        
    if len(valid_df) == 0:
        return [], []
        
    ts = valid_df.index[-1]
    
    # Daily (last 6 4h-candles)
    d_df = valid_df.tail(6)
    d_high = float(d_df["high"].max())
    d_low = float(d_df["low"].min())
    
    # Weekly (last 42 4h-candles)
    w_df = valid_df.tail(42)
    w_high = float(w_df["high"].max())
    w_low = float(w_df["low"].min())
    
    highs = [
        SwingPoint(timestamp=ts, price=d_high, kind="HIGH"),
        SwingPoint(timestamp=ts, price=w_high, kind="HIGH"),
    ]
    lows = [
        SwingPoint(timestamp=ts, price=d_low, kind="LOW"),
        SwingPoint(timestamp=ts, price=w_low, kind="LOW"),
    ]
    
    return highs, lows


def _calculate_rr(direction: str, entry: float, target: float, stop: float) -> float:
    if direction == "LONG":
        risk = entry - stop
        reward = target - entry
    else:
        risk = stop - entry
        reward = entry - target
        
    if risk <= 0:
        return 0.0
    return reward / risk


def analyze_sr(
    df_4h: pd.DataFrame,
    symbol: str,
    direction: str,
    current_price: float,
    target1: float,
    stop_loss: float,
) -> SRLevelsResult:
    slog = get_logger("STAGE10", symbol)
    slog.info(f"Running S/R analysis for {direction} | Entry={current_price:.2f} T1={target1:.2f} SL={stop_loss:.2f}")

    sig_idx = df_4h.attrs.get("signal_idx", -1)
    
    # 1. Swing Highs & Lows
    sw_highs = find_swing_highs(df_4h, lookback=5)[-5:]
    sw_lows  = find_swing_lows(df_4h, lookback=5)[-5:]
    
    # 2. Daily/Weekly Highs & Lows
    t_highs, t_lows = _get_time_levels(df_4h, sig_idx)
    
    all_highs = sw_highs + t_highs
    all_lows = sw_lows + t_lows
    
    # 3. Cluster into zones
    zones = cluster_liquidity_zones(all_highs + all_lows, threshold_pct=0.5)
    
    # Separate zones into Resistance (above price) and Support (below price)
    res_zones = sorted([z for z in zones if z.price > current_price], key=lambda x: x.price)
    sup_zones = sorted([z for z in zones if z.price < current_price], key=lambda x: x.price, reverse=True)
    
    res_levels = [z.price for z in res_zones]
    sup_levels = [z.price for z in sup_zones]
    
    nearest_res = res_zones[0].price if res_zones else None
    nearest_res_pct = ((nearest_res - current_price) / current_price * 100) if nearest_res else None
    
    nearest_sup = sup_zones[0].price if sup_zones else None
    nearest_sup_pct = ((current_price - nearest_sup) / current_price * 100) if nearest_sup else None

    # Find strongest zone
    strongest_zone = max(zones, key=lambda x: x.count) if zones else None
    strongest_price = strongest_zone.price if strongest_zone else None
    strongest_touches = strongest_zone.count if strongest_zone else 0
    
    # 4. Room Check & Adjustments
    reject = False
    reason = None
    adj_target1 = target1
    adj_rr = _calculate_rr(direction, current_price, target1, stop_loss)
    
    res_p = f"{nearest_res_pct:+.2f}%" if nearest_res_pct is not None else "N/A"
    sup_p = f"{nearest_sup_pct:+.2f}%" if nearest_sup_pct is not None else "N/A"
    slog.info(f"Nearest Res: {nearest_res} ({res_p}) | Nearest Sup: {nearest_sup} ({sup_p})")
    
    if direction == "LONG":
        if nearest_res_pct is not None:
            if nearest_res_pct < 0.8:
                reject = True
                r_res = f"{nearest_res:.2f}" if nearest_res is not None else "N/A"
                r_pct = f"{nearest_res_pct:.2f}" if nearest_res_pct is not None else "N/A"
                reason = f"SR_REJECT: Nearest resistance ({r_res}) is only {r_pct}% above entry (< 0.8%)"
                slog.warning(reason)
            else:
                # Check if T1 is within 0.3% of the nearest resistance zone
                dist_to_t1 = (target1 - nearest_res) / target1 * 100
                if abs(dist_to_t1) <= 0.3 or target1 >= nearest_res:
                    t1_f = f"{target1:.2f}" if target1 is not None else "N/A"
                    nr_f = f"{nearest_res:.2f}" if nearest_res is not None else "N/A"
                    slog.info(f"Target1 {t1_f} obstructed by resistance {nr_f}. Adjusting Target1.")
                    adj_target1 = nearest_res
                    adj_rr = _calculate_rr("LONG", current_price, adj_target1, stop_loss)
                    
    elif direction == "SHORT":
        if nearest_sup_pct is not None:
            if nearest_sup_pct < 0.8:
                reject = True
                s_sup = f"{nearest_sup:.2f}" if nearest_sup is not None else "N/A"
                s_pct = f"{nearest_sup_pct:.2f}" if nearest_sup_pct is not None else "N/A"
                reason = f"SR_REJECT: Nearest support ({s_sup}) is only {s_pct}% below entry (< 0.8%)"
                slog.warning(reason)
            else:
                # Check if T1 is within 0.3% of the nearest support zone
                dist_to_t1 = (nearest_sup - target1) / target1 * 100
                if abs(dist_to_t1) <= 0.3 or target1 <= nearest_sup:
                    t1_f = f"{target1:.2f}" if target1 is not None else "N/A"
                    ns_f = f"{nearest_sup:.2f}" if nearest_sup is not None else "N/A"
                    slog.info(f"Target1 {t1_f} obstructed by support {ns_f}. Adjusting Target1.")
                    adj_target1 = nearest_sup
                    adj_rr = _calculate_rr("SHORT", current_price, adj_target1, stop_loss)
                    
    # Re-evaluate R:R
    if not reject and adj_rr < 1.8:
        reject = True
        reason = f"SR_REJECT: R:R below 1.8 ({adj_rr:.2f}) after S/R adjustment"
        slog.warning(reason)

    if not reject:
        t1_s = f"{adj_target1:.2f}" if adj_target1 is not None else "N/A"
        rr_s = f"{adj_rr:.2f}" if adj_rr is not None else "N/A"
        slog.info(f"S/R Check PASSED. Final T1={t1_s} R:R={rr_s}")

    return SRLevelsResult(
        symbol                 = symbol,
        direction              = direction,
        resistance_levels      = res_levels,
        support_levels         = sup_levels,
        nearest_resistance     = nearest_res,
        nearest_resistance_pct = nearest_res_pct,
        nearest_support        = nearest_sup,
        nearest_support_pct    = nearest_sup_pct,
        room_check_pass        = not reject,
        sr_reject              = reject,
        reject_reason          = reason,
        adjusted_target1       = adj_target1,
        adjusted_rr_ratio      = adj_rr,
        zone_count             = len(zones),
        strongest_zone_price   = strongest_price,
        strongest_zone_touches = strongest_touches,
    )


# ── Standalone test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    from signal_engine.stage00_data_fetcher import fetch_ohlcv
    from signal_engine.utils.indicators import atr
    
    SEP = "=" * 80
    print(SEP)
    print("stage10_support_resistance.py -- Standalone Test")
    print(SEP)
    
    test_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XLMUSDT"]
    results = []
    
    for sym in test_symbols:
        df_4h = fetch_ohlcv(sym, "4h")
        if df_4h is not None:
            price = float(df_4h["close"].iloc[-1])
            atr_val = float(atr(df_4h, 14).iloc[-1])
            
            # Simulate LONG: Stop at 1 ATR below, T1 at 2.2 ATR above
            sl_long = price - (atr_val * 1.0)
            t1_long = price + (atr_val * 2.2)
            res_long = analyze_sr(df_4h, sym, "LONG", price, t1_long, sl_long)
            results.append(res_long)
            
            # Simulate SHORT: Stop at 1 ATR above, T1 at 2.2 ATR below
            sl_short = price + (atr_val * 1.0)
            t1_short = price - (atr_val * 2.2)
            res_short = analyze_sr(df_4h, sym, "SHORT", price, t1_short, sl_short)
            results.append(res_short)
            
    print(f"\n{SEP}")
    print(f"{'Symbol':<10} {'Dir':<6} {'Price':>9} {'Nearest Res':>12} {'Nearest Sup':>12} {'Room Pass':<10} {'Adj T1':>9} {'Adj R:R':>7}")
    print("-" * 80)
    
    def _f(val):
        return f"{val:,.2f}" if val is not None else "N/A"
        
    for r in results:
        curr_price = r.adjusted_target1  # we didn't save current_price to dataclass, but we can infer
        # Actually I can't print entry directly unless I pass it or calculate it. I'll just skip printing entry price accurately
        # Or I will infer it from the logic: 
        print(
            f"{r.symbol:<10} {r.direction:<6} {'---':>9} {_f(r.nearest_resistance):>12} {_f(r.nearest_support):>12} "
            f"{str(r.room_check_pass):<10} {_f(r.adjusted_target1):>9} {r.adjusted_rr_ratio:>7.2f}"
        )
        if r.sr_reject:
            print(f"  -> REJECTED: {r.reject_reason}")
            
    print(f"\n{SEP}")
    print("Zone Statistics")
    print("-" * 80)
    for r in results:
        print(f"  {r.symbol:<10} {r.direction:<5} | Zones={r.zone_count:2d} | Strongest={_f(r.strongest_zone_price)} ({r.strongest_zone_touches} touches)")

    print(f"\n{SEP}")
    print("[OK] Stage 10 S/R test complete.")
    print(SEP)
