from __future__ import annotations

from rene.core import *


async def on_message(message: discord.Message) -> None:
    if message.author.bot or message.guild is None or bot.stopping:
        return

    if await process_moderator_answer(message):
        return

    config = bot.get_guild_config(message.guild.id)
    questions_channel_id = config.get("questions_channel_id")

    if (
        questions_channel_id
        and message.channel.id == int(questions_channel_id)
        and isinstance(message.author, discord.Member)
        and not member_has_moderator_role(message.author)
    ):
        await register_question(message)
        return

    await distribute_announcement(message)

    # Les liens sont inspectés avant le filtre de grossièretés.
    link_result = await inspect_links(message)

    # Une publicité supprimée a déjà généré son avertissement.
    if link_result == "blocked":
        return

    if not contains_bad_word(message.content):
        return

    original_content = message.content

    try:
        await message.delete()
    except discord.HTTPException:
        logger.warning("Impossible de supprimer le message grossier.")

    if not isinstance(message.author, discord.Member):
        return

    warning_count = await add_warning(
        message.author,
        message.channel,
        reason="Langage grossier ou insultant",
        deleted_content=original_content,
        public_image=IMAGE_CRY,
    )

    if warning_count >= MAX_WARNINGS:
        await punish_member(message.author, message.channel)


async def setup(client: commands.Bot) -> None:
    client.add_listener(on_message, "on_message")


async def teardown(client: commands.Bot) -> None:
    client.remove_listener(on_message, "on_message")
