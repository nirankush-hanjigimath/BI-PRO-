"""
data_engine.py — Stage 1 + 2
Fetches OHLCV candles from Binance Futures public REST API and computes
technical indicators (BB, RSI, EMA 20/50, swing high/low).
No authentication required — uses public market data endpoints only.
"""

import os
import csv
import time
import logging
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

BINANCE_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_klines_raw(symbol: str, interval: str, limit: int = 200,
                      retries: int = 3, backoff_base: float = 2.0) -> list:
    """
    Call Binance Futures klines endpoint with exponential backoff retry.
    Returns list of raw kline arrays or raises after all retries exhausted.
    """
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
            if resp.status_code == 429:
                wait = backoff_base ** attempt
                logger.warning(
                    f"[{symbol}/{interval}] Rate-limited (429). "
                    f"Waiting {wait:.1f}s before retry {attempt}/{retries}."
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            wait = backoff_base ** attempt
            logger.error(
                f"[{symbol}/{interval}] Fetch error (attempt {attempt}/{retries}): "
                f"{exc}. Retrying in {wait:.1f}s."
            )
            if attempt < retries:
                time.sleep(wait)

    raise RuntimeError(
        f"Failed to fetch klines for {symbol}/{interval} after {retries} attempts."
    )


def _parse_klines(raw: list) -> pd.DataFrame:
    """Convert raw Binance kline list to a typed DataFrame."""
    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "num_trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ]
    df = pd.DataFrame(raw, columns=cols)

    # Keep only the columns we care about
    df = df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]

    # Type conversions
    df["open_time"]  = pd.to_datetime(df["open_time"],  unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df.reset_index(drop=True, inplace=True)
    return df


# ---------------------------------------------------------------------------
# Indicator calculation (all manual — no pandas-ta dependency)
# ---------------------------------------------------------------------------

def _calc_bollinger_bands(close: pd.Series, period: int = 20,
                          std_dev: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (upper, middle, lower) Bollinger Band series."""
    middle = close.rolling(window=period).mean()
    std    = close.rolling(window=period).std(ddof=0)
    upper  = middle + std_dev * std
    lower  = middle - std_dev * std
    return upper, middle, lower


def _calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI using exponential moving average of gains/losses."""
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)

    # Use Wilder's smoothing (alpha = 1/period)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def _calc_ema(close: pd.Series, span: int) -> pd.Series:
    """Exponential Moving Average."""
    return close.ewm(span=span, adjust=False).mean()


def _calc_swing_levels(high: pd.Series, low: pd.Series,
                        lookback: int = 50) -> tuple[float, float]:
    """Returns (swing_high, swing_low) over the last `lookback` candles."""
    recent_high = high.iloc[-lookback:].max()
    recent_low  = low.iloc[-lookback:].min()
    return float(recent_high), float(recent_low)


def add_indicators(df: pd.DataFrame, bb_period: int = 20, bb_std: float = 2.0,
                   rsi_period: int = 14, ema_short: int = 20,
                   ema_long: int = 50, swing_lookback: int = 50) -> pd.DataFrame:
    """
    Compute and attach all required indicators to the DataFrame.
    Modifies df in place AND returns it for chaining.
    """
    df = df.copy()
    close = df["close"]

    df["bb_upper"], df["bb_middle"], df["bb_lower"] = _calc_bollinger_bands(
        close, bb_period, bb_std
    )
    df["rsi"]    = _calc_rsi(close, rsi_period)
    df["ema20"]  = _calc_ema(close, ema_short)
    df["ema50"]  = _calc_ema(close, ema_long)

    swing_high, swing_low = _calc_swing_levels(df["high"], df["low"], swing_lookback)
    df["swing_high"] = swing_high
    df["swing_low"]  = swing_low

    return df


# ---------------------------------------------------------------------------
# CSV logging
# ---------------------------------------------------------------------------

def _log_fetch(log_dir: str, symbol: str, timeframe: str,
               latest_close: float) -> None:
    """Append a single row to the market_data CSV log."""
    log_path = Path(log_dir) / "market_data.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    write_header = not log_path.exists()
    with open(log_path, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp_utc", "symbol", "timeframe", "latest_close"])
        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            symbol,
            timeframe,
            latest_close,
        ])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_and_calculate(symbol: str, timeframe: str, config: dict) -> pd.DataFrame:
    """
    Main entry point: fetch Binance candles, compute indicators, log, return DataFrame.

    Args:
        symbol:    e.g. "XLMUSDT"
        timeframe: e.g. "15m", "1h", "4h"
        config:    dict with keys: bb_period, bb_std, rsi_period, ema_short,
                   ema_long, swing_lookback, log_dir

    Returns:
        pd.DataFrame with OHLCV + all indicators. NaN rows (warm-up) preserved.
    """
    logger.info(f"Fetching {symbol} / {timeframe} ...")
    raw = _fetch_klines_raw(symbol, timeframe, limit=200)
    df  = _parse_klines(raw)
    df  = add_indicators(
        df,
        bb_period      = config.get("bb_period", 20),
        bb_std         = config.get("bb_std", 2.0),
        rsi_period     = config.get("rsi_period", 14),
        ema_short      = config.get("ema_short", 20),
        ema_long       = config.get("ema_long", 50),
        swing_lookback = config.get("swing_lookback", 50),
    )

    latest_close = float(df["close"].iloc[-1])
    _log_fetch(config.get("log_dir", "logs"), symbol, timeframe, latest_close)
    logger.info(
        f"  {symbol}/{timeframe} latest close={latest_close:.6g} | "
        f"RSI={df['rsi'].iloc[-1]:.1f} | "
        f"BB({df['bb_lower'].iloc[-1]:.6g} / {df['bb_middle'].iloc[-1]:.6g} / {df['bb_upper'].iloc[-1]:.6g})"
    )
    return df
