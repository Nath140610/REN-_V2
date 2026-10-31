from __future__ import annotations

import asyncio
import importlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from rene.core import (
    COLOR_DANGER,
    COLOR_INFO,
    COLOR_SUCCESS,
    bot,
    build_embed,
    logger,
    save_state_immediately,
)

PARIS = ZoneInfo("Europe/Paris")
STORE_KEY = "_rendezvous"
proposal_views: dict[str, "RescheduleView"] = {}
restore_lock = asyncio.Lock()


def store() -> dict[str, dict]:
    data = bot.config_data.setdefault(STORE_KEY, {})
    if not isinstance(data, dict):
        data = {}
        bot.config_data[STORE_KEY] = data
    return data


def parse_hour(value: str) -> tuple[int, int]:
    cleaned = value.strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d{1,2})(?:(?:h|:)(\d{1,2}))?h?", cleaned)
    if not match:
        raise ValueError
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError
    return hour, minute


def next_datetime(hour: int, minute: int) -> datetime:
    now = datetime.now(PARIS)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def read_dt(entry: dict) -> datetime | None:
    raw = entry.get("scheduled_at")
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def discord_time(dt: datetime, style="F"):
    return f"<t:{int(dt.timestamp())}:{style}>"


async def safe_dm(user_id: int, embed: discord.Embed, view=None):
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        return await user.send(embed=embed, view=view)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        return None


def find_next_rdv(user_a: int, user_b: int) -> tuple[str, dict] | tuple[None, None]:
    now = datetime.now(timezone.utc)
    candidates = []

    for rdv_id, entry in store().items():
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "accepted":
            continue

        pair = {int(entry.get("requester_id", 0)), int(entry.get("target_id", 0))}
        if pair != {user_a, user_b}:
            continue

        scheduled = read_dt(entry)
        if scheduled is None or scheduled <= now:
            continue

        candidates.append((scheduled, rdv_id, entry))

    if not candidates:
        return None, None

    candidates.sort(key=lambda x: x[0])
    _, rdv_id, entry = candidates[0]
    return rdv_id, entry


def refresh_original_reminder(rdv_id: str):
    try:
        module = importlib.import_module("rene.commands.rendevous")
        cancel = getattr(module, "cancel_reminder", None)
        schedule = getattr(module, "schedule_reminder", None)

        if callable(cancel):
            cancel(rdv_id)
        if callable(schedule):
            schedule(rdv_id)
    except Exception:
        logger.exception(
            "REPORTERRDV : impossible de reprogrammer le rappel %s",
            rdv_id,
        )


class RescheduleView(discord.ui.View):
    def __init__(self, proposal_id: str, rdv_id: str):
        super().__init__(timeout=None)
        self.proposal_id = proposal_id
        self.rdv_id = rdv_id

        yes = discord.ui.Button(
            label="Accepter la nouvelle heure",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"rene:reporterrdv:yes:{proposal_id}",
        )
        no = discord.ui.Button(
            label="Refuser",
            style=discord.ButtonStyle.danger,
            emoji="❌",
            custom_id=f"rene:reporterrdv:no:{proposal_id}",
        )
        yes.callback = self.accept
        no.callback = self.decline
        self.add_item(yes)
        self.add_item(no)

    def proposal(self):
        entry = store().get(self.rdv_id)
        if not isinstance(entry, dict):
            return None, None
        proposal = entry.get("reschedule_proposal")
        if not isinstance(proposal, dict):
            return entry, None
        if proposal.get("proposal_id") != self.proposal_id:
            return entry, None
        return entry, proposal

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        entry, proposal = self.proposal()
        if not entry or not proposal:
            await interaction.response.send_message(
                "Cette proposition n'existe plus.",
                ephemeral=True,
            )
            return False

        if interaction.user.id != int(proposal["recipient_id"]):
            await interaction.response.send_message(
                "Cette proposition ne t'est pas destinée.",
                ephemeral=True,
            )
            return False
        return True

    async def accept(self, interaction: discord.Interaction):
        entry, proposal = self.proposal()
        if not entry or not proposal:
            return

        if proposal.get("status") != "pending":
            await interaction.response.send_message(
                "Cette proposition a déjà été traitée.",
                ephemeral=True,
            )
            return

        new_dt = datetime.fromisoformat(proposal["proposed_at"])
        if new_dt.tzinfo is None:
            new_dt = new_dt.replace(tzinfo=timezone.utc)

        entry["scheduled_at"] = new_dt.astimezone(timezone.utc).isoformat()
        entry["reminder_sent"] = False
        proposal["status"] = "accepted"
        proposal["answered_at"] = datetime.now(timezone.utc).isoformat()

        await save_state_immediately()
        refresh_original_reminder(self.rdv_id)

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=build_embed(
                "✅ Rendez-vous reporté",
                (
                    f"Nouvelle date : {discord_time(new_dt, 'F')}\n\n"
                    "René a reprogrammé le rappel 10 minutes avant."
                ),
                COLOR_SUCCESS,
            ),
            view=self,
        )

        await safe_dm(
            int(proposal["requested_by"]),
            build_embed(
                "✅ Report accepté",
                (
                    f"<@{proposal['recipient_id']}> a accepté le report.\n\n"
                    f"📅 **Nouvelle date :** {discord_time(new_dt, 'F')}"
                ),
                COLOR_SUCCESS,
            ),
        )

    async def decline(self, interaction: discord.Interaction):
        entry, proposal = self.proposal()
        if not entry or not proposal:
            return

        if proposal.get("status") != "pending":
            await interaction.response.send_message(
                "Cette proposition a déjà été traitée.",
                ephemeral=True,
            )
            return

        proposal["status"] = "declined"
        proposal["answered_at"] = datetime.now(timezone.utc).isoformat()
        await save_state_immediately()

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=build_embed(
                "❌ Report refusé",
                "Le rendez-vous reste à son heure actuelle.",
                COLOR_DANGER,
            ),
            view=self,
        )

        await safe_dm(
            int(proposal["requested_by"]),
            build_embed(
                "❌ Report refusé",
                (
                    f"<@{proposal['recipient_id']}> a refusé la nouvelle heure.\n"
                    "Le rendez-vous initial reste inchangé."
                ),
                COLOR_DANGER,
            ),
        )


@app_commands.command(
    name="reporterrdv",
    description="Proposer une nouvelle heure pour un rendez-vous accepté.",
)
@app_commands.describe(
    personne="L'autre personne du rendez-vous",
    nouvelle_heure="Exemple : 19h30 ou 19:30",
)
@app_commands.guild_only()
async def reporterrdv_command(
    interaction: discord.Interaction,
    personne: discord.Member,
    nouvelle_heure: str,
):
    if personne.bot or personne.id == interaction.user.id:
        await interaction.response.send_message(
            "❌ Personne invalide.",
            ephemeral=True,
        )
        return

    rdv_id, entry = find_next_rdv(interaction.user.id, personne.id)
    if not rdv_id or not entry:
        await interaction.response.send_message(
            f"❌ Aucun rendez-vous accepté à venir avec {personne.mention}.",
            ephemeral=True,
        )
        return

    try:
        hour, minute = parse_hour(nouvelle_heure)
        proposed = next_datetime(hour, minute)
    except ValueError:
        await interaction.response.send_message(
            "❌ Heure invalide. Exemple : `19h30`.",
            ephemeral=True,
        )
        return

    if proposed - datetime.now(PARIS) < timedelta(minutes=10):
        await interaction.response.send_message(
            "❌ La nouvelle heure doit être au moins 10 minutes dans le futur.",
            ephemeral=True,
        )
        return

    proposal_id = uuid.uuid4().hex[:10].upper()
    proposal = {
        "proposal_id": proposal_id,
        "requested_by": interaction.user.id,
        "recipient_id": personne.id,
        "proposed_at": proposed.astimezone(timezone.utc).isoformat(),
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dm_message_id": None,
    }

    entry["reschedule_proposal"] = proposal
    await save_state_immediately()

    view = RescheduleView(proposal_id, rdv_id)
    dm = await safe_dm(
        personne.id,
        build_embed(
            "📅 Demande de report",
            (
                f"<@{interaction.user.id}> souhaite reporter votre rendez-vous.\n\n"
                f"🆕 **Nouvelle proposition :** {discord_time(proposed, 'F')}\n\n"
                "Acceptes-tu cette nouvelle heure ?"
            ),
            COLOR_INFO,
        ),
        view=view,
    )

    if dm is None:
        proposal["status"] = "dm_failed"
        await save_state_immediately()
        await interaction.response.send_message(
            f"📪 René ne peut pas envoyer de MP à {personne.mention}.",
            ephemeral=True,
        )
        return

    proposal["dm_message_id"] = dm.id
    await save_state_immediately()

    bot.add_view(view, message_id=dm.id)
    proposal_views[proposal_id] = view

    await interaction.response.send_message(
        f"📨 René a proposé la nouvelle heure à {personne.mention}.",
        ephemeral=True,
    )


async def restore_after_ready():
    async with restore_lock:
        for _ in range(60):
            if bot.remote_state_loaded:
                break
            await asyncio.sleep(0.5)

        for rdv_id, entry in list(store().items()):
            if not isinstance(entry, dict):
                continue
            proposal = entry.get("reschedule_proposal")
            if not isinstance(proposal, dict):
                continue
            if proposal.get("status") != "pending":
                continue

            proposal_id = proposal.get("proposal_id")
            message_id = proposal.get("dm_message_id")

            if (
                isinstance(proposal_id, str)
                and isinstance(message_id, int)
                and proposal_id not in proposal_views
            ):
                view = RescheduleView(proposal_id, rdv_id)
                bot.add_view(view, message_id=message_id)
                proposal_views[proposal_id] = view


async def setup(client: commands.Bot):
    client.tree.add_command(reporterrdv_command)
    client.add_listener(restore_after_ready, "on_ready")


async def teardown(client: commands.Bot):
    client.tree.remove_command(reporterrdv_command.name)
    client.remove_listener(restore_after_ready, "on_ready")
    for view in list(proposal_views.values()):
        try:
            client.remove_view(view)
        except Exception:
            pass
    proposal_views.clear()