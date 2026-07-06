"""
signal_engine/stage02_time_filter.py
UTC time gate with volume-based override.

Zones:
  BLOCKED  : 22:00–23:59 UTC  OR  00:00–01:59 UTC
  MARGINAL : 02:00–03:59 UTC  → −5 confidence modifier
  CLEAR    : 04:00–21:59 UTC  → no modifier

Override: BLOCKED + vol_z > 2.5 → ALLOWED (tagged TIME_FILTER_OVERRIDE)
"""

import io
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


# ── Result dataclass ───────────────────────────────────────────────────────

@dataclass
class TimeFilterResult:
    current_utc:         datetime
    status:              str    # CLEAR | MARGINAL | BLOCKED | ALLOWED
    confidence_modifier: int    # 0 or −5 (MARGINAL only)
    override_applied:    bool
    reason:              str


# ── Core logic ─────────────────────────────────────────────────────────────

def _classify_hour(hour: int) -> str:
    """
    Classify UTC hour into BLOCKED / MARGINAL / CLEAR.
    Uses explicit OR logic — no range check — to handle midnight boundary correctly.

    BLOCKED  : hour >= 22 OR hour < 2   (22, 23, 0, 1)
    MARGINAL : hour >= 2 AND hour < 4   (2, 3)
    CLEAR    : hour >= 4 AND hour < 22  (4 … 21)
    """
    if hour >= 22 or hour < 2:
        return "BLOCKED"
    if 2 <= hour < 4:
        return "MARGINAL"
    return "CLEAR"


def check_time_filter(
    volume_zscore:    float = 0.0,
    _override_utc:    Optional[datetime] = None,   # for testing only
) -> TimeFilterResult:
    """
    Run the time filter for the current UTC time.

    Parameters
    ----------
    volume_zscore : Current candle volume Z-score (used for BLOCKED override).
    _override_utc : Pass a fixed datetime to simulate a specific hour (test only).
    """
    now   = _override_utc or datetime.now(timezone.utc)
    hour  = now.hour
    zone  = _classify_hour(hour)

    override_threshold = 2.5   # from cfg — hardcoded here to avoid circular import

    # ── BLOCKED ────────────────────────────────────────────────────────────
    if zone == "BLOCKED":
        if volume_zscore > override_threshold:
            return TimeFilterResult(
                current_utc         = now,
                status              = "ALLOWED",
                confidence_modifier = 0,
                override_applied    = True,
                reason              = (
                    f"TIME_FILTER_OVERRIDE — blocked hour {hour:02d}:xx UTC "
                    f"but volume Z-score {volume_zscore:.2f} > {override_threshold} "
                    f"signals an unusual move"
                ),
            )
        return TimeFilterResult(
            current_utc         = now,
            status              = "BLOCKED",
            confidence_modifier = 0,
            override_applied    = False,
            reason              = (
                f"TIME_FILTER_ACTIVE — hour {hour:02d}:xx UTC is in the "
                f"22:00–02:00 dead zone (vol Z-score {volume_zscore:.2f} <= {override_threshold})"
            ),
        )

    # ── MARGINAL ───────────────────────────────────────────────────────────
    if zone == "MARGINAL":
        return TimeFilterResult(
            current_utc         = now,
            status              = "MARGINAL",
            confidence_modifier = -5,
            override_applied    = False,
            reason              = (
                f"MARGINAL_ZONE — hour {hour:02d}:xx UTC is in the 02:00–04:00 "
                f"low-liquidity window — confidence −5"
            ),
        )

    # ── CLEAR ──────────────────────────────────────────────────────────────
    return TimeFilterResult(
        current_utc         = now,
        status              = "CLEAR",
        confidence_modifier = 0,
        override_applied    = False,
        reason              = f"CLEAR — hour {hour:02d}:xx UTC is within active trading hours",
    )


# ── Standalone test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    def _mock(hour: int, minute: int = 30) -> datetime:
        """Build a UTC datetime with a specific hour for simulation."""
        return datetime(2026, 7, 4, hour, minute, 0, tzinfo=timezone.utc)

    scenarios = [
        # (label,                          hour,  vol_z,  expected_status)
        ("1. CLEAR          (12:30 UTC)",  12,    0.5,    "CLEAR"),
        ("2. MARGINAL       (03:00 UTC)",   3,    0.8,    "MARGINAL"),
        ("3. BLOCKED/low vol(23:00 UTC)",  23,    1.2,    "BLOCKED"),
        ("4. BLOCKED/override(23:00 UTC)", 23,    3.1,    "ALLOWED"),
        ("5. Midnight boundary(00:30 UTC)", 0,    0.3,    "BLOCKED"),
    ]

    SEP = "=" * 70
    print(SEP)
    print("stage02_time_filter.py -- 5-Scenario Simulation Test")
    print(SEP)

    all_pass = True
    for label, hour, vol_z, expected in scenarios:
        result = check_time_filter(volume_zscore=vol_z, _override_utc=_mock(hour))
        ok     = result.status == expected
        tick   = "[OK]" if ok else "[FAIL]"
        if not ok:
            all_pass = False

        print(f"\n{tick} {label}")
        print(f"     UTC time          : {result.current_utc.strftime('%H:%M UTC')}")
        print(f"     Volume Z-score    : {vol_z}")
        print(f"     Status            : {result.status}  (expected: {expected})")
        print(f"     Confidence mod    : {result.confidence_modifier:+d}")
        print(f"     Override applied  : {result.override_applied}")
        print(f"     Reason            : {result.reason}")

    print(f"\n{SEP}")
    if all_pass:
        print("[OK] All 5 scenarios produced correct output.")
    else:
        print("[FAIL] One or more scenarios did not match expected status.")
    print(SEP)
