from __future__ import annotations

# Ce fichier est auto-détecté par rene.loader.
# Aucun changement dans main.py n'est nécessaire.
from rene.core import *  # API interne partagée de René


@app_commands.command(
    name="diagnosticvocal",
    description="Vérifier toute la configuration du vocal d'attente.",
)
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def diagnostic_voice_command(interaction: discord.Interaction) -> None:
    assert interaction.guild is not None

    await begin_interaction_thinking(interaction)
    config = bot.get_guild_config(interaction.guild.id)
    channel_id = config.get("waiting_voice_channel_id")
    channel = (
        interaction.guild.get_channel(int(channel_id))
        if channel_id
        else None
    )

    try:
        discord_version = importlib_metadata.version("discord.py")
    except importlib_metadata.PackageNotFoundError:
        discord_version = "introuvable"
    try:
        davey_version = importlib_metadata.version("davey")
    except importlib_metadata.PackageNotFoundError:
        davey_version = "NON INSTALLÉ"

    audio_ok = AUDIO_WAITING.is_file()
    ffmpeg_ok = False
    ffmpeg_text = "introuvable"
    try:
        ffmpeg_text = get_ffmpeg_executable()
        ffmpeg_ok = Path(ffmpeg_text).is_file()
    except Exception as error:
        ffmpeg_text = str(error)

    if isinstance(channel, discord.VoiceChannel) and interaction.guild.me:
        perms = channel.permissions_for(interaction.guild.me)
        permission_text = (
            f"Voir : {'✅' if perms.view_channel else '❌'} • "
            f"Connexion : {'✅' if perms.connect else '❌'} • "
            f"Parler : {'✅' if perms.speak else '❌'}"
        )
        humans = waiting_members(channel)
        channel_text = f"{channel.mention} (`{channel.id}`)"
    else:
        permission_text = "Salon non configuré ou introuvable."
        humans = []
        channel_text = "non configuré"

    voice_client = interaction.guild.voice_client
    voice_text = (
        f"connecté dans {voice_client.channel.mention}"
        if voice_client and voice_client.is_connected() and voice_client.channel
        else "déconnecté"
    )
    task = bot.waiting_voice_tasks.get(interaction.guild.id)
    task_text = "active" if task and not task.done() else "inactive"

    await finish_interaction(
        interaction,
        title="Diagnostic vocal terminé",
        description=(
            f"🎙️ **Salon :** {channel_text}\n"
            f"🔐 **Permissions :** {permission_text}\n"
            f"👥 **Humains présents :** {len(humans)}\n"
            f"🎵 **ATTENTE.mp3 :** {'✅' if audio_ok else '❌'}\n"
            f"🧰 **FFmpeg :** {'✅' if ffmpeg_ok else '⚠️'} `{ffmpeg_text}`\n"
            f"📦 **discord.py :** `{discord_version}`\n"
            f"🔒 **DAVE/davey :** `{davey_version}`\n"
            f"🔊 **VoiceClient :** {voice_text}\n"
            f"🔁 **Boucle :** {task_text}"
        ),
        color=COLOR_SUCCESS if audio_ok and davey_version != "NON INSTALLÉ" else COLOR_WARNING,
        image_path=IMAGE_INSPECT,
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(diagnostic_voice_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(diagnostic_voice_command.name)
