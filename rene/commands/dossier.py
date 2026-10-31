from __future__ import annotations

# Ce fichier est auto-détecté par rene.loader.
# Aucun changement dans main.py n'est nécessaire.
from rene.core import *  # API interne partagée de René


@app_commands.command(
    name="dossier",
    description="Consulter le dossier de modération d'un membre.",
)
@app_commands.describe(membre="Membre dont le dossier doit être consulté")
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def dossier_command(
    interaction: discord.Interaction,
    membre: discord.Member,
) -> None:
    assert interaction.guild is not None

    await begin_interaction_thinking(interaction)

    cases = [
        case
        for case in bot.moderation_cases.get(str(interaction.guild.id), [])
        if int(case.get("user_id", 0)) == membre.id
    ]

    if not cases:
        await finish_interaction(
            interaction,
            title="Dossier vide",
            description=(
                f"{membre.mention} ne possède aucun dossier de modération."
            ),
        )
        return

    recent_cases = cases[-5:]
    lines: list[str] = []

    for case in reversed(recent_cases):
        created_at = case.get("created_at", "")
        try:
            timestamp = int(datetime.fromisoformat(created_at).timestamp())
            date_text = f"<t:{timestamp}:f>"
        except (ValueError, TypeError):
            date_text = "date inconnue"

        lines.append(
            f"**Dossier #{case.get('id')}** — {case.get('type')}\n"
            f"Motif : {case.get('reason')}\n"
            f"Date : {date_text}\n"
            f"Warns après action : {case.get('warning_count')}/{MAX_WARNINGS}"
        )

    await finish_interaction(
        interaction,
        title=f"Dossier de {membre.display_name}",
        description=(
            f"📂 **{len(cases)} action(s) enregistrée(s)**\n\n"
            + "\n\n".join(lines)
        ),
        color=COLOR_WARNING,
        image_path=IMAGE_READ,
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(dossier_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(dossier_command.name)
