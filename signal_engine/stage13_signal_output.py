"""
signal_engine/stage13_signal_output.py
Final assembly point for signals and non-signal alerts.
Generates narrative, identifies risks, and formats Discord embeds.
"""

import os
import requests
import datetime
from typing import Dict, Any

from dotenv import load_dotenv
from signal_engine.models import (
    Signal, RegimeState, BTCMacro, RelativeStrength, FuturesData,
    SRLevels, EntrySignal, ConfidenceScore
)
from signal_engine.utils.logger import get_logger
from signal_engine.utils.narrative import select_template

load_dotenv()

last_signal_time = {}

COLOR_LONG = 0x00ff88
COLOR_SHORT = 0xff4444
COLOR_WARN = 0xffa500
COLOR_ALERT = 0xff0000

def _post_discord(embed: dict, webhook_url: str = None, content: str = None) -> bool:
    """Sends the embed to the Discord webhook."""
    from signal_engine.config import cfg
    if getattr(cfg, 'mode', None) == 'backtest':
        return False
    slog = get_logger("STAGE13", "DISCORD")
    
    url = webhook_url or getattr(cfg, 'discord_webhook_system', None)
    if not url:
        slog.error("No valid webhook URL found.")
        return False
        
    slog.info(f"Routing to Webhook URL: {url[:40]}... (obfuscated)")
        
    data = {"embeds": [embed]}
    if content:
        data["content"] = content
    try:
        r = requests.post(url, json=data, timeout=5.0)
        r.raise_for_status()
        slog.info(f"Discord webhook sent successfully to {url[:40]}...")
        return True
    except Exception as e:
        slog.error(f"Discord webhook failed to post to {url[:40]}...: {e}")
        return False

def _generate_risks(tags: list, btc_state: str, matrix_stale: bool, stop_pct: float) -> str:
    risks = []
    
    if "CROWDED_TRADE" in tags:
        risks.append("Crowded positioning — high percentage of traders already long/short")
    if "SHORT_COVERING" in tags:
        risks.append("Move may be short covering rather than real demand — less sustainable")
    if "OVEREXTENDED" in tags or "SEVERELY_OVEREXTENDED" in tags:
        risks.append("Price extended from EMA50 — pullback risk elevated")
    if "HIGH_VOL_ENVIRONMENT" in tags or stop_pct > 3.0:
        risks.append("Elevated volatility environment — wider stops, reduced size applied")
    if "OPPOSING_BTC" in tags or btc_state in ("STRONGLY_BEARISH", "BEARISH"): # Rough check
        risks.append("BTC macro trend opposes this signal — higher reversal risk")
    if matrix_stale:
        risks.append("Correlation data stale — cluster risk may be underestimated")
        
    if len(risks) < 2:
        risks.append("Generic risk: market conditions can change rapidly — strict stop loss required")
    if len(risks) < 2:
        risks.append("Generic risk: volume confirmation may fail post-entry")
        
    # Return bulleted string
    return "\n".join([f"• {r}" for r in risks])


def _extract_tags(futures: FuturesData, trend_tag: str, vol_tag: str, vol_env: bool) -> list:
    """Consolidate tags from multiple stage outputs."""
    t = []
    if futures.ls_signal in ("CROWDED_LONG", "CROWDED_SHORT"):
        t.append("CROWDED_TRADE")
    if futures.oi_signal == "SHORT_COVER":
        t.append("SHORT_COVERING")
    if trend_tag:
        t.append(trend_tag)
    if vol_tag:
        t.append(vol_tag)
    if vol_env:
        t.append("HIGH_VOL_ENVIRONMENT")
    return t


def assemble_and_send_signal(
    symbol: str, direction: str,
    regime: RegimeState, btc_macro: BTCMacro, rs: RelativeStrength,
    futures: FuturesData, sr: SRLevels, entry: EntrySignal,
    confidence: ConfidenceScore,
    entry_price: float, stop_loss: float, target1: float, target2: float,
    rr_ratio: float, position_size_pct: float, invalidation_price: float,
    trend_tag: str, vol_tag: str, vol_env: bool, matrix_stale: bool,
    volume_z: float, ema_price: float,
) -> Signal:
    """
    Assembles the final Signal dataclass, generating narratives and formatting the embed.
    Sends to Discord if grade is valid.
    """
    slog = get_logger("STAGE13", symbol)
    
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    if symbol in last_signal_time:
        diff_mins = (now_utc - last_signal_time[symbol]).total_seconds() / 60.0
        if diff_mins < 10.0:
            slog.info(f"Deduplication triggered: dropping duplicate {symbol} signal ({diff_mins:.1f}m since last)")
            return Signal(
                symbol=symbol, direction=direction, timestamp=now_utc,
                regime=regime, btc_macro=btc_macro, relative_strength=rs, futures=futures, sr=sr, entry=entry, confidence=confidence,
                entry_price=entry_price, stop_loss=stop_loss, target1=target1, target2=target2, rr_ratio=rr_ratio,
                position_size_pct=position_size_pct, invalidation_price=invalidation_price, narrative="", risks="", tags=[]
            )
            
    last_signal_time[symbol] = now_utc
    slog.info(f"Assembling signal for {direction} with Grade {confidence.grade}...")

    # Combine tags for risks
    tags = _extract_tags(futures, trend_tag, vol_tag, vol_env)

    # Narrative building
    signal_data = {
        "symbol": symbol,
        "direction": direction,
        "timeframe": "15m",
        "btc_trend": btc_macro.classification,
        "volume_z": volume_z,
        "target1": target1,
        "rs_pct": rs.rs_pct,
        "ema_price": ema_price,
        "entry_pattern": entry.pattern_name or "NONE",
        "confidence": confidence.final_score,
        "oi_status": futures.oi_signal or "UNAVAILABLE",
    }
    
    narrative_text = select_template(signal_data)
    stop_dist = abs(entry_price - stop_loss) / entry_price * 100.0
    risks_text = _generate_risks(tags, btc_macro.classification, matrix_stale, stop_dist)

    sig_obj = Signal(
        symbol=symbol, direction=direction, timestamp=datetime.datetime.now(datetime.timezone.utc),
        regime=regime, btc_macro=btc_macro, relative_strength=rs, futures=futures, sr=sr, entry=entry, confidence=confidence,
        entry_price=entry_price, stop_loss=stop_loss, target1=target1, target2=target2, rr_ratio=rr_ratio,
        position_size_pct=position_size_pct, invalidation_price=invalidation_price, narrative=narrative_text, risks=risks_text, tags=tags
    )

    if confidence.grade == "REJECT":
        slog.info("Signal graded REJECT, skipping Discord assembly.")
        return sig_obj

    # Build Discord Embed
    color = COLOR_LONG if direction == "LONG" else COLOR_SHORT
    emoji = "🟢" if direction == "LONG" else "🔴"
    ts_str = sig_obj.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Layer Breakdown Formatting
    def _pass_fail(score):
        return "✅" if score >= 60 else "⚠️" if score >= 40 else "❌"

    layers = confidence.layer_scores
    breakdown = (
        f"{_pass_fail(layers.get('Market Regime', 0))} Regime: {layers.get('Market Regime', 0)}\n"
        f"{_pass_fail(layers.get('BTC Alignment', 0))} BTC Align: {layers.get('BTC Alignment', 0)}\n"
        f"{_pass_fail(layers.get('Higher TF Trend', 0))} Trend: {layers.get('Higher TF Trend', 0)}\n"
        f"{_pass_fail(layers.get('Relative Strength', 0))} RS: {layers.get('Relative Strength', 0)}\n"
        f"{_pass_fail(layers.get('Volume Z-Score', 0))} Volume: {layers.get('Volume Z-Score', 0)}\n"
        f"{_pass_fail(layers.get('Open Interest', 0))} OI: {layers.get('Open Interest', 0)}\n"
        f"{_pass_fail(layers.get('Funding Rate', 0))} Funding: {layers.get('Funding Rate', 0)}\n"
        f"{_pass_fail(layers.get('S/R Room', 0))} S/R: {layers.get('S/R Room', 0)}\n"
        f"{_pass_fail(layers.get('Volatility Context', 0))} Volatility: {layers.get('Volatility Context', 0)}\n"
        f"{_pass_fail(layers.get('Price Action', 0))} Price Act: {layers.get('Price Action', 0)}"
    )

    embed = {
        "title": f"{emoji} {symbol} · {direction} · Grade {confidence.grade} · {ts_str}",
        "color": color,
        "fields": [
            {"name": "Confidence", "value": f"{confidence.final_score}/100 · Grade: {confidence.grade}", "inline": True},
            {"name": "Market Regime", "value": f"{regime.regime} ({regime.timeframe}) — active {regime.regime_age_candles} candles", "inline": True},
            {"name": "BTC Trend", "value": f"{btc_macro.classification} ({btc_macro.confidence_modifier:+d})", "inline": True},
            {"name": "Relative Strength", "value": f"{rs.classification} ({rs.rs_pct:+.2f}% vs BTC)", "inline": True},
            {"name": "WHY THIS TRADE EXISTS", "value": narrative_text, "inline": False},
            {"name": "LAYER BREAKDOWN", "value": breakdown, "inline": False},
            {"name": "Entry", "value": f"${entry_price:,.4f}" if entry_price is not None else "N/A", "inline": True},
            {"name": "Stop Loss", "value": f"${stop_loss:,.4f} (Swing)" if stop_loss is not None else "N/A", "inline": True},
            {"name": "Target 1 (1R)", "value": f"${target1:,.4f} ← close 50% here" if target1 is not None else "N/A", "inline": True},
            {"name": "Target 2 (2R)", "value": f"${target2:,.4f} ← trail stop after" if target2 is not None else "N/A", "inline": True},
            {"name": "R:R Ratio", "value": f"{rr_ratio:.2f}:1" if rr_ratio is not None else "N/A", "inline": True},
            {"name": "Position Size", "value": f"{position_size_pct:.1f}% of account" if position_size_pct is not None else "N/A", "inline": True},
            {"name": "Invalidation", "value": f"${invalidation_price:,.4f} — if breached thesis is wrong" if invalidation_price is not None else "N/A", "inline": False},
            {"name": "RISKS", "value": risks_text, "inline": False},
        ]
    }
    
    from signal_engine.utils.alerts import get_webhook_for_grade
    webhook_url = get_webhook_for_grade(confidence.grade)
    
    if not webhook_url:
        slog.info(f"No webhook configured for grade {confidence.grade}, or sending disabled.")
        return sig_obj
        
    content_str = None
    if confidence.grade == 'A+':
        content_str = "@everyone"
    elif confidence.grade == 'A':
        content_str = "@here"
        
    _post_discord(embed, webhook_url=webhook_url, content=content_str)
    return sig_obj

# ── Non-signal alerts ──────────────────────────────────────────────────────

def send_squeeze_alert(symbol: str, timeframe: str, bbwidth_percentile: float):
    embed = {
        "title": f"⚠️ {symbol} · LOW VOLATILITY SQUEEZE",
        "color": COLOR_WARN,
        "description": f"Timeframe: {timeframe}\nBBWidth is at the {bbwidth_percentile:.1f}th percentile.\nExpect expansion. No trade signal will fire until resolved."
    }
    _post_discord(embed)
    get_logger("STAGE13", symbol).warning(f"Squeeze alert sent for {timeframe}")

def send_loss_limit_alert(daily_or_weekly: str, drawdown_pct: float, account_balance: float):
    embed = {
        "title": f"🚨 {daily_or_weekly.upper()} LOSS LIMIT BREACHED",
        "color": COLOR_ALERT,
        "description": f"Drawdown: {drawdown_pct:.1f}%\nCurrent Balance: ${account_balance:,.2f}\nTrading halted for the remainder of the period."
    }
    _post_discord(embed)
    get_logger("STAGE13", "SYSTEM").error(f"Loss limit alert sent: {daily_or_weekly}")

def send_api_warning(endpoint: str, error_message: str):
    embed = {
        "title": f"⚠️ API WARNING: {endpoint}",
        "color": COLOR_WARN,
        "description": f"Error: {error_message}\nSystem performance or data may be degraded."
    }
    _post_discord(embed)
    get_logger("STAGE13", "SYSTEM").warning(f"API Warning sent: {endpoint}")

def send_matrix_stale_alert(hours_since_refresh: float):
    embed = {
        "title": f"⚠️ CORRELATION MATRIX STALE",
        "color": COLOR_WARN,
        "description": f"Matrix is {hours_since_refresh:.1f} hours old.\nAssuming all symbols correlated until refreshed."
    }
    _post_discord(embed)
    get_logger("STAGE13", "SYSTEM").warning(f"Matrix stale alert sent.")


# ── Standalone Test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("================================================================================")
    print("stage13_signal_output.py -- Standalone Test")
    print("================================================================================")

    import time
    
    # Check webhook config
    if not DISCORD_WEBHOOK_URL:
        print("[WARNING] DISCORD_WEBHOOK_URL not set in .env. Output will only log, not actually post.")
        
    print("\n--- 1. Testing Non-Signal Alerts ---")
    send_squeeze_alert("BTCUSDT", "4h", 8.5)
    time.sleep(1)
    send_loss_limit_alert("DAILY", 3.2, 968.50)
    time.sleep(1)
    send_api_warning("Bybit Futures Open Interest", "Connection timeout after 5s")
    time.sleep(1)
    send_matrix_stale_alert(26.4)
    time.sleep(1)
    
    print("\n--- 2. Testing Signal Assembly & Send (A+ SOLUSDT LONG) ---")
    
    # Mock inputs
    regime = RegimeState("15m", "TRENDING", 12, 45.2, 38.1, 4.2, 85.0, 0)
    btc = BTCMacro("STRONGLY_BULLISH", 2.1, 1.5, 65.4, 1.8, 5)
    rs = RelativeStrength(4.5, "LEADER", 8, "ETHUSDT")
    futures = FuturesData(False, 5.2, 0.003, 50.0, "REAL_DEMAND", "NEUTRAL", "BALANCED", 8, 0)
    sr = SRLevels([150.0, 160.0], [140.0, 130.0], 150.0, 140.0, 4.5, 4.0, False, False, None)
    entry = EntrySignal("Strong Breakout", "LONG", 1.8, "CLOSED", True, None)
    
    layers = {
        "Market Regime": 90, "BTC Alignment": 100, "Higher TF Trend": 90,
        "Relative Strength": 90, "Volume Z-Score": 95, "Open Interest": 90,
        "Funding Rate": 70, "S/R Room": 90, "Volatility Context": 80, "Price Action": 95
    }
    conf = ConfidenceScore(92.5, [], 92, "A+", 1.0, layers, False)
    
    assemble_and_send_signal(
        symbol="SOLUSDT", direction="LONG",
        regime=regime, btc_macro=btc, rs=rs,
        futures=futures, sr=sr, entry=entry, confidence=conf,
        entry_price=143.50, stop_loss=140.20, target1=150.00, target2=158.00,
        rr_ratio=2.5, position_size_pct=10.0, invalidation_price=140.00,
        trend_tag=None, vol_tag=None, vol_env=False, matrix_stale=False,
        volume_z=2.5, ema_price=141.0
    )
    
    print("\n================================================================================")
    print("[OK] Stage 13 signal output test complete.")
    print("================================================================================")
