# Institutional Crypto Signal Engine - Technical Handover

# 1. Project Overview

*   **Project name:** Institutional Crypto Signal Engine
*   **Purpose:** To automate the detection, validation, and delivery of high-probability cryptocurrency trading signals across multiple timeframes with institutional-grade risk management and strict market structure alignment.
*   **Problem it solves:** Replaces a legacy, LLM-driven trading script with a deterministic, math-heavy, 14-stage quant pipeline that eliminates emotion, enforces strict liquidity/volume criteria, restricts execution based on global BTC regime, and outputs scored trades via Discord webhooks.
*   **Target users:** Quant developers, algorithmic traders, and portfolio managers managing institutional capital in crypto derivatives.
*   **Current development stage:** Advanced Stage (Feature Complete for Paper Trading/Alerting). The core 14-stage engine, Discord integration, mock backtester, and paper trader are fully built. Live execution logic is intentionally disconnected/mocked for safety.
*   **Overall architecture:**
    *   A continuous daemon process running a polling loop every 15 minutes (`schedule` library).
    *   Parallel processing (via `joblib`) to concurrently analyze a configured basket of assets.
    *   A rigid, immutable 14-stage procedural pipeline where each stage returns a strongly-typed `dataclass` that feeds into the next.
    *   Persistent flat-file JSON state (`engine_state.json`, `paper_state.json`) for tracking cooldowns, portfolio limits, and trade history.
*   **Tech stack:**
    *   **Language:** Python 3.10+
    *   **Data Handling:** `pandas`, `numpy`
    *   **Concurrency & Scheduling:** `joblib`, `schedule`
    *   **Networking:** `requests` (for REST API calls to Binance/Bybit/Discord)
    *   **Configuration:** `python-dotenv`, `pyyaml`
*   **Repository structure:**
    *   Root: Entry points (`run_signal_engine.py`, legacy `main.py`), config files (`config.yaml`, `.env`).
    *   `signal_engine/`: The core pipeline. Contains `models.py`, `config.py`, `paper_trader.py`, and the 14 `stageXX_*.py` files.
    *   `signal_engine/utils/`: Math-heavy indicator logic (`indicators.py`), swing point calculation (`swing_points.py`), and helpers.
    *   `signal_engine/backtester/`: Environment for 3-year historical walk-forward simulation.

---

# 2. Business Logic

## Workflow & System Flow
The engine executes on a cron-like schedule, waking up at the close of every 15-minute candle (e.g., xx:00, xx:15, xx:30, xx:45). 
1.  **Global Checks:** It updates the 7-day correlation matrix (Stage 05) and calculates the BTC Macro environment (Stage 04).
2.  **Parallel Execution:** The engine spawns parallel workers for every symbol in `config.yaml` using `joblib`.
3.  **Pipeline Gauntlet (Stages 00-14):**
    *   Fetches OHLCV data.
    *   Checks liquidity and trading hours. If failed, **Hard Reject**.
    *   Determines trend regime.
    *   Checks Relative Strength vs BTC.
    *   Checks Trend Quality and Volume profiles.
    *   Analyzes derivatives (OI/Funding).
    *   Identifies nearest Support/Resistance and checks if the trade has room to breathe.
    *   Waits for specific candlestick entry patterns (e.g., Engulfing, Break & Retest).
    *   Scores all accumulated data out of 100 points (Stage 12). If score < 60, **Hard Reject**.
4.  **Portfolio Risk Check (Stage 14):** Checks if daily/weekly loss limits are hit, if max open positions are exceeded, or if the asset is in a 30-min cooldown.
5.  **Output:** If approved, it registers the trade in the Paper Trader and fires a rich Discord Webhook with entry, stops, targets, and risks.

## User Journey
The user does not interact with a GUI. The user acts as an administrator modifying `config.yaml` to adjust asset baskets, risk allocations, and confidence weights. The user consumes the output asynchronously via Discord, reading the highly detailed embed cards to decide whether to execute the trade manually on their exchange terminal (or monitor the paper trader's performance).

## Core Features
*   **Multi-Timeframe Alignment:** Requires 4h, 1h, and 15m trends to align before entry.
*   **Deterministic Grading:** A strict 100-point scoring system (A+, A, B, C) based on weighted metrics.
*   **Dynamic Stop-Loss:** Sizes stops dynamically using 1.5x ATR, widening if the 30-day Realized Volatility indicates a high-vol environment, or snapping to structural swing lows/highs if they are further away.
*   **Correlation Clustering:** Groups assets dynamically based on a rolling 7-day Pearson correlation matrix to prevent over-exposure to a single market movement (e.g., rejecting a UNI trade if LDO and AAVE are already open).

## Edge Cases & Current Limitations
*   **API Rate Limits:** Running 20+ symbols fetching 15m, 1h, 4h data plus Bybit derivatives concurrently can trigger HTTP 429s. The system relies on small sleeps and retry loops to mitigate this.
*   **Data Staleness:** If the correlation matrix fails to update, it defaults to assuming *all* assets are correlated (fail-safe).
*   **Bybit API Failures:** Stage 09 gracefully degrades. If Bybit is down, it proceeds without the OI/Funding modifier rather than crashing the pipeline.

---

# 3. Folder Structure & 4. Backend (Pipeline Deep Dive)

## Root Directory

### `run_signal_engine.py`
*   **Purpose:** The main entry point and orchestrator for the entire 14-stage pipeline.
*   **Responsibility:** Schedules the cron loop, handles parallel processing, manages the global BTC macro state, catches outer-loop exceptions, and logs fatal crashes.
*   **Dependencies:** `joblib`, `schedule`, `signal_engine.*`
*   **Functions/Classes:**
    *   `analyze_symbol()`: The wrapper function executed by joblib for each symbol. Contains the massive `try/except` block that sequentially calls `stage00` through `stage14`.
    *   `_run_direction()`: Evaluates the pipeline for a specific direction (LONG or SHORT) against the fetched data.
    *   `main_loop()`: Wakes up every 15 minutes, updates the correlation matrix, fetches BTC data, and triggers `Parallel()`.
*   **How it interacts:** Imports every stage from `signal_engine/` and feeds the output of one stage as arguments to the next.

### `config.yaml`
*   **Purpose:** The single source of truth for hyper-parameters.
*   **Contents:** Lists `symbols`, `risk_limits` (max positions, daily/weekly drawdowns), `confidence_weights` (how much the 100-point scale values Volume vs. Regime vs. BTC Macro), and `webhooks`.
*   **Design Decision:** Extracted from code to allow users to tweak the quant model without touching Python.

### `main.py` & `ai_analysis.py` (Legacy)
*   **Purpose:** Leftovers from the old V1 version of the project.
*   **What it does:** Uses a basic 5-stage setup with Google Gemini/OpenRouter to generate trading narratives based on raw technical data. 
*   **Note:** Kept for reference but largely superseded by the deterministic Institutional Signal Engine.

## Directory: `signal_engine/`

### `config.py`
*   **Purpose:** Configuration loader and validator.
*   **Responsibility:** Reads `config.yaml` and `.env`, injecting them into a strongly-typed `EngineConfig` dataclass singleton.
*   **Classes:** `EngineConfig`
*   **Variables affecting trading:** Exposes `cfg.symbols`, `cfg.confidence_weights`, `cfg.risk_limits`.

### `models.py`
*   **Purpose:** The nervous system of the architecture. Defines the immutable data contracts.
*   **Responsibility:** Ensures that Stage 3 outputs a `RegimeState` object with guaranteed fields. NEVER change these without changing the stages that consume them.
*   **Classes:** `BTCMacro`, `RegimeState`, `RelativeStrength`, `FuturesData`, `SRLevels`, `EntrySignal`, `ConfidenceScore`, `Signal`.

### `stage00_data_fetcher.py`
*   **Purpose:** Acquires market data from Binance and Bybit.
*   **How it works:** Implements a robust `requests` wrapper with a 60-second in-memory cache to prevent spamming the exchange when multiple stages need the same 1h candle data.
*   **Functions:** 
    *   `fetch_ohlcv(symbol, interval, limit)`: Returns a pandas DataFrame with datetime indexing.

### `stage01_liquidity_gate.py`
*   **Purpose:** Prevents trading on illiquid or manipulated assets. (Hard Reject stage).
*   **Algorithm:** 
    1. Looks at the last 24 hours of volume.
    2. Sorts the volumes and finds the 40th percentile (P40).
    3. Requires the *current* candle's volume to be > P40 * configured multiplier.
    4. Requires Bid/Ask spread < 0.2%.
*   **Variables:** `current_volume_usd`, `current_spread_pct`.

### `stage02_time_filter.py`
*   **Purpose:** Prevents trading during dead hours (e.g., Asian session chop).
*   **Algorithm:** Checks current UTC time against allowed windows in `config.yaml`.
*   **Exception Logic:** If the market is technically "closed" but the 15m volume Z-score is > 2.5 (massive sudden volume), it overrides the block and allows the trade.

### `stage03_regime.py`
*   **Purpose:** Multi-timeframe trend classification.
*   **How it works:** Analyzes 4h, 1h, and 15m data using ADX, Choppiness Index, and Bollinger Band Width. 
*   **Internal logic:** 
    *   If ADX > 25 and Choppiness < 38.2 -> TRENDING.
    *   If BBWidth is at the 10th percentile of its 720-candle history -> SQUEEZE.
    *   Assigns a point system (+2 for 4h trend, +1 for 1h trend) to classify the global asset regime.

### `stage04_btc_macro.py`
*   **Purpose:** Evaluates Bitcoin as a global filter.
*   **How it works:** Looks at BTC 1h and 4h EMA slopes, RSI, and Volume. Calculates a net score from -8 to +8.
*   **Output:** Returns a base modifier applied to ALL downstream altcoin trades (e.g., if BTC is `STRONGLY_BEARISH`, LONG signals get a -30 point penalty, causing an automatic rejection).

### `stage05_relative_strength.py`
*   **Purpose:** Ensures the engine only buys the strongest assets and shorts the weakest.
*   **How it works:** Computes the % return of the asset vs BTC over the last 1h and 4h. 
*   **Correlation:** Also pulls 7 days of 1h close data for all tracked symbols, running `df.corr(method="pearson")` to build a matrix. Groups symbols with > 0.75 correlation into clusters, saving this to `engine_state.json`.

### `stage06_trend_quality.py`
*   **Purpose:** Deep analysis of the asset's EMAs and market structure.
*   **How it works:** 
    *   Checks if the EMA50 slope is flat (slope < 0.05% of price).
    *   Determines if price is overextended (Distance from EMA50 > 3 ATR -> -8 penalty; > 5 ATR -> -15 penalty).
    *   Evaluates consecutive candles on the same side of the EMA50 to determine trend persistence.

### `stage07_volume.py`
*   **Purpose:** Volume health and divergence tracking on the 15m chart.
*   **Algorithms:**
    *   **Z-Score:** Classifies volume (e.g., > 2.0 = VOLUME_CLIMAX).
    *   **Divergence:** Checks if the last 3 candles have rising closes but falling volume (Divergence penalty -10).
    *   **Exhaustion:** Checks if a VOLUME_CLIMAX occurs exactly as a 3-candle trend reverses.

### `stage08_volatility.py`
*   **Purpose:** Stop loss and position sizing engine.
*   **Internal Logic (Math):** 
    *   Calculates 7-day and 30-day annualized realized volatility using log returns: `std * sqrt(candles_per_year) * 100`.
    *   If 7-day RV > 2 * 30-day RV, tags a "High Vol Environment".
    *   **Stop Loss:** `max(1.5 * ATR, distance_to_nearest_swing_low)`.
    *   **Position Sizing:** Risks exactly 1% of the $1,000 portfolio. If in a high-vol environment, reduces risk to 0.7%. Size = Risk USD / Stop Loss %.

### `stage09_futures.py`
*   **Purpose:** Derivatives data gating.
*   **Dependencies:** Bybit Public API.
*   **Logic:**
    *   If Open Interest is rising while price rises -> REAL DEMAND (+8 points).
    *   If L/S ratio > 70% -> CROWDED LONG (-8 points, squeeze risk).
    *   If Funding Rate is highly positive -> LONGS PAYING (-8 points).

### `stage10_support_resistance.py`
*   **Purpose:** Validates trade targets and blocks trades hitting walls.
*   **Algorithm:** 
    *   Collects all 15m swing highs/lows and Daily/Weekly highs/lows.
    *   Clusters them into Liquidity Zones (if within 0.5% of each other).
    *   If the nearest resistance is < 0.8% away for a LONG, **Hard Reject**.
    *   If Target 1 (e.g. 2R) exceeds a major resistance, Target 1 is aggressively pulled down to sit exactly at the resistance level. It then recalculates the R:R ratio. If R:R drops below 1.8 -> **Hard Reject**.

### `stage11_entry_confirmation.py`
*   **Purpose:** Candlestick pattern detection for sniper entries.
*   **Algorithm:** 
    *   Measures current candle body against the 10-period average body. If body < 10% of candle range -> Doji (Reject).
    *   Searches for 4 specific patterns: Engulfing, Break & Retest (price broke S/R recently and pulled back to within 0.3% of it), Continuation Pullback (pulled back to EMA20), Strong Breakout (closing above resistance with high volume).

### `stage12_confidence.py`
*   **Purpose:** The Brain. Aggregates the pipeline.
*   **How it works:** Imports `cfg.confidence_weights` (e.g., Trend=20%, Macro=15%, S/R=10%). Normalizes all the modifiers from previous stages.
*   **Scoring:** 
    *   < 60 = REJECT
    *   60-74 = C Grade
    *   75-84 = B Grade
    *   85-94 = A Grade
    *   95+ = A+ Grade

### `stage13_signal_output.py`
*   **Purpose:** Formatting and dispatching to Discord.
*   **Logic:** Assembles the `Signal` dataclass. Uses `narrative.py` to write a human-readable explanation of why the trade was taken. Posts a rich embed with color-coded layers. Includes deduplication logic (blocks identical signals sent within 10 minutes).

### `stage14_portfolio_risk.py`
*   **Purpose:** The final gatekeeper.
*   **State:** Interacts directly with `paper_state.json`.
*   **Rules Enforced:** 
    *   Max 4 open positions globally.
    *   Max 2 open positions from the same correlation cluster.
    *   30-minute cooldown on a symbol after it closes.
    *   If Daily PnL hits -3.0%, halts all trading until UTC midnight.
    *   If Weekly PnL hits -8.0%, halts all trading until Monday.

### `paper_trader.py`
*   **Purpose:** Simulates live execution.
*   **How it works:** Registers trades. Checks current prices against the open positions to simulate Stop Loss, Target 1 (50% close, stop to BE), and Target 2 hits. Applies a hardcoded 0.05% slippage on entry. Sends a daily PnL summary embed at 23:50 UTC.

## Directory: `signal_engine/utils/`

### `indicators.py`
*   **Purpose:** Pure numpy/pandas implementation of TA. Zero external TA dependencies.
*   **Functions:** `ema`, `ema_slope`, `rsi`, `atr`, `bollinger_bands`, `adx`, `choppiness_index`, `volume_zscore`, `realized_volatility`, `bbwidth_percentile`. All meticulously use Wilder's Smoothing where appropriate to match TradingView standards.

### `swing_points.py`
*   **Purpose:** Structure logic.
*   **Algorithm:** 
    *   `find_swing_highs`: Scans array. A point is a swing high if it's strictly higher than the 5 candles to its left and 5 candles to its right.
    *   `classify_swing_structure`: Evaluates the sequence of the last 3 highs/lows to label structure as HH_HL (Higher Highs, Higher Lows), LH_LL, MIXED, etc.

### `narrative.py`
*   **Purpose:** Contains pre-written text templates for long and short trades. Returns a formatted string injecting variables like volume Z-scores and confidence scores to give the Discord output a professional "Quant Voice".

### `alerts.py`
*   **Purpose:** Webhook router. Maps grades (A+, A, B) to specific Discord channel URLs defined in `config.yaml`.

## Directory: `signal_engine/backtester/`

### `engine.py`
*   **Purpose:** Time-machine simulator.
*   **How it works:** Iterates over 3 years of 15m historical data row-by-row. Uses `unittest.mock.patch` to violently hijack the `run_signal_engine.py` functions (`fetch_ohlcv`, `analyze_futures`, `check_liquidity`), injecting perfectly sliced historical DataFrames to prevent lookahead bias. Tracks gross PnL, net PnL (0.04% maker fee assumption), and R-Multiples for every trade.

### `data_loader.py` & `report.py`
*   **Purpose:** Helper scripts. `data_loader` downloads Binance CSV zips and parses them into pandas DataFrames. `report.py` calculates Sharpe Ratio, Profit Factor, Max Drawdown, and Win Rate, outputting a formatted terminal summary of the backtest.
