from __future__ import annotations

import asyncio
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
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_WARNING,
    bot,
    build_embed,
    logger,
    save_state_immediately,
)

PARIS = ZoneInfo("Europe/Paris")
STORE_KEY = "_secretariat"
views: dict[str, "AvailabilityView"] = {}
reminder_tasks: dict[str, asyncio.Task[None]] = {}
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


def resolve(value: str) -> datetime:
    hour, minute = parse_hour(value)
    now = datetime.now(PARIS)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def dtime(dt: datetime, style="t"):
    return f"<t:{int(dt.timestamp())}:{style}>"


async def safe_dm(user_id: int, *, embed: discord.Embed, view=None):
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        return await user.send(embed=embed, view=view)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        return None


def session_view_key(session_id: str, user_id: int):
    return f"{session_id}:{user_id}"


async def notify_all(entry: dict, embed: discord.Embed):
    for user_id in entry.get("participants", []):
        await safe_dm(int(user_id), embed=embed)


def common_slot(entry: dict) -> int | None:
    invitees = [
        int(user_id)
        for user_id in entry.get("participants", [])
        if int(user_id) != int(entry["creator_id"])
    ]

    if not invitees:
        return 0

    responses = entry.get("responses", {})
    if not isinstance(responses, dict):
        return None

    if not all(str(user_id) in responses for user_id in invitees):
        return None

    sets = []
    for user_id in invitees:
        response = responses.get(str(user_id), {})
        if not response.get("validated"):
            return None
        sets.append(set(int(i) for i in response.get("slots", [])))

    if not sets:
        return None

    intersection = set.intersection(*sets)
    if not intersection:
        return -1

    return min(intersection)


async def reminder_worker(session_id: str):
    try:
        entry = store().get(session_id)
        if not isinstance(entry, dict):
            return
        if entry.get("status") != "accepted":
            return

        raw = entry.get("scheduled_at")
        if not isinstance(raw, str):
            return

        scheduled = datetime.fromisoformat(raw)
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)

        reminder_at = scheduled - timedelta(minutes=10)
        delay = (reminder_at - datetime.now(timezone.utc)).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)

        entry = store().get(session_id)
        if not isinstance(entry, dict):
            return
        if entry.get("status") != "accepted" or entry.get("reminder_sent"):
            return

        if scheduled <= datetime.now(timezone.utc):
            entry["status"] = "expired"
            await save_state_immediately()
            return

        mentions = " ".join(f"<@{x}>" for x in entry["participants"])
        embed = build_embed(
            "🧑‍💼 Réunion dans 10 minutes",
            (
                f"**Sujet :** {entry['subject']}\n"
                f"**Heure :** {dtime(scheduled, 'F')}\n"
                f"**Participants :** {mentions}\n\n"
                "René vous rappelle que la réunion approche."
            ),
            COLOR_WARNING,
        )

        await notify_all(entry, embed)
        entry["reminder_sent"] = True
        await save_state_immediately()

    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("SECRETAIRE : erreur rappel %s", session_id)
    finally:
        reminder_tasks.pop(session_id, None)


def schedule_reminder(session_id: str):
    task = reminder_tasks.get(session_id)
    if task is not None and not task.done():
        return
    reminder_tasks[session_id] = asyncio.create_task(
        reminder_worker(session_id),
        name=f"rene-secretaire-{session_id}",
    )


async def evaluate_session(session_id: str):
    entry = store().get(session_id)
    if not isinstance(entry, dict):
        return

    slot_index = common_slot(entry)
    if slot_index is None:
        return

    creator_id = int(entry["creator_id"])

    if slot_index == -1:
        entry["status"] = "no_common_slot"
        await save_state_immediately()

        await safe_dm(
            creator_id,
            embed=build_embed(
                "❌ Aucun créneau commun",
                (
                    f"René n'a trouvé aucun créneau commun pour **{entry['subject']}**.\n\n"
                    "Tu peux relancer `/secretaire` avec d'autres horaires."
                ),
                COLOR_DANGER,
            ),
        )
        return

    slots = entry["slots"]
    selected = datetime.fromisoformat(slots[slot_index])
    if selected.tzinfo is None:
        selected = selected.replace(tzinfo=timezone.utc)

    entry["status"] = "accepted"
    entry["selected_slot"] = slot_index
    entry["scheduled_at"] = selected.astimezone(timezone.utc).isoformat()
    entry["reminder_sent"] = False
    await save_state_immediately()

    mentions = " ".join(f"<@{x}>" for x in entry["participants"])
    embed = build_embed(
        "✅ René a trouvé un créneau",
        (
            f"**Sujet :** {entry['subject']}\n"
            f"**Date :** {dtime(selected, 'F')}\n"
            f"**Participants :** {mentions}\n\n"
            "Tout le monde est disponible sur ce créneau.\n"
            "René vous rappellera la réunion 10 minutes avant."
        ),
        COLOR_SUCCESS,
    )

    await notify_all(entry, embed)
    schedule_reminder(session_id)


class AvailabilityView(discord.ui.View):
    def __init__(self, session_id: str, user_id: int):
        super().__init__(timeout=None)
        self.session_id = session_id
        self.user_id = user_id

        entry = store().get(session_id, {})
        slots = entry.get("slots", []) if isinstance(entry, dict) else []

        for index, raw in enumerate(slots[:3]):
            try:
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                label = dt.astimezone(PARIS).strftime("%H:%M")
            except Exception:
                label = f"Créneau {index + 1}"

            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                custom_id=f"rene:secretaire:slot:{session_id}:{user_id}:{index}",
            )

            async def callback(interaction: discord.Interaction, slot_index=index):
                await self.toggle(interaction, slot_index)

            button.callback = callback
            self.add_item(button)

        validate = discord.ui.Button(
            label="Valider mes disponibilités",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"rene:secretaire:validate:{session_id}:{user_id}",
        )
        unavailable = discord.ui.Button(
            label="Aucun créneau",
            style=discord.ButtonStyle.danger,
            emoji="❌",
            custom_id=f"rene:secretaire:none:{session_id}:{user_id}",
        )

        validate.callback = self.validate
        unavailable.callback = self.none

        self.add_item(validate)
        self.add_item(unavailable)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Cette demande de disponibilités ne t'est pas destinée.",
                ephemeral=True,
            )
            return False
        return True

    def response_data(self):
        entry = store().get(self.session_id)
        if not isinstance(entry, dict):
            return None, None

        responses = entry.setdefault("responses", {})
        response = responses.setdefault(
            str(self.user_id),
            {"slots": [], "validated": False},
        )
        return entry, response

    async def toggle(self, interaction: discord.Interaction, slot_index: int):
        entry, response = self.response_data()
        if not entry or not response:
            await interaction.response.send_message(
                "Cette demande n'existe plus.",
                ephemeral=True,
            )
            return

        if response.get("validated"):
            await interaction.response.send_message(
                "Tu as déjà validé ta réponse.",
                ephemeral=True,
            )
            return

        selected = set(int(x) for x in response.get("slots", []))
        if slot_index in selected:
            selected.remove(slot_index)
        else:
            selected.add(slot_index)

        response["slots"] = sorted(selected)
        await save_state_immediately()

        chosen = []
        for idx in sorted(selected):
            raw = entry["slots"][idx]
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            chosen.append(dtime(dt, "t"))

        text = ", ".join(chosen) if chosen else "aucun pour le moment"
        await interaction.response.send_message(
            f"🗓️ Créneaux sélectionnés : {text}",
            ephemeral=True,
        )

    async def validate(self, interaction: discord.Interaction):
        entry, response = self.response_data()
        if not entry or not response:
            return

        if not response.get("slots"):
            await interaction.response.send_message(
                "Sélectionne au moins un créneau, ou clique sur **Aucun créneau**.",
                ephemeral=True,
            )
            return

        response["validated"] = True
        response["validated_at"] = datetime.now(timezone.utc).isoformat()
        await save_state_immediately()

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=build_embed(
                "✅ Disponibilités enregistrées",
                "René a noté tes disponibilités et attend les autres personnes.",
                COLOR_SUCCESS,
            ),
            view=self,
        )

        await evaluate_session(self.session_id)

    async def none(self, interaction: discord.Interaction):
        entry, response = self.response_data()
        if not entry or not response:
            return

        response["slots"] = []
        response["validated"] = True
        response["validated_at"] = datetime.now(timezone.utc).isoformat()
        await save_state_immediately()

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=build_embed(
                "❌ Aucun créneau disponible",
                "René a enregistré que tu n'es disponible sur aucun des créneaux.",
                COLOR_DANGER,
            ),
            view=self,
        )

        await evaluate_session(self.session_id)


@app_commands.command(
    name="secretaire",
    description="Demander à René de trouver un créneau commun pour une réunion.",
)
@app_commands.describe(
    personne1="Première personne à inviter",
    sujet="Sujet de la réunion",
    heure1="Premier créneau, ex : 18h",
    heure2="Deuxième créneau, ex : 19h",
    heure3="Troisième créneau, ex : 20h",
    personne2="Deuxième personne, optionnelle",
    personne3="Troisième personne, optionnelle",
)
@app_commands.guild_only()
async def secretaire_command(
    interaction: discord.Interaction,
    personne1: discord.Member,
    sujet: str,
    heure1: str,
    heure2: str,
    heure3: str,
    personne2: discord.Member | None = None,
    personne3: discord.Member | None = None,
):
    people = [personne1, personne2, personne3]
    people = [p for p in people if p is not None]

    if any(p.bot for p in people):
        await interaction.response.send_message(
            "❌ René ne convoque pas les bots aux réunions.",
            ephemeral=True,
        )
        return

    ids = [p.id for p in people]
    if interaction.user.id in ids or len(ids) != len(set(ids)):
        await interaction.response.send_message(
            "❌ Les participants doivent être différents de toi et les uns des autres.",
            ephemeral=True,
        )
        return

    try:
        proposed = [resolve(heure1), resolve(heure2), resolve(heure3)]
    except ValueError:
        await interaction.response.send_message(
            "❌ Heure invalide. Exemple : `18h30`.",
            ephemeral=True,
        )
        return

    # Supprime les doublons et trie.
    unique = {}
    for dt in proposed:
        unique[int(dt.timestamp())] = dt
    proposed = sorted(unique.values())

    if len(proposed) < 2:
        await interaction.response.send_message(
            "❌ Propose au moins deux horaires différents.",
            ephemeral=True,
        )
        return

    if any(dt - datetime.now(PARIS) < timedelta(minutes=15) for dt in proposed):
        await interaction.response.send_message(
            "❌ Tous les créneaux doivent être au moins 15 minutes dans le futur.",
            ephemeral=True,
        )
        return

    session_id = uuid.uuid4().hex[:10].upper()
    participants = [interaction.user.id] + ids

    entry = {
        "id": session_id,
        "guild_id": interaction.guild_id,
        "creator_id": interaction.user.id,
        "subject": sujet.strip()[:300] or "Réunion",
        "participants": participants,
        "slots": [dt.astimezone(timezone.utc).isoformat() for dt in proposed],
        "responses": {},
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scheduled_at": None,
        "reminder_sent": False,
        "dm_messages": {},
    }
    store()[session_id] = entry
    await save_state_immediately()

    failed = []

    for person in people:
        view = AvailabilityView(session_id, person.id)
        slot_lines = "\n".join(
            f"• {dtime(dt, 'F')}" for dt in proposed
        )

        dm = await safe_dm(
            person.id,
            embed=build_embed(
                "🧑‍💼 René cherche un créneau",
                (
                    f"<@{interaction.user.id}> souhaite organiser une réunion.\n\n"
                    f"**Sujet :** {entry['subject']}\n\n"
                    f"**Créneaux proposés :**\n{slot_lines}\n\n"
                    "Sélectionne tous les créneaux où tu es disponible, "
                    "puis valide ta réponse."
                ),
                COLOR_PRIMARY,
            ),
            view=view,
        )

        if dm is None:
            failed.append(person.id)
            continue

        entry["dm_messages"][str(person.id)] = dm.id
        key = session_view_key(session_id, person.id)
        bot.add_view(view, message_id=dm.id)
        views[key] = view

    if failed:
        entry["status"] = "dm_failed"
        entry["failed_users"] = failed
        await save_state_immediately()

        mentions = " ".join(f"<@{x}>" for x in failed)
        await interaction.response.send_message(
            (
                f"📪 René n'a pas pu contacter : {mentions}.\n"
                "La recherche de créneau est annulée."
            ),
            ephemeral=True,
        )
        return

    await save_state_immediately()

    await interaction.response.send_message(
        (
            f"🧑‍💼 René a contacté **{len(people)} personne(s)**.\n"
            "Il te préviendra automatiquement dès qu'il trouve un créneau commun."
        ),
        ephemeral=True,
    )


async def restore_after_ready():
    async with restore_lock:
        for _ in range(60):
            if bot.remote_state_loaded:
                break
            await asyncio.sleep(0.5)

        now = datetime.now(timezone.utc)

        for session_id, entry in list(store().items()):
            if not isinstance(entry, dict):
                continue

            if entry.get("status") == "pending":
                messages = entry.get("dm_messages", {})
                if not isinstance(messages, dict):
                    continue

                responses = entry.get("responses", {})
                for raw_user_id, message_id in messages.items():
                    try:
                        user_id = int(raw_user_id)
                    except ValueError:
                        continue

                    response = responses.get(str(user_id), {})
                    if response.get("validated"):
                        continue

                    key = session_view_key(session_id, user_id)
                    if isinstance(message_id, int) and key not in views:
                        view = AvailabilityView(session_id, user_id)
                        bot.add_view(view, message_id=message_id)
                        views[key] = view

            elif entry.get("status") == "accepted" and not entry.get("reminder_sent"):
                raw = entry.get("scheduled_at")
                if not isinstance(raw, str):
                    continue
                try:
                    scheduled = datetime.fromisoformat(raw)
                    if scheduled.tzinfo is None:
                        scheduled = scheduled.replace(tzinfo=timezone.utc)
                    if scheduled > now:
                        schedule_reminder(session_id)
                except ValueError:
                    pass


async def setup(client: commands.Bot):
    client.tree.add_command(secretaire_command)
    client.add_listener(restore_after_ready, "on_ready")


async def teardown(client: commands.Bot):
    client.tree.remove_command(secretaire_command.name)
    client.remove_listener(restore_after_ready, "on_ready")

    for task in list(reminder_tasks.values()):
        task.cancel()
    reminder_tasks.clear()

    for view in list(views.values()):
        try:
            client.remove_view(view)
        except Exception:
            pass
    views.clear()