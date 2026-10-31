from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from rene.core import (
    COLOR_DANGER,
    COLOR_INFO,
    COLOR_SUCCESS,
    COLOR_WARNING,
    bot,
    build_embed,
    logger,
    save_state_immediately,
)

STORE_KEY = "_rdvexpress"
tasks: dict[str, asyncio.Task[None]] = {}
views: dict[str, "ExpressView"] = {}
restore_lock = asyncio.Lock()


def store() -> dict[str, dict]:
    data = bot.config_data.setdefault(STORE_KEY, {})
    if not isinstance(data, dict):
        data = {}
        bot.config_data[STORE_KEY] = data
    return data


async def safe_dm(user_id: int, embed: discord.Embed, view: discord.ui.View | None = None):
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        return await user.send(embed=embed, view=view)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        return None


async def reminder_worker(request_id: str) -> None:
    try:
        entry = store().get(request_id)
        if not isinstance(entry, dict):
            return

        raw_due = entry.get("due_at")
        if not raw_due:
            return

        due = datetime.fromisoformat(raw_due)
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)

        delay = (due - datetime.now(timezone.utc)).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)

        entry = store().get(request_id)
        if not isinstance(entry, dict):
            return
        if entry.get("status") not in {"accepted_5", "accepted_10"}:
            return
        if entry.get("reminder_sent"):
            return

        requester_id = int(entry["requester_id"])
        target_id = int(entry["target_id"])

        embed = build_embed(
            "⚡ Rendez-vous express",
            (
                "C'est l'heure du rendez-vous express.\n\n"
                f"👤 <@{requester_id}> ↔ <@{target_id}>\n"
                "René considère maintenant que vous pouvez vous retrouver."
            ),
            COLOR_WARNING,
        )

        await safe_dm(requester_id, embed)
        await safe_dm(target_id, embed)

        entry["reminder_sent"] = True
        entry["reminder_sent_at"] = datetime.now(timezone.utc).isoformat()
        await save_state_immediately()

    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("RDVEXPRESS : erreur rappel %s", request_id)
    finally:
        tasks.pop(request_id, None)


def schedule(request_id: str) -> None:
    existing = tasks.get(request_id)
    if existing is not None and not existing.done():
        return
    tasks[request_id] = asyncio.create_task(
        reminder_worker(request_id),
        name=f"rene-rdvexpress-{request_id}",
    )


class ExpressView(discord.ui.View):
    def __init__(self, request_id: str):
        super().__init__(timeout=None)
        self.request_id = request_id

        options = [
            ("J'arrive maintenant", discord.ButtonStyle.success, "now", "✅"),
            ("Dans 5 min", discord.ButtonStyle.primary, "5", "5️⃣"),
            ("Dans 10 min", discord.ButtonStyle.primary, "10", "🔟"),
            ("Pas disponible", discord.ButtonStyle.danger, "no", "❌"),
        ]

        for label, style, value, emoji in options:
            button = discord.ui.Button(
                label=label,
                style=style,
                emoji=emoji,
                custom_id=f"rene:rdvexpress:{value}:{request_id}",
            )

            async def callback(
                interaction: discord.Interaction,
                selected=value,
            ):
                await self.handle(interaction, selected)

            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        entry = store().get(self.request_id)
        if not isinstance(entry, dict):
            await interaction.response.send_message(
                "Cette demande n'existe plus.",
                ephemeral=True,
            )
            return False

        if interaction.user.id != int(entry["target_id"]):
            await interaction.response.send_message(
                "Cette demande ne t'est pas destinée.",
                ephemeral=True,
            )
            return False

        return True

    async def handle(self, interaction: discord.Interaction, choice: str):
        entry = store().get(self.request_id)
        if not isinstance(entry, dict):
            await interaction.response.send_message("Demande introuvable.", ephemeral=True)
            return

        if entry.get("status") != "pending":
            await interaction.response.send_message(
                "Cette demande a déjà reçu une réponse.",
                ephemeral=True,
            )
            return

        requester_id = int(entry["requester_id"])
        target_id = int(entry["target_id"])

        for child in self.children:
            child.disabled = True

        if choice == "no":
            entry["status"] = "declined"
            await save_state_immediately()

            await interaction.response.edit_message(
                embed=build_embed(
                    "❌ Indisponible",
                    f"Tu as indiqué ne pas être disponible pour <@{requester_id}>.",
                    COLOR_DANGER,
                ),
                view=self,
            )

            await safe_dm(
                requester_id,
                build_embed(
                    "❌ Rendez-vous express refusé",
                    f"<@{target_id}> n'est pas disponible maintenant.",
                    COLOR_DANGER,
                ),
            )
            return

        if choice == "now":
            entry["status"] = "accepted_now"
            await save_state_immediately()

            await interaction.response.edit_message(
                embed=build_embed(
                    "✅ Disponible maintenant",
                    f"Tu as indiqué à <@{requester_id}> que tu es disponible maintenant.",
                    COLOR_SUCCESS,
                ),
                view=self,
            )

            await safe_dm(
                requester_id,
                build_embed(
                    "✅ Rendez-vous express accepté",
                    f"<@{target_id}> est disponible **maintenant**.",
                    COLOR_SUCCESS,
                ),
            )
            return

        minutes = 5 if choice == "5" else 10
        due = datetime.now(timezone.utc) + timedelta(minutes=minutes)

        entry["status"] = f"accepted_{minutes}"
        entry["due_at"] = due.isoformat()
        entry["reminder_sent"] = False
        await save_state_immediately()

        await interaction.response.edit_message(
            embed=build_embed(
                "✅ Rendez-vous express accepté",
                (
                    f"Tu as indiqué être disponible dans **{minutes} minutes** "
                    f"pour <@{requester_id}>."
                ),
                COLOR_SUCCESS,
            ),
            view=self,
        )

        await safe_dm(
            requester_id,
            build_embed(
                "⚡ Rendez-vous express",
                (
                    f"<@{target_id}> sera disponible dans **{minutes} minutes**.\n\n"
                    "René vous préviendra au moment prévu."
                ),
                COLOR_SUCCESS,
            ),
        )

        schedule(self.request_id)


@app_commands.command(
    name="rdvexpress",
    description="Demander rapidement à quelqu'un s'il est disponible.",
)
@app_commands.describe(membre="Personne à contacter")
@app_commands.guild_only()
async def rdvexpress_command(
    interaction: discord.Interaction,
    membre: discord.Member,
):
    if membre.bot:
        await interaction.response.send_message(
            "❌ Tu ne peux pas demander un rendez-vous express à un bot.",
            ephemeral=True,
        )
        return

    if membre.id == interaction.user.id:
        await interaction.response.send_message(
            "❌ Tu ne peux pas te demander un rendez-vous à toi-même.",
            ephemeral=True,
        )
        return

    request_id = uuid.uuid4().hex[:10].upper()
    entry = {
        "id": request_id,
        "guild_id": interaction.guild_id,
        "requester_id": interaction.user.id,
        "target_id": membre.id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "dm_message_id": None,
        "reminder_sent": False,
    }
    store()[request_id] = entry
    await save_state_immediately()

    view = ExpressView(request_id)
    message = await safe_dm(
        membre.id,
        build_embed(
            "⚡ Rendez-vous express",
            (
                f"<@{interaction.user.id}> souhaite te parler rapidement.\n\n"
                "Quand es-tu disponible ?"
            ),
            COLOR_INFO,
        ),
        view=view,
    )

    if message is None:
        entry["status"] = "dm_failed"
        await save_state_immediately()
        await interaction.response.send_message(
            f"📪 René ne peut pas envoyer de MP à {membre.mention}.",
            ephemeral=True,
        )
        return

    entry["dm_message_id"] = message.id
    await save_state_immediately()

    bot.add_view(view, message_id=message.id)
    views[request_id] = view

    await interaction.response.send_message(
        f"📨 René a demandé à {membre.mention} s'il est disponible.",
        ephemeral=True,
    )


async def restore_after_ready():
    async with restore_lock:
        for _ in range(60):
            if bot.remote_state_loaded:
                break
            await asyncio.sleep(0.5)

        now = datetime.now(timezone.utc)

        for request_id, entry in list(store().items()):
            if not isinstance(entry, dict):
                continue

            status = entry.get("status")

            if status == "pending":
                message_id = entry.get("dm_message_id")
                if isinstance(message_id, int) and request_id not in views:
                    view = ExpressView(request_id)
                    bot.add_view(view, message_id=message_id)
                    views[request_id] = view

            elif status in {"accepted_5", "accepted_10"} and not entry.get("reminder_sent"):
                raw_due = entry.get("due_at")
                try:
                    due = datetime.fromisoformat(raw_due)
                    if due.tzinfo is None:
                        due = due.replace(tzinfo=timezone.utc)
                    if due > now:
                        schedule(request_id)
                except Exception:
                    pass


async def setup(client: commands.Bot):
    client.tree.add_command(rdvexpress_command)
    client.add_listener(restore_after_ready, "on_ready")


async def teardown(client: commands.Bot):
    client.tree.remove_command(rdvexpress_command.name)
    client.remove_listener(restore_after_ready, "on_ready")

    for task in list(tasks.values()):
        task.cancel()
    tasks.clear()

    for view in list(views.values()):
        try:
            client.remove_view(view)
        except Exception:
            pass
    views.clear()