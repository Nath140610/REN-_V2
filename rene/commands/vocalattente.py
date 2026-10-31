from __future__ import annotations

# Ce fichier est auto-détecté par rene.loader.
# Aucun changement dans main.py n'est nécessaire.
from rene.core import *  # API interne partagée de René


@app_commands.command(
    name="vocalattente",
    description="Définir le vocal d'attente urgente.",
)
@app_commands.describe(salon="Vocal dans lequel ATTENTE.mp3 sera joué en boucle")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def waiting_voice_command(
    interaction: discord.Interaction,
    salon: discord.VoiceChannel,
) -> None:
    assert interaction.guild is not None

    await begin_interaction_thinking(interaction)
    config = bot.get_guild_config(interaction.guild.id)
    config["waiting_voice_channel_id"] = salon.id
    await save_state_immediately()
    await ensure_waiting_voice_task(interaction.guild)

    await finish_interaction(
        interaction,
        title="C'est noté !",
        description=(
            f"Le vocal d'attente est maintenant {salon.mention}.\n\n"
            "Quand un membre y entre, René rejoint le vocal, joue "
            "`ATTENTE.mp3` en boucle et prévient les modérateurs en MP "
            "à chaque redémarrage du son."
        ),
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(waiting_voice_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(waiting_voice_command.name)
