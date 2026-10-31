from __future__ import annotations

# Auto-détecté par rene.loader : aucun changement dans main.py.
from rene.core import *


def _can_send_mail(interaction: discord.Interaction) -> bool:
    """
    /sendmail est volontairement réservé au staff.
    Cela évite que n'importe qui utilise René pour spammer les MP.
    """
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
    name="sendmail",
    description="Envoyer un message privé à un membre avec René.",
)
@app_commands.describe(
    membre="Personne qui recevra le MP",
    message="Message à transmettre",
)
@app_commands.guild_only()
async def sendmail_command(
    interaction: discord.Interaction,
    membre: discord.Member,
    message: str,
) -> None:
    assert interaction.guild is not None

    if not _can_send_mail(interaction):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser `/sendmail`.",
            ephemeral=True,
        )
        return

    if membre.bot:
        await interaction.response.send_message(
            "❌ René ne peut pas envoyer ce courrier à un bot.",
            ephemeral=True,
        )
        return

    text = message.strip()

    if not text:
        await interaction.response.send_message(
            "❌ Le message ne peut pas être vide.",
            ephemeral=True,
        )
        return

    # Discord limite la description d'un embed.
    if len(text) > 3500:
        await interaction.response.send_message(
            "❌ Ton message est trop long. Limite-le à 3500 caractères.",
            ephemeral=True,
        )
        return

    await begin_interaction_thinking(interaction)

    embed = build_embed(
        "📬 Courrier de René",
        (
            f"René a reçu un message à te transmettre depuis "
            f"**{interaction.guild.name}**.\n\n"
            f"**Message :**\n{text}\n\n"
            f"— Envoyé par {interaction.user.mention}"
        ),
        COLOR_INFO,
    )

    try:
        await membre.send(embed=embed)
    except discord.Forbidden:
        await finish_interaction(
            interaction,
            title="📪 Livraison impossible",
            description=(
                f"René ne peut pas envoyer de MP à {membre.mention}.\n"
                "La personne a probablement fermé ses messages privés."
            ),
            color=COLOR_DANGER,
            image_path=IMAGE_CRY,
        )
        return
    except discord.HTTPException as error:
        logger.warning(
            "SENDMAIL : erreur MP vers %s (%s) : %s",
            membre,
            membre.id,
            error,
        )
        await finish_interaction(
            interaction,
            title="📪 Erreur de livraison",
            description="Discord a refusé l'envoi du message.",
            color=COLOR_DANGER,
            image_path=IMAGE_CRY,
        )
        return

    logger.info(
        "SENDMAIL : %s (%s) -> %s (%s) sur %s (%s)",
        interaction.user,
        interaction.user.id,
        membre,
        membre.id,
        interaction.guild.name,
        interaction.guild.id,
    )

    await finish_interaction(
        interaction,
        title="📨 Courrier livré",
        description=(
            f"René a envoyé le message en MP à {membre.mention}.\n\n"
            f"**Message :** {text[:1000]}"
        ),
        color=COLOR_SUCCESS,
        image_path=IMAGE_DELIVER,
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(sendmail_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(sendmail_command.name)
