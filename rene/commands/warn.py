from __future__ import annotations

# Ce fichier est auto-détecté par rene.loader.
# Aucun changement dans main.py n'est nécessaire.
from rene.core import *  # API interne partagée de René


@app_commands.command(
    name="warn",
    description="Donner manuellement un avertissement à un membre.",
)
@app_commands.describe(
    membre="Membre à avertir",
    raison="Motif de l'avertissement",
)
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def manual_warn_command(
    interaction: discord.Interaction,
    membre: discord.Member,
    raison: str,
) -> None:
    assert interaction.guild is not None

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

    channel = interaction.channel
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        await finish_interaction(
            interaction,
            title="Salon incompatible",
            description="Utilise cette commande dans un salon textuel.",
            color=COLOR_DANGER,
            image_path=IMAGE_CRY,
        )
        return

    count = await add_warning(
        membre,
        channel,
        reason=f"Avertissement manuel par {interaction.user}: {raison[:500]}",
        deleted_content="Aucun message supprimé — sanction manuelle.",
        public_image=IMAGE_CRY,
    )
    if count >= MAX_WARNINGS:
        await punish_member(membre, channel)

    await finish_interaction(
        interaction,
        title="C'est noté !",
        description=(
            f"{membre.mention} possède maintenant **{count}/{MAX_WARNINGS} "
            f"avertissements**.\nMotif : {raison[:500]}"
        ),
        color=COLOR_WARNING,
        image_path=IMAGE_NOTED,
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(manual_warn_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(manual_warn_command.name)
