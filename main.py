"""
main.py — Stage 6
Orchestrates the continuous monitoring loop.
Loads configuration, schedules polling cycles, and ties together
data_engine → setup_detector → ai_analysis → alert_sender.

Usage:
    python main.py                  # normal continuous run
    python main.py --dry-run        # fetch + detect only, no Claude / Discord calls
    python main.py --once           # run exactly one cycle then exit
    python main.py --dry-run --once # one cycle, no API calls (great for testing)

Or with a custom config file:
    MONITOR_CONFIG=my_config.yaml python main.py
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

from data_engine import fetch_and_calculate
from setup_detector import CooldownManager, detect_trend_state, run_all_detectors
from ai_analysis import get_ai_analysis
from alert_sender import send_discord_alert, send_startup_notification
from alert_logger import log_alert
import yaml

# ---------------------------------------------------------------------------
# Logging setup — console + rotating file
# ---------------------------------------------------------------------------

def setup_logging(log_dir: str = "logs") -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_format = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(log_dir) / "monitor.log", encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=log_format, handlers=handlers)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """
    Load configuration from config.yaml (or MONITOR_CONFIG env var path).
    Environment variables override config file values where applicable.
    """
    config_path = os.environ.get("MONITOR_CONFIG", "config.yaml")
    config: dict = {}

    if Path(config_path).exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        logger.info(f"Loaded config from {config_path}")
    else:
        logger.warning(
            f"Config file '{config_path}' not found. Using defaults + env vars."
        )

    # Defaults (env vars take precedence for secrets)
    config.setdefault("symbols",                ["XLMUSDT", "SOLUSDT", "BTCUSDT"])
    config.setdefault("timeframes",             ["15m", "1h"])
    config.setdefault("poll_interval_minutes",  5)
    config.setdefault("cooldown_minutes",       30)
    config.setdefault("bb_period",              20)
    config.setdefault("bb_std",                 2.0)
    config.setdefault("rsi_period",             14)
    config.setdefault("rsi_overbought",         70.0)
    config.setdefault("rsi_oversold",           30.0)
    config.setdefault("ema_short",              20)
    config.setdefault("ema_long",               50)
    config.setdefault("swing_lookback",         50)
    config.setdefault("log_dir",                "logs")

    return config

# ---------------------------------------------------------------------------
# Single monitoring cycle for one symbol across ALL timeframes
# ---------------------------------------------------------------------------

def process_symbol(symbol: str, timeframes: list[str],
                   config: dict, cooldown_mgr: CooldownManager,
                   dry_run: bool = False) -> None:
    """
    Run one full monitoring cycle for a symbol across ALL configured timeframes.
    Checks for MTF agreement before sending an alert.
    """
    symbol_data = {}
    directions = set()
    all_triggers = set()
    
    # Lowest/shortest timeframe data (used for entry/stop/target generation)
    shortest_tf = timeframes[0]
    shortest_last_candle = None

    for timeframe in timeframes:
        try:
            # Stage 1+2: Fetch + calculate
            df = fetch_and_calculate(symbol, timeframe, config)

            # Ensure we have enough data (warm-up period for indicators)
            required_rows = max(
                config.get("bb_period", 20),
                config.get("rsi_period", 14),
                config.get("ema_long", 50),
            ) + 5
            
            if len(df) < required_rows:
                logger.warning(
                    f"[{symbol}/{timeframe}] Not enough candles ({len(df)} < "
                    f"{required_rows}). Skipping symbol."
                )
                return  # Skip the whole symbol if one timeframe is missing data

            # Stage 3: Detect raw setup triggers (NO COOLDOWN YET)
            triggered = run_all_detectors(df, config)
            all_triggers.update(triggered)

            # Compute strict trend state
            trend = detect_trend_state(df)
            directions.add(trend)

            last = df.iloc[-1]
            
            if timeframe == shortest_tf:
                shortest_last_candle = last

            symbol_data[timeframe] = {
                "trend": trend,
                "triggered": triggered,
                "price": float(last["close"]),
                "bb_upper": float(last["bb_upper"]),
                "bb_middle": float(last["bb_middle"]),
                "bb_lower": float(last["bb_lower"]),
                "rsi": float(last["rsi"]),
                "ema20": float(last["ema20"]),
                "ema50": float(last["ema50"]),
                "swing_high": float(last["swing_high"]),
                "swing_low": float(last["swing_low"]),
                "recent_closes": ", ".join(f"{c:.6g}" for c in df["close"].iloc[-10:].tolist()),
            }
            
            # Small gap between timeframes to avoid hammering Binance
            time.sleep(0.3)

        except RuntimeError as exc:
            logger.error(f"[{symbol}/{timeframe}] Skipped due to error: {exc}")
            return
        except Exception as exc:
            logger.exception(f"[{symbol}/{timeframe}] Unexpected error: {exc}")
            return

    # Check MTF agreement
    if len(directions) != 1 or "ranging" in directions:
        logger.debug(f"[{symbol}/MTF] Checked, no confirmation. Trends: {directions}")
        return

    direction = list(directions)[0]  # "uptrend" or "downtrend"

    # Check for at least ONE fresh trigger across all timeframes
    if not all_triggers:
        logger.debug(f"[{symbol}/MTF] Trend confirmed ({direction}), but no fresh triggers. Skipping.")
        return

    # Apply MTF Cooldown
    condition_key = f"{direction}_{'-'.join(sorted(all_triggers))}"
    if cooldown_mgr.is_on_cooldown(symbol, "MTF", condition_key):
        logger.debug(f"[{symbol}/MTF] {condition_key} is on cooldown. Skipping.")
        return

    # Build the combined multi-timeframe text block
    tf_data_lines = []
    for tf, data in symbol_data.items():
        cond_str = ", ".join(data['triggered']) if data['triggered'] else "None"
        line = (
            f"--- {tf} ---\n"
            f"Trend: {data['trend']}\n"
            f"Price: {data['price']:.6g}\n"
            f"Conditions Triggered: {cond_str}\n"
            f"Indicators: BB({data['bb_lower']:.6g}/{data['bb_middle']:.6g}/{data['bb_upper']:.6g}), "
            f"RSI={data['rsi']:.1f}, EMA20={data['ema20']:.6g}, EMA50={data['ema50']:.6g}, "
            f"SwingHi={data['swing_high']:.6g}, SwingLo={data['swing_low']:.6g}\n"
        )
        tf_data_lines.append(line)

    timeframes_data = "\n".join(tf_data_lines)

    if dry_run:
        # ── DRY RUN: print summary, skip all external API calls ───────────
        print()
        print("=" * 56)
        print(f"  [DRY RUN] {symbol} / MTF CONFIRMED")
        print(f"  Direction  : {direction.upper()}")
        print(f"  Triggers   : {', '.join(all_triggers)}")
        for tf, data in symbol_data.items():
            print(f"  {tf:>4} Trend : {data['trend']} (RSI: {data['rsi']:.1f})")
        print("  → Gemini API call SKIPPED (dry-run mode)")
        print("  → Discord alert  SKIPPED (dry-run mode)")
        print("=" * 56)
        return

    # Stage 4: AI analysis
    logger.info(f"[{symbol}/MTF] 🚀 MTF Setup Confirmed: {direction} with {all_triggers}")
    
    analysis_data = {
        "symbol": symbol,
        "direction": direction,
        "timeframes_data": timeframes_data,
    }
    
    try:
        analysis = get_ai_analysis(analysis_data)
    except RuntimeError as exc:
        logger.error(f"[{symbol}/MTF] AI analysis failed: {exc}")
        analysis = "⚠️ AI analysis unavailable (API error). Review MTF setup manually."

    # Parse out simple fields for CSV logging if possible
    entry_zone = "N/A"
    stop_loss = "N/A"
    target = "N/A"
    tf_agreement = " | ".join(f"{tf}: {data['trend']}" for tf, data in symbol_data.items())
    aligned_cond = ", ".join(all_triggers)
    
    for line in analysis.split("\n"):
        if line.startswith("ENTRY ZONE:"):
            entry_zone = line.split("ENTRY ZONE:")[1].strip()
        elif line.startswith("STOP LOSS:"):
            stop_loss = line.split("STOP LOSS:")[1].strip()
        elif line.startswith("TARGET:"):
            target = line.split("TARGET:")[1].strip()

    # Stage 5: Send Discord alert
    success = send_discord_alert(
        symbol=symbol,
        direction=direction,
        price=float(shortest_last_candle["close"]),
        ai_analysis=analysis,
    )

    if success:
        # Mark cooldown only if alert sent successfully
        cooldown_mgr.record_trigger(symbol, "MTF", condition_key)
        
        # Log to CSV
        log_alert(
            log_dir=config.get("log_dir", "logs"),
            symbol=symbol,
            confirmed_direction=direction,
            timeframe_agreement=tf_agreement,
            aligned_conditions=aligned_cond,
            entry_zone=entry_zone,
            stop_loss=stop_loss,
            target=target,
            raw_ai_analysis=analysis
        )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Binance Market Monitor — AI-assisted trade alerts"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + detect setups but skip Claude API and Discord (no cost, for testing)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run exactly one polling cycle then exit (useful with --dry-run)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # Load .env file first (before config so env vars are available)
    load_dotenv()

    config = load_config()
    setup_logging(config["log_dir"])

    symbols    = config["symbols"]
    timeframes = config["timeframes"]
    poll_secs  = config["poll_interval_minutes"] * 60

    dry_run_tag = "  ⚠️  DRY-RUN MODE — no Gemini / Discord calls\n" if args.dry_run else ""
    once_tag    = "  🔁  SINGLE CYCLE MODE\n" if args.once else ""

    logger.info("=" * 60)
    logger.info("  Binance Market Monitor — Starting")
    if dry_run_tag:
        logger.info(dry_run_tag.strip())
    if once_tag:
        logger.info(once_tag.strip())
    logger.info(f"  Symbols:    {symbols}")
    logger.info(f"  Timeframes: {timeframes}")
    logger.info(f"  Poll every: {config['poll_interval_minutes']} min")
    logger.info(f"  Cooldown:   {config['cooldown_minutes']} min")
    logger.info("=" * 60)

    if not args.dry_run:
        send_startup_notification(symbols, timeframes)

    cooldown_file = (
        str(Path(config["log_dir"]) / "cooldowns_dryrun.json")
        if args.dry_run
        else str(Path(config["log_dir"]) / "cooldowns.json")
    )
    cooldown_mgr = CooldownManager(
        cooldown_minutes=config["cooldown_minutes"],
        state_file=cooldown_file,
    )

    cycle = 0
    while True:
        cycle += 1
        logger.info(f"─── Cycle {cycle} ───────────────────────────────────────")

        for symbol in symbols:
            process_symbol(
                symbol, timeframes, config, cooldown_mgr,
                dry_run=args.dry_run,
            )

        if args.once:
            logger.info("--once flag set. Exiting after single cycle.")
            break

        logger.info(
            f"Cycle {cycle} complete. Sleeping {config['poll_interval_minutes']} min …"
        )
        time.sleep(poll_secs)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nMonitor stopped by user (Ctrl+C).")
        sys.exit(0)

