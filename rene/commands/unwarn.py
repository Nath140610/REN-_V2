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
    name="unwarn",
    description="Retirer un avertissement à un membre.",
)
@app_commands.describe(
    membre="Membre auquel retirer un avertissement",
    raison="Raison du retrait",
)
@app_commands.guild_only()
async def unwarn_command(
    interaction: discord.Interaction,
    membre: discord.Member,
    raison: str = "Avertissement retiré par le staff",
) -> None:
    assert interaction.guild is not None

    if not _can_moderate(interaction):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.",
            ephemeral=True,
        )
        return

    await begin_interaction_thinking(interaction)

    current_count = get_warning_count(interaction.guild.id, membre.id)

    if current_count <= 0:
        await finish_interaction(
            interaction,
            title="Aucun avertissement",
            description=(
                f"{membre.mention} possède déjà **0/{MAX_WARNINGS}** "
                "avertissement."
            ),
            color=COLOR_INFO,
            image_path=IMAGE_NOTED,
        )
        return

    new_count = max(0, current_count - 1)
    set_warning_count(interaction.guild.id, membre.id, new_count)

    reason_text = raison.strip()[:500] or "Avertissement retiré par le staff"

    # On garde une trace du retrait dans les dossiers du staff.
    channel_id = interaction.channel_id or 0
    case = create_case(
        interaction.guild.id,
        membre.id,
        interaction.user.id,
        case_type="Retrait d'avertissement",
        reason=(
            f"{reason_text} — retiré par "
            f"{interaction.user} ({interaction.user.id})"
        ),
        warning_count=new_count,
        channel_id=channel_id,
        deleted_content=(
            f"Compteur avant : {current_count}/{MAX_WARNINGS} | "
            f"Compteur après : {new_count}/{MAX_WARNINGS}"
        ),
    )

    await send_case_to_staff(interaction.guild, case)
    await save_state_immediately()

    # Prévenir le membre en MP, sans faire échouer la commande si ses MP sont fermés.
    dm_status = "✅ MP envoyé"
    try:
        await membre.send(
            embed=build_embed(
                "✅ Un avertissement a été retiré",
                (
                    f"Un membre du staff de **{interaction.guild.name}** "
                    "a retiré un de tes avertissements.\n\n"
                    f"⚠️ **Nouveau total :** {new_count}/{MAX_WARNINGS}\n"
                    f"📝 **Motif :** {reason_text}"
                ),
                COLOR_SUCCESS,
            )
        )
    except (discord.Forbidden, discord.HTTPException):
        dm_status = "⚠️ MP impossible"

    await finish_interaction(
        interaction,
        title="✅ Avertissement retiré",
        description=(
            f"Un avertissement a été retiré à {membre.mention}.\n\n"
            f"**Avant :** {current_count}/{MAX_WARNINGS}\n"
            f"**Maintenant :** {new_count}/{MAX_WARNINGS}\n"
            f"**Motif :** {reason_text}\n"
            f"**Dossier :** #{case['id']}\n"
            f"**Notification :** {dm_status}"
        ),
        color=COLOR_SUCCESS,
        image_path=IMAGE_NOTED,
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(unwarn_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(unwarn_command.name)
