"""
signal_engine/paper_trader.py
Manages paper trading logic, tracking virtual positions and PnL,
and sending daily summaries to Discord.
"""

import io
import sys
import json
import os
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import requests

from signal_engine.config import cfg
from signal_engine.utils.logger import get_logger

logger = get_logger("ENGINE", "PAPER_TRADER")

PAPER_STATE_FILE = cfg.state_file.replace("engine_state", "paper_state")


def _get_current_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _get_current_utc_week() -> str:
    dt = datetime.now(timezone.utc)
    iso_year, iso_week, _ = dt.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _load_state() -> dict:
    if os.path.exists(PAPER_STATE_FILE):
        try:
            with open(PAPER_STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
            
    # Default state
    return {
        "balance": 1000.0,
        "start_date": _get_current_utc_date(),
        "open_positions": [],
        "closed_trades": [],
        "daily_pnl": 0.0,
        "weekly_pnl": 0.0,
        "total_pnl": 0.0,
        "trade_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "last_daily_reset": _get_current_utc_date(),
        "last_weekly_reset": _get_current_utc_week(),
        "last_summary_date": ""
    }


def _save_state(state: dict) -> None:
    try:
        with open(PAPER_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save paper state: {e}")


def _ensure_periodic_resets(state: dict):
    now_date = _get_current_utc_date()
    now_week = _get_current_utc_week()
    
    if state.get("last_daily_reset") != now_date:
        state["daily_pnl"] = 0.0
        state["last_daily_reset"] = now_date
        
    if state.get("last_weekly_reset") != now_week:
        state["weekly_pnl"] = 0.0
        state["last_weekly_reset"] = now_week


def get_paper_history_days() -> int:
    """Returns the number of calendar days of paper trading history."""
    state = _load_state()
    start_str = state.get("start_date", _get_current_utc_date())
    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - start_date
        return delta.days
    except ValueError:
        return 0


def open_paper_position(
    symbol: str, 
    direction: str, 
    entry_price: float, 
    stop_loss: float, 
    target1: float, 
    target2: float, 
    size_pct: float
) -> None:
    state = _load_state()
    _ensure_periodic_resets(state)
    
    # Apply 0.05% slippage
    slippage = 0.0005
    if direction == "LONG":
        filled_price = entry_price * (1 + slippage)
    else:
        filled_price = entry_price * (1 - slippage)
        
    pos = {
        "id": int(time.time()),
        "symbol": symbol,
        "direction": direction,
        "entry_price": filled_price,
        "stop_loss": stop_loss,
        "target1": target1,
        "target2": target2,
        "size_pct": size_pct,
        "open_time": time.time(),
        "t1_hit": False,
        "original_entry": entry_price
    }
    
    state["open_positions"].append(pos)
    _save_state(state)
    logger.info(f"[PAPER] Opened {direction} on {symbol} at {filled_price:.4f} (Slippage applied)")

    try:
        from signal_engine.utils.alerts import alert_paper_fill
        alert_paper_fill(
            symbol=symbol,
            direction=direction,
            fill_price=filled_price,
            stop=stop_loss,
            target1=target1,
            target2=target2,
            position_size_pct=size_pct,
            slippage_pct=0.05
        )
    except Exception as e:
        logger.error(f"[PAPER] Failed to send fill alert for {symbol}: {e}")


def _close_position(state: dict, pos: dict, exit_price: float, reason: str, partial: bool = False):
    direction = pos["direction"]
    entry = pos["entry_price"]
    
    # Profit calculation
    if direction == "LONG":
        pnl_pct = (exit_price - entry) / entry
    else:
        pnl_pct = (entry - exit_price) / entry
        
    # How much of the total account was risked / is impacted
    # Actually simpler to track absolute PnL or percentage of account
    size_decimal = pos["size_pct"] / 100.0
    position_usd_size = state["balance"] * size_decimal
    
    if partial:
        # Close 50% of position
        realized_pnl_usd = (position_usd_size * 0.5) * pnl_pct
    else:
        # Close remaining position (which could be 50% or 100%)
        size_multiplier = 0.5 if pos["t1_hit"] else 1.0
        realized_pnl_usd = (position_usd_size * size_multiplier) * pnl_pct
        
    pct_impact = (realized_pnl_usd / state["balance"]) * 100.0
    
    # Calculate R (Risk)
    # 1R = position size at entry to stop loss
    risk_price_dist = abs(entry - pos["stop_loss"])
    risk_pct_dist = risk_price_dist / entry if entry > 0 else 1.0
    # The max loss in pct of position is risk_pct_dist.
    # Total account risk = size_decimal * risk_pct_dist
    account_risk_usd = position_usd_size * risk_pct_dist
    
    r_multiple = realized_pnl_usd / account_risk_usd if account_risk_usd > 0 else 0.0
    
    # Update State
    state["balance"] += realized_pnl_usd
    state["daily_pnl"] += realized_pnl_usd
    state["weekly_pnl"] += realized_pnl_usd
    state["total_pnl"] += realized_pnl_usd
    
    if not partial:
        state["trade_count"] += 1
        # Net R multiple across whole trade
        net_r = r_multiple
        if pos["t1_hit"]:
            # Approx logic: earlier T1 was ~1R, plus this T2 or breakeven
            # T1 gives ~0.5R (half pos * 1R), T2 gives ~1R (half pos * 2R) -> 1.5R
            # For simplicity, if it's a T2 close we consider it a Win.
            state["win_count"] += 1
        else:
            if realized_pnl_usd > 0:
                state["win_count"] += 1
            else:
                state["loss_count"] += 1
                
        trade_record = {
            "symbol": pos["symbol"],
            "direction": pos["direction"],
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "reason": reason,
            "pnl_usd": realized_pnl_usd,
            "pnl_pct_impact": pct_impact,
            "r_multiple": net_r,
            "close_time": time.time()
        }
        state["closed_trades"].append(trade_record)
        
    logger.info(f"[PAPER] {pos['symbol']} Closed ({reason}) | PnL: ${realized_pnl_usd:+.2f} ({pct_impact:+.2f}%)")

    # ── Discord exit notification ─────────────────────────────────────────
    try:
        from signal_engine.utils.alerts import alert_paper_exit
        alert_paper_exit(
            symbol=pos['symbol'],
            direction=pos['direction'],
            exit_price=exit_price,
            exit_reason=reason,
            pnl_usd=realized_pnl_usd,
            pnl_r=r_multiple,
            new_balance=state['balance'],
        )
    except Exception as e:
        logger.error(f"[PAPER] Failed to send exit alert for {pos['symbol']}: {e}")


def check_paper_positions(current_prices: Dict[str, float]) -> None:
    """Check open positions against current market prices."""
    state = _load_state()
    _ensure_periodic_resets(state)
    
    open_positions = state["open_positions"]
    to_remove = []
    
    for idx, pos in enumerate(open_positions):
        sym = pos["symbol"]
        if sym not in current_prices:
            continue
            
        curr_price = current_prices[sym]
        direction = pos["direction"]
        
        # Check Stop Loss
        if (direction == "LONG" and curr_price <= pos["stop_loss"]) or \
           (direction == "SHORT" and curr_price >= pos["stop_loss"]):
            _close_position(state, pos, curr_price, "STOP_LOSS", partial=False)
            to_remove.append(idx)
            continue
            
        # Check Target 1 (50% scale out + move stop to BE)
        if not pos["t1_hit"]:
            if (direction == "LONG" and curr_price >= pos["target1"]) or \
               (direction == "SHORT" and curr_price <= pos["target1"]):
                _close_position(state, pos, pos["target1"], "TARGET_1", partial=True)
                pos["t1_hit"] = True
                pos["stop_loss"] = pos["entry_price"]  # move to breakeven
                continue
                
        # Check Target 2
        if (direction == "LONG" and curr_price >= pos["target2"]) or \
           (direction == "SHORT" and curr_price <= pos["target2"]):
            _close_position(state, pos, pos["target2"], "TARGET_2", partial=False)
            to_remove.append(idx)
            continue
            
    # Remove closed positions
    for idx in sorted(to_remove, reverse=True):
        state["open_positions"].pop(idx)
        
    _save_state(state)


def send_daily_summary() -> None:
    """Send Discord summary of paper trading performance."""
    state = _load_state()
    _ensure_periodic_resets(state)
    
    from signal_engine.config import cfg
    webhook_url = cfg.discord_webhook_system
    if not webhook_url:
        return
        
    now_date = _get_current_utc_date()
    if state.get("last_summary_date") == now_date:
        return  # Already sent today
        
    # Calculate daily metrics
    balance = state["balance"]
    start_bal = balance - state["daily_pnl"]
    daily_pct = (state["daily_pnl"] / start_bal) * 100.0 if start_bal > 0 else 0.0
    
    embed = {
        "title": "📊 Paper Trading Daily Summary",
        "description": f"Performance for **{now_date} UTC**",
        "color": 0x3498db if state["daily_pnl"] >= 0 else 0xe74c3c,
        "fields": [
            {
                "name": "💰 Balance",
                "value": f"${balance:,.2f}",
                "inline": True
            },
            {
                "name": "📈 Daily PnL",
                "value": f"${state['daily_pnl']:+,.2f} ({daily_pct:+.2f}%)",
                "inline": True
            },
            {
                "name": "🏆 Win/Loss",
                "value": f"{state['win_count']} W / {state['loss_count']} L",
                "inline": True
            },
            {
                "name": "📂 Open Positions",
                "value": str(len(state["open_positions"])),
                "inline": True
            }
        ],
        "footer": {
            "text": "Institutional Signal Engine • Paper Trader"
        }
    }
    
    try:
        logger.info(f"[DEBUG] Sending daily summary to {webhook_url[:40]}...")
        r = requests.post(webhook_url, json={"embeds": [embed]}, timeout=5)
        logger.info(f"[DEBUG] Daily summary response: {r.status_code} - {r.text}")
        r.raise_for_status()
        state["last_summary_date"] = now_date
        _save_state(state)
        logger.info("[PAPER] Daily summary sent to Discord.")
    except Exception as e:
        import traceback
        logger.error(f"[PAPER] Failed to send Discord summary to {webhook_url[:40]}...: {e}")
        logger.error(traceback.format_exc())


def run_daily_summary_check():
    from datetime import timedelta
    from signal_engine.utils.logger import get_logger
    get_logger("PAPER", "SUMMARY").info("[DEBUG] run_daily_summary_check() called")
    
    state = _load_state()
    today_ist = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d')
    last_summary = state.get('last_summary_date', '')

    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    ist_hour = ist_now.hour

    if last_summary != today_ist and ist_hour >= 21:
        send_daily_summary()
        state['last_summary_date'] = today_ist
        _save_state(state)


# ── Standalone Test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("================================================================================")
    print("paper_trader.py -- Standalone Test")
    print("================================================================================")
    
    # 1. Clean slate
    if os.path.exists(PAPER_STATE_FILE):
        os.remove(PAPER_STATE_FILE)
        
    print("\n[Scenario 1] Open 3 paper positions")
    # ETHUSDT LONG, SOLUSDT SHORT, BTCUSDT LONG
    open_paper_position("ETHUSDT", "LONG", 3000, 2900, 3200, 3400, 10.0)
    open_paper_position("SOLUSDT", "SHORT", 150, 160, 140, 130, 10.0)
    open_paper_position("BTCUSDT", "LONG", 60000, 58000, 62000, 64000, 10.0)
    
    state = _load_state()
    print(f"Open positions: {len(state['open_positions'])}")
    
    print("\n[Scenario 2] Simulate ETH hitting Target 1, then Target 2")
    # Hits T1 (3200)
    check_paper_positions({"ETHUSDT": 3200, "SOLUSDT": 150, "BTCUSDT": 60000})
    state = _load_state()
    eth_pos = next((p for p in state["open_positions"] if p["symbol"] == "ETHUSDT"), None)
    print(f"ETH T1 Hit: {eth_pos['t1_hit']}, Stop moved to: {eth_pos['stop_loss']}")
    
    # Hits T2 (3400)
    check_paper_positions({"ETHUSDT": 3400, "SOLUSDT": 150, "BTCUSDT": 60000})
    state = _load_state()
    print(f"ETH position closed. Open positions left: {len(state['open_positions'])}")
    
    print("\n[Scenario 3] Simulate SOL hitting Stop Loss")
    check_paper_positions({"SOLUSDT": 160, "BTCUSDT": 60000})
    state = _load_state()
    print(f"SOL position closed. Open positions left: {len(state['open_positions'])}")
    print(f"Daily PnL: ${state['daily_pnl']:.2f}")
    print(f"Wins: {state['win_count']}, Losses: {state['loss_count']}")
    
    print("\n[Scenario 4] Send Daily Summary to Discord")
    # Trick it into thinking it's time to send
    state["last_summary_date"] = ""
    _save_state(state)
    send_daily_summary()
    print("Check Discord for the daily summary embed.")
    
    print("\n[Scenario 5] Check Paper History Days")
    days = get_paper_history_days()
    print(f"History Days: {days}")
    
    print("\n================================================================================")
    print("[OK] paper_trader.py test complete.")
    print("================================================================================")
