"""
setup_detector.py — Stage 3
Rule-based, deterministic setup detection. No AI, no randomness.
Each detector function is a pure function that operates on the DataFrame
returned by data_engine.fetch_and_calculate().

Cooldown state is JSON-persisted so it survives process restarts.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Individual condition detectors
# Each returns True/False (except trend_state which returns a string).
# All receive a *complete* DataFrame (with indicators) and work on the
# last few rows.
# ---------------------------------------------------------------------------

def detect_breakdown(df: pd.DataFrame) -> bool:
    """
    BREAKDOWN: Latest close crossed below lower Bollinger Band
    AND the previous 3 candles were ALL inside the bands.
    """
    if len(df) < 5:
        return False

    close     = df["close"]
    bb_upper  = df["bb_upper"]
    bb_lower  = df["bb_lower"]

    # Latest candle crossed below lower band
    current_below = close.iloc[-1] < bb_lower.iloc[-1]
    if not current_below:
        return False

    # Previous 3 candles inside bands
    inside_prev_3 = all(
        (bb_lower.iloc[i] <= close.iloc[i] <= bb_upper.iloc[i])
        for i in [-4, -3, -2]
    )
    return inside_prev_3


def detect_breakout(df: pd.DataFrame) -> bool:
    """
    BREAKOUT: Latest close crossed above upper Bollinger Band
    AND the previous 3 candles were ALL inside the bands.
    """
    if len(df) < 5:
        return False

    close    = df["close"]
    bb_upper = df["bb_upper"]
    bb_lower = df["bb_lower"]

    current_above = close.iloc[-1] > bb_upper.iloc[-1]
    if not current_above:
        return False

    inside_prev_3 = all(
        (bb_lower.iloc[i] <= close.iloc[i] <= bb_upper.iloc[i])
        for i in [-4, -3, -2]
    )
    return inside_prev_3


def detect_band_rejection(df: pd.DataFrame) -> list[str]:
    """
    BAND_REJECTION: Returns a list of active rejection types.

    - "BAND_REJECTION_DOWN": Previous candle's high touched/exceeded upper band,
      current candle closed back inside the bands (reversal down signal).
    - "BAND_REJECTION_UP": Previous candle's low touched/exceeded lower band,
      current candle closed back inside the bands (reversal up signal).

    Returns list of matched sub-condition strings (may be empty).
    """
    if len(df) < 3:
        return []

    results = []

    high    = df["high"]
    low     = df["low"]
    close   = df["close"]
    bb_upper = df["bb_upper"]
    bb_lower = df["bb_lower"]

    # Rejection DOWN: prior candle touched upper, current closed back inside
    prev_touched_upper = high.iloc[-2] >= bb_upper.iloc[-2]
    curr_inside_upper  = close.iloc[-1] < bb_upper.iloc[-1]
    if prev_touched_upper and curr_inside_upper:
        results.append("BAND_REJECTION_DOWN")

    # Rejection UP: prior candle touched lower, current closed back inside
    prev_touched_lower = low.iloc[-2] <= bb_lower.iloc[-2]
    curr_inside_lower  = close.iloc[-1] > bb_lower.iloc[-1]
    if prev_touched_lower and curr_inside_lower:
        results.append("BAND_REJECTION_UP")

    return results


def detect_trend_state(df: pd.DataFrame) -> str:
    """
    TREND_STATE: Classify market structure with strict definitions.
    - "uptrend"   if price > EMA20 > EMA50 AND high >= bb_upper
    - "downtrend" if price < EMA20 < EMA50 AND low <= bb_lower
    - "ranging"   otherwise
    """
    if df[["ema20", "ema50", "bb_upper", "bb_lower"]].iloc[-1].isna().any():
        return "ranging"

    price = df["close"].iloc[-1]
    ema20 = df["ema20"].iloc[-1]
    ema50 = df["ema50"].iloc[-1]
    high = df["high"].iloc[-1]
    low = df["low"].iloc[-1]
    bb_upper = df["bb_upper"].iloc[-1]
    bb_lower = df["bb_lower"].iloc[-1]

    if price > ema20 > ema50 and high >= bb_upper:
        return "uptrend"
    if price < ema20 < ema50 and low <= bb_lower:
        return "downtrend"
    return "ranging"


def detect_rsi_extreme(df: pd.DataFrame,
                        overbought: float = 70.0,
                        oversold: float  = 30.0) -> str | None:
    """
    RSI_EXTREME: Returns "RSI_OVERBOUGHT", "RSI_OVERSOLD", or None.
    """
    rsi = df["rsi"].iloc[-1]
    if pd.isna(rsi):
        return None
    if rsi > overbought:
        return "RSI_OVERBOUGHT"
    if rsi < oversold:
        return "RSI_OVERSOLD"
    return None


# ---------------------------------------------------------------------------
# Cooldown manager (JSON-persisted)
# ---------------------------------------------------------------------------

class CooldownManager:
    """
    Tracks last-trigger timestamps per (symbol, timeframe, condition) key.
    State is persisted to a JSON file so cooldowns survive restarts.
    """

    def __init__(self, cooldown_minutes: int, state_file: str = "logs/cooldowns.json"):
        self.cooldown = timedelta(minutes=cooldown_minutes)
        self.state_path = Path(state_file)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, str] = self._load()

    def _load(self) -> dict:
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(f"Could not read cooldown state: {exc}. Starting fresh.")
        return {}

    def _save(self) -> None:
        with open(self.state_path, "w") as f:
            json.dump(self._data, f, indent=2)

    def _key(self, symbol: str, timeframe: str, condition: str) -> str:
        return f"{symbol}|{timeframe}|{condition}"

    def is_on_cooldown(self, symbol: str, timeframe: str, condition: str) -> bool:
        key = self._key(symbol, timeframe, condition)
        if key not in self._data:
            return False
        last_trigger = datetime.fromisoformat(self._data[key])
        return (datetime.now(timezone.utc) - last_trigger) < self.cooldown

    def record_trigger(self, symbol: str, timeframe: str, condition: str) -> None:
        key = self._key(symbol, timeframe, condition)
        self._data[key] = datetime.now(timezone.utc).isoformat()
        self._save()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_all_detectors(df: pd.DataFrame, config: dict) -> list[str]:
    """
    Run all setup detectors against the given DataFrame.
    Returns list of triggered condition strings (e.g. ["BREAKDOWN", "RSI_OVERSOLD"]).
    Empty list means no actionable setup this cycle.
    """
    candidates: list[str] = []

    if detect_breakdown(df):
        candidates.append("BREAKDOWN")

    if detect_breakout(df):
        candidates.append("BREAKOUT")

    for rejection in detect_band_rejection(df):
        candidates.append(rejection)

    rsi_cond = detect_rsi_extreme(
        df,
        overbought=config.get("rsi_overbought", 70.0),
        oversold=config.get("rsi_oversold", 30.0),
    )
    if rsi_cond:
        candidates.append(rsi_cond)

    return candidates
