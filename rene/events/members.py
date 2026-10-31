from __future__ import annotations

from rene.core import *


async def on_member_join(member: discord.Member) -> None:
    config = bot.get_guild_config(member.guild.id)
    channel_id = config.get("welcome_channel_id")

    if not channel_id:
        return

    channel = member.guild.get_channel(int(channel_id))

    if isinstance(channel, discord.TextChannel):
        await send_embed_with_thumbnail(
            channel,
            title="Bienvenue à bord !",
            description=WELCOME_MESSAGE.format(mention=member.mention),
            color=COLOR_PRIMARY,
            image_path=IMAGE_NEW,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    await update_seniority_board(member.guild)


async def on_member_remove(member: discord.Member) -> None:
    if member.bot:
        return

    guild_key = str(member.guild.id)
    records = bot.departed_members.setdefault(guild_key, [])

    records.append(
        {
            "user_id": member.id,
            "display_name": member.display_name,
            "joined_at": (
                member.joined_at.isoformat()
                if member.joined_at else None
            ),
            "left_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    # Garde au maximum les 500 derniers départs enregistrés.
    bot.departed_members[guild_key] = records[-500:]
    save_runtime_json(DEPARTED_MEMBERS_FILE, bot.departed_members)
    await update_seniority_board(member.guild)


async def setup(client: commands.Bot) -> None:
    client.add_listener(on_member_join, "on_member_join")
    client.add_listener(on_member_remove, "on_member_remove")


async def teardown(client: commands.Bot) -> None:
    client.remove_listener(on_member_join, "on_member_join")
    client.remove_listener(on_member_remove, "on_member_remove")
