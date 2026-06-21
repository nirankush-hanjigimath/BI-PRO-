# Binance Market Monitor — AI-Assisted Trade Alerts

A Python application that continuously monitors Binance Futures (USDT-M perpetuals),
computes technical indicators, detects rule-based trading setups, and sends
AI-analysed alerts to Discord via the Claude API.

> **⚠️ No trades are placed automatically.**  
> This is an alert-only system. All execution decisions are made manually by the user.

---

## Features

| Feature | Detail |
|---|---|
| **Data Source** | Binance Futures public REST API (no API key needed) |
| **Indicators** | Bollinger Bands (20/2σ), RSI-14, EMA 20/50, Swing High/Low |
| **Setup Conditions** | BREAKDOWN, BREAKOUT, BAND_REJECTION_UP/DOWN, RSI_EXTREME |
| **AI Model** | `claude-sonnet-4-6` via Anthropic API |
| **Alerts** | Discord webhook (formatted, with emoji) |
| **Cooldown** | Per condition/symbol/timeframe, JSON-persisted across restarts |
| **Logging** | CSV (market data), rotating log file, cooldown state JSON |
| **Deployment** | Local Python, Docker, or systemd on a Linux VPS |

---

## Project Structure

```
Binance Trading/
├── data_engine.py           # Stage 1+2: Fetching & indicators
├── setup_detector.py        # Stage 3: Rule-based detection + cooldown
├── ai_analysis.py           # Stage 4: Claude API call + prompt
├── alert_sender.py          # Stage 5: Discord webhook delivery
├── main.py                  # Stage 6: Orchestration loop
├── config.yaml              # All tunable parameters
├── .env.example             # Secret keys template
├── requirements.txt
├── Dockerfile
├── binance_monitor.service  # systemd unit for VPS hosting
└── README.md
```

---

## Quick Start (Local)

### 1. Clone / copy the project folder

```bash
cd "Binance Trading"
```

### 2. Create a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` and fill in:

```dotenv
ANTHROPIC_API_KEY=sk-ant-...      # see below
DISCORD_WEBHOOK_URL=https://...   # see below
```

### 5. Adjust `config.yaml` (optional)

Edit the symbols list, timeframes, cooldown window, etc. to suit your strategy.

### 6. Run

```bash
python main.py
```

You will see live console output and a startup message in your Discord channel.

---

## Getting an Anthropic API Key

1. Go to [https://console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)
2. Sign in or create an account
3. Click **Create Key**, give it a name (e.g. `binance-monitor`)
4. Copy the key and paste it as `ANTHROPIC_API_KEY` in your `.env`

> **Cost note:** Each alert triggers one Claude API call with max 500 tokens output.  
> With default cooldowns and a few symbols, monthly cost should be well under $5.

---

## Getting a Discord Webhook URL

1. Open Discord and go to your private server (create one if needed — it's free)
2. Right-click the channel you want alerts in → **Edit Channel**
3. Go to **Integrations** → **Webhooks** → **New Webhook**
4. Give it a name (e.g. `Crypto Alerts`) and click **Copy Webhook URL**
5. Paste it as `DISCORD_WEBHOOK_URL` in your `.env`

---

## Configuration Reference (`config.yaml`)

| Key | Default | Description |
|---|---|---|
| `symbols` | `[XLMUSDT, SOLUSDT, BTCUSDT, ETHUSDT]` | Binance Futures pairs to monitor |
| `timeframes` | `[15m, 1h]` | Candlestick intervals |
| `poll_interval_minutes` | `5` | How often to fetch + check |
| `cooldown_minutes` | `30` | Min gap between identical alerts |
| `bb_period` | `20` | Bollinger Band SMA period |
| `bb_std` | `2.0` | Bollinger Band std multiplier |
| `rsi_period` | `14` | RSI lookback |
| `rsi_overbought` | `70.0` | RSI overbought threshold |
| `rsi_oversold` | `30.0` | RSI oversold threshold |
| `ema_short` | `20` | Short EMA span |
| `ema_long` | `50` | Long EMA span |
| `swing_lookback` | `50` | Candles for swing high/low |
| `log_dir` | `logs` | Directory for all log files |

---

## Setup Detection Logic

### BREAKDOWN
Latest close crosses **below** the lower Bollinger Band, AND the previous 3 candles
were all **inside** the bands. Suggests momentum breakdown / volatility expansion downward.

### BREAKOUT
Latest close crosses **above** the upper Bollinger Band, AND the previous 3 candles
were all **inside** the bands. Suggests momentum breakout / volatility expansion upward.

### BAND_REJECTION_DOWN
Previous candle's **high** touched or exceeded the upper band, and the latest candle
closed **back inside** the bands. Potential reversal / rejection from resistance.

### BAND_REJECTION_UP
Previous candle's **low** touched or exceeded the lower band, and the latest candle
closed **back inside** the bands. Potential reversal / rejection from support.

### RSI_EXTREME
RSI crosses into overbought (>70) or oversold (<30) territory.

---

## Output Files (`logs/` directory)

| File | Contents |
|---|---|
| `market_data.csv` | Every fetch: timestamp, symbol, timeframe, latest close |
| `monitor.log` | Full application log (info + errors) |
| `cooldowns.json` | Persisted cooldown state (survives restarts) |

---

## Deployment: Docker

```bash
# Build
docker build -t binance-monitor .

# Run (pass secrets as env vars — do NOT commit .env into Docker images)
docker run -d \
  --name binance-monitor \
  --restart unless-stopped \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... \
  -v $(pwd)/logs:/app/logs \
  binance-monitor
```

### View logs
```bash
docker logs -f binance-monitor
```

---

## Deployment: Oracle Cloud Free Tier (Ubuntu 22.04)

Oracle Cloud provides a **permanently free** 4-core ARM VM with 24 GB RAM.

### 1. Provision a VM
- Sign up at [cloud.oracle.com](https://cloud.oracle.com) (requires credit card for verification, not charged)
- Create an instance: **Ampere A1 Compute** → Ubuntu 22.04 → 4 OCPUs, 24 GB RAM (all free-tier)
- Download the SSH key

### 2. SSH into the VM
```bash
ssh -i ~/your-key.key ubuntu@YOUR_VM_PUBLIC_IP
```

### 3. Set up Python & the app
```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv git

git clone YOUR_REPO_URL binance-monitor
cd binance-monitor

python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env   # paste your API keys
```

### 4. Install as a systemd service
```bash
# Edit the service file to match your paths
nano binance_monitor.service

sudo cp binance_monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable binance-monitor
sudo systemctl start binance-monitor

# Check status
sudo systemctl status binance-monitor

# Live logs
journalctl -u binance-monitor -f
```

---

## Deployment: Railway (easiest — 1-click)

1. Push the project to a GitHub repository
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Select your repo
4. Go to **Variables** tab and add:
   - `ANTHROPIC_API_KEY`
   - `DISCORD_WEBHOOK_URL`
5. Railway auto-detects the Dockerfile and deploys it

Free tier: 500 hours/month (enough for ~21 days continuous — upgrade for full month).

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `ANTHROPIC_API_KEY is not set` | Make sure `.env` exists and is in the project root |
| `DISCORD_WEBHOOK_URL is not set` | Check `.env` — the value must start with `https://discord.com/api/webhooks/` |
| No alerts after hours | Check `logs/cooldowns.json` — cooldown may still be active. Delete the file to reset. |
| Binance returns 429 | You're polling too fast. Increase `poll_interval_minutes` in `config.yaml`. |
| `NaN` in indicators | Not enough candles (warm-up period). The app skips pairs with insufficient data. |

---

## Disclaimer

This tool is for **informational and educational purposes only**. It does not constitute
financial advice. Cryptocurrency trading involves substantial risk of loss. Always do
your own research and never risk money you cannot afford to lose.
