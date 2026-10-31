from __future__ import annotations

# Ce fichier est auto-détecté par rene.loader.
# Aucun changement dans main.py n'est nécessaire.
from rene.core import *  # API interne partagée de René


@app_commands.command(
    name="lieroblox",
    description="Lier ton pseudo Roblox à ton compte Discord.",
)
@app_commands.describe(pseudo="Ton pseudo Roblox exact")
@app_commands.guild_only()
async def link_roblox_command(
    interaction: discord.Interaction,
    pseudo: str,
) -> None:
    assert interaction.guild is not None

    await begin_interaction_thinking(interaction)
    pseudo = pseudo.strip()

    if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", pseudo):
        await finish_interaction(
            interaction,
            title="Pseudo invalide",
            description=(
                "Le pseudo doit contenir entre 3 et 20 caractères, "
                "avec uniquement des lettres, chiffres ou `_`."
            ),
            color=COLOR_DANGER,
            image_path=IMAGE_CRY,
        )
        return

    links = bot.roblox_links.setdefault(str(interaction.guild.id), {})
    links[str(interaction.user.id)] = pseudo
    save_runtime_json(ROBLOX_LINKS_FILE, bot.roblox_links)

    await finish_interaction(
        interaction,
        title="C'est noté !",
        description=(
            f"Ton compte est lié au pseudo Roblox **{pseudo}**.\n"
            "Ce lien sert seulement aux sanctions Roblox simulées."
        ),
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(link_roblox_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(link_roblox_command.name)
