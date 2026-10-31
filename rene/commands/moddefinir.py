from __future__ import annotations

# Ce fichier est auto-détecté par rene.loader.
# Aucun changement dans main.py n'est nécessaire.
from rene.core import *  # API interne partagée de René


@app_commands.command(
    name="moddefinir",
    description="Définir le rôle des modérateurs de René.",
)
@app_commands.describe(role="Rôle autorisé à répondre aux questions")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def mod_define_command(
    interaction: discord.Interaction,
    role: discord.Role,
) -> None:
    assert interaction.guild is not None

    await begin_interaction_thinking(interaction)
    config = bot.get_guild_config(interaction.guild.id)
    config["moderator_role_id"] = role.id
    await save_state_immediately()

    await finish_interaction(
        interaction,
        title="C'est noté !",
        description=f"Le rôle {role.mention} est maintenant reconnu comme modérateur.",
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(mod_define_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(mod_define_command.name)
