from __future__ import annotations

import logging

import discord
from discord import app_commands

from backend.config import settings
from backend.database import async_session
from bot.formatters import format_sync_result, truncate
from bot.handler import ChatHandler

logger = logging.getLogger(__name__)


class HealthBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if settings.discord.guild_id:
            guild = discord.Object(id=settings.discord.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        logger.info("Discord slash commands synced")

    async def on_ready(self):
        logger.info(f"Discord bot logged in as {self.user}")


async def _get_handler() -> ChatHandler:
    session = async_session()
    return ChatHandler(session)


def _make_embed(title: str, description: str, color: discord.Color = discord.Color.blue()) -> discord.Embed:
    """Create a standard embed."""
    embed = discord.Embed(title=title, description=truncate(description, 4000), color=color)
    return embed


def setup_commands(bot: HealthBot):
    """Register slash commands on the bot."""

    @bot.tree.command(name="today", description="Get today's training briefing")
    @app_commands.describe(model="AI model to use (optional)")
    async def today(interaction: discord.Interaction, model: str | None = None):
        await interaction.response.defer()
        handler = await _get_handler()
        try:
            result = await handler.daily_briefing(model=model)
            embed = _make_embed("Daily Briefing", result.answer, discord.Color.green())
            embed.set_footer(text=f"Model: {result.model}")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @bot.tree.command(name="last", description="Analyze your last workout")
    @app_commands.describe(model="AI model to use (optional)")
    async def last(interaction: discord.Interaction, model: str | None = None):
        await interaction.response.defer()
        handler = await _get_handler()
        try:
            result = await handler.last_workout_analysis(model=model)
            embed = _make_embed("Last Workout Analysis", result.answer, discord.Color.orange())
            embed.set_footer(text=f"Model: {result.model}")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @bot.tree.command(name="week", description="Weekly training summary")
    @app_commands.describe(model="AI model to use (optional)")
    async def week(interaction: discord.Interaction, model: str | None = None):
        await interaction.response.defer()
        handler = await _get_handler()
        try:
            result = await handler.weekly_summary(model=model)
            embed = _make_embed("Weekly Summary", result.answer, discord.Color.purple())
            embed.set_footer(text=f"Model: {result.model}")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @bot.tree.command(name="ask", description="Ask a question about your health data")
    @app_commands.describe(
        question="Your question",
        model="AI model to use (optional)",
    )
    async def ask(interaction: discord.Interaction, question: str, model: str | None = None):
        await interaction.response.defer()
        handler = await _get_handler()
        try:
            result = await handler.handle_question(question=question, model=model)
            embed = _make_embed("Health Analysis", result.answer)
            embed.set_footer(text=f"Model: {result.model}")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @bot.tree.command(name="sync", description="Sync data from external sources")
    @app_commands.describe(source="Data source to sync (default: all)")
    @app_commands.choices(
        source=[
            app_commands.Choice(name="All", value="all"),
            app_commands.Choice(name="Strava", value="strava"),
            app_commands.Choice(name="Eight Sleep", value="eight_sleep"),
            app_commands.Choice(name="Whoop", value="whoop"),
            app_commands.Choice(name="Weather", value="weather"),
        ]
    )
    async def sync(interaction: discord.Interaction, source: str = "all"):
        await interaction.response.defer()
        handler = await _get_handler()
        try:
            results = await handler.trigger_sync(source=source)
            embed = _make_embed("Sync Complete", format_sync_result(results), discord.Color.green())
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Sync error: {e}")

    @bot.tree.command(name="models", description="List available AI models")
    async def models(interaction: discord.Interaction):
        from backend.services.llm_providers import list_available_models

        available = list_available_models()
        default = settings.llm.default_llm_provider
        lines = []
        for m in available:
            marker = " **(default)**" if m == default else ""
            lines.append(f"- `{m}`{marker}")
        embed = _make_embed("Available Models", "\n".join(lines))
        embed.set_footer(text="Use the 'model' parameter with /ask to choose a model")
        await interaction.followup.send(embed=embed)


def create_discord_bot() -> HealthBot:
    """Create and configure the Discord bot."""
    bot = HealthBot()
    setup_commands(bot)
    return bot


async def run_discord_bot():
    """Run the Discord bot. Stops cleanly when the task is cancelled."""
    import asyncio

    if not settings.discord.bot_token:
        logger.warning("DISCORD_BOT_TOKEN not set, skipping Discord bot")
        return
    bot = create_discord_bot()
    try:
        await bot.start(settings.discord.bot_token)
    except asyncio.CancelledError:
        logger.info("Discord bot stopping...")
        await bot.close()
        raise
