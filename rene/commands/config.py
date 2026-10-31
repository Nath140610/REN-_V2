from __future__ import annotations

# Ce fichier est auto-détecté par rene.loader.
# Aucun changement dans main.py n'est nécessaire.
from rene.core import *  # API interne partagée de René


@app_commands.command(
    name="config",
    description="Configurer René L'Intérimaire.",
)
@app_commands.describe(
    salon_bienvenue="Salon des messages de bienvenue",
    salon_annonces="Salon où les @everyone sont envoyés en MP",
    salon_dossiers="Salon privé contenant les dossiers de modération",
    salon_anciennete="Salon du classement d'ancienneté",
    salon_questions="Salon où les membres posent leurs questions",
    role_moderateur="Rôle autorisé à répondre aux questions",
    vocal_attente="Vocal où René joue ATTENTE.mp3 en boucle",
)
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def config_command(
    interaction: discord.Interaction,
    salon_bienvenue: discord.TextChannel | None = None,
    salon_annonces: discord.TextChannel | None = None,
    salon_dossiers: discord.TextChannel | None = None,
    salon_anciennete: discord.TextChannel | None = None,
    salon_questions: discord.TextChannel | None = None,
    role_moderateur: discord.Role | None = None,
    vocal_attente: discord.VoiceChannel | None = None,
) -> None:
    assert interaction.guild is not None

    await begin_interaction_thinking(interaction)
    config = bot.get_guild_config(interaction.guild.id)

    if salon_bienvenue is not None:
        config["welcome_channel_id"] = salon_bienvenue.id
    if salon_annonces is not None:
        config["announcement_channel_id"] = salon_annonces.id
    if salon_dossiers is not None:
        config["staff_records_channel_id"] = salon_dossiers.id
    if salon_anciennete is not None:
        config["seniority_channel_id"] = salon_anciennete.id
        config["seniority_message_id"] = None
    if salon_questions is not None:
        config["questions_channel_id"] = salon_questions.id
    if role_moderateur is not None:
        config["moderator_role_id"] = role_moderateur.id
    if vocal_attente is not None:
        config["waiting_voice_channel_id"] = vocal_attente.id

    await save_state_immediately()

    if salon_anciennete is not None:
        await update_seniority_board(interaction.guild)
    if vocal_attente is not None:
        await ensure_waiting_voice_task(interaction.guild)

    await asyncio.sleep(0.6)

    await finish_interaction(
        interaction,
        title="C'est noté !",
        description=(
            "La configuration de René est enregistrée.\n\n"
            f"👋 **Bienvenue :** "
            f"{f'<#{config.get('welcome_channel_id')}>' if config.get('welcome_channel_id') else 'non configuré'}\n"
            f"📢 **Annonces :** "
            f"{f'<#{config.get('announcement_channel_id')}>' if config.get('announcement_channel_id') else 'non configuré'}\n"
            f"📂 **Dossiers :** "
            f"{f'<#{config.get('staff_records_channel_id')}>' if config.get('staff_records_channel_id') else 'non configuré'}\n"
            f"🏆 **Ancienneté :** "
            f"{f'<#{config.get('seniority_channel_id')}>' if config.get('seniority_channel_id') else 'non configuré'}\n"
            f"❓ **Questions :** "
            f"{f'<#{config.get('questions_channel_id')}>' if config.get('questions_channel_id') else 'non configuré'}\n"
            f"🛡️ **Rôle modérateur :** "
            f"{f'<@&{config.get('moderator_role_id')}>' if config.get('moderator_role_id') else 'non configuré'}\n"
            f"🔊 **Vocal d'attente :** "
            f"{f'<#{config.get('waiting_voice_channel_id')}>' if config.get('waiting_voice_channel_id') else 'non configuré'}"
        ),
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(config_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(config_command.name)
