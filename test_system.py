"""
test_system.py — Stage-by-stage verification script

Run individual tests or all at once to verify each component works before
committing to a full live run.

Usage:
    # Run all tests (no API keys needed for stages 1-3)
    python test_system.py

    # Test individual stage
    python test_system.py --stage 1   # Data fetch + indicators
    python test_system.py --stage 2   # Setup detector logic
    python test_system.py --stage 3   # Cooldown manager
    python test_system.py --stage 4   # Claude API (requires ANTHROPIC_API_KEY)
    python test_system.py --stage 5   # Discord webhook (requires DISCORD_WEBHOOK_URL)

Stages 1-3 hit only Binance public endpoints — no API keys required.
"""

import argparse
import os
import sys
import time
from datetime import timezone, datetime

# Ensure emoji / Unicode prints correctly on Windows terminals
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

PASS = "✅ PASS"
FAIL = "❌ FAIL"
SKIP = "⏭️  SKIP"
SEP  = "─" * 56


def header(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


# ---------------------------------------------------------------------------
# Stage 1: Data engine + indicators
# ---------------------------------------------------------------------------

def test_stage1(symbol: str = "XLMUSDT", timeframe: str = "15m") -> bool:
    header("Stage 1 — Data Engine & Indicators")
    from data_engine import fetch_and_calculate

    config = {
        "bb_period": 20, "bb_std": 2.0, "rsi_period": 14,
        "ema_short": 20, "ema_long": 50, "swing_lookback": 50,
        "log_dir": "logs",
    }

    try:
        df = fetch_and_calculate(symbol, timeframe, config)
    except Exception as exc:
        print(f"{FAIL}  fetch_and_calculate raised: {exc}")
        return False

    checks = {
        "DataFrame not empty"       : len(df) > 0,
        "Has 'close' column"        : "close" in df.columns,
        "Has 'bb_upper' column"     : "bb_upper" in df.columns,
        "Has 'rsi' column"          : "rsi" in df.columns,
        "Has 'ema20' column"        : "ema20" in df.columns,
        "Has 'ema50' column"        : "ema50" in df.columns,
        "Has 'swing_high' column"   : "swing_high" in df.columns,
        "BB upper > BB lower"       : (df["bb_upper"].iloc[-1] > df["bb_lower"].iloc[-1]),
        "RSI in [0, 100]"           : 0 <= df["rsi"].iloc[-1] <= 100,
        "EMA20 is finite"           : df["ema20"].iloc[-1] > 0,
        "open_time is datetime"     : hasattr(df["open_time"].iloc[-1], "tzinfo"),
        "log/market_data.csv written": __import__("pathlib").Path("logs/market_data.csv").exists(),
    }

    all_pass = True
    for desc, result in checks.items():
        status = PASS if result else FAIL
        print(f"  {status}  {desc}")
        if not result:
            all_pass = False

    print(f"\n  {symbol}/{timeframe} latest close : {df['close'].iloc[-1]:.6g}")
    print(f"  RSI : {df['rsi'].iloc[-1]:.1f}")
    print(f"  BB  : {df['bb_lower'].iloc[-1]:.6g} / "
          f"{df['bb_middle'].iloc[-1]:.6g} / {df['bb_upper'].iloc[-1]:.6g}")

    return all_pass


# ---------------------------------------------------------------------------
# Stage 2: Setup detector logic
# ---------------------------------------------------------------------------

def test_stage2() -> bool:
    header("Stage 2 — Setup Detector (logic-level unit tests)")

    import numpy as np
    import pandas as pd
    from setup_detector import (
        detect_breakdown, detect_breakout, detect_band_rejection,
        detect_trend_state, detect_rsi_extreme,
    )

    def _make_df(closes, highs=None, lows=None,
                 ema20=None, ema50=None, rsi_val=50.0):
        n = len(closes)
        closes_s = pd.Series(closes, dtype=float)
        highs  = highs  or closes
        lows   = lows   or closes
        bb_m   = closes_s.rolling(20, min_periods=1).mean()
        bb_std = closes_s.rolling(20, min_periods=1).std(ddof=0).fillna(0)
        return pd.DataFrame({
            "close"     : closes,
            "high"      : highs,
            "low"       : lows,
            "bb_upper"  : (bb_m + 2 * bb_std).values,
            "bb_middle" : bb_m.values,
            "bb_lower"  : (bb_m - 2 * bb_std).values,
            "rsi"       : [rsi_val] * n,
            "ema20"     : [ema20 or closes[-1]] * n,
            "ema50"     : [ema50 or closes[-1]] * n,
            "swing_high": [max(closes)] * n,
            "swing_low" : [min(closes)] * n,
        })

    # --- BREAKDOWN: stable price then big drop below lower band ----
    stable = [1.0] * 30
    df_bd = _make_df(stable + [1.0, 1.0, 1.0, 0.85])   # last close breaks below
    breakdown_result = detect_breakdown(df_bd)

    # --- BREAKOUT: stable price then big jump above upper band ----
    df_bo = _make_df(stable + [1.0, 1.0, 1.0, 1.15])
    breakout_result = detect_breakout(df_bo)

    # --- BAND_REJECTION_DOWN: high touched upper, current closed inside ----
    base = [1.0] * 25
    bb_u = 1.05   # approximate upper band for this distribution
    df_rej = _make_df(
        closes = base + [1.0, 1.0, 1.0, 1.0],
        highs  = base + [1.0, 1.0, 1.0, 1.07],    # prev high above upper
        lows   = base + [1.0, 1.0, 1.0, 1.0],
    )
    # Override bb columns and specific cells to make the test deterministic
    df_rej["bb_upper"] = 1.03
    df_rej["bb_lower"] = 0.97
    last_idx  = df_rej.index[-1]
    prev_idx  = df_rej.index[-2]
    df_rej.loc[prev_idx, "high"]   = 1.05   # touched upper on second-to-last candle
    df_rej.loc[last_idx, "close"]  = 1.02   # closed back inside
    rejections = detect_band_rejection(df_rej)

    # --- TREND_STATE ----
    df_up   = _make_df([1.0]*30, ema20=1.05, ema50=1.00)
    df_up["close"]  = 1.10
    df_up["high"]   = df_up["bb_upper"] + 0.01  # testing upper band
    df_down = _make_df([1.0]*30, ema20=0.95, ema50=1.00)
    df_down["close"] = 0.90
    df_down["low"]   = df_down["bb_lower"] - 0.01  # testing lower band
    df_range = _make_df([1.0]*30, ema20=1.01, ema50=0.99)
    df_range["close"] = 1.00
    trend_up    = detect_trend_state(df_up)
    trend_down  = detect_trend_state(df_down)
    trend_range = detect_trend_state(df_range)

    # --- RSI_EXTREME ----
    df_ob = _make_df([1.0]*30, rsi_val=75.0)
    df_os = _make_df([1.0]*30, rsi_val=25.0)
    df_neutral = _make_df([1.0]*30, rsi_val=50.0)

    checks = {
        "detect_breakdown returns bool"       : isinstance(breakdown_result, bool),
        "detect_breakout returns bool"        : isinstance(breakout_result, bool),
        "detect_band_rejection returns list"  : isinstance(rejections, list),
        "BAND_REJECTION_DOWN detected"        : "BAND_REJECTION_DOWN" in rejections,
        "trend_state=uptrend when price>EMA20>EMA50"  : trend_up   == "uptrend",
        "trend_state=downtrend when price<EMA20<EMA50": trend_down  == "downtrend",
        "trend_state=ranging when mixed"              : trend_range == "ranging",
        "RSI 75 → RSI_OVERBOUGHT"            : detect_rsi_extreme(df_ob)  == "RSI_OVERBOUGHT",
        "RSI 25 → RSI_OVERSOLD"              : detect_rsi_extreme(df_os)  == "RSI_OVERSOLD",
        "RSI 50 → None"                      : detect_rsi_extreme(df_neutral) is None,
    }

    all_pass = True
    for desc, result in checks.items():
        status = PASS if result else FAIL
        print(f"  {status}  {desc}")
        if not result:
            all_pass = False

    return all_pass


# ---------------------------------------------------------------------------
# Stage 3: Cooldown manager
# ---------------------------------------------------------------------------

def test_stage3() -> bool:
    header("Stage 3 — Cooldown Manager")
    import os
    from setup_detector import CooldownManager

    test_file = "logs/cooldowns_test_stage3.json"
    # Clean state for test
    if __import__("pathlib").Path(test_file).exists():
        os.remove(test_file)

    mgr = CooldownManager(cooldown_minutes=1, state_file=test_file)

    mgr.record_trigger("BTCUSDT", "15m", "BREAKDOWN")
    on_cd_immediately = mgr.is_on_cooldown("BTCUSDT", "15m", "BREAKDOWN")
    not_on_cd_other   = not mgr.is_on_cooldown("BTCUSDT", "15m", "BREAKOUT")
    not_on_cd_sym     = not mgr.is_on_cooldown("ETHUSDT", "15m", "BREAKDOWN")

    # Reload from disk to verify persistence
    mgr2 = CooldownManager(cooldown_minutes=1, state_file=test_file)
    persisted = mgr2.is_on_cooldown("BTCUSDT", "15m", "BREAKDOWN")

    checks = {
        "On cooldown immediately after trigger"       : on_cd_immediately,
        "Different condition not on cooldown"         : not_on_cd_other,
        "Different symbol not on cooldown"            : not_on_cd_sym,
        "Cooldown persisted after reload from JSON"   : persisted,
        f"State file created at {test_file}"          : __import__("pathlib").Path(test_file).exists(),
    }

    all_pass = True
    for desc, result in checks.items():
        status = PASS if result else FAIL
        print(f"  {status}  {desc}")
        if not result:
            all_pass = False

    # Cleanup
    if __import__("pathlib").Path(test_file).exists():
        os.remove(test_file)

    return all_pass


# ---------------------------------------------------------------------------
# Stage 4: Claude API
# ---------------------------------------------------------------------------

def test_stage4() -> bool:
    header("Stage 4 — Gemini API (ai_analysis.py)")
    import os
    from data_engine import fetch_and_calculate
    from setup_detector import detect_trend_state
    from ai_analysis import get_ai_analysis

    key = os.environ.get("GEMINI_API_KEY", "")
    if not key or key.startswith("your-gemini"):
        print(f"  {SKIP}  GEMINI_API_KEY not set — skipping live API test.")
        print("         Set it in .env and re-run: python test_system.py --stage 4")
        return True   # Not a failure — just skipped

    config = {
        "bb_period": 20, "bb_std": 2.0, "rsi_period": 14,
        "ema_short": 20, "ema_long": 50, "swing_lookback": 50, "log_dir": "logs",
    }

    print("  Fetching XLMUSDT/15m for AI analysis context …")
    df = fetch_and_calculate("XLMUSDT", "15m", config)

    last = df.iloc[-1]
    analysis_data = {
        "symbol": "XLMUSDT",
        "direction": "downtrend",
        "timeframes_data": "--- 15m ---\nTrend: downtrend\nPrice: 0.20\nConditions: RSI_OVERSOLD\nIndicators: BB(0.19/0.20/0.21)\n",
    }

    print("  Calling Gemini API …")
    try:
        analysis = get_ai_analysis(analysis_data)
    except RuntimeError as exc:
        print(f"  {FAIL}  API call raised RuntimeError: {exc}")
        return False

    # Check for the fixed-format labels the prompt requires
    required_fields = ["SYMBOL:", "CONFIRMED DIRECTION:", "TIMEFRAME AGREEMENT:", "ALIGNED CONDITIONS:", "ENTRY ZONE:", "STOP LOSS:", "TARGET:", "NOTE:"]

    checks = {
        "Response is a non-empty string"      : isinstance(analysis, str) and len(analysis) > 20,
        "Response under 1000 chars"           : len(analysis) < 1000,
        **{f"Contains '{f}'"                  : f in analysis for f in required_fields},
    }

    all_pass = True
    for desc, result in checks.items():
        status = PASS if result else FAIL
        print(f"  {status}  {desc}")
        if not result:
            all_pass = False

    print(f"\n  Gemini response ({len(analysis)} chars):")
    for line in analysis.strip().split("\n"):
        print(f"    {line}")

    return all_pass


# ---------------------------------------------------------------------------
# Stage 5: Discord webhook
# ---------------------------------------------------------------------------

def test_stage5() -> bool:
    header("Stage 5 — Discord Webhook (alert_sender.py)")
    import os
    from alert_sender import send_discord_alert

    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url or "YOUR_WEBHOOK" in url:
        print(f"  {SKIP}  DISCORD_WEBHOOK_URL not set — skipping live webhook test.")
        print("         Set it in .env and re-run: python test_system.py --stage 5")
        return True

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    test_analysis = (
        f"🧪 **Test alert** sent from test_system.py at {now}.\n"
        "If you see this in Discord, Stage 5 is working correctly. "
        "This is NOT a real trade setup — it is a system test."
    )

    print("  Sending test Discord alert …")
    success = send_discord_alert(
        symbol="TESTUSDT",
        direction="downtrend",
        price=1.2345,
        ai_analysis=test_analysis,
    )

    status = PASS if success else FAIL
    print(f"  {status}  Discord webhook returned success={success}")
    if success:
        print("         👀 Check your Discord channel for the test message.")

    return success


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_stage(n: int) -> bool:
    runners = {
        1: test_stage1,
        2: test_stage2,
        3: test_stage3,
        4: test_stage4,
        5: test_stage5,
    }
    fn = runners.get(n)
    if fn is None:
        print(f"Unknown stage {n}. Valid: 1-5")
        return False
    return fn()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test individual stages of the Binance Market Monitor"
    )
    parser.add_argument(
        "--stage", type=int, choices=[1, 2, 3, 4, 5],
        help="Run a specific stage (1-5). Omit to run all."
    )
    args = parser.parse_args()

    print("\n" + "=" * 56)
    print("  Binance Market Monitor — System Test")
    print("=" * 56)

    if args.stage:
        ok = run_stage(args.stage)
        print(f"\n{'=' * 56}")
        print(f"  Stage {args.stage}: {'PASSED' if ok else 'FAILED'}")
        print(f"{'=' * 56}\n")
        sys.exit(0 if ok else 1)
    else:
        results = {}
        for n in [1, 2, 3, 4, 5]:
            results[n] = run_stage(n)

        print(f"\n{'=' * 56}")
        print("  SUMMARY")
        print("─" * 56)
        overall = True
        for n, ok in results.items():
            status = PASS if ok else FAIL
            print(f"  Stage {n}: {status}")
            if not ok:
                overall = False
        print(f"{'=' * 56}")
        print(f"  Overall: {'ALL PASSED ✅' if overall else 'SOME FAILED ❌'}")
        print(f"{'=' * 56}\n")
        sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
