from __future__ import annotations

# Ce fichier est auto-détecté par rene.loader.
# Aucun changement dans main.py n'est nécessaire.
from rene.core import *  # API interne partagée de René


@app_commands.command(
    name="stop",
    description="Arrêter René proprement.",
)
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def stop_command(interaction: discord.Interaction) -> None:
    await begin_interaction_thinking(interaction, ephemeral=False)
    bot.stopping = True
    await asyncio.sleep(0.8)

    await finish_interaction(
        interaction,
        title="C'est noté !",
        description=(
            "René range ses dossiers, termine son café et va dormir.\n"
            "Le bot va maintenant s'arrêter."
        ),
        color=COLOR_SLEEP,
        image_path=IMAGE_SLEEP,
    )

    try:
        await bot.change_presence(
            status=discord.Status.idle,
            activity=discord.Game(name="dormir après son intérim"),
        )
    except discord.HTTPException:
        pass

    await set_bot_avatar(IMAGE_SLEEP)
    await persist_state_to_discord()
    await asyncio.sleep(2)
    await bot.close()


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(stop_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(stop_command.name)
