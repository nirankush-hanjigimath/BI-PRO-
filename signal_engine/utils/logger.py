"""
signal_engine/utils/logger.py
──────────────────────────────────────────────────────────────────────────────
Colored, structured UTC logger for the Signal Engine.

Every log line format:
  [2026-06-22 01:51:00 UTC] [STAGE00] [SOLUSDT] INFO — message here

Usage:
  from signal_engine.utils.logger import get_logger
  log = get_logger("STAGE00", "SOLUSDT")
  log.info("Fetched 200 candles")
  log.warning("Spread too wide")
  log.error("Fetch failed")
──────────────────────────────────────────────────────────────────────────────
"""

import io
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

# Force UTF-8 on Windows terminals to handle Unicode log messages
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── ANSI colour codes ──────────────────────────────────────────────────────

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"

_LEVEL_COLOURS = {
    "DEBUG":    "\033[36m",   # Cyan
    "INFO":     "\033[32m",   # Green
    "WARNING":  "\033[33m",   # Yellow
    "ERROR":    "\033[31m",   # Red
    "CRITICAL": "\033[35m",   # Magenta
}

_STAGE_COLOUR  = "\033[34m"   # Blue  — stage tag
_SYMBOL_COLOUR = "\033[96m"   # Bright Cyan — symbol tag
_TIME_COLOUR   = _DIM         # Dimmed — timestamp


# ── Plain (file) formatter ─────────────────────────────────────────────────

class _PlainFormatter(logging.Formatter):
    """Writes plain text to the log file — no ANSI codes."""

    def formatTime(self, record, datefmt=None) -> str:  # type: ignore[override]
        return datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    def format(self, record: logging.LogRecord) -> str:
        stage  = getattr(record, "stage",  "SYSTEM")
        symbol = getattr(record, "symbol", "-------")
        ts     = self.formatTime(record)
        level  = record.levelname
        msg    = record.getMessage()

        # Append exception info if present
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            msg = f"{msg}\n{exc_text}"

        return f"[{ts}] [{stage}] [{symbol}] {level} — {msg}"


# ── Coloured (console) formatter ───────────────────────────────────────────

class _ColorFormatter(logging.Formatter):
    """Writes ANSI-coloured lines to stdout."""

    def formatTime(self, record, datefmt=None) -> str:  # type: ignore[override]
        return datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    def format(self, record: logging.LogRecord) -> str:
        stage  = getattr(record, "stage",  "SYSTEM")
        symbol = getattr(record, "symbol", "-------")
        ts     = self.formatTime(record)
        level  = record.levelname
        msg    = record.getMessage()
        lc     = _LEVEL_COLOURS.get(level, "")

        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            msg = f"{msg}\n{exc_text}"

        return (
            f"{_TIME_COLOUR}[{ts}]{_RESET} "
            f"{_BOLD}{_STAGE_COLOUR}[{stage}]{_RESET} "
            f"{_SYMBOL_COLOUR}[{symbol}]{_RESET} "
            f"{lc}{_BOLD}{level}{_RESET} — {msg}"
        )


# ── LoggerAdapter — injects stage + symbol into every record ───────────────

class EngineLogger(logging.LoggerAdapter):
    """Adapter that stamps `stage` and `symbol` onto every LogRecord."""

    def process(self, msg: str, kwargs: dict) -> tuple:
        extra = kwargs.setdefault("extra", {})
        extra["stage"]  = self.extra.get("stage",  "SYSTEM")
        extra["symbol"] = self.extra.get("symbol", "-------")
        return msg, kwargs


# ── Shared file handler (initialised once) ─────────────────────────────────

_file_handler: Optional[logging.FileHandler] = None


def _get_file_handler(log_dir: str = "logs") -> logging.FileHandler:
    global _file_handler
    if _file_handler is None:
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, "signal_engine.log")
        _file_handler = logging.FileHandler(path, encoding="utf-8")
        _file_handler.setLevel(logging.DEBUG)
        _file_handler.setFormatter(_PlainFormatter())
    return _file_handler


# ── Public factory ─────────────────────────────────────────────────────────

def get_logger(stage: str, symbol: str = "-------") -> EngineLogger:
    """
    Return a configured EngineLogger for the given stage and symbol.

    Parameters
    ----------
    stage  : Short stage tag, e.g. "STAGE00", "REGIME", "ALERTS"
    symbol : Trading pair, e.g. "BTCUSDT". Defaults to "-------" for system logs.

    Example
    -------
    log = get_logger("STAGE03", "SOLUSDT")
    log.info("Regime classified as TRENDING (ADX=31.4)")
    log.warning("Regime age only 2 candles — confidence -5")
    log.error("ADX calculation failed: not enough data")
    """
    name        = f"signal_engine.{stage}.{symbol}"
    base_logger = logging.getLogger(name)

    if not base_logger.handlers:
        base_logger.setLevel(logging.DEBUG)
        base_logger.propagate = False

        # Console — coloured
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(_ColorFormatter())
        base_logger.addHandler(console_handler)

        # File — plain
        base_logger.addHandler(_get_file_handler())

    return EngineLogger(base_logger, {"stage": stage, "symbol": symbol})


# ── Standalone test block ──────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("logger.py — Standalone Test")
    print("=" * 70)
    print()

    # Test 1: System-level logger (no symbol)
    sys_log = get_logger("SYSTEM")
    sys_log.debug("Debug message — should appear in cyan")
    sys_log.info("Info message — should appear in green")
    sys_log.warning("Warning message — should appear in yellow")
    sys_log.error("Error message — should appear in red")
    sys_log.critical("Critical message — should appear in magenta")
    print()

    # Test 2: Stage + symbol logger
    s0_log = get_logger("STAGE00", "BTCUSDT")
    s0_log.info("Fetched 200 candles from Binance — candle status: CLOSED")
    s0_log.warning("Last candle still FORMING — using candle[-2] as signal candle")

    s3_log = get_logger("REGIME", "SOLUSDT")
    s3_log.info("Regime classified as TRENDING (ADX=31.4, Choppiness=44.2)")

    s14_log = get_logger("PORTFOLIO", "ETHUSDT")
    s14_log.error("Daily loss limit reached: -3.2% — halting all signals")

    print()
    print("="*70)
    print("[OK] Check above for correct format:")
    print("   [YYYY-MM-DD HH:MM:SS UTC] [STAGE] [SYMBOL] LEVEL -- message")
    print("[OK] Check logs/signal_engine.log for plain-text version")
    print("="*70)
