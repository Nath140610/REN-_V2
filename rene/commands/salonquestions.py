from __future__ import annotations

# Ce fichier est auto-détecté par rene.loader.
# Aucun changement dans main.py n'est nécessaire.
from rene.core import *  # API interne partagée de René


@app_commands.command(
    name="salonquestions",
    description="Définir le salon dans lequel les membres posent leurs questions.",
)
@app_commands.describe(salon="Salon réservé aux questions")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def questions_channel_command(
    interaction: discord.Interaction,
    salon: discord.TextChannel,
) -> None:
    assert interaction.guild is not None

    await begin_interaction_thinking(interaction)
    config = bot.get_guild_config(interaction.guild.id)
    config["questions_channel_id"] = salon.id
    await save_state_immediately()

    await finish_interaction(
        interaction,
        title="C'est noté !",
        description=(
            f"Les questions des membres seront maintenant prises en charge dans "
            f"{salon.mention}."
        ),
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(questions_channel_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(questions_channel_command.name)
