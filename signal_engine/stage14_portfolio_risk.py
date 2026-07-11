"""
signal_engine/stage14_portfolio_risk.py
Final gate before signal dispatch. Manages position limits, 
correlation exposure, daily/weekly loss limits, and cooldowns.
"""

import io
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

from signal_engine.config import cfg
from signal_engine.utils.logger import get_logger
from signal_engine.stage05_relative_strength import get_correlation_cluster
from signal_engine.stage13_signal_output import send_loss_limit_alert

@dataclass
class PortfolioCheckResult:
    approved: bool
    reject_reason: Optional[str]
    open_position_count: int
    cluster_position_count: int
    cooldown_remaining_minutes: float
    daily_pnl_pct: float
    weekly_pnl_pct: float
    halted: bool


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
        get_logger("STAGE14", "STATE").error(f"Failed to save engine state: {e}")


def _get_current_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _get_current_utc_week() -> str:
    # ISO year and week number, e.g. "2026-W27"
    dt = datetime.now(timezone.utc)
    iso_year, iso_week, _ = dt.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _ensure_initialized(state: dict) -> None:
    """Ensures all necessary keys exist and processes automatic resets."""
    now_date = _get_current_utc_date()
    now_week = _get_current_utc_week()

    if "open_positions" not in state:
        state["open_positions"] = []
    if "daily_pnl" not in state:
        state["daily_pnl"] = 0.0
    if "weekly_pnl" not in state:
        state["weekly_pnl"] = 0.0
    if "cooldown_timestamps" not in state:
        state["cooldown_timestamps"] = {}
    if "signals_halted" not in state:
        state["signals_halted"] = False
    if "halt_reason" not in state:
        state["halt_reason"] = None
        
    last_daily = state.get("last_daily_reset")
    if last_daily != now_date:
        state["daily_pnl"] = 0.0
        state["last_daily_reset"] = now_date
        # Clear daily halt if it was daily loss limit
        if state.get("halt_reason") == "DAILY_LOSS_LIMIT":
            state["signals_halted"] = False
            state["halt_reason"] = None

    last_weekly = state.get("last_weekly_reset")
    if last_weekly != now_week:
        state["weekly_pnl"] = 0.0
        state["last_weekly_reset"] = now_week
        # Automatic weekly reset on new week (Monday 00:00 UTC)
        if state.get("halt_reason") == "WEEKLY_LOSS_LIMIT":
            state["signals_halted"] = False
            state["halt_reason"] = None


def check_signal(symbol: str, direction: str, cluster: List[str], confidence_score: float) -> PortfolioCheckResult:
    """
    Checks if a signal passes portfolio and risk limits.
    """
    slog = get_logger("STAGE14", symbol)
    state = _load_state()
    _ensure_initialized(state)
    
    halted = state["signals_halted"]
    daily_pnl = state["daily_pnl"]
    weekly_pnl = state["weekly_pnl"]
    open_positions = state["open_positions"]
    cooldowns = state["cooldown_timestamps"]
    
    # 1. Halt Check
    if halted:
        reason = state["halt_reason"]
        slog.warning(f"Portfolio halted: {reason}")
        return PortfolioCheckResult(False, f"HALTED: {reason}", len(open_positions), 0, 0.0, daily_pnl, weekly_pnl, True)
        
    # 2. Cooldown Check
    last_exit = cooldowns.get(symbol, 0)
    now_ts = time.time()
    elapsed_minutes = (now_ts - last_exit) / 60.0
    remaining_cooldown = 30.0 - elapsed_minutes
    
    if remaining_cooldown > 0:
        msg = f"SYMBOL_COOLDOWN — {remaining_cooldown:.1f} minutes remaining"
        slog.warning(msg)
        return PortfolioCheckResult(False, msg, len(open_positions), 0, remaining_cooldown, daily_pnl, weekly_pnl, False)
        
    # 3. Max Positions Check
    if len(open_positions) >= 4:
        msg = "MAX_POSITIONS_REACHED"
        slog.warning(msg)
        return PortfolioCheckResult(False, msg, len(open_positions), 0, 0.0, daily_pnl, weekly_pnl, False)
        
    # 4. Correlation Cluster Check
    # if matrix is stale, cluster will contain all symbols.
    cluster_count = sum(1 for pos in open_positions if pos["symbol"] in cluster)
    if cluster_count >= 2:
        msg = "CLUSTER_LIMIT_REACHED"
        slog.warning(msg)
        return PortfolioCheckResult(False, msg, len(open_positions), cluster_count, 0.0, daily_pnl, weekly_pnl, False)
        
    slog.info("Signal PASSED portfolio risk checks.")
    return PortfolioCheckResult(True, None, len(open_positions), cluster_count, 0.0, daily_pnl, weekly_pnl, False)


def open_position(symbol: str, direction: str, entry: float, stop: float, target1: float, target2: float, size_pct: float) -> None:
    slog = get_logger("STAGE14", symbol)
    state = _load_state()
    _ensure_initialized(state)
    
    pos = {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "target1": target1,
        "target2": target2,
        "size_pct": size_pct,
        "open_time": time.time()
    }
    state["open_positions"].append(pos)
    _save_state(state)
    slog.info(f"Opened {direction} position on {symbol} (Size: {size_pct:.1f}%). Open positions: {len(state['open_positions'])}")


def close_position(symbol: str, exit_price: float, pnl_r: float, account_balance: float = 1000.0) -> None:
    slog = get_logger("STAGE14", symbol)
    state = _load_state()
    _ensure_initialized(state)
    
    # Find position
    positions = state["open_positions"]
    pos_idx = -1
    for i, p in enumerate(positions):
        if p["symbol"] == symbol:
            pos_idx = i
            break
            
    if pos_idx == -1:
        slog.warning(f"Attempted to close {symbol} but no open position found.")
        return
        
    pos = positions.pop(pos_idx)
    
    # For testing/simulation, we assume pnl_r represents the PnL % impact on the account.
    # E.g. pnl_r = -1.0 means we lost 1% of the account.
    state["daily_pnl"] += pnl_r
    state["weekly_pnl"] += pnl_r
    state["cooldown_timestamps"][symbol] = time.time()
    
    slog.info(f"Closed {symbol}. Impact: {pnl_r:+.2f}%. Daily PnL: {state['daily_pnl']:+.2f}% | Weekly PnL: {state['weekly_pnl']:+.2f}%")
    
    # Check loss limits
    if state["daily_pnl"] <= -3.0:
        state["signals_halted"] = True
        state["halt_reason"] = "DAILY_LOSS_LIMIT"
        slog.error("DAILY_LOSS_LIMIT breached. Signals halted.")
        send_loss_limit_alert("DAILY", state["daily_pnl"], account_balance)
        
    elif state["weekly_pnl"] <= -8.0:
        state["signals_halted"] = True
        state["halt_reason"] = "WEEKLY_LOSS_LIMIT"
        slog.error("WEEKLY_LOSS_LIMIT breached. Signals halted.")
        send_loss_limit_alert("WEEKLY", state["weekly_pnl"], account_balance)
        
    _save_state(state)


def get_portfolio_status() -> dict:
    state = _load_state()
    _ensure_initialized(state)
    return {
        "open_positions": state["open_positions"],
        "daily_pnl": state["daily_pnl"],
        "weekly_pnl": state["weekly_pnl"],
        "halted": state["signals_halted"],
        "halt_reason": state.get("halt_reason")
    }


def manual_reset_weekly() -> None:
    slog = get_logger("STAGE14", "SYSTEM")
    state = _load_state()
    _ensure_initialized(state)
    
    state["weekly_pnl"] = 0.0
    if state.get("halt_reason") == "WEEKLY_LOSS_LIMIT":
        state["signals_halted"] = False
        state["halt_reason"] = None
        
    # Also reset daily just in case
    state["daily_pnl"] = 0.0
    if state.get("halt_reason") == "DAILY_LOSS_LIMIT":
        state["signals_halted"] = False
        state["halt_reason"] = None
        
    _save_state(state)
    slog.info("Manual reset executed. PnL tracking cleared and halts lifted.")


def force_periodic_resets() -> None:
    """Forces the daily/weekly reset check directly, bypassing signal generation."""
    state = _load_state()
    _ensure_initialized(state)
    _save_state(state)


# ── Standalone Test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("================================================================================")
    print("stage14_portfolio_risk.py -- Standalone Test")
    print("================================================================================")

    # 1. Clean state
    if os.path.exists(cfg.state_file):
        os.remove(cfg.state_file)
    
    print("\n[Scenario 1] Clean state — signal approved")
    cluster = get_correlation_cluster("BTCUSDT")[0]
    res1 = check_signal("BTCUSDT", "LONG", cluster, 85.0)
    print(f"  Result: Approved={res1.approved} | Reason={res1.reject_reason}")
    open_position("BTCUSDT", "LONG", 60000, 59000, 62000, 64000, 10.0)
    
    print("\n[Scenario 2] Open 4 positions — 5th signal rejected with MAX_POSITIONS_REACHED")
    open_position("ETHUSDT", "LONG", 3000, 2900, 3100, 3200, 10.0)
    open_position("SOLUSDT", "LONG", 140, 130, 150, 160, 10.0)
    open_position("ADAUSDT", "LONG", 0.4, 0.38, 0.45, 0.5, 10.0)
    res2 = check_signal("XRPUSDT", "LONG", ["XRPUSDT"], 85.0)
    print(f"  Result: Approved={res2.approved} | Reason={res2.reject_reason}")
    
    print("\n[Scenario 3] Open 2 correlated positions — 3rd correlated signal rejected with CLUSTER_LIMIT_REACHED")
    # Reset to 2 positions from same cluster
    if os.path.exists(cfg.state_file):
        os.remove(cfg.state_file)
    open_position("LDOUSDT", "LONG", 1.5, 1.4, 1.7, 1.8, 10.0)
    open_position("UNIUSDT", "LONG", 6.0, 5.5, 7.0, 8.0, 10.0)
    # Simulate UNI and LDO are in DEFI cluster
    cluster_defi = ["LDOUSDT", "UNIUSDT", "AAVEUSDT"]
    res3 = check_signal("AAVEUSDT", "LONG", cluster_defi, 85.0)
    print(f"  Result: Approved={res3.approved} | Reason={res3.reject_reason}")
    
    print("\n[Scenario 4] Close a position and immediately retry — rejected with SYMBOL_COOLDOWN")
    close_position("LDOUSDT", 1.6, 0.5) # +0.5% profit
    res4 = check_signal("LDOUSDT", "LONG", ["LDOUSDT"], 85.0)
    print(f"  Result: Approved={res4.approved} | Reason={res4.reject_reason}")
    
    print("\n[Scenario 5] Simulate -3.5% daily loss — signals halted, Discord alert fires")
    close_position("UNIUSDT", 5.0, -4.0) # -4.0% loss => daily pnl = -3.5%
    res5 = check_signal("ETHUSDT", "LONG", ["ETHUSDT"], 85.0)
    print(f"  Result: Approved={res5.approved} | Reason={res5.reject_reason}")
    
    print("\n[Scenario 6] Reset daily and confirm signals resume")
    manual_reset_weekly()
    res6 = check_signal("ETHUSDT", "LONG", ["ETHUSDT"], 85.0)
    print(f"  Result: Approved={res6.approved} | Reason={res6.reject_reason}")
    
    print("\n================================================================================")
    print("[OK] Stage 14 portfolio risk test complete.")
    print("================================================================================")
