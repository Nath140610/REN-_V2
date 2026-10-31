from __future__ import annotations

# Ce fichier est auto-détecté par rene.loader.
# Aucun changement dans main.py n'est nécessaire.
from rene.core import *  # API interne partagée de René


@app_commands.command(
    name="warnings",
    description="Voir les avertissements d'un membre.",
)
@app_commands.describe(membre="Membre à vérifier")
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def warnings_command(
    interaction: discord.Interaction,
    membre: discord.Member,
) -> None:
    assert interaction.guild is not None

    await begin_interaction_thinking(interaction)
    count = get_warning_count(interaction.guild.id, membre.id)

    await finish_interaction(
        interaction,
        title="C'est noté !",
        description=(
            f"{membre.mention} possède **{count}/{MAX_WARNINGS} avertissements**."
        ),
        color=COLOR_WARNING if count else COLOR_SUCCESS,
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(warnings_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(warnings_command.name)
