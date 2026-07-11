"""
signal_engine/stage00_data_fetcher.py
Data fetching layer: Binance Spot OHLCV + Bybit Futures + volume cache.
Handles stale candle detection, 60s response cache, 3-retry backoff, 451 fallback.
"""

import io
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from signal_engine.config import cfg
from signal_engine.utils.alerts import alert_futures_blocked
from signal_engine.utils.logger import get_logger

_log = get_logger("STAGE00")

_SPOT_BASE  = "https://api.binance.com"
_BYBIT_BASE = "https://api.bybit.com"
CACHE_TTL   = 60  # seconds

# ── In-memory caches ───────────────────────────────────────────────────────
_ohlcv_cache:     Dict[Tuple[str, str], Tuple[pd.DataFrame, float]] = {}
_daily_vol_cache: Dict[str, np.ndarray] = {}
_daily_vol_date:  Optional[date]         = None


# ── Futures snapshot ───────────────────────────────────────────────────────

@dataclass
class FuturesSnapshot:
    symbol:        str
    oi_current:    Optional[float] = None
    oi_prev:       Optional[float] = None
    oi_change_pct: Optional[float] = None
    funding_rate:  Optional[float] = None
    buy_ratio:     Optional[float] = None
    sell_ratio:    Optional[float] = None
    ls_ratio:      Optional[float] = None
    source:        str = "BYBIT"
    blocked:       bool = False
    error:         Optional[str] = None


# ── Retry with exponential backoff ─────────────────────────────────────────

def _retry(fn, symbol: str, context: str = "", delays=(2, 4, 8)):
    """Call fn() up to 3 times with exponential backoff. Returns None on final failure."""
    slog = get_logger("STAGE00", symbol)
    for attempt, delay in enumerate(delays, 1):
        try:
            return fn()
        except Exception as exc:
            if attempt < len(delays):
                slog.warning(f"{context} attempt {attempt} failed: {exc} — retry in {delay}s")
                time.sleep(delay)
            else:
                slog.error(f"{context} failed after {len(delays)} attempts: {exc}")
    return None


# ── OHLCV raw fetch ────────────────────────────────────────────────────────

def _fetch_ohlcv_raw(symbol: str, timeframe: str, limit: int = 300) -> Optional[pd.DataFrame]:
    slog   = get_logger("STAGE00", symbol)
    url    = f"{_SPOT_BASE}/api/v3/klines"
    params = {"symbol": symbol, "interval": timeframe, "limit": limit}

    def do_fetch():
        t0   = time.time()
        resp = requests.get(url, params=params, timeout=10)

        if resp.status_code == 451:
            alert_futures_blocked(symbol)
            raise RuntimeError(f"Binance Spot 451 on {symbol}/{timeframe} — unexpected geo-block")

        resp.raise_for_status()

        cols = ["open_time", "open", "high", "low", "close", "volume",
                "close_time", "qvol", "trades", "tbv", "tbq", "ignore"]
        df = pd.DataFrame(resp.json(), columns=cols)

        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)

        df["close_time_ms"] = df["close_time"].astype(np.int64)
        df["close_time"]    = pd.to_datetime(df["close_time_ms"], unit="ms", utc=True)
        df["open_time"]     = pd.to_datetime(df["open_time"].astype(np.int64), unit="ms", utc=True)
        df = df.set_index("open_time")
        df = df[["open", "high", "low", "close", "volume", "close_time", "close_time_ms"]]

        elapsed = (time.time() - t0) * 1000
        slog.info(f"{timeframe} — {len(df)} candles fetched in {elapsed:.0f}ms")
        return df

    return _retry(do_fetch, symbol, f"{symbol}/{timeframe} OHLCV")


# ── Stale candle check (Issue 1) ───────────────────────────────────────────

def _check_candle_status(df: pd.DataFrame) -> Tuple[str, int]:
    """
    Returns (candle_status, signal_idx).
    signal_idx = -2 if last candle is still FORMING, -1 if CLOSED.
    """
    now_ms        = time.time() * 1000.0
    last_close_ms = float(df["close_time_ms"].iloc[-1])

    if last_close_ms > now_ms:
        return ("FORMING", -2)
    return ("CLOSED", -1)


# ── OHLCV public fetch (cache + stale check) ──────────────────────────────

def fetch_ohlcv(symbol: str, timeframe: str, limit: int = 300) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV with 60s in-memory cache.
    Attaches df.attrs['candle_status'] and df.attrs['signal_idx'].
    """
    slog      = get_logger("STAGE00", symbol)
    cache_key = (symbol, timeframe)
    cached    = _ohlcv_cache.get(cache_key)

    if cached is not None:
        df, ts = cached
        if time.time() - ts < CACHE_TTL:
            slog.debug(f"{timeframe} — cache hit ({CACHE_TTL - (time.time()-ts):.0f}s remaining)")
            return df

    df = _fetch_ohlcv_raw(symbol, timeframe, limit)
    if df is None:
        return None

    status, sig_idx = _check_candle_status(df)
    df.attrs["candle_status"] = status
    df.attrs["signal_idx"]    = sig_idx

    if status == "FORMING":
        slog.warning(
            f"{timeframe} — last candle FORMING "
            f"(closes {df['close_time'].iloc[-1].strftime('%H:%M:%S UTC')}) "
            f"→ signal candle = candle[-2]"
        )
    else:
        slog.info(f"{timeframe} — candle CLOSED → signal candle = candle[-1]")

    _ohlcv_cache[cache_key] = (df, time.time())
    return df


# ── 30-day daily volume cache (Issue 2) ────────────────────────────────────

def _refresh_daily_volume_cache(symbols: list = None) -> None:
    """Fetch 30d of 1d candles per symbol. Runs at most once per UTC day."""
    global _daily_vol_date
    today = datetime.now(timezone.utc).date()
    if _daily_vol_date == today:
        return

    targets = symbols or cfg.symbols
    slog    = get_logger("STAGE00", "VOLCACHE")
    slog.info(f"Refreshing 30-day daily volume cache for {len(targets)} symbols")

    for sym in targets:
        def do_fetch(s=sym):
            r = requests.get(
                f"{_SPOT_BASE}/api/v3/klines",
                params={"symbol": s, "interval": "1d", "limit": 31},
                timeout=10,
            )
            r.raise_for_status()
            # index 7 = quote asset volume (USD) — NOT index 5 (base asset, e.g. BTC units)
            return np.array([float(row[7]) for row in r.json()])

        vols = _retry(do_fetch, sym, f"{sym} 30d volume")
        if vols is not None and len(vols) > 0:
            _daily_vol_cache[sym] = vols
            p40 = float(np.percentile(vols, 40))
            slog.info(f"{sym} — {len(vols)} days cached, P40 = ${p40:,.0f}")
        else:
            slog.error(f"{sym} — daily volume cache refresh failed")

    _daily_vol_date = today


def get_volume_p40(symbol: str) -> Optional[float]:
    """40th percentile of the symbol's 30-day daily volume. None if cache empty."""
    vols = _daily_vol_cache.get(symbol)
    if vols is None or len(vols) == 0:
        return None
    return float(np.percentile(vols, 40))

def get_volume_p20(symbol: str) -> Optional[float]:
    """20th percentile of the symbol's 30-day daily volume. None if cache empty."""
    vols = _daily_vol_cache.get(symbol)
    if vols is None or len(vols) == 0:
        return None
    return float(np.percentile(vols, 20))


# ── Bybit futures ──────────────────────────────────────────────────────────

def fetch_bybit_futures(symbol: str) -> FuturesSnapshot:
    """
    Fetch OI, funding rate, and L/S ratio from Bybit public endpoints.
    Any individual field failure → field stays None, engine continues.
    """
    slog = get_logger("STAGE00", symbol)
    snap = FuturesSnapshot(symbol=symbol)
    sess = requests.Session()

    # Open Interest
    try:
        r = sess.get(
            f"{_BYBIT_BASE}/v5/market/open-interest",
            params={"category": "linear", "symbol": symbol,
                    "intervalTime": "1h", "limit": 2},
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("retCode") != 0:
            raise ValueError(data.get("retMsg", "Bybit OI error"))
        items = data["result"]["list"]
        if len(items) >= 2:
            snap.oi_current = float(items[0]["openInterest"])
            snap.oi_prev    = float(items[1]["openInterest"])
            if snap.oi_prev:
                snap.oi_change_pct = (snap.oi_current - snap.oi_prev) / snap.oi_prev * 100
        slog.info(f"OI={snap.oi_current:,.0f}  change={snap.oi_change_pct:+.2f}%"
                  if snap.oi_current else "OI=None")
    except Exception as exc:
        slog.warning(f"Bybit OI failed: {exc}")

    # Funding Rate
    try:
        r = sess.get(
            f"{_BYBIT_BASE}/v5/market/funding/history",
            params={"category": "linear", "symbol": symbol, "limit": 1},
            timeout=8,
        )
        r.raise_for_status()
        data  = r.json()
        if data.get("retCode") != 0:
            raise ValueError(data.get("retMsg", "Bybit funding error"))
        items = data["result"]["list"]
        if items:
            snap.funding_rate = float(items[0]["fundingRate"])
        slog.info(f"Funding={snap.funding_rate:+.4%}" if snap.funding_rate is not None else "Funding=None")
    except Exception as exc:
        slog.warning(f"Bybit funding failed: {exc}")

    # Long/Short Ratio
    try:
        r = sess.get(
            f"{_BYBIT_BASE}/v5/market/account-ratio",
            params={"category": "linear", "symbol": symbol,
                    "period": "1h", "limit": 1},
            timeout=8,
        )
        r.raise_for_status()
        data  = r.json()
        if data.get("retCode") != 0:
            raise ValueError(data.get("retMsg", "Bybit L/S error"))
        items = data["result"]["list"]
        if items:
            snap.buy_ratio  = float(items[0]["buyRatio"])
            snap.sell_ratio = float(items[0]["sellRatio"])
            if snap.sell_ratio:
                snap.ls_ratio = snap.buy_ratio / snap.sell_ratio
        slog.info(
            f"L/S  long={snap.buy_ratio:.1%}  short={snap.sell_ratio:.1%}"
            if snap.buy_ratio else "L/S=None"
        )
    except Exception as exc:
        slog.warning(f"Bybit L/S failed: {exc}")

    return snap


# ── Main orchestrator ──────────────────────────────────────────────────────

def fetch_all(
    symbols:    list = None,
    timeframes: list = None,
) -> Dict[Tuple[str, str], pd.DataFrame]:
    """
    Fetch OHLCV for all symbol+timeframe combinations.
    Refreshes daily volume cache if stale (once per UTC day).
    Returns dict keyed by (symbol, timeframe).
    """
    syms = symbols    or cfg.symbols
    tfs  = timeframes or cfg.timeframes

    _refresh_daily_volume_cache(syms)

    result: Dict[Tuple[str, str], pd.DataFrame] = {}
    for sym in syms:
        for tf in tfs:
            df = fetch_ohlcv(sym, tf)
            if df is not None:
                result[(sym, tf)] = df
            else:
                get_logger("STAGE00", sym).error(f"{tf} returned None — skipped this cycle")

    _log.info(f"fetch_all complete: {len(result)}/{len(syms)*len(tfs)} datasets ready")
    return result


# ── Standalone test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    SEP = "=" * 70
    print(SEP)
    print("stage00_data_fetcher.py -- Standalone Test")
    print(SEP)

    # 1. Fetch all OHLCV
    print("\n[1/3] Fetching OHLCV — 4 symbols x 3 timeframes (12 requests)...\n")
    data = fetch_all()

    print(f"\n{'Symbol':<10} {'TF':<5} {'Candles':<9} {'Close':>12} {'Status':<10} Close Time (UTC)")
    print("-" * 70)
    for (sym, tf), df in sorted(data.items()):
        sig_idx = df.attrs.get("signal_idx", -1)
        status  = df.attrs.get("candle_status", "UNKNOWN")
        row     = df.iloc[sig_idx]
        ct      = row["close_time"].strftime("%Y-%m-%d %H:%M")
        print(f"{sym:<10} {tf:<5} {len(df):<9} ${row['close']:>11,.4f} {status:<10} {ct}")

    # 2. Bybit futures
    print(f"\n[2/3] Bybit futures data for BTCUSDT and SOLUSDT...\n")
    for sym in ["BTCUSDT", "SOLUSDT"]:
        snap = fetch_bybit_futures(sym)
        print(f"  {sym}:")
        print(f"    OI current    : {snap.oi_current:>16,.2f}" if snap.oi_current else "    OI current    : None")
        print(f"    OI change     : {snap.oi_change_pct:>+15.3f}%" if snap.oi_change_pct is not None else "    OI change     : None")
        print(f"    Funding rate  : {snap.funding_rate:>+15.4%}" if snap.funding_rate is not None else "    Funding rate  : None")
        print(f"    Long ratio    : {snap.buy_ratio:>15.2%}" if snap.buy_ratio else "    Long ratio    : None")
        print(f"    Short ratio   : {snap.sell_ratio:>15.2%}" if snap.sell_ratio else "    Short ratio   : None")
        print()

    # 3. P40 thresholds
    print(f"[3/3] P40 daily volume thresholds (30-day history):\n")
    for sym in cfg.symbols:
        p40 = get_volume_p40(sym)
        if p40:
            print(f"  {sym:<10}  P40 = ${p40:>18,.0f}")
        else:
            print(f"  {sym:<10}  P40 = N/A")

    print(f"\n{SEP}")
    print("[OK] Stage 00 test complete.")
    print(SEP)
