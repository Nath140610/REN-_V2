from __future__ import annotations

# Ce fichier est auto-détecté par rene.loader.
# Aucun changement dans main.py n'est nécessaire.
from rene.core import *  # API interne partagée de René


@app_commands.command(
    name="anciennete",
    description="Actualiser manuellement le classement d'ancienneté.",
)
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def seniority_command(interaction: discord.Interaction) -> None:
    assert interaction.guild is not None

    await begin_interaction_thinking(interaction)
    await update_seniority_board(interaction.guild)
    await finish_interaction(
        interaction,
        title="C'est noté !",
        description="Le classement d'ancienneté a été actualisé.",
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(seniority_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(seniority_command.name)
