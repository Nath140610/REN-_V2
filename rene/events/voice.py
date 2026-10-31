from __future__ import annotations

from rene.core import *


async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    if member.bot or bot.stopping:
        return

    before_id = before.channel.id if before.channel else None
    after_id = after.channel.id if after.channel else None
    config = bot.get_guild_config(member.guild.id)
    channel_id = config.get("waiting_voice_channel_id")

    logger.info(
        "VOCAL : membre=%s avant=%s après=%s configuré=%s",
        member,
        before_id,
        after_id,
        channel_id,
    )

    if not channel_id:
        return

    watched_id = int(channel_id)
    if before_id != watched_id and after_id != watched_id:
        return

    await asyncio.sleep(1.0)
    await ensure_waiting_voice_task(member.guild)


async def setup(client: commands.Bot) -> None:
    client.add_listener(on_voice_state_update, "on_voice_state_update")


async def teardown(client: commands.Bot) -> None:
    client.remove_listener(on_voice_state_update, "on_voice_state_update")
