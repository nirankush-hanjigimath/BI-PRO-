"""
signal_engine/config.py
Loads config.yaml + .env, validates all required keys, exposes `cfg` singleton.
"""

import os
import sys
from dataclasses import dataclass
from typing import List

import yaml
from dotenv import load_dotenv

# ── Project root (one level above this file) ──────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_ROOT, "config.yaml")


# ── Config dataclass ───────────────────────────────────────────────────────

@dataclass
class EngineConfig:
    # Account
    account_size_usd: float

    # Symbols & timeframes
    symbols:    List[str]
    timeframes: List[str]

    # Engine
    run_interval_minutes: int
    default_mode:         str
    max_open_positions:   int
    log_dir:              str
    state_file:           str
    paper_state_file:     str

    # Risk
    risk_per_trade_pct:         float
    daily_loss_limit_pct:       float
    weekly_loss_limit_pct:      float
    cooldown_minutes:           int
    max_cluster_positions:      int
    atr_stop_multiplier:        float
    min_rr_ratio:               float
    high_vol_position_reduction:float
    high_vol_stop_widening:     float

    # Filters
    time_filter_enabled:            bool
    liquidity_gate_enabled:         bool
    spread_threshold_pct:           float
    liquidity_volume_percentile:    int
    liquidity_lookback_days:        int
    time_filter_start_utc:          int
    time_filter_end_utc:            int
    vol_zscore_override_threshold:  float
    marginal_zone_start_utc:        int
    marginal_zone_end_utc:          int
    marginal_zone_confidence_penalty: int

    # Indicators
    bb_period:            int
    bb_std:               float
    rsi_period:           int
    ema_short:            int
    ema_long:             int
    adx_period:           int
    choppiness_period:    int
    atr_period:           int
    atr_timeframe:        str
    volume_zscore_period: int
    swing_lookback:       int
    ema_slope_lookback:   int

    # Confidence
    min_confidence_score: float
    futures_blocked_cap:  float
    confidence_weights:   dict

    # Paper trading
    paper_min_days_before_live: int
    paper_slippage_pct:         float
    paper_summary_utc_hour:     int
    paper_summary_utc_minute:   int

    # Discord routing
    discord_webhook_a_plus: str
    discord_webhook_a: str
    discord_webhook_b: str
    discord_webhook_c: str
    discord_webhook_system: str
    send_grade_c: bool


# ── Validation helpers ─────────────────────────────────────────────────────

def _require_env(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        raise EnvironmentError(
            f"\n[CONFIG ERROR] Required environment variable '{key}' is missing or empty.\n"
            f"Add it to your .env file:\n  {key}=<your_value>\n"
        )
    return val


def _require_yaml(data: dict, *path: str) -> object:
    node = data
    trail = []
    for key in path:
        trail.append(key)
        if not isinstance(node, dict) or key not in node:
            raise KeyError(
                f"\n[CONFIG ERROR] Missing required key in config.yaml: '{' > '.join(trail)}'\n"
                f"Add it under the correct section in config.yaml.\n"
            )
        node = node[key]
    return node


# ── Loader ────────────────────────────────────────────────────────────────

def _load() -> EngineConfig:
    # 1. Load .env
    load_dotenv(os.path.join(_ROOT, ".env"))

    # 2. Load config.yaml
    if not os.path.exists(_CONFIG_PATH):
        raise FileNotFoundError(
            f"\n[CONFIG ERROR] config.yaml not found at: {_CONFIG_PATH}\n"
        )
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        y = yaml.safe_load(f)

    # 3. Discord webhooks from .env
    webhook_a_plus = os.getenv("DISCORD_WEBHOOK_A_PLUS", "")
    webhook_a = os.getenv("DISCORD_WEBHOOK_A", "")
    webhook_b = os.getenv("DISCORD_WEBHOOK_B", "")
    webhook_c = os.getenv("DISCORD_WEBHOOK_C", "")
    webhook_system = _require_env("DISCORD_WEBHOOK_SYSTEM")  # At least system is required

    # 4. Validate required yaml sections
    for section in ("account", "engine", "symbols", "risk", "filters",
                    "indicators", "confidence", "paper_trading"):
        _require_yaml(y, section)

    # 5. Build and return config
    r  = y["risk"]
    fi = y["filters"]
    e  = y["engine"]
    i  = y["indicators"]
    c  = y["confidence"]
    p  = y["paper_trading"]
    a  = y["account"]

    return EngineConfig(
        # Account
        account_size_usd = float(a["size_usd"]),

        # Symbols
        symbols    = list(y["symbols"]),
        timeframes = list(y.get("timeframes", ["15m", "1h", "4h"])),

        # Engine
        run_interval_minutes = int(e["run_interval_minutes"]),
        default_mode         = str(e["default_mode"]),
        max_open_positions   = int(e["max_open_positions"]),
        log_dir              = str(e.get("log_dir", "logs")),
        state_file           = str(e.get("state_file", "engine_state.json")),
        paper_state_file     = str(e.get("paper_state_file", "paper_state.json")),

        # Risk
        risk_per_trade_pct          = float(r["per_trade_pct"]),
        daily_loss_limit_pct        = float(r["daily_loss_limit_pct"]),
        weekly_loss_limit_pct       = float(r["weekly_loss_limit_pct"]),
        cooldown_minutes            = int(r["cooldown_minutes"]),
        max_cluster_positions       = int(r["max_cluster_positions"]),
        atr_stop_multiplier         = float(r["atr_stop_multiplier"]),
        min_rr_ratio                = float(r["min_rr_ratio"]),
        high_vol_position_reduction = float(r["high_vol_position_reduction"]),
        high_vol_stop_widening      = float(r["high_vol_stop_widening"]),

        # Filters
        time_filter_enabled              = bool(fi["time_filter_enabled"]),
        liquidity_gate_enabled           = bool(fi["liquidity_gate_enabled"]),
        spread_threshold_pct             = float(fi["spread_threshold_pct"]),
        liquidity_volume_percentile      = int(fi["liquidity_volume_percentile"]),
        liquidity_lookback_days          = int(fi["liquidity_lookback_days"]),
        time_filter_start_utc            = int(fi["time_filter_start_utc"]),
        time_filter_end_utc              = int(fi["time_filter_end_utc"]),
        vol_zscore_override_threshold    = float(fi["vol_zscore_override_threshold"]),
        marginal_zone_start_utc          = int(fi["marginal_zone_start_utc"]),
        marginal_zone_end_utc            = int(fi["marginal_zone_end_utc"]),
        marginal_zone_confidence_penalty = int(fi["marginal_zone_confidence_penalty"]),

        # Indicators
        bb_period            = int(i["bb_period"]),
        bb_std               = float(i["bb_std"]),
        rsi_period           = int(i["rsi_period"]),
        ema_short            = int(i["ema_short"]),
        ema_long             = int(i["ema_long"]),
        adx_period           = int(i["adx_period"]),
        choppiness_period    = int(i["choppiness_period"]),
        atr_period           = int(i["atr_period"]),
        atr_timeframe        = str(i["atr_timeframe"]),
        volume_zscore_period = int(i["volume_zscore_period"]),
        swing_lookback       = int(i["swing_lookback"]),
        ema_slope_lookback   = int(i["ema_slope_lookback"]),

        # Confidence
        min_confidence_score = float(c["min_score"]),
        futures_blocked_cap  = float(c["futures_blocked_cap"]),
        confidence_weights   = dict(c["weights"]),

        # Paper trading
        paper_min_days_before_live = int(p["min_days_before_live"]),
        paper_slippage_pct         = float(p["slippage_pct"]),
        paper_summary_utc_hour     = int(p["daily_summary_utc_hour"]),
        paper_summary_utc_minute   = int(p["daily_summary_utc_minute"]),

        # Discord
        discord_webhook_a_plus = webhook_a_plus,
        discord_webhook_a = webhook_a,
        discord_webhook_b = webhook_b,
        discord_webhook_c = webhook_c,
        discord_webhook_system = webhook_system,
        send_grade_c = bool(y.get("discord", {}).get("send_grade_c", False)),
    )


# ── Singleton ──────────────────────────────────────────────────────────────

try:
    cfg: EngineConfig = _load()
except (EnvironmentError, KeyError, FileNotFoundError) as _e:
    print(str(_e), file=sys.stderr)
    sys.exit(1)


# ── Standalone test block ──────────────────────────────────────────────────

if __name__ == "__main__":
    import io
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    W = 42
    SEP = "=" * 70

    def row(label, value):
        print(f"  {label:<{W}} {value}")

    print(SEP)
    print("config.py -- Loaded Configuration")
    print(SEP)

    print("\n[ACCOUNT]")
    row("account_size_usd",              f"${cfg.account_size_usd:,.2f}")

    print("\n[SYMBOLS & TIMEFRAMES]")
    row("symbols",                       ", ".join(cfg.symbols))
    row("timeframes",                    ", ".join(cfg.timeframes))

    print("\n[ENGINE]")
    row("run_interval_minutes",          cfg.run_interval_minutes)
    row("default_mode",                  cfg.default_mode)
    row("max_open_positions",            cfg.max_open_positions)
    row("log_dir",                       cfg.log_dir)
    row("state_file",                    cfg.state_file)
    row("paper_state_file",              cfg.paper_state_file)

    print("\n[RISK]")
    row("risk_per_trade_pct",            f"{cfg.risk_per_trade_pct}%")
    row("daily_loss_limit_pct",          f"-{cfg.daily_loss_limit_pct}%")
    row("weekly_loss_limit_pct",         f"-{cfg.weekly_loss_limit_pct}%")
    row("cooldown_minutes",              cfg.cooldown_minutes)
    row("max_cluster_positions",         cfg.max_cluster_positions)
    row("atr_stop_multiplier",           cfg.atr_stop_multiplier)
    row("min_rr_ratio",                  cfg.min_rr_ratio)
    row("high_vol_position_reduction",   f"{cfg.high_vol_position_reduction*100:.0f}%")
    row("high_vol_stop_widening",        f"{cfg.high_vol_stop_widening*100:.0f}%")

    print("\n[FILTERS]")
    row("time_filter_enabled",           cfg.time_filter_enabled)
    row("time_filter_window",            f"{cfg.time_filter_start_utc}:00–{cfg.time_filter_end_utc}:00 UTC")
    row("vol_zscore_override",           f"> {cfg.vol_zscore_override_threshold}")
    row("marginal_zone",                 f"{cfg.marginal_zone_start_utc}:00–{cfg.marginal_zone_end_utc}:00 UTC ({cfg.marginal_zone_confidence_penalty} penalty)")
    row("liquidity_gate_enabled",        cfg.liquidity_gate_enabled)
    row("liquidity_volume_percentile",   f"P{cfg.liquidity_volume_percentile} of {cfg.liquidity_lookback_days}-day history")
    row("spread_threshold_pct",          f"< {cfg.spread_threshold_pct}%")

    print("\n[INDICATORS]")
    row("bb_period / bb_std",            f"{cfg.bb_period} / {cfg.bb_std}")
    row("rsi_period",                    cfg.rsi_period)
    row("ema_short / ema_long",          f"{cfg.ema_short} / {cfg.ema_long}")
    row("adx_period",                    cfg.adx_period)
    row("choppiness_period",             cfg.choppiness_period)
    row("atr_period / atr_timeframe",    f"{cfg.atr_period} / {cfg.atr_timeframe}")
    row("volume_zscore_period",          cfg.volume_zscore_period)
    row("swing_lookback",                f"{cfg.swing_lookback} candles each side")
    row("ema_slope_lookback",            f"{cfg.ema_slope_lookback} candles")

    print("\n[CONFIDENCE]")
    row("min_confidence_score",          cfg.min_confidence_score)
    row("futures_blocked_cap",           cfg.futures_blocked_cap)
    print("  Weights:")
    for layer, weight in cfg.confidence_weights.items():
        row(f"    {layer}", f"{weight}%")

    print("\n[PAPER TRADING]")
    row("min_days_before_live",          cfg.paper_min_days_before_live)
    row("slippage_pct",                  f"{cfg.paper_slippage_pct}%")
    row("daily_summary_time",            f"{cfg.paper_summary_utc_hour:02d}:{cfg.paper_summary_utc_minute:02d} UTC")

    print("\n[DISCORD]")
    row("webhook_a_plus", bool(cfg.discord_webhook_a_plus))
    row("webhook_a", bool(cfg.discord_webhook_a))
    row("webhook_b", bool(cfg.discord_webhook_b))
    row("webhook_c", bool(cfg.discord_webhook_c))
    row("webhook_system", bool(cfg.discord_webhook_system))
    row("send_grade_c", cfg.send_grade_c)

    print(f"\n{SEP}")
    print("[OK] All config values loaded and validated successfully.")
    print(SEP)
