"""
alert_logger.py
Writes structured multi-timeframe alert data to logs/alerts.csv for later
scorecard evaluation.
"""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

def log_alert(
    log_dir: str,
    symbol: str,
    confirmed_direction: str,
    timeframe_agreement: str,
    aligned_conditions: str,
    entry_zone: str,
    stop_loss: str,
    target: str,
    raw_ai_analysis: str
) -> None:
    """
    Appends a triggered alert to logs/alerts.csv.
    """
    log_path = Path(log_dir) / "alerts.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    write_header = not log_path.exists()
    
    row = [
        datetime.now(timezone.utc).isoformat(),
        symbol,
        confirmed_direction,
        timeframe_agreement,
        aligned_conditions,
        entry_zone,
        stop_loss,
        target,
        raw_ai_analysis.replace("\n", " ")  # Keep CSV strictly one row per alert
    ]

    try:
        with open(log_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow([
                    "timestamp_utc", 
                    "symbol", 
                    "confirmed_direction", 
                    "timeframe_agreement", 
                    "aligned_conditions", 
                    "entry_zone", 
                    "stop_loss", 
                    "target", 
                    "raw_ai_analysis"
                ])
            writer.writerow(row)
    except OSError as exc:
        logger.error(f"Failed to write to alerts.csv: {exc}")
