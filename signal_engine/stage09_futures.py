"""
signal_engine/stage09_futures.py
Fetches derivatives data from Bybit public API for open interest, funding, and long/short ratio.
"""

import io
import sys
from dataclasses import dataclass, field
from typing import List, Optional

import requests
import pandas as pd

from signal_engine.models import FuturesData
from signal_engine.utils.logger import get_logger


@dataclass
class FuturesResult:
    symbol:            str
    oi_current:        Optional[float]
    oi_previous:       Optional[float]
    oi_change_pct:     Optional[float]
    oi_signal:         Optional[str]
    funding_rate:      Optional[float]
    funding_signal:    Optional[str]
    long_ratio:        Optional[float]
    short_ratio:       Optional[float]
    ls_signal:         Optional[str]
    combined_modifier: int
    tags:              List[str] = field(default_factory=list)
    blocked:           bool = False

    def to_futures_data(self) -> FuturesData:
        return FuturesData(
            blocked                     = self.blocked,
            oi_change_pct               = self.oi_change_pct,
            funding_rate                = self.funding_rate,
            ls_ratio                    = self.long_ratio,  # using long ratio as proxy if needed
            oi_signal                   = self.oi_signal,
            funding_signal              = self.funding_signal,
            ls_signal                   = self.ls_signal,
            # For backward compatibility with models.py, map combined modifier
            oi_confidence_modifier      = self.combined_modifier,
            funding_confidence_modifier = 0,
        )


def _fetch_bybit(endpoint: str, params: dict, slog) -> Optional[dict]:
    try:
        url = f"https://api.bybit.com/v5/market/{endpoint}"
        r = requests.get(url, params=params, timeout=5.0)
        r.raise_for_status()
        data = r.json()
        if data.get("retCode") == 0:
            return data.get("result")
    except Exception as e:
        slog.warning(f"Bybit API error on {endpoint}: {e}")
    return None


def analyze_futures(
    symbol: str,
    price_up: bool,
    signal_direction: str = "LONG",
) -> FuturesResult:
    """
    Fetch and analyze futures data.
    """
    slog = get_logger("STAGE09", symbol)
    slog.info(f"Running futures analysis (Price Up={price_up}, Signal={signal_direction})...")
    
    # ── Fetch Data ─────────────────────────────────────────────────────────
    # Bybit symbols are mostly same as Binance, e.g. BTCUSDT, ETHUSDT
    oi_data = _fetch_bybit("open-interest", {"category": "linear", "symbol": symbol, "intervalTime": "1h", "limit": 3}, slog)
    fund_data = _fetch_bybit("funding/history", {"category": "linear", "symbol": symbol, "limit": 1}, slog)
    ls_data = _fetch_bybit("account-ratio", {"category": "linear", "symbol": symbol, "period": "1h", "limit": 1}, slog)
    
    blocked = (oi_data is None and fund_data is None and ls_data is None)
    if blocked:
        slog.warning("All Bybit endpoints failed. Futures data blocked.")
        return FuturesResult(symbol=symbol, oi_current=None, oi_previous=None, oi_change_pct=None, oi_signal=None, 
                             funding_rate=None, funding_signal=None, long_ratio=None, short_ratio=None, ls_signal=None, 
                             combined_modifier=0, blocked=True)

    tags = []
    mod_oi = 0
    mod_fund = 0
    mod_ls = 0
    
    # ── Open Interest ──────────────────────────────────────────────────────
    oi_current = None
    oi_previous = None
    oi_change_pct = None
    oi_signal = None
    
    if oi_data and "list" in oi_data and len(oi_data["list"]) >= 2:
        try:
            # Bybit returns newest first
            oi_current = float(oi_data["list"][0]["openInterest"])
            oi_previous = float(oi_data["list"][1]["openInterest"])
            oi_change_pct = ((oi_current - oi_previous) / oi_previous) * 100.0
            
            oi_up = oi_change_pct > 0
            
            if price_up and oi_up:
                oi_signal = "REAL_DEMAND"
                if signal_direction == "LONG":
                    mod_oi += 8
            elif price_up and not oi_up:
                oi_signal = "SHORT_COVER"
                tags.append("SHORT_COVERING")
                if signal_direction == "LONG":
                    mod_oi -= 5
            elif not price_up and oi_up:
                oi_signal = "REAL_SELLING"
                if signal_direction == "SHORT":
                    mod_oi += 8
                elif signal_direction == "LONG":
                    mod_oi -= 8
            elif not price_up and not oi_up:
                oi_signal = "LONG_FLUSH"
                tags.append("LONG_FLUSH")
                
            slog.info(f"OI Change: {oi_change_pct:+.2f}% → {oi_signal} (Mod: {mod_oi:+d})")
        except Exception as e:
            slog.warning(f"Failed to parse OI: {e}")

    # ── Funding Rate ───────────────────────────────────────────────────────
    funding_rate = None
    funding_signal = None
    
    if fund_data and "list" in fund_data and len(fund_data["list"]) >= 1:
        try:
            funding_rate = float(fund_data["list"][0]["fundingRate"]) * 100.0  # as percentage
            
            if funding_rate > 0.1:
                funding_signal = "LONGS_PAYING"
                if signal_direction == "LONG":
                    mod_fund -= 8
                    tags.append("LONG_SQUEEZE_RISK")
            elif funding_rate > 0.05:
                funding_signal = "ELEVATED"
                if signal_direction == "LONG":
                    mod_fund -= 4
            elif funding_rate < -0.05:
                funding_signal = "SHORTS_PAYING"
                if signal_direction == "SHORT":
                    mod_fund -= 8
                    tags.append("SHORT_SQUEEZE_RISK")
            else:
                funding_signal = "NEUTRAL"
                
            slog.info(f"Funding: {funding_rate:+.4f}% → {funding_signal} (Mod: {mod_fund:+d})")
        except Exception as e:
            slog.warning(f"Failed to parse Funding: {e}")

    # ── Long/Short Ratio ───────────────────────────────────────────────────
    long_ratio = None
    short_ratio = None
    ls_signal = None
    
    if ls_data and "list" in ls_data and len(ls_data["list"]) >= 1:
        try:
            # Bybit 'buyRatio' and 'sellRatio'
            long_ratio = float(ls_data["list"][0]["buyRatio"]) * 100.0
            short_ratio = float(ls_data["list"][0]["sellRatio"]) * 100.0
            
            if long_ratio > 70.0:
                ls_signal = "CROWDED_LONG"
                if signal_direction == "LONG":
                    mod_ls -= 8
                    tags.append("CROWDED_TRADE")
            elif short_ratio > 70.0:
                ls_signal = "CROWDED_SHORT"
                if signal_direction == "SHORT":
                    mod_ls -= 8
                    tags.append("CROWDED_TRADE")
            else:
                ls_signal = "BALANCED"
                
            slog.info(f"L/S Ratio: L {long_ratio:.1f}% / S {short_ratio:.1f}% → {ls_signal} (Mod: {mod_ls:+d})")
        except Exception as e:
            slog.warning(f"Failed to parse L/S Ratio: {e}")

    # ── Combined Modifier ──────────────────────────────────────────────────
    combined = mod_oi + mod_fund + mod_ls
    combined = max(-20, min(8, combined))
    
    return FuturesResult(
        symbol            = symbol,
        oi_current        = oi_current,
        oi_previous       = oi_previous,
        oi_change_pct     = oi_change_pct,
        oi_signal         = oi_signal,
        funding_rate      = funding_rate,
        funding_signal    = funding_signal,
        long_ratio        = long_ratio,
        short_ratio       = short_ratio,
        ls_signal         = ls_signal,
        combined_modifier = combined,
        tags              = tags,
        blocked           = False,
    )


# ── Standalone test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    SEP = "=" * 70
    print(SEP)
    print("stage09_futures.py -- Standalone Test (Assume LONG, Price UP)")
    print(SEP)
    
    test_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XLMUSDT"]
    results = []
    
    for sym in test_symbols:
        results.append(analyze_futures(sym, price_up=True, signal_direction="LONG"))
        
    print(f"\n{SEP}")
    print(f"{'Symbol':<10} {'OI Change':>10} {'OI Signal':<15} {'Funding':>10} {'Fund Sig':<15} {'L/S %':>10} {'L/S Sig':<15}")
    print("-" * 90)
    
    def _f(val, fmt="{:+.4f}%"):
        return fmt.format(val) if val is not None else "N/A"
        
    for r in results:
        oi_ch = _f(r.oi_change_pct, "{:+.2f}%")
        fund  = _f(r.funding_rate, "{:+.4f}%")
        ls    = f"{r.long_ratio:.1f}/{r.short_ratio:.1f}" if r.long_ratio else "N/A"
        
        print(
            f"{r.symbol:<10} {oi_ch:>10} {str(r.oi_signal):<15} {fund:>10} {str(r.funding_signal):<15} "
            f"{ls:>10} {str(r.ls_signal):<15}"
        )
        
    print(f"\n{SEP}")
    print(f"{'Symbol':<10} {'Mod':>4} {'Tags'}")
    print("-" * 90)
    for r in results:
        t = ",".join(r.tags) if r.tags else "NONE"
        print(f"{r.symbol:<10} {r.combined_modifier:>+4d} {t}")

    print(f"\n{SEP}")
    print("[OK] Stage 09 futures test complete.")
    print(SEP)
