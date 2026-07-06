"""
signal_engine/utils/indicators.py
All technical indicators — built from scratch using numpy/pandas only.
No pandas-ta. No TA-Lib. Input: DataFrame with open/high/low/close/volume columns.
No function mutates the input DataFrame.
"""

from typing import NamedTuple
import numpy as np
import pandas as pd


# ── Named return types ─────────────────────────────────────────────────────

class BBResult(NamedTuple):
    upper:     pd.Series
    middle:    pd.Series
    lower:     pd.Series
    bandwidth: pd.Series   # (upper-lower)/middle * 100
    pct_b:     pd.Series   # (close-lower)/(upper-lower)

class ADXResult(NamedTuple):
    adx:      pd.Series
    plus_di:  pd.Series
    minus_di: pd.Series


# ── Internal: Wilder's EWM (alpha = 1/period) ─────────────────────────────

def _wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing = EWM with alpha=1/period, adjust=False."""
    return series.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


# ── EMA ───────────────────────────────────────────────────────────────────

def ema(df: pd.DataFrame, period: int, column: str = "close") -> pd.Series:
    """Standard EMA using pandas ewm (alpha=2/(period+1))."""
    return df[column].ewm(span=period, adjust=False).mean()


# ── EMA Slope (linear regression) ─────────────────────────────────────────

def ema_slope(ema_series: pd.Series, lookback: int = 10) -> pd.Series:
    """
    Rolling linear-regression slope of an EMA series.
    Returns slope per candle (price units). Positive = rising, Negative = falling.
    Normalised slope (%/candle) = slope / price * 100  (done in stage06).
    """
    result = pd.Series(np.nan, index=ema_series.index, dtype=float)
    arr = ema_series.values.astype(float)
    x   = np.arange(lookback, dtype=float)

    for i in range(lookback - 1, len(arr)):
        window = arr[i - lookback + 1 : i + 1]
        if np.any(np.isnan(window)):
            continue
        slope = np.polyfit(x, window, 1)[0]
        result.iat[i] = slope

    return result


# ── RSI (Wilder smoothing) ─────────────────────────────────────────────────

def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI using Wilder's smoothing (EWM alpha=1/period)."""
    delta    = df["close"].diff()
    gain     = delta.clip(lower=0.0)
    loss     = (-delta).clip(lower=0.0)
    avg_gain = _wilder(gain, period)
    avg_loss = _wilder(loss, period)
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    rsi_s    = 100.0 - (100.0 / (1.0 + rs))
    rsi_s[avg_loss == 0] = 100.0
    return rsi_s


# ── ATR (Wilder smoothing) ─────────────────────────────────────────────────

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR using Wilder's smoothing."""
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return _wilder(tr, period)


# ── Bollinger Bands ────────────────────────────────────────────────────────

def bollinger_bands(df: pd.DataFrame, period: int = 20, std_mult: float = 2.0) -> BBResult:
    """Bollinger Bands with bandwidth and %B."""
    close  = df["close"]
    mid    = close.rolling(period).mean()
    std    = close.rolling(period).std(ddof=1)
    upper  = mid + std_mult * std
    lower  = mid - std_mult * std
    bw     = (upper - lower) / mid.replace(0, np.nan) * 100.0
    pct_b  = (close - lower) / (upper - lower).replace(0, np.nan)
    return BBResult(upper=upper, middle=mid, lower=lower, bandwidth=bw, pct_b=pct_b)


# ── ADX (+DI / -DI) ───────────────────────────────────────────────────────

def adx(df: pd.DataFrame, period: int = 14) -> ADXResult:
    """Full ADX with +DI and -DI using Wilder smoothing."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)

    # True Range
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Directional movement
    up   = high - prev_high
    down = prev_low - low

    plus_dm  = pd.Series(np.where((up > down) & (up > 0),   up,   0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)

    # Wilder sums: mean * period
    atr_sum      = _wilder(tr,       period) * period
    plus_dm_sum  = _wilder(plus_dm,  period) * period
    minus_dm_sum = _wilder(minus_dm, period) * period

    plus_di  = 100.0 * plus_dm_sum  / atr_sum.replace(0, np.nan)
    minus_di = 100.0 * minus_dm_sum / atr_sum.replace(0, np.nan)

    dx_denom = (plus_di + minus_di).replace(0, np.nan)
    dx       = 100.0 * (plus_di - minus_di).abs() / dx_denom
    adx_s    = _wilder(dx.fillna(0.0), period)

    return ADXResult(adx=adx_s, plus_di=plus_di, minus_di=minus_di)


# ── Choppiness Index ───────────────────────────────────────────────────────

def choppiness_index(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Choppiness Index = 100 * LOG10(SUM(ATR1, n) / (HH(n) - LL(n))) / LOG10(n)
    < 38.2 → strong trend | > 61.8 → choppy/ranging
    """
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)

    tr_sum  = tr.rolling(period).sum()
    hh      = df["high"].rolling(period).max()
    ll      = df["low"].rolling(period).min()
    denom   = (hh - ll).replace(0, np.nan)

    return 100.0 * np.log10(tr_sum / denom) / np.log10(period)


# ── Volume Z-Score ─────────────────────────────────────────────────────────

def volume_zscore(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """(current_volume - rolling_mean) / rolling_std"""
    vol  = df["volume"]
    mean = vol.rolling(period).mean()
    std  = vol.rolling(period).std(ddof=1).replace(0, np.nan)
    return (vol - mean) / std


# ── Realized Volatility (annualized %) ────────────────────────────────────

def realized_volatility(
    df: pd.DataFrame,
    days: int = 7,
    candle_interval_minutes: int = 60,
) -> float:
    """
    Annualized realized volatility over `days` days.
    candle_interval_minutes: 15, 60, or 240 depending on timeframe.
    Returns a float (percentage, e.g. 82.3 means 82.3% annualized).
    Returns np.nan if insufficient data.
    """
    candles_per_day  = 1440 // candle_interval_minutes
    lookback         = days * candles_per_day
    candles_per_year = candles_per_day * 365

    log_ret = np.log(df["close"] / df["close"].shift(1)).dropna()
    if len(log_ret) < lookback:
        return np.nan

    recent = log_ret.iloc[-lookback:]
    return float(recent.std(ddof=1) * np.sqrt(candles_per_year) * 100.0)


# ── BBWidth percentile (for regime detection) ──────────────────────────────

def bbwidth_percentile(bw_series: pd.Series, lookback_candles: int = 720) -> float:
    """
    Returns the percentile (0-100) of the current BBWidth value
    relative to its own history over `lookback_candles` candles.
    """
    valid = bw_series.dropna()
    if len(valid) < 2:
        return 50.0
    history = valid.iloc[-lookback_candles:] if len(valid) >= lookback_candles else valid
    current = float(valid.iloc[-1])
    return float((history < current).mean() * 100.0)


# ── Standalone test block ──────────────────────────────────────────────────

if __name__ == "__main__":
    import io, sys
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    import requests

    print("=" * 70)
    print("indicators.py -- Standalone Test (BTCUSDT 4h, last 300 candles)")
    print("=" * 70)

    resp = requests.get(
        "https://api.binance.com/api/v3/klines",
        params={"symbol": "BTCUSDT", "interval": "4h", "limit": 300},
        timeout=10,
    )
    resp.raise_for_status()
    cols = ["open_time","open","high","low","close","volume",
            "close_time","quote_vol","trades","tbv","tbq","ignore"]
    df = pd.DataFrame(resp.json(), columns=cols)
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.set_index("open_time", inplace=True)

    N = 5   # print last N values

    # EMA
    ema50  = ema(df, 50)
    ema200 = ema(df, 200)
    print(f"\nEMA50  (last {N}):\n{ema50.tail(N).round(2).to_string()}")
    print(f"\nEMA200 (last {N}):\n{ema200.tail(N).round(2).to_string()}")

    # EMA slope
    slope50 = ema_slope(ema50, lookback=10)
    print(f"\nEMA50 Slope (last {N}):\n{slope50.tail(N).round(4).to_string()}")

    # RSI
    rsi14 = rsi(df, 14)
    print(f"\nRSI(14) (last {N}):\n{rsi14.tail(N).round(2).to_string()}")

    # ATR
    atr14 = atr(df, 14)
    print(f"\nATR(14) (last {N}):\n{atr14.tail(N).round(4).to_string()}")

    # Bollinger Bands
    bb = bollinger_bands(df, 20, 2.0)
    print(f"\nBB Upper (last {N}):\n{bb.upper.tail(N).round(2).to_string()}")
    print(f"BB Mid   (last {N}):\n{bb.middle.tail(N).round(2).to_string()}")
    print(f"BB Lower (last {N}):\n{bb.lower.tail(N).round(2).to_string()}")
    print(f"BBWidth  (last {N}):\n{bb.bandwidth.tail(N).round(4).to_string()}")
    print(f"BB %B    (last {N}):\n{bb.pct_b.tail(N).round(4).to_string()}")

    # ADX
    adx_res = adx(df, 14)
    print(f"\nADX(14)   (last {N}):\n{adx_res.adx.tail(N).round(2).to_string()}")
    print(f"+DI(14)   (last {N}):\n{adx_res.plus_di.tail(N).round(2).to_string()}")
    print(f"-DI(14)   (last {N}):\n{adx_res.minus_di.tail(N).round(2).to_string()}")

    # Choppiness Index
    ci = choppiness_index(df, 14)
    print(f"\nChoppiness(14) (last {N}):\n{ci.tail(N).round(2).to_string()}")

    # Volume Z-Score
    vz = volume_zscore(df, 20)
    print(f"\nVolume Z-Score (last {N}):\n{vz.tail(N).round(3).to_string()}")

    # Realized Volatility
    rv7  = realized_volatility(df, days=7,  candle_interval_minutes=240)
    rv30 = realized_volatility(df, days=30, candle_interval_minutes=240)
    print(f"\nRealized Vol  7d: {rv7:.2f}%  annualized")
    print(f"Realized Vol 30d: {rv30:.2f}%  annualized")

    # BBWidth percentile
    bwp = bbwidth_percentile(bb.bandwidth, lookback_candles=180)
    print(f"BBWidth Percentile (vs 180 candles): {bwp:.1f}th")

    print("\n" + "=" * 70)
    print("[OK] All indicators computed. Check for NaN-free tail values.")
    print("=" * 70)
