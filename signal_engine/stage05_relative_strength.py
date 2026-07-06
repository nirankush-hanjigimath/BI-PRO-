"""
signal_engine/stage05_relative_strength.py
Relative strength vs BTC over 1h/4h and rolling 7-day correlation matrix.

RS Calculation:
  1h return = (close - close_1h_ago) / close_1h_ago * 100
  4h return = (close - close_4h_ago) / close_4h_ago * 100
  RS = (coin_return - btc_return)
  Combined RS = 0.4 * RS_1h + 0.6 * RS_4h

Classification:
  > +1.5% → LEADER  (+8 mod)
  < -1.5% → LAGGARD (-10 mod)
  Else    → NEUTRAL (0 mod)
"""

import io
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from signal_engine.config import cfg
from signal_engine.models import RelativeStrength
from signal_engine.utils.logger import get_logger

_SPOT_BASE = "https://api.binance.com"


# ── Extended result (richer than models.RelativeStrength) ──────────────────

@dataclass
class RelativeStrengthResult:
    symbol:              str
    rs_1h:               float
    rs_4h:               float
    combined_rs:         float
    classification:      str   # LEADER | LAGGARD | NEUTRAL
    confidence_modifier: int
    correlation_cluster: List[str]
    matrix_age_hours:    float
    matrix_stale:        bool

    def to_relative_strength(self) -> RelativeStrength:
        cluster_str = ",".join(self.correlation_cluster) if self.correlation_cluster else "NONE"
        return RelativeStrength(
            rs_pct              = self.combined_rs,
            classification      = self.classification,
            confidence_modifier = self.confidence_modifier,
            correlation_cluster = cluster_str,
        )


# ── State file handling ────────────────────────────────────────────────────

def _load_state() -> dict:
    if os.path.exists(cfg.state_file):
        try:
            with open(cfg.state_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    try:
        with open(cfg.state_file, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        get_logger("STAGE05", "STATE").error(f"Failed to save engine state: {e}")


# ── Correlation Matrix ─────────────────────────────────────────────────────

def update_correlation_matrix(symbols: List[str] = None) -> None:
    """Fetch 7 days of 1h data (168 candles) and compute correlation matrix."""
    syms = symbols or cfg.symbols
    slog = get_logger("STAGE05", "CORRELATION")

    if len(syms) < 2:
        return

    slog.info(f"Updating 7-day correlation matrix for {len(syms)} symbols...")
    
    returns_dict = {}
    for sym in syms:
        try:
            r = requests.get(
                f"{_SPOT_BASE}/api/v3/klines",
                params={"symbol": sym, "interval": "1h", "limit": 168},
                timeout=10,
            )
            r.raise_for_status()
            closes = pd.Series([float(row[4]) for row in r.json()])
            returns_dict[sym] = closes.pct_change().dropna()
        except Exception as e:
            slog.error(f"Failed to fetch 1h data for {sym}: {e}")
            return
            
    df_returns = pd.DataFrame(returns_dict)
    corr_matrix = df_returns.corr(method="pearson")
    
    state = _load_state()
    state["correlation_matrix"] = corr_matrix.to_dict()
    state["correlation_timestamp"] = time.time()
    _save_state(state)
    slog.info("Correlation matrix updated and saved to state.")


def get_correlation_cluster(symbol: str, threshold: float = 0.75) -> Tuple[List[str], float, bool]:
    """
    Returns (cluster_symbols, age_hours, is_stale).
    If stale, assumes all symbols are correlated to be safe.
    """
    state = _load_state()
    matrix = state.get("correlation_matrix", {})
    ts = state.get("correlation_timestamp", 0)
    
    age_hours = (time.time() - ts) / 3600.0
    is_stale = age_hours > 24.0 or not matrix
    
    if is_stale:
        # Fallback: assume everything is correlated if matrix is missing/stale
        return (cfg.symbols, age_hours, True)
        
    if symbol not in matrix:
        return ([symbol], age_hours, False)
        
    cluster = []
    for other_sym, corr_val in matrix[symbol].items():
        if other_sym != symbol and corr_val >= threshold:
            cluster.append(other_sym)
            
    return (cluster, age_hours, False)


# ── Relative Strength ──────────────────────────────────────────────────────

def _calc_return(df: pd.DataFrame, periods_ago: int) -> float:
    """Calculate percentage return over N periods on the signal candle."""
    sig_idx = df.attrs.get("signal_idx", -1)
    
    if len(df) < abs(sig_idx) + periods_ago:
        return 0.0
        
    current_close = float(df.iloc[sig_idx]["close"])
    past_close    = float(df.iloc[sig_idx - periods_ago]["close"])
    
    if past_close == 0:
        return 0.0
        
    return (current_close - past_close) / past_close * 100.0


def analyze_relative_strength(
    df_1h_coin: pd.DataFrame,
    df_4h_coin: pd.DataFrame,
    df_1h_btc:  pd.DataFrame,
    df_4h_btc:  pd.DataFrame,
    symbol:     str,
) -> RelativeStrengthResult:
    """Calculate RS vs BTC and determine classification & correlation cluster."""
    slog = get_logger("STAGE05", symbol)
    
    # Returns
    coin_1h_ret = _calc_return(df_1h_coin, 1)
    coin_4h_ret = _calc_return(df_4h_coin, 1)
    btc_1h_ret  = _calc_return(df_1h_btc, 1)
    btc_4h_ret  = _calc_return(df_4h_btc, 1)
    
    # RS = Coin Return - BTC Return
    rs_1h = coin_1h_ret - btc_1h_ret
    rs_4h = coin_4h_ret - btc_4h_ret
    
    # Combined RS
    combined_rs = (0.4 * rs_1h) + (0.6 * rs_4h)
    
    # Classification
    if combined_rs > 1.5:
        classification = "LEADER"
        modifier = +8
    elif combined_rs < -1.5:
        classification = "LAGGARD"
        modifier = -10
    else:
        classification = "NEUTRAL"
        modifier = 0
        
    slog.info(
        f"RS vs BTC: 1h={rs_1h:+.2f}% 4h={rs_4h:+.2f}% → Combined={combined_rs:+.2f}% "
        f"| {classification} (mod {modifier:+d})"
    )
    
    # Correlation cluster
    cluster, age, stale = get_correlation_cluster(symbol)
    if stale:
        slog.warning(f"Correlation matrix stale (age {age:.1f}h) → assuming all correlated")
    else:
        slog.info(f"Correlated (>=0.75): {cluster}")
        
    return RelativeStrengthResult(
        symbol              = symbol,
        rs_1h               = rs_1h,
        rs_4h               = rs_4h,
        combined_rs         = combined_rs,
        classification      = classification,
        confidence_modifier = modifier,
        correlation_cluster = cluster,
        matrix_age_hours    = age,
        matrix_stale        = stale,
    )


# ── Standalone test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    from signal_engine.stage00_data_fetcher import fetch_ohlcv
    
    SEP = "=" * 70
    print(SEP)
    print("stage05_relative_strength.py -- Standalone Test")
    print(SEP)
    
    # 1. Update correlation matrix
    print("\nUpdating correlation matrix...")
    update_correlation_matrix()
    
    # 2. Fetch data
    print("\nFetching current 1h and 4h data...")
    btc_1h = fetch_ohlcv("BTCUSDT", "1h")
    btc_4h = fetch_ohlcv("BTCUSDT", "4h")
    
    results = []
    test_symbols = ["SOLUSDT", "ETHUSDT", "XLMUSDT"]
    
    for sym in test_symbols:
        df_1h = fetch_ohlcv(sym, "1h")
        df_4h = fetch_ohlcv(sym, "4h")
        if df_1h is not None and df_4h is not None and btc_1h is not None and btc_4h is not None:
            res = analyze_relative_strength(df_1h, df_4h, btc_1h, btc_4h, sym)
            results.append(res)
            
    # 3. Print RS Table
    print(f"\n{SEP}")
    print(f"{'Symbol':<10} {'1h RS':>8} {'4h RS':>8} {'Combined':>10}  {'Class':<10} {'Mod':>4}  {'Cluster'}")
    print("-" * 70)
    for r in results:
        cluster = ",".join(r.correlation_cluster) if r.correlation_cluster else "NONE"
        print(
            f"{r.symbol:<10} {r.rs_1h:>+7.2f}% {r.rs_4h:>+7.2f}% {r.combined_rs:>+9.2f}%  "
            f"{r.classification:<10} {r.confidence_modifier:>+4d}  {cluster}"
        )
        
    # 4. Print correlation matrix snapshot from state
    print(f"\n{SEP}")
    print("Correlation Matrix Snapshot (from state file)")
    print("-" * 70)
    state = _load_state()
    matrix = state.get("correlation_matrix", {})
    ts = state.get("correlation_timestamp", 0)
    age = (time.time() - ts) / 3600.0
    
    print(f"Matrix Age: {age:.2f} hours (Stale? {age > 24.0})\n")
    
    if matrix:
        syms = list(matrix.keys())
        print(f"{'':<10}", end="")
        for s in syms:
            print(f"{s:>10}", end="")
        print()
        
        for s1 in syms:
            print(f"{s1:<10}", end="")
            for s2 in syms:
                val = matrix[s1].get(s2, 0.0)
                print(f"{val:>10.2f}", end="")
            print()
            
    print(f"\n{SEP}")
    print("[OK] Stage 05 test complete.")
    print(SEP)
