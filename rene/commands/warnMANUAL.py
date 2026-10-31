from __future__ import annotations

# Auto-détecté par rene.loader : aucun changement dans main.py.
from rene.core import *


def _can_moderate(interaction: discord.Interaction) -> bool:
    user = interaction.user
    return (
        isinstance(user, discord.Member)
        and (
            user.guild_permissions.manage_messages
            or user.guild_permissions.administrator
            or member_has_moderator_role(user)
        )
    )


@app_commands.command(
    name="warnmanual",
    description="Ajouter un avertissement à un membre.",
)
@app_commands.describe(
    membre="Membre à avertir",
    raison="Motif de l'avertissement",
)
@app_commands.guild_only()
async def warn_command(
    interaction: discord.Interaction,
    membre: discord.Member,
    raison: str,
) -> None:
    assert interaction.guild is not None

    if not _can_moderate(interaction):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.",
            ephemeral=True,
        )
        return

    await begin_interaction_thinking(interaction)

    if membre.bot:
        await finish_interaction(
            interaction,
            title="Action impossible",
            description="René ne peut pas avertir un bot.",
            color=COLOR_DANGER,
            image_path=IMAGE_CRY,
        )
        return

    if membre.id == interaction.user.id:
        await finish_interaction(
            interaction,
            title="Action impossible",
            description="Tu ne peux pas t'avertir toi-même.",
            color=COLOR_DANGER,
            image_path=IMAGE_CRY,
        )
        return

    channel = interaction.channel

    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        await finish_interaction(
            interaction,
            title="Salon incompatible",
            description="Utilise `/warn` dans un salon textuel.",
            color=COLOR_DANGER,
            image_path=IMAGE_CRY,
        )
        return

    raison = raison.strip()[:500]

    if not raison:
        await finish_interaction(
            interaction,
            title="Motif manquant",
            description="Indique un motif pour l'avertissement.",
            color=COLOR_DANGER,
            image_path=IMAGE_CRY,
        )
        return

    count = await add_warning(
        membre,
        channel,
        reason=(
            f"Avertissement manuel par {interaction.user} "
            f"({interaction.user.id}) — {raison}"
        ),
        deleted_content="Aucun message supprimé — avertissement manuel.",
        public_image=IMAGE_CRY,
    )

    if count >= MAX_WARNINGS:
        await punish_member(membre, channel)

    await save_state_immediately()

    await finish_interaction(
        interaction,
        title="⚠️ Avertissement ajouté",
        description=(
            f"{membre.mention} possède maintenant "
            f"**{count}/{MAX_WARNINGS} avertissements**.\n\n"
            f"📝 **Motif :** {raison}\n"
            f"👮 **Modérateur :** {interaction.user.mention}"
        ),
        color=COLOR_WARNING,
        image_path=IMAGE_NOTED,
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(warn_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(warn_command.name)
