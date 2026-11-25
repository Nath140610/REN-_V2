"""Accueil automatique des nouveaux tickets (voir rene/ticketassistant.py)."""
from __future__ import annotations

from discord.ext import commands

from rene import ticketassistant


async def setup(client: commands.Bot) -> None:
    client.add_listener(ticketassistant.on_guild_channel_create, "on_guild_channel_create")
    client.add_dynamic_items(ticketassistant.TargetButton)


async def teardown(client: commands.Bot) -> None:
    client.remove_listener(ticketassistant.on_guild_channel_create, "on_guild_channel_create")
    client.remove_dynamic_items(ticketassistant.TargetButton)
