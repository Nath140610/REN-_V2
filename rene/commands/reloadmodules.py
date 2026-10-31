from __future__ import annotations

from rene.core import *


@app_commands.command(
    name="reloadmodules",
    description="Recharger les modules et détecter les nouvelles commandes.",
)
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def reload_modules_command(interaction: discord.Interaction) -> None:
    await begin_interaction_thinking(interaction)

    reloaded, loaded, errors = await bot.reload_rene_modules()
    synced = await bot.tree.sync()

    details = [
        f"♻️ **Modules rechargés :** {len(reloaded)}",
        f"🆕 **Nouveaux modules détectés :** {len(loaded)}",
        f"⚙️ **Commandes Discord synchronisées :** {len(synced)}",
    ]
    if loaded:
        details.append("\n**Nouveaux :**\n" + "\n".join(f"• `{x}`" for x in loaded[:15]))
    if errors:
        details.append("\n⚠️ **Erreurs :**\n" + "\n".join(f"• `{x[:180]}`" for x in errors[:8]))

    await finish_interaction(
        interaction,
        title="Modules de René actualisés",
        description="\n".join(details),
        color=COLOR_WARNING if errors else COLOR_SUCCESS,
        image_path=IMAGE_NOTED if not errors else IMAGE_CRY,
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(reload_modules_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(reload_modules_command.name)
