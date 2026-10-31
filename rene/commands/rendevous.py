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


# ============================================================
# /rendevous
# ------------------------------------------------------------
# Tout est contenu dans ce module :
# - confirmation de la demande
# - MP à la personne concernée
# - boutons Disponible / Pas disponible
# - rappel 10 minutes avant
# - restauration après redémarrage de Render
#
# AUCUNE modification de main.py n'est nécessaire.
# ============================================================

PARIS_TZ = ZoneInfo("Europe/Paris")
STORE_KEY = "_rendezvous"
MINIMUM_DELAY = timedelta(minutes=10)

reminder_tasks: dict[str, asyncio.Task[None]] = {}
registered_views: dict[str, "RendezVousInviteView"] = {}
restore_lock = asyncio.Lock()


def get_store() -> dict[str, dict]:
    """Stocke les rendez-vous dans config_data pour profiter du backup existant."""
    raw = bot.config_data.setdefault(STORE_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
        bot.config_data[STORE_KEY] = raw
    return raw


def get_rendezvous(rdv_id: str) -> dict | None:
    value = get_store().get(rdv_id)
    return value if isinstance(value, dict) else None


def parse_hour(value: str) -> tuple[int, int]:
    """
    Accepte :
    18
    18h
    18:30
    18h30
    08:05
    """
    cleaned = value.strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d{1,2})(?:(?:h|:)(\d{1,2}))?h?", cleaned)

    if not match:
        raise ValueError("Format d'heure invalide.")

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)

    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Heure invalide.")

    return hour, minute


def resolve_next_datetime(hour: int, minute: int) -> datetime:
    """
    Le rendez-vous est prévu au prochain passage de cette heure
    dans le fuseau Europe/Paris.

    Exemple :
    - il est 12:00, heure=18:00 -> aujourd'hui 18:00
    - il est 20:00, heure=18:00 -> demain 18:00
    """
    now = datetime.now(PARIS_TZ)
    target = now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )

    if target <= now:
        target += timedelta(days=1)

    return target


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def read_datetime(entry: dict) -> datetime | None:
    raw = entry.get("scheduled_at")
    if not isinstance(raw, str):
        return None

    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def discord_time(dt: datetime, style: str = "F") -> str:
    return f"<t:{int(dt.timestamp())}:{style}>"


def new_rendezvous_id() -> str:
    return uuid.uuid4().hex[:10].upper()


async def safe_dm(user_id: int, *, embed: discord.Embed) -> bool:
    try:
        user = bot.get_user(user_id)
        if user is None:
            user = await bot.fetch_user(user_id)
        await user.send(embed=embed)
        return True
    except (
        discord.Forbidden,
        discord.NotFound,
        discord.HTTPException,
    ):
        return False


async def notify_requester(
    entry: dict,
    *,
    title: str,
    description: str,
    color: discord.Color,
) -> bool:
    requester_id = int(entry["requester_id"])
    return await safe_dm(
        requester_id,
        embed=build_embed(title, description, color),
    )


def cancel_reminder(rdv_id: str) -> None:
    task = reminder_tasks.pop(rdv_id, None)
    if task is not None and not task.done():
        task.cancel()


async def reminder_worker(rdv_id: str) -> None:
    try:
        entry = get_rendezvous(rdv_id)
        if entry is None:
            return

        scheduled = read_datetime(entry)
        if scheduled is None:
            return

        reminder_at = scheduled - timedelta(minutes=10)
        now = datetime.now(timezone.utc)

        if reminder_at > now:
            await asyncio.sleep((reminder_at - now).total_seconds())

        # On relit les données après l'attente.
        entry = get_rendezvous(rdv_id)
        if entry is None:
            return

        if entry.get("status") != "accepted":
            return

        if entry.get("reminder_sent"):
            return

        scheduled = read_datetime(entry)
        if scheduled is None:
            return

        now = datetime.now(timezone.utc)

        # Si le rendez-vous est déjà passé, on ne rappelle pas.
        if scheduled <= now:
            entry["status"] = "expired"
            await save_state_immediately()
            return

        requester_id = int(entry["requester_id"])
        target_id = int(entry["target_id"])

        reminder_embed = build_embed(
            "⏰ Rendez-vous dans 10 minutes",
            (
                f"René vous rappelle votre rendez-vous.\n\n"
                f"👤 **Avec :** <@{target_id}> / <@{requester_id}>\n"
                f"🕐 **Heure :** {discord_time(scheduled, 't')}\n"
                f"📅 **Date :** {discord_time(scheduled, 'D')}\n\n"
                "Préparez-vous, René a déjà sorti son agenda."
            ),
            COLOR_WARNING,
        )

        sent_requester = await safe_dm(requester_id, embed=reminder_embed)
        sent_target = await safe_dm(target_id, embed=reminder_embed)

        entry["reminder_sent"] = True
        entry["reminder_sent_at"] = datetime.now(timezone.utc).isoformat()
        entry["reminder_delivery"] = {
            "requester": sent_requester,
            "target": sent_target,
        }
        await save_state_immediately()

        logger.info(
            "RENDEVOUS : rappel envoyé rdv=%s requester=%s target=%s",
            rdv_id,
            sent_requester,
            sent_target,
        )

    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("RENDEVOUS : erreur dans le rappel %s.", rdv_id)
    finally:
        reminder_tasks.pop(rdv_id, None)


def schedule_reminder(rdv_id: str) -> None:
    existing = reminder_tasks.get(rdv_id)
    if existing is not None and not existing.done():
        return

    reminder_tasks[rdv_id] = asyncio.create_task(
        reminder_worker(rdv_id),
        name=f"rene-rendezvous-{rdv_id}",
    )


class RendezVousInviteView(discord.ui.View):
    """Boutons envoyés en MP à la personne à qui le rendez-vous est demandé."""

    def __init__(self, rdv_id: str) -> None:
        super().__init__(timeout=None)
        self.rdv_id = rdv_id

        accept_button = discord.ui.Button(
            label="Je suis disponible",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"rene:rdv:accept:{rdv_id}",
        )
        decline_button = discord.ui.Button(
            label="Je ne suis pas disponible",
            style=discord.ButtonStyle.danger,
            emoji="❌",
            custom_id=f"rene:rdv:decline:{rdv_id}",
        )

        accept_button.callback = self.accept_callback
        decline_button.callback = self.decline_callback

        self.add_item(accept_button)
        self.add_item(decline_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        entry = get_rendezvous(self.rdv_id)

        if entry is None:
            await interaction.response.send_message(
                "Ce rendez-vous n'existe plus.",
                ephemeral=True,
            )
            return False

        if interaction.user.id != int(entry["target_id"]):
            await interaction.response.send_message(
                "Cette demande de rendez-vous ne t'est pas destinée.",
                ephemeral=True,
            )
            return False

        return True

    async def accept_callback(self, interaction: discord.Interaction) -> None:
        entry = get_rendezvous(self.rdv_id)
        if entry is None:
            await interaction.response.send_message(
                "Ce rendez-vous n'existe plus.",
                ephemeral=True,
            )
            return

        if entry.get("status") != "pending":
            await interaction.response.send_message(
                "Cette demande a déjà été traitée.",
                ephemeral=True,
            )
            return

        scheduled = read_datetime(entry)
        if scheduled is None or scheduled <= datetime.now(timezone.utc):
            entry["status"] = "expired"
            await save_state_immediately()

            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(
                embed=build_embed(
                    "⌛ Rendez-vous expiré",
                    "L'heure prévue est déjà passée.",
                    COLOR_DANGER,
                ),
                view=self,
            )
            return

        entry["status"] = "accepted"
        entry["responded_at"] = datetime.now(timezone.utc).isoformat()
        await save_state_immediately()

        for item in self.children:
            item.disabled = True

        requester_id = int(entry["requester_id"])

        await interaction.response.edit_message(
            embed=build_embed(
                "✅ Rendez-vous accepté",
                (
                    f"Tu as accepté le rendez-vous avec <@{requester_id}>.\n\n"
                    f"🕐 **Heure :** {discord_time(scheduled, 't')}\n"
                    f"📅 **Date :** {discord_time(scheduled, 'D')}\n\n"
                    "René vous enverra un rappel 10 minutes avant."
                ),
                COLOR_SUCCESS,
            ),
            view=self,
        )

        await notify_requester(
            entry,
            title="✅ Rendez-vous accepté",
            description=(
                f"<@{entry['target_id']}> a accepté ta demande de rendez-vous.\n\n"
                f"🕐 **Heure :** {discord_time(scheduled, 't')}\n"
                f"📅 **Date :** {discord_time(scheduled, 'D')}\n\n"
                "René vous enverra un rappel 10 minutes avant."
            ),
            color=COLOR_SUCCESS,
        )

        schedule_reminder(self.rdv_id)

        logger.info(
            "RENDEVOUS : %s accepté par %s.",
            self.rdv_id,
            interaction.user.id,
        )

    async def decline_callback(self, interaction: discord.Interaction) -> None:
        entry = get_rendezvous(self.rdv_id)
        if entry is None:
            await interaction.response.send_message(
                "Ce rendez-vous n'existe plus.",
                ephemeral=True,
            )
            return

        if entry.get("status") != "pending":
            await interaction.response.send_message(
                "Cette demande a déjà été traitée.",
                ephemeral=True,
            )
            return

        entry["status"] = "declined"
        entry["responded_at"] = datetime.now(timezone.utc).isoformat()
        await save_state_immediately()
        cancel_reminder(self.rdv_id)

        for item in self.children:
            item.disabled = True

        requester_id = int(entry["requester_id"])
        scheduled = read_datetime(entry)

        date_text = (
            f"\n🕐 **Heure demandée :** {discord_time(scheduled, 't')}"
            f"\n📅 **Date :** {discord_time(scheduled, 'D')}"
            if scheduled is not None
            else ""
        )

        await interaction.response.edit_message(
            embed=build_embed(
                "❌ Rendez-vous refusé",
                (
                    f"Tu as indiqué ne pas être disponible pour "
                    f"<@{requester_id}>.{date_text}"
                ),
                COLOR_DANGER,
            ),
            view=self,
        )

        await notify_requester(
            entry,
            title="❌ Rendez-vous refusé",
            description=(
                f"<@{entry['target_id']}> a indiqué ne pas être disponible "
                f"pour le rendez-vous demandé.{date_text}\n\n"
                "Tu peux refaire `/rendevous` avec une autre heure."
            ),
            color=COLOR_DANGER,
        )

        logger.info(
            "RENDEVOUS : %s refusé par %s.",
            self.rdv_id,
            interaction.user.id,
        )


class RendezVousConfirmView(discord.ui.View):
    """Confirmation affichée uniquement à l'auteur de /rendevous."""

    def __init__(
        self,
        *,
        requester_id: int,
        target_id: int,
        guild_id: int,
        channel_id: int | None,
        scheduled: datetime,
    ) -> None:
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.target_id = target_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.scheduled = scheduled
        self.finished_action = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Seule la personne ayant lancé la commande peut confirmer.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Confirmer la demande",
        style=discord.ButtonStyle.success,
        emoji="📅",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.finished_action:
            await interaction.response.send_message(
                "Cette demande a déjà été traitée.",
                ephemeral=True,
            )
            return

        self.finished_action = True
        await interaction.response.defer()

        rdv_id = new_rendezvous_id()

        entry = {
            "id": rdv_id,
            "guild_id": self.guild_id,
            "requester_id": self.requester_id,
            "target_id": self.target_id,
            "channel_id": self.channel_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "scheduled_at": utc_iso(self.scheduled),
            "status": "pending",
            "dm_message_id": None,
            "reminder_sent": False,
        }

        get_store()[rdv_id] = entry
        await save_state_immediately()

        target = bot.get_user(self.target_id)
        if target is None:
            try:
                target = await bot.fetch_user(self.target_id)
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                target = None

        if target is None:
            entry["status"] = "dm_failed"
            await save_state_immediately()

            await interaction.edit_original_response(
                embed=build_embed(
                    "❌ Impossible d'envoyer la demande",
                    "René n'arrive pas à retrouver cette personne.",
                    COLOR_DANGER,
                ),
                view=None,
            )
            return

        invite_view = RendezVousInviteView(rdv_id)

        try:
            dm_message = await target.send(
                embed=build_embed(
                    "📅 Demande de rendez-vous",
                    (
                        f"<@{self.requester_id}> souhaite prendre rendez-vous avec toi.\n\n"
                        f"🕐 **Heure :** {discord_time(self.scheduled, 't')}\n"
                        f"📅 **Date :** {discord_time(self.scheduled, 'D')}\n\n"
                        "Es-tu disponible ?"
                    ),
                    COLOR_INFO,
                ),
                view=invite_view,
            )
        except (discord.Forbidden, discord.HTTPException):
            entry["status"] = "dm_failed"
            await save_state_immediately()

            await interaction.edit_original_response(
                embed=build_embed(
                    "📪 MP impossible",
                    (
                        f"René ne peut pas envoyer de message privé à "
                        f"<@{self.target_id}>.\n\n"
                        "La personne doit autoriser les messages privés provenant "
                        "des membres du serveur."
                    ),
                    COLOR_DANGER,
                ),
                view=None,
            )
            return

        entry["dm_message_id"] = dm_message.id
        await save_state_immediately()

        registered_views[rdv_id] = invite_view
        # La vue est déjà attachée au message. On l'enregistre aussi comme
        # vue persistante pour les futures reconnexions.
        bot.add_view(invite_view, message_id=dm_message.id)

        await interaction.edit_original_response(
            embed=build_embed(
                "📨 Demande envoyée",
                (
                    f"René a envoyé un MP à <@{self.target_id}>.\n\n"
                    f"🕐 **Rendez-vous :** {discord_time(self.scheduled, 'F')}\n"
                    "Tu recevras un MP dès que la personne accepte ou refuse."
                ),
                COLOR_SUCCESS,
            ),
            view=None,
        )

        logger.info(
            "RENDEVOUS : demande %s créée requester=%s target=%s.",
            rdv_id,
            self.requester_id,
            self.target_id,
        )

        self.stop()

    @discord.ui.button(
        label="Annuler",
        style=discord.ButtonStyle.secondary,
        emoji="✖️",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.finished_action:
            await interaction.response.send_message(
                "Cette demande a déjà été traitée.",
                ephemeral=True,
            )
            return

        self.finished_action = True

        await interaction.response.edit_message(
            embed=build_embed(
                "Demande annulée",
                "Aucun rendez-vous n'a été envoyé.",
                COLOR_WARNING,
            ),
            view=None,
        )
        self.stop()

    async def on_timeout(self) -> None:
        self.stop()


@app_commands.command(
    name="rendevous",
    description="Demander un rendez-vous à une personne.",
)
@app_commands.describe(
    personne="Personne avec qui tu veux prendre rendez-vous",
    heure="Heure du rendez-vous, par exemple 18:30 ou 18h30",
)
@app_commands.guild_only()
async def rendevous_command(
    interaction: discord.Interaction,
    personne: discord.Member,
    heure: str,
) -> None:
    # Aucune permission spéciale : tout le monde peut utiliser la commande.
    if personne.bot:
        await interaction.response.send_message(
            embed=build_embed(
                "Impossible",
                "Tu ne peux pas demander un rendez-vous à un bot.",
                COLOR_DANGER,
            ),
            ephemeral=True,
        )
        return

    if personne.id == interaction.user.id:
        await interaction.response.send_message(
            embed=build_embed(
                "Impossible",
                "René refuse d'organiser un rendez-vous entre toi et toi-même.",
                COLOR_DANGER,
            ),
            ephemeral=True,
        )
        return

    try:
        hour, minute = parse_hour(heure)
    except ValueError:
        await interaction.response.send_message(
            embed=build_embed(
                "Heure invalide",
                (
                    "Utilise par exemple :\n"
                    "`18:30`\n"
                    "`18h30`\n"
                    "`18h`\n"
                    "`18`"
                ),
                COLOR_DANGER,
            ),
            ephemeral=True,
        )
        return

    scheduled = resolve_next_datetime(hour, minute)
    now = datetime.now(PARIS_TZ)

    if scheduled - now < MINIMUM_DELAY:
        await interaction.response.send_message(
            embed=build_embed(
                "Rendez-vous trop proche",
                (
                    "Le rendez-vous doit être prévu au moins **10 minutes** "
                    "à l'avance.\n\n"
                    "Choisis une heure un peu plus tard."
                ),
                COLOR_DANGER,
            ),
            ephemeral=True,
        )
        return

    view = RendezVousConfirmView(
        requester_id=interaction.user.id,
        target_id=personne.id,
        guild_id=interaction.guild_id or 0,
        channel_id=interaction.channel_id,
        scheduled=scheduled,
    )

    await interaction.response.send_message(
        embed=build_embed(
            "📅 Confirmer le rendez-vous",
            (
                f"👤 **Avec :** {personne.mention}\n"
                f"🕐 **Heure :** {discord_time(scheduled, 't')}\n"
                f"📅 **Date :** {discord_time(scheduled, 'D')}\n\n"
                "Après confirmation, René enverra un MP à la personne.\n"
                "Si elle accepte, vous recevrez tous les deux un rappel "
                "**10 minutes avant**."
            ),
            COLOR_PRIMARY,
        ),
        view=view,
        ephemeral=True,
    )


async def restore_rendezvous_after_ready() -> None:
    """
    Restaure les boutons et les rappels après un redémarrage/redeploy Render.
    """
    async with restore_lock:
        # on_ready du moteur recharge d'abord la sauvegarde distante.
        for _ in range(60):
            if bot.remote_state_loaded:
                break
            await asyncio.sleep(0.5)

        now = datetime.now(timezone.utc)
        changed = False

        for rdv_id, entry in list(get_store().items()):
            if not isinstance(entry, dict):
                continue

            scheduled = read_datetime(entry)
            if scheduled is None:
                continue

            status = entry.get("status")

            if scheduled <= now and status in {"pending", "accepted"}:
                entry["status"] = "expired"
                cancel_reminder(rdv_id)
                changed = True
                continue

            if status == "pending":
                message_id = entry.get("dm_message_id")
                if isinstance(message_id, int) and rdv_id not in registered_views:
                    view = RendezVousInviteView(rdv_id)
                    bot.add_view(view, message_id=message_id)
                    registered_views[rdv_id] = view

            elif status == "accepted" and not entry.get("reminder_sent"):
                schedule_reminder(rdv_id)

        if changed:
            await save_state_immediately()

        logger.info(
            "RENDEVOUS : restauration terminée (%s rendez-vous enregistrés).",
            len(get_store()),
        )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(rendevous_command)
    client.add_listener(
        restore_rendezvous_after_ready,
        "on_ready",
    )


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(rendevous_command.name)
    client.remove_listener(
        restore_rendezvous_after_ready,
        "on_ready",
    )

    for task in list(reminder_tasks.values()):
        task.cancel()
    reminder_tasks.clear()

    for view in list(registered_views.values()):
        try:
            client.remove_view(view)
        except Exception:
            pass
    registered_views.clear()