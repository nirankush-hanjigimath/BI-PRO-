"""
alert_sender.py — Stage 5
Sends formatted trading alerts to a Discord channel via webhook.
Uses only the standard `requests` library — no Discord SDK needed.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Discord webhook character limit per message
DISCORD_MAX_CHARS = 2000


# ---------------------------------------------------------------------------
# Emoji mappings for visual clarity in Discord
# ---------------------------------------------------------------------------

_CONDITION_EMOJI = {
    "BREAKDOWN":           "🔴",
    "BREAKOUT":            "🟢",
    "BAND_REJECTION_DOWN": "🔻",
    "BAND_REJECTION_UP":   "🔺",
    "RSI_OVERBOUGHT":      "🔥",
    "RSI_OVERSOLD":        "❄️",
}

_TREND_EMOJI = {
    "uptrend":   "📈",
    "downtrend": "📉",
    "ranging":   "↔️",
}


# ---------------------------------------------------------------------------
# Message formatter
# ---------------------------------------------------------------------------

def _format_message(symbol: str, direction: str, price: float, ai_analysis: str) -> str:
    """
    Build the Discord message string with emoji, indicators, and AI analysis.
    Truncated to DISCORD_MAX_CHARS if necessary.
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    trend_emoji = _TREND_EMOJI.get(direction, "❓")

    message = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔔 **{symbol}** · MTF CONFIRMED · {now_utc}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"**Trend:** {trend_emoji} {direction.upper()}\n"
        f"**Latest Price:** `{price:.6g}`\n"
        f"\n"
        f"📊 **MTF Analysis:**\n"
        f"{ai_analysis}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    if len(message) > DISCORD_MAX_CHARS:
        # Trim AI analysis to fit
        overhead = len(message) - len(ai_analysis)
        max_analysis_len = DISCORD_MAX_CHARS - overhead - 20
        truncated_analysis = ai_analysis[:max_analysis_len] + "... *(truncated)*"
        message = message.replace(ai_analysis, truncated_analysis)

    return message


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_discord_alert(symbol: str, direction: str, price: float,
                       ai_analysis: str, webhook_url: Optional[str] = None) -> bool:
    """
    Format and POST a Discord alert via webhook.

    Args:
        webhook_url: Discord webhook URL. Falls back to DISCORD_WEBHOOK_URL env var.

    Returns:
        True on success, False on failure (errors are logged, not raised).
    """
    url = webhook_url or os.environ.get("DISCORD_WEBHOOK_SYSTEM", "")
    if not url:
        logger.error(
            "DISCORD_WEBHOOK_URL is not set. Cannot send alert. "
            "Add it to your .env file."
        )
        return False

    message = _format_message(
        symbol=symbol,
        direction=direction,
        price=price,
        ai_analysis=ai_analysis,
    )

    payload = {"content": message}

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            logger.info(f"[{symbol}/MTF] Discord alert sent successfully.")
            return True
        else:
            logger.error(
                f"[{symbol}/MTF] Discord webhook returned HTTP "
                f"{resp.status_code}: {resp.text[:200]}"
            )
            return False
    except requests.RequestException as exc:
        logger.error(f"[{symbol}/MTF] Failed to send Discord alert: {exc}")
        return False


def send_startup_notification(symbols: list[str], timeframes: list[str],
                               webhook_url: Optional[str] = None) -> None:
    """
    Send a brief startup message to Discord so you know the monitor is live.
    Failures are silently logged — startup should not be blocked.
    """
    url = webhook_url or os.environ.get("DISCORD_WEBHOOK_SYSTEM", "")
    if not url:
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    symbols_str   = ", ".join(symbols)
    timeframes_str = ", ".join(timeframes)

    message = (
        f"🟢 **Binance Market Monitor — STARTED**\n"
        f"Time: {now}\n"
        f"Symbols: `{symbols_str}`\n"
        f"Timeframes: `{timeframes_str}`\n"
        f"Watching for: BREAKDOWN, BREAKOUT, BAND_REJECTION, RSI_EXTREME"
    )

    try:
        requests.post(url, json={"content": message}, timeout=10)
    except requests.RequestException as exc:
        logger.warning(f"Could not send startup notification: {exc}")
