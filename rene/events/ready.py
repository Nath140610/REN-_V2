from __future__ import annotations

from rene.core import *


async def on_ready() -> None:
    if bot.user is None:
        return

    logger.info("Connecté en tant que %s (%s).", bot.user, bot.user.id)

    if not bot.remote_state_loaded:
        bot.remote_state_loaded = True
        loaded = await load_state_from_discord()
        if not loaded or bot.remote_state_message_id is None:
            await persist_state_to_discord()

    # Les boucles démarrent seulement après le chargement de l'état persistant.
    if not temporary_ban_checker.is_running():
        temporary_ban_checker.start()
    if not funny_presence_loop.is_running():
        funny_presence_loop.start()
    if not seniority_refresh_loop.is_running():
        seniority_refresh_loop.start()

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Game(name=random.choice(FUNNY_ACTIVITIES)),
    )

    if not bot.idle_avatar_applied:
        bot.idle_avatar_applied = True
        await set_bot_avatar(IMAGE_IDLE)

    status_channel = bot.get_channel(STATUS_CHANNEL_ID)

    if status_channel is None:
        try:
            status_channel = await bot.fetch_channel(STATUS_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            status_channel = None

    if isinstance(status_channel, discord.TextChannel):
        try:
            await send_embed_with_thumbnail(
                status_channel,
                title="René est reconnecté !",
                description=(
                    "🟢 **René L'Intérimaire est de nouveau en service.**\n\n"
                    "La connexion avec Discord est rétablie et René reprend "
                    "ses dossiers là où il les avait laissés."
                ),
                color=COLOR_SUCCESS,
                image_path=IMAGE_NEW,
            )
        except discord.HTTPException:
            logger.exception(
                "Impossible d'envoyer le message de reconnexion dans le salon status."
            )


    # Si Render ou Discord a redémarré pendant qu'une personne attendait,
    # René reprend automatiquement la boucle sonore.
    for guild in bot.guilds:
        await ensure_waiting_voice_task(guild)


async def setup(client: commands.Bot) -> None:
    client.add_listener(on_ready, "on_ready")


async def teardown(client: commands.Bot) -> None:
    client.remove_listener(on_ready, "on_ready")
