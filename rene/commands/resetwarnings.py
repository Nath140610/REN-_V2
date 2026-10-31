from __future__ import annotations

# Ce fichier est auto-détecté par rene.loader.
# Aucun changement dans main.py n'est nécessaire.
from rene.core import *  # API interne partagée de René


@app_commands.command(
    name="resetwarnings",
    description="Remettre les avertissements d'un membre à zéro.",
)
@app_commands.describe(membre="Membre à réinitialiser")
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def reset_warnings_command(
    interaction: discord.Interaction,
    membre: discord.Member,
) -> None:
    assert interaction.guild is not None

    await begin_interaction_thinking(interaction)
    set_warning_count(interaction.guild.id, membre.id, 0)

    await finish_interaction(
        interaction,
        title="C'est noté !",
        description=(
            f"Les avertissements de {membre.mention} ont été remis à zéro."
        ),
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(reset_warnings_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(reset_warnings_command.name)
