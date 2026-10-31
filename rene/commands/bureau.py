from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from rene.core import (
    COLOR_INFO,
    COLOR_PRIMARY,
    bot,
    build_embed,
)


def dict_store(key: str) -> dict:
    value = bot.config_data.get(key, {})
    return value if isinstance(value, dict) else {}


def future_rendezvous_for(user_id: int):
    result = []
    now = datetime.now(timezone.utc)

    for rdv_id, entry in dict_store("_rendezvous").items():
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "accepted":
            continue
        if user_id not in {
            int(entry.get("requester_id", 0)),
            int(entry.get("target_id", 0)),
        }:
            continue

        try:
            dt = datetime.fromisoformat(entry["scheduled_at"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        if dt > now:
            result.append((dt, rdv_id, entry))

    result.sort(key=lambda x: x[0])
    return result


def summary_embed(user_id: int):
    rdvs = future_rendezvous_for(user_id)

    courriers = [
        entry for entry in dict_store("_courriers").values()
        if isinstance(entry, dict)
        and user_id in {
            int(entry.get("sender_id", 0)),
            int(entry.get("recipient_id", 0)),
        }
    ]

    express = [
        entry for entry in dict_store("_rdvexpress").values()
        if isinstance(entry, dict)
        and user_id in {
            int(entry.get("requester_id", 0)),
            int(entry.get("target_id", 0)),
        }
        and entry.get("status") == "pending"
    ]

    secretariat = [
        entry for entry in dict_store("_secretariat").values()
        if isinstance(entry, dict)
        and user_id in [int(x) for x in entry.get("participants", [])]
        and entry.get("status") in {"pending", "accepted"}
    ]

    next_rdv = "Aucun"
    if rdvs:
        dt, _, entry = rdvs[0]
        other = (
            int(entry["target_id"])
            if int(entry["requester_id"]) == user_id
            else int(entry["requester_id"])
        )
        next_rdv = f"<@{other}> — <t:{int(dt.timestamp())}:F>"

    return build_embed(
        "🗃️ Bureau de René",
        (
            f"Bienvenue <@{user_id}> au bureau administratif.\n\n"
            f"📅 **Rendez-vous à venir :** {len(rdvs)}\n"
            f"⚡ **Demandes express en attente :** {len(express)}\n"
            f"📨 **Courriers liés à ton compte :** {len(courriers)}\n"
            f"🧑‍💼 **Dossiers secrétaire actifs :** {len(secretariat)}\n\n"
            f"**Prochain rendez-vous :**\n{next_rdv}\n\n"
            "Utilise les boutons ci-dessous pour consulter les détails."
        ),
        COLOR_PRIMARY,
    )


class BureauView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Ce bureau appartient à quelqu'un d'autre.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Mes RDV", emoji="📅", style=discord.ButtonStyle.primary)
    async def rdv_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        rdvs = future_rendezvous_for(self.user_id)
        if not rdvs:
            text = "Aucun rendez-vous accepté à venir."
        else:
            lines = []
            for dt, rdv_id, entry in rdvs[:10]:
                other = (
                    int(entry["target_id"])
                    if int(entry["requester_id"]) == self.user_id
                    else int(entry["requester_id"])
                )
                lines.append(
                    f"• <@{other}> — <t:{int(dt.timestamp())}:F>"
                )
            text = "\n".join(lines)

        await interaction.response.edit_message(
            embed=build_embed("📅 Mes rendez-vous", text, COLOR_INFO),
            view=self,
        )

    @discord.ui.button(label="Mes courriers", emoji="📨", style=discord.ButtonStyle.secondary)
    async def mail_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        entries = []
        for entry in dict_store("_courriers").values():
            if not isinstance(entry, dict):
                continue
            sender = int(entry.get("sender_id", 0))
            recipient = int(entry.get("recipient_id", 0))
            if self.user_id not in {sender, recipient}:
                continue
            direction = "Envoyé à" if sender == self.user_id else "Reçu de"
            other = recipient if sender == self.user_id else sender
            status = "lu" if entry.get("read_at") else "non lu"
            entries.append(f"• {direction} <@{other}> — **{status}**")

        text = "\n".join(entries[-10:]) if entries else "Aucun courrier."
        await interaction.response.edit_message(
            embed=build_embed("📨 Mes courriers", text, COLOR_INFO),
            view=self,
        )

    @discord.ui.button(label="Commandes", emoji="⌨️", style=discord.ButtonStyle.secondary)
    async def commands_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_embed(
                "⌨️ Commandes du bureau",
                (
                    "`/rendevous` — rendez-vous classique\n"
                    "`/rdvexpress` — disponibilité immédiate\n"
                    "`/reporterrdv` — proposer un report\n"
                    "`/courrier` — envoyer un courrier\n"
                    "`/secretaire` — organiser automatiquement une réunion"
                ),
                COLOR_INFO,
            ),
            view=self,
        )

    @discord.ui.button(label="Actualiser", emoji="🔄", style=discord.ButtonStyle.success)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=summary_embed(self.user_id),
            view=self,
        )


@app_commands.command(
    name="bureau",
    description="Ouvrir ton bureau personnel avec René.",
)
@app_commands.guild_only()
async def bureau_command(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=summary_embed(interaction.user.id),
        view=BureauView(interaction.user.id),
        ephemeral=True,
    )


async def setup(client: commands.Bot):
    client.tree.add_command(bureau_command)


async def teardown(client: commands.Bot):
    client.tree.remove_command(bureau_command.name)