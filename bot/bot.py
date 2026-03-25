import asyncio
import logging
import re

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from sqlalchemy import text

from config import settings
from indexer.database import SessionMaker

from . import agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

dp = Dispatcher()

_chat_history: dict[int, list] = {}
_last_address: dict[int, str] = {}

_ADDRESS_RE = re.compile(r"\b(EQ|UQ|Ef|kQ)[A-Za-z0-9_\-]{46}\b")


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 TON DeFi Copilot\n\n"
        "I have real-time access to on-chain data. Just ask:\n\n"
        "🔍 Whale &amp; Network Intelligence\n"
        "- Who are the top TON holders?\n"
        "- Which accounts are acting strangely right now?\n"
        "- Show me recent large transactions and network health\n\n"
        "💎 Jetton &amp; DEX Insights\n"
        "- What's the price of a token?\n"
        "- Who are the top holders of a token?\n"
        "- How deep is the liquidity for NOT on DeDust?\n\n"
        "⚖️ Staking &amp; Vesting\n"
        "- Tell me about the Believers Fund\n"
        "- When is the next vesting unlock?\n"
        "- Show me recent validator unstakes\n\n"
        "📅 Historical Events\n"
        "- What happened on TON the day Durov was arrested?\n"
        "- Show me on-chain activity during the Notcoin launch\n"
        "- Replay the Hamster Kombat listing\n\n"
        "🔔 Alerts\n"
        "Use /subscribe to get notified about whale spikes, large transactions, and liquidity drains.\n"
        "Use /unsubscribe to stop.\n\n"
        "Paste any TON address or jetton master to get started.",
        parse_mode="HTML",
    )


@dp.message(Command("subscribe"))
async def cmd_subscribe(message: types.Message):
    async with SessionMaker.begin() as db:
        await db.execute(
            text("""
                INSERT INTO bt_alert_subscriptions (chat_id, active, created_at)
                VALUES (:chat_id, TRUE, NOW())
                ON CONFLICT (chat_id) DO UPDATE SET active = TRUE
            """),
            {"chat_id": message.chat.id},
        )
    await message.answer(
        "✅ You're subscribed to TON alerts.\n\n"
        "You'll be notified when:\n"
        "- 🐳 A whale shows unusual activity\n"
        "- 💸 A very large transaction occurs\n"
        "- 🏊 USDT pool liquidity drops sharply\n\n"
        "Use /unsubscribe to stop alerts.",
        parse_mode="HTML",
    )


@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: types.Message):
    async with SessionMaker.begin() as db:
        await db.execute(
            text(
                "UPDATE bt_alert_subscriptions SET active = FALSE WHERE chat_id = :chat_id"
            ),
            {"chat_id": message.chat.id},
        )
    await message.answer(
        "🔕 You've been unsubscribed. Use /subscribe to turn alerts back on."
    )


@dp.message()
async def handle_message(message: types.Message):
    if not message.text:
        return

    await message.bot.send_chat_action(message.chat.id, "typing")

    user_message = message.text
    chat_id = message.chat.id

    # track the most recently mentioned address per chat
    match = _ADDRESS_RE.search(user_message)
    if match:
        _last_address[chat_id] = match.group(0)
    elif _last_address.get(chat_id) and _ADDRESS_RE.search(user_message) is None:
        # inject the last known address so the model doesn't lose context
        user_message = (
            f"[context: address in scope is {_last_address[chat_id]}] {user_message}"
        )

    try:
        reply, history = await agent.run(
            api_key=settings.gemini.api_key,
            user_message=user_message,
            history=_chat_history.get(chat_id),
        )
        _chat_history[chat_id] = history
        await message.answer(reply, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.exception(e)
        await message.answer("Something went wrong, please try again.")


async def main():
    logger.info("Starting TON DeFi Copilot bot powered by TONSCAN.COM")
    bot = Bot(token=settings.telegram.bot_token)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
