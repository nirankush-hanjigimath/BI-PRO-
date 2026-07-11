"""
signal_engine/stage01_liquidity_gate.py
First hard gate — symbols that fail here are skipped entirely downstream.

Two checks (both must pass):
  1. Volume gate  : current 24h USD volume >= P40 of own 30-day history
  2. Spread gate  : best_ask-best_bid / best_ask < 0.15%
"""

import io
import sys
from dataclasses import dataclass
from typing import Optional

import requests

from signal_engine.config import cfg
from signal_engine.stage00_data_fetcher import get_volume_p40, get_volume_p20, _refresh_daily_volume_cache
from signal_engine.utils.logger import get_logger

_SPOT_BASE = "https://api.binance.com"


# ── Result dataclass ───────────────────────────────────────────────────────

@dataclass
class LiquidityResult:
    symbol:              str
    volume_pass:         bool
    spread_pass:         bool
    overall_pass:        bool
    current_volume_usd:  Optional[float]  # 24h quote volume in USD
    p40_threshold_usd:   Optional[float]  # P40 of 30-day daily volume
    current_spread_pct:  Optional[float]  # bid/ask spread %
    liquidity_tier:      str              # "P40", "P20_ONLY", or "FAILED"
    reject_reason:       Optional[str]    # None if passed


# ── Volume gate ────────────────────────────────────────────────────────────

def _check_volume(symbol: str) -> tuple:
    """
    Returns (pass: bool, current_vol: float|None, p40: float|None, tier: str, reason: str|None)
    """
    slog = get_logger("STAGE01", symbol)

    p40 = get_volume_p40(symbol)
    p20 = get_volume_p20(symbol)
    if p40 is None or p20 is None:
        slog.warning("P40/P20 threshold unavailable — volume gate SKIPPED (treating as PASS)")
        return (True, None, None, "P40", None)

    try:
        resp = requests.get(
            f"{_SPOT_BASE}/api/v3/ticker/24hr",
            params={"symbol": symbol},
            timeout=8,
        )
        resp.raise_for_status()
        data       = resp.json()
        current_vol = float(data["quoteVolume"])   # already in USD

    except Exception as exc:
        slog.error(f"24h ticker fetch failed: {exc} — volume gate API_ERROR")
        return (False, None, p40, "FAILED", f"API_ERROR — 24h ticker: {exc}")

    if current_vol >= p40:
        tier = "P40"
        passed = True
        slog.info(f"Volume PASS  ${current_vol/1e6:,.1f}M >= P40 ${p40/1e6:,.1f}M")
        reason = None
    elif current_vol >= p20:
        tier = "P20_ONLY"
        passed = True
        slog.info(f"Volume P20_ONLY  ${current_vol/1e6:,.1f}M >= P20 ${p20/1e6:,.1f}M (but < P40)")
        reason = None
    else:
        tier = "FAILED"
        passed = False
        reason = (
            f"LIQUIDITY_GATE_VOLUME — current 24h volume "
            f"${current_vol/1e6:,.1f}M below P20 threshold ${p20/1e6:,.1f}M"
        )
        slog.warning(f"Volume FAIL  {reason}")

    return (passed, current_vol, p40, tier, reason)


# ── Spread gate ────────────────────────────────────────────────────────────

def _check_spread(symbol: str) -> tuple:
    """
    Returns (pass: bool, spread_pct: float|None, reason: str|None)
    """
    slog      = get_logger("STAGE01", symbol)
    threshold = cfg.spread_threshold_pct  # 0.15

    try:
        resp = requests.get(
            f"{_SPOT_BASE}/api/v3/depth",
            params={"symbol": symbol, "limit": 5},
            timeout=8,
        )
        resp.raise_for_status()
        book     = resp.json()
        best_bid = float(book["bids"][0][0])
        best_ask = float(book["asks"][0][0])

    except Exception as exc:
        slog.error(f"Orderbook fetch failed: {exc} — spread gate API_ERROR")
        return (False, None, f"API_ERROR — orderbook: {exc}")

    if best_ask == 0:
        return (False, None, "API_ERROR — best_ask is zero")

    spread_pct = (best_ask - best_bid) / best_ask * 100.0
    passed     = spread_pct < threshold

    if passed:
        slog.info(f"Spread PASS  {spread_pct:.4f}% < {threshold}%  "
                  f"(bid={best_bid:.6g}  ask={best_ask:.6g})")
    else:
        reason = (
            f"LIQUIDITY_GATE_SPREAD — spread {spread_pct:.4f}% "
            f"exceeds {threshold}% threshold"
        )
        slog.warning(f"Spread FAIL  {reason}")

    return (passed, spread_pct, None if passed else reason)


# ── Public gate function ───────────────────────────────────────────────────

def check_liquidity(symbol: str) -> LiquidityResult:
    """
    Run volume + spread gate for a single symbol.
    Returns LiquidityResult. overall_pass=True only if BOTH gates pass.
    Never raises — API errors produce overall_pass=False.
    """
    slog = get_logger("STAGE01", symbol)
    slog.info("Running liquidity gate...")

    vol_pass, current_vol, p40, tier, vol_reason = _check_volume(symbol)
    sprd_pass, spread_pct,  sprd_reason             = _check_spread(symbol)

    overall = vol_pass and sprd_pass
    reason  = vol_reason or sprd_reason   # first failure wins

    if overall:
        slog.info(f"Liquidity gate PASSED ({tier}) — symbol cleared for analysis")
    else:
        slog.warning(f"Liquidity gate REJECTED — {reason}")

    return LiquidityResult(
        symbol             = symbol,
        volume_pass        = vol_pass,
        spread_pass        = sprd_pass,
        overall_pass       = overall,
        current_volume_usd = current_vol,
        p40_threshold_usd  = p40,
        current_spread_pct = spread_pct,
        liquidity_tier     = tier if overall else "FAILED",
        reject_reason      = reason,
    )


def run_liquidity_gate(symbols: list = None) -> dict:
    """
    Run liquidity gate on all symbols. Returns {symbol: LiquidityResult}.
    """
    targets = symbols or cfg.symbols
    return {sym: check_liquidity(sym) for sym in targets}


# ── Standalone test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    SEP = "=" * 70
    print(SEP)
    print("stage01_liquidity_gate.py -- Standalone Test")
    print(SEP)

    # Ensure volume cache is populated before running the gate
    print("\nRefreshing 30-day volume cache...")
    _refresh_daily_volume_cache(cfg.symbols)

    print("\nRunning liquidity gate on all 4 symbols...\n")
    results = run_liquidity_gate()

    # Summary table
    print(f"\n{'='*70}")
    print(f"{'Symbol':<10} {'Status':<8} {'24h Vol (USD)':>18} {'P40 (USD)':>18} {'Spread':>8}  Reason")
    print(f"{'-'*70}")

    for sym, r in results.items():
        status   = "PASS" if r.overall_pass else "FAIL"
        vol_str  = f"${r.current_volume_usd/1e6:>7,.1f}M" if r.current_volume_usd else "       N/A"
        p40_str  = f"${r.p40_threshold_usd/1e6:>7,.1f}M"  if r.p40_threshold_usd  else "       N/A"
        sprd_str = f"{r.current_spread_pct:.4f}%"           if r.current_spread_pct is not None else "    N/A"
        reason   = r.reject_reason or "—"

        # Truncate long reject reasons for table display
        if len(reason) > 30:
            reason = reason[:30] + "..."

        print(f"{sym:<10} {status:<8} {vol_str:>18} {p40_str:>18} {sprd_str:>8}  {reason}")

    print(f"{'='*70}")

    passed = [s for s, r in results.items() if r.overall_pass]
    failed = [s for s, r in results.items() if not r.overall_pass]

    print(f"\nPASSED ({len(passed)}): {', '.join(passed) if passed else 'none'}")
    print(f"FAILED ({len(failed)}): {', '.join(failed) if failed else 'none'}")

    print(f"\n{SEP}")
    print("[OK] Liquidity gate test complete.")
    print(SEP)
