from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from backend.config import settings
from backend.database import async_session
from bot.formatters import format_for_telegram, format_sync_result
from bot.handler import ChatHandler

logger = logging.getLogger(__name__)


async def _get_handler() -> ChatHandler:
    session = async_session()
    return ChatHandler(session)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "Welcome to Health Tracker!\n\n"
        "Available commands:\n"
        "/today - Today's training briefing\n"
        "/last - Analyze your last workout\n"
        "/week - Weekly training summary\n"
        "/ask <question> - Ask anything about your data\n"
        "/sync - Sync data from all sources\n"
        "/models - List available AI models\n\n"
        "You can also use --model flag with /ask:\n"
        "/ask --model gpt-4o How was my run?"
    )


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /today command - daily briefing."""
    await update.message.reply_text("Analyzing your data...")
    handler = await _get_handler()
    try:
        model = _extract_model(context.args)
        result = await handler.daily_briefing(model=model)
        await update.message.reply_text(
            format_for_telegram(result), parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def last_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /last command - last workout analysis."""
    await update.message.reply_text("Analyzing your last workout...")
    handler = await _get_handler()
    try:
        model = _extract_model(context.args)
        result = await handler.last_workout_analysis(model=model)
        await update.message.reply_text(
            format_for_telegram(result), parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /week command - weekly summary."""
    await update.message.reply_text("Generating weekly summary...")
    handler = await _get_handler()
    try:
        model = _extract_model(context.args)
        result = await handler.weekly_summary(model=model)
        await update.message.reply_text(
            format_for_telegram(result), parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ask command - free-form question."""
    if not context.args:
        await update.message.reply_text("Usage: /ask <your question>\nExample: /ask How did my sleep affect today's run?")
        return

    args = list(context.args)
    model = _extract_model(args)
    question = " ".join(args)

    if not question:
        await update.message.reply_text("Please include a question after /ask")
        return

    await update.message.reply_text("Thinking...")
    handler = await _get_handler()
    try:
        result = await handler.handle_question(question=question, model=model)
        await update.message.reply_text(
            format_for_telegram(result), parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /sync command - trigger data sync."""
    source = context.args[0] if context.args else "all"
    await update.message.reply_text(f"Syncing {source}...")
    handler = await _get_handler()
    try:
        results = await handler.trigger_sync(source=source)
        await update.message.reply_text(format_sync_result(results), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Sync error: {e}")


async def models_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /models command - list available models."""
    from backend.services.llm_providers import list_available_models

    models = list_available_models()
    default = settings.llm.default_llm_provider
    lines = ["**Available models:**"]
    for m in models:
        marker = " (default)" if m == default else ""
        lines.append(f"- `{m}`{marker}")
    lines.append("\nUse with: /ask --model <name> <question>")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def plain_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages as questions."""
    question = update.message.text
    handler = await _get_handler()
    try:
        result = await handler.handle_question(question=question)
        await update.message.reply_text(
            format_for_telegram(result), parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


def _extract_model(args: list[str] | None) -> str | None:
    """Extract --model flag from args, removing it from the list in place."""
    if not args:
        return None
    for i, arg in enumerate(args):
        if arg == "--model" and i + 1 < len(args):
            model = args[i + 1]
            del args[i : i + 2]
            return model
    return None


def create_telegram_app() -> Application:
    """Create and configure the Telegram bot application."""
    app = Application.builder().token(settings.telegram.bot_token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("last", last_command))
    app.add_handler(CommandHandler("week", week_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("sync", sync_command))
    app.add_handler(CommandHandler("models", models_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, plain_message))

    return app


async def run_telegram_bot():
    """Run the Telegram bot."""
    if not settings.telegram.bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set, skipping Telegram bot")
        return
    app = create_telegram_app()
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logger.info("Telegram bot started")
