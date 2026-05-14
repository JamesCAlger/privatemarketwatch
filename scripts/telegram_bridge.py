"""Telegram bot that bridges messages to Claude Code CLI (uses Max subscription)."""

import asyncio
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
# Set your Telegram user ID here to restrict access (message @userinfobot to get it)
ALLOWED_USER_IDS: set[int] = {1929884649}


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_USER_IDS and update.effective_user.id not in ALLOWED_USER_IDS:
        return

    msg = update.message.text
    await update.message.reply_text("Thinking...")

    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", msg,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    response = stdout.decode().strip() or stderr.decode().strip() or "(empty response)"

    # Telegram has a 4096 char limit per message
    for i in range(0, len(response), 4096):
        await update.message.reply_text(response[i : i + 4096])


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
