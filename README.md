# Whale Intelligence

A Telegram bot for real-time TON blockchain analytics. Powered by Gemini and tonscan.com data.

## Features

- Whale tracking and anomaly detection
- DEX prices across STON.fi, DeDust, TonCo, and Coffee
- Jetton holder analysis and flow tracking
- USDT and jetton pool liquidity monitoring
- Validator unstake events
- Believers Fund / The Locker vesting schedule
- Historical on-chain event replay (Notcoin launch, Durov arrest, etc.)
- Alert subscriptions for whale spikes and large transactions

## Setup

1. Clone the repo and install dependencies:
   ```bash
   uv sync
   ```

2. Copy the config template and fill in your keys:
   ```bash
   cp bot/config/settings.yaml.example bot/config/settings.yaml
   ```

3. Edit `bot/config/settings.yaml`:
   ```yaml
   telegram:
     bot_token: YOUR_TELEGRAM_BOT_TOKEN
   gemini:
     api_key: YOUR_GEMINI_API_KEY
   ```

4. Run the bot:
   ```bash
   python -m bot.bot
   ```

## Requirements

- Python 3.11+
- PostgreSQL (for alert subscriptions)
