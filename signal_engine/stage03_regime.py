"""
signal_engine/stage03_regime.py
Market regime detection — runs on 1h and 4h independently, then computes agreement.

Priority order (highest wins):
  1. LOW_VOL_SQUEEZE  — BBWidth < P10 of last 100 candles
  2. HIGH_VOLATILITY  — ATR > 1.5× 20-period avg AND BBWidth > P90
  3. TRENDING         — ADX > 25 AND Choppiness < 50 AND BBWidth expanding
  4. RANGING          — ADX < 20 AND Choppiness > 61.8 AND BBWidth flat/contracting
  5. UNDEFINED        — mixed conditions (treated as RANGING downstream)
"""

import io
import sys
from typing import Tuple

import numpy as np
import pandas as pd

from signal_engine.models import RegimeState
from signal_engine.utils.indicators import adx, atr, bollinger_bands, choppiness_index
from signal_engine.utils.logger import get_logger

_PERCENTILE_LOOKBACK = 100   # candles for P10/P90 thresholds
_ADX_PERIOD          = 14
_CI_PERIOD           = 14
_BB_PERIOD           = 20
_ATR_PERIOD          = 14
_ATR_AVG_PERIOD      = 20
_BB_EXPAND_SHIFT     = 3     # compare current BBWidth vs 3 candles ago


# ── Vectorised regime classification ──────────────────────────────────────

def _classify_all(
    adx_s:   pd.Series,
    ci_s:    pd.Series,
    bb_bw:   pd.Series,
    atr_s:   pd.Series,
) -> Tuple[pd.Series, float, float, float]:
    """
    Classify every candle in the series.
    Returns (labels, p10, p90, current_bbwidth_percentile).
    """
    # Percentile thresholds from last N candles of BBWidth
    valid_bw  = bb_bw.dropna()
    lookback  = min(_PERCENTILE_LOOKBACK, len(valid_bw))
    tail_bw   = valid_bw.iloc[-lookback:]
    p10       = float(np.percentile(tail_bw, 10))
    p90       = float(np.percentile(tail_bw, 90))

    # Current BBWidth percentile (0-100 vs history)
    current_bw     = float(valid_bw.iloc[-1]) if len(valid_bw) else np.nan
    bw_percentile  = float((tail_bw < current_bw).mean() * 100.0)

    # ATR 20-period rolling mean
    atr_avg20  = atr_s.rolling(_ATR_AVG_PERIOD).mean()

    # BBWidth expanding vs 3 candles ago
    bw_prev3        = bb_bw.shift(_BB_EXPAND_SHIFT)
    bw_expanding    = bb_bw > bw_prev3
    bw_contracting  = ~bw_expanding

    # Vectorised conditions
    squeeze  = bb_bw < p10
    high_vol = (atr_s > 1.5 * atr_avg20) & (bb_bw > p90)
    trending = (adx_s > 25) & (ci_s < 50)  & bw_expanding
    ranging  = (adx_s < 20) & (ci_s > 61.8) & bw_contracting

    # Build label series — lower priority first so higher priority overwrites
    labels = pd.Series("UNDEFINED", index=adx_s.index)
    labels[ranging.fillna(False)]  = "RANGING"
    labels[trending.fillna(False)] = "TRENDING"
    labels[high_vol.fillna(False)] = "HIGH_VOLATILITY"
    labels[squeeze.fillna(False)]  = "LOW_VOL_SQUEEZE"

    return labels, p10, p90, bw_percentile


# ── Regime age ────────────────────────────────────────────────────────────

def _calc_regime_age(labels: pd.Series) -> int:
    """Count consecutive candles from the end that share the current regime."""
    if len(labels) == 0:
        return 0
    current = labels.iloc[-1]
    count   = 0
    for label in reversed(labels.values):
        if label == current:
            count += 1
        else:
            break
    return count


# ── Confidence modifier from age ───────────────────────────────────────────

def _age_modifier(age: int) -> int:
    if age > 48:
        return -10    # mature trend — reversal risk
    if age < 3:
        return -5     # regime not yet confirmed
    return 0


# ── Single-timeframe detection ─────────────────────────────────────────────

def detect_regime(
    df:        pd.DataFrame,
    timeframe: str,
    symbol:    str = "UNKNOWN",
) -> Tuple[RegimeState, bool]:
    """
    Classify market regime for one timeframe DataFrame.

    Returns
    -------
    (RegimeState, fire_squeeze_alert: bool)
    fire_squeeze_alert is True when regime == LOW_VOL_SQUEEZE.
    """
    slog = get_logger("STAGE03", symbol)

    # Calculate indicators (do NOT mutate df)
    adx_res = adx(df, _ADX_PERIOD)
    ci_s    = choppiness_index(df, _CI_PERIOD)
    bb      = bollinger_bands(df, _BB_PERIOD)
    atr_s   = atr(df, _ATR_PERIOD)

    labels, p10, p90, bw_pct = _classify_all(
        adx_res.adx, ci_s, bb.bandwidth, atr_s
    )

    # Current regime = last label
    current_regime = labels.iloc[-1] if len(labels) else "UNDEFINED"

    # Regime age (walk last 100 labels)
    tail_labels = labels.iloc[-_PERCENTILE_LOOKBACK:]
    age         = _calc_regime_age(tail_labels)
    modifier    = _age_modifier(age)

    # Current indicator snapshot
    cur_adx  = float(adx_res.adx.iloc[-1])  if not adx_res.adx.isna().all()  else np.nan
    cur_ci   = float(ci_s.iloc[-1])          if not ci_s.isna().all()          else np.nan
    cur_bw   = float(bb.bandwidth.iloc[-1])  if not bb.bandwidth.isna().all()  else np.nan

    fire_squeeze = (current_regime == "LOW_VOL_SQUEEZE")

    slog.info(
        f"{timeframe} | Regime={current_regime} | Age={age} candles | "
        f"ADX={cur_adx:.1f} | CI={cur_ci:.1f} | BBW={cur_bw:.3f}% | "
        f"BBW_pct={bw_pct:.0f}th | Mod={modifier:+d}"
    )

    if fire_squeeze:
        slog.warning(f"{timeframe} | LOW_VOL_SQUEEZE — squeeze alert will fire, no trade")

    state = RegimeState(
        timeframe           = timeframe,
        regime              = current_regime,
        regime_age_candles  = age,
        adx                 = cur_adx,
        choppiness          = cur_ci,
        bbwidth             = cur_bw,
        bbwidth_percentile  = bw_pct,
        confidence_modifier = modifier,
    )

    return state, fire_squeeze


# ── Agreement check ───────────────────────────────────────────────────────

# Regimes considered "adjacent" (not opposite)
_ADJACENT_PAIRS = {
    frozenset({"TRENDING",       "HIGH_VOLATILITY"}),
    frozenset({"RANGING",        "LOW_VOL_SQUEEZE"}),
    frozenset({"RANGING",        "UNDEFINED"}),
    frozenset({"TRENDING",       "UNDEFINED"}),
    frozenset({"HIGH_VOLATILITY","UNDEFINED"}),
    frozenset({"LOW_VOL_SQUEEZE","UNDEFINED"}),
}

def get_regime_agreement(regime_1h: RegimeState, regime_4h: RegimeState) -> str:
    """
    Compare 1h and 4h regime states.

    Returns
    -------
    "STRONG_AGREEMENT"  — same regime on both timeframes
    "PARTIAL_AGREEMENT" — adjacent / compatible regimes
    "DISAGREEMENT"      — opposite regimes (e.g. TRENDING vs RANGING)
    """
    r1, r4 = regime_1h.regime, regime_4h.regime

    if r1 == r4:
        return "STRONG_AGREEMENT"

    pair = frozenset({r1, r4})
    if pair in _ADJACENT_PAIRS:
        return "PARTIAL_AGREEMENT"

    return "DISAGREEMENT"


# ── Multi-timeframe wrapper ────────────────────────────────────────────────

def analyze_regime(
    df_1h:  pd.DataFrame,
    df_4h:  pd.DataFrame,
    symbol: str = "UNKNOWN",
) -> dict:
    """
    Run regime detection on 1h and 4h, compute agreement.

    Returns dict with keys:
      regime_1h, regime_4h (RegimeState)
      agreement (str)
      fire_squeeze_alert (bool)
    """
    state_1h, sq_1h = detect_regime(df_1h, "1h", symbol)
    state_4h, sq_4h = detect_regime(df_4h, "4h", symbol)
    agreement       = get_regime_agreement(state_1h, state_4h)

    get_logger("STAGE03", symbol).info(f"Agreement: {agreement}")

    return {
        "regime_1h":          state_1h,
        "regime_4h":          state_4h,
        "agreement":          agreement,
        "fire_squeeze_alert": sq_1h or sq_4h,
    }


# ── Standalone test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    from signal_engine.stage00_data_fetcher import fetch_ohlcv, _refresh_daily_volume_cache
    from signal_engine.config import cfg

    SEP = "=" * 70
    print(SEP)
    print("stage03_regime.py -- Standalone Test (BTCUSDT, SOLUSDT)")
    print(SEP)

    _refresh_daily_volume_cache(cfg.symbols)

    test_symbols = ["BTCUSDT", "SOLUSDT"]

    for sym in test_symbols:
        print(f"\n{'─'*70}")
        print(f"  {sym}")
        print(f"{'─'*70}")

        df_1h = fetch_ohlcv(sym, "1h")
        df_4h = fetch_ohlcv(sym, "4h")

        if df_1h is None or df_4h is None:
            print(f"  ERROR: failed to fetch candles for {sym}")
            continue

        result = analyze_regime(df_1h, df_4h, sym)

        for tf, state in [("1h", result["regime_1h"]), ("4h", result["regime_4h"])]:
            print(f"\n  [{tf}]")
            print(f"    Regime          : {state.regime}")
            print(f"    Age             : {state.regime_age_candles} candles")
            print(f"    ADX(14)         : {state.adx:.2f}")
            print(f"    Choppiness(14)  : {state.choppiness:.2f}")
            print(f"    BBWidth         : {state.bbwidth:.4f}%")
            print(f"    BBWidth Pct     : {state.bbwidth_percentile:.0f}th percentile")
            print(f"    Confidence Mod  : {state.confidence_modifier:+d}")

        print(f"\n  Agreement (1h vs 4h) : {result['agreement']}")
        print(f"  Squeeze alert fire   : {result['fire_squeeze_alert']}")

    print(f"\n{SEP}")
    print("[OK] Stage 03 regime detection complete.")
    print(SEP)
