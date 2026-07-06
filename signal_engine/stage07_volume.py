"""
signal_engine/stage07_volume.py
Volume analysis for divergence, exhaustion, and trend health.
Primary timeframe: 15m.
"""

import io
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

import pandas as pd

from signal_engine.utils.indicators import volume_zscore
from signal_engine.utils.logger import get_logger


@dataclass
class VolumeResult:
    symbol:                str
    timeframe:             str
    volume_z_score:        float
    volume_classification: str
    divergence_tag:        Optional[str]
    exhaustion_tag:        Optional[str]
    health_tag:            Optional[str]
    confidence_modifier:   int
    green_avg_volume:      float
    red_avg_volume:        float
    current_volume:        float
    average_volume:        float


def _classify_zscore(z: float) -> str:
    if z > 2.0:
        return "VOLUME_CLIMAX"
    if z > 1.0:
        return "ABOVE_AVERAGE"
    if z > 0.0:
        return "NORMAL"
    if z > -1.0:
        return "VOLUME_DRY_UP"
    return "ACCUM_DIST"


def _check_divergence(closes: pd.Series, volumes: pd.Series) -> Optional[str]:
    """Check last 3 consecutive candles for volume divergence."""
    if len(closes) < 4:
        return None
        
    c = closes.values[-4:]
    v = volumes.values[-4:]
    
    # 0, 1, 2, 3 (3 is current)
    higher_closes = (c[3] > c[2]) and (c[2] > c[1]) and (c[1] > c[0])
    lower_closes  = (c[3] < c[2]) and (c[2] < c[1]) and (c[1] < c[0])
    falling_volume = (v[3] < v[2]) and (v[2] < v[1]) and (v[1] < v[0])
    
    if higher_closes and falling_volume:
        return "VOLUME_DIVERGENCE"
    if lower_closes and falling_volume:
        return "SELLING_EXHAUSTION"
        
    return None


def _check_exhaustion(
    is_climax: bool, 
    closes: pd.Series, 
    opens: pd.Series
) -> Optional[str]:
    """
    If VOLUME_CLIMAX and candle reverses a 3-candle trend, tag VOLUME_EXHAUSTION.
    """
    if not is_climax or len(closes) < 4:
        return None
        
    c = closes.values[-4:]
    o = opens.values[-4:]
    
    # Prior 3 trend (excluding current candle index 3)
    prior_up = (c[2] > c[1]) and (c[1] > c[0])
    prior_down = (c[2] < c[1]) and (c[1] < c[0])
    
    # Current candle direction
    current_up = c[3] > o[3]
    current_down = c[3] < o[3]
    
    if prior_down and current_up:
        return "VOLUME_EXHAUSTION"
    if prior_up and current_down:
        return "VOLUME_EXHAUSTION"
        
    return None


def _check_health(df: pd.DataFrame, sig_idx: int) -> Tuple[Optional[str], float, float]:
    """
    Check volume health over last 10 candles.
    Uptrend = close > close 10 periods ago.
    Returns (health_tag, avg_green_vol, avg_red_vol).
    """
    if sig_idx == -1:
        tail = df.tail(10)
    else:
        tail = df.iloc[sig_idx-9 : sig_idx+1]
        
    if len(tail) < 10:
        return None, 0.0, 0.0
        
    green_mask = tail["close"] > tail["open"]
    red_mask = tail["close"] < tail["open"]
    
    avg_green = tail.loc[green_mask, "volume"].mean() if green_mask.any() else 0.0
    avg_red = tail.loc[red_mask, "volume"].mean() if red_mask.any() else 0.0
    
    start_close = tail["close"].iloc[0]
    end_close = tail["close"].iloc[-1]
    
    health_tag = None
    if end_close > start_close:
        # Uptrend
        if avg_red > avg_green:
            health_tag = "UNHEALTHY_VOLUME"
    elif end_close < start_close:
        # Downtrend
        if avg_green > avg_red:
            health_tag = "UNHEALTHY_VOLUME"
            
    return health_tag, float(avg_green), float(avg_red)


def analyze_volume(df: pd.DataFrame, timeframe: str, symbol: str) -> VolumeResult:
    slog = get_logger("STAGE07", symbol)
    slog.info(f"Running volume analysis on {timeframe}...")
    
    sig_idx = df.attrs.get("signal_idx", -1)
    
    # ── Volume Z-Score ─────────────────────────────────────────────────────
    vz_s = volume_zscore(df, 20)
    z_score = float(vz_s.iloc[sig_idx]) if not vz_s.isna().all() else 0.0
    classification = _classify_zscore(z_score)
    
    # Extract historical slice up to sig_idx
    if sig_idx == -1:
        df_slice = df
    else:
        df_slice = df.iloc[:sig_idx+1]
        
    closes = df_slice["close"]
    opens = df_slice["open"]
    volumes = df_slice["volume"]
    
    # ── Divergence ─────────────────────────────────────────────────────────
    div_tag = _check_divergence(closes, volumes)
    
    # ── Exhaustion ─────────────────────────────────────────────────────────
    is_climax = (classification == "VOLUME_CLIMAX")
    exh_tag = _check_exhaustion(is_climax, closes, opens)
    
    # ── Trend Health ───────────────────────────────────────────────────────
    health_tag, avg_green, avg_red = _check_health(df, sig_idx)
    
    # ── Confidence Modifiers ───────────────────────────────────────────────
    mod = 0
    if div_tag == "VOLUME_DIVERGENCE":
        mod -= 10
    if health_tag == "UNHEALTHY_VOLUME":
        mod -= 5
        
    current_vol = float(volumes.iloc[-1])
    avg_vol = float(volumes.rolling(20).mean().iloc[-1])
    
    slog.info(f"{timeframe} Vol Z={z_score:+.2f} ({classification}) | Div={div_tag} Exh={exh_tag} Health={health_tag}")
    slog.info(f"Avg Green Vol={avg_green:,.0f} | Avg Red Vol={avg_red:,.0f} | Mod={mod:+d}")

    return VolumeResult(
        symbol                = symbol,
        timeframe             = timeframe,
        volume_z_score        = z_score,
        volume_classification = classification,
        divergence_tag        = div_tag,
        exhaustion_tag        = exh_tag,
        health_tag            = health_tag,
        confidence_modifier   = mod,
        green_avg_volume      = avg_green,
        red_avg_volume        = avg_red,
        current_volume        = current_vol,
        average_volume        = avg_vol,
    )


# ── Standalone test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    from signal_engine.stage00_data_fetcher import fetch_ohlcv
    
    SEP = "=" * 70
    print(SEP)
    print("stage07_volume.py -- Standalone Test")
    print(SEP)
    
    test_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XLMUSDT"]
    results_15m = []
    results_1h = []
    
    for sym in test_symbols:
        df_15m = fetch_ohlcv(sym, "15m")
        df_1h = fetch_ohlcv(sym, "1h")
        
        if df_15m is not None:
            results_15m.append(analyze_volume(df_15m, "15m", sym))
        if df_1h is not None:
            results_1h.append(analyze_volume(df_1h, "1h", sym))
            
    print(f"\n{SEP}")
    print("15m Volume Analysis")
    print(f"{SEP}")
    print(f"{'Symbol':<10} {'Z-Score':>8} {'Class':<15} {'Mod':>4} {'Div Tag':<20} {'Exh Tag':<20} {'Health Tag':<18}")
    print("-" * 105)
    for r in results_15m:
        print(
            f"{r.symbol:<10} {r.volume_z_score:>+8.2f} {r.volume_classification:<15} {r.confidence_modifier:>+4d} "
            f"{str(r.divergence_tag):<20} {str(r.exhaustion_tag):<20} {str(r.health_tag):<18}"
        )
        
    print(f"\n{SEP}")
    print("1h Volume Analysis")
    print(f"{SEP}")
    print(f"{'Symbol':<10} {'Z-Score':>8} {'Class':<15} {'Mod':>4} {'Div Tag':<20} {'Exh Tag':<20} {'Health Tag':<18}")
    print("-" * 105)
    for r in results_1h:
        print(
            f"{r.symbol:<10} {r.volume_z_score:>+8.2f} {r.volume_classification:<15} {r.confidence_modifier:>+4d} "
            f"{str(r.divergence_tag):<20} {str(r.exhaustion_tag):<20} {str(r.health_tag):<18}"
        )

    print(f"\n{SEP}")
    print("Volume Health Averages (15m)")
    print(f"{SEP}")
    print(f"{'Symbol':<10} {'Avg Green':>15} {'Avg Red':>15} {'Trend Health'}")
    print("-" * 65)
    for r in results_15m:
        health_str = "UNHEALTHY" if r.health_tag else "HEALTHY"
        print(f"{r.symbol:<10} {r.green_avg_volume:>15,.0f} {r.red_avg_volume:>15,.0f} {health_str}")

    print(f"\n{SEP}")
    print("[OK] Stage 07 volume test complete.")
    print(SEP)
