from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

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

STORE_KEY = "_courriers"
COOLDOWN_SECONDS = 60
views: dict[str, "CourrierView"] = {}
restore_registered = False


def store() -> dict[str, dict]:
    data = bot.config_data.setdefault(STORE_KEY, {})
    if not isinstance(data, dict):
        data = {}
        bot.config_data[STORE_KEY] = data
    return data


async def safe_dm(user_id: int, *, embed: discord.Embed, view=None):
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        return await user.send(embed=embed, view=view)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        return None


def latest_sent_time(sender_id: int) -> float | None:
    latest = None
    for entry in store().values():
        if not isinstance(entry, dict):
            continue
        if int(entry.get("sender_id", 0)) != sender_id:
            continue
        raw = entry.get("created_at")
        if not isinstance(raw, str):
            continue
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts = dt.timestamp()
            latest = ts if latest is None else max(latest, ts)
        except ValueError:
            pass
    return latest


class ReplyModal(discord.ui.Modal, title="Répondre au courrier"):
    response = discord.ui.TextInput(
        label="Ta réponse",
        style=discord.TextStyle.paragraph,
        max_length=1800,
        required=True,
    )

    def __init__(self, mail_id: str):
        super().__init__()
        self.mail_id = mail_id

    async def on_submit(self, interaction: discord.Interaction):
        entry = store().get(self.mail_id)
        if not isinstance(entry, dict):
            await interaction.response.send_message(
                "Ce courrier n'existe plus.",
                ephemeral=True,
            )
            return

        recipient_id = int(entry["recipient_id"])
        if interaction.user.id != recipient_id:
            await interaction.response.send_message(
                "Tu n'es pas le destinataire de ce courrier.",
                ephemeral=True,
            )
            return

        sender_id = int(entry["sender_id"])
        text = str(self.response.value).strip()

        sent = await safe_dm(
            sender_id,
            embed=build_embed(
                "↩️ Réponse à ton courrier",
                (
                    f"<@{recipient_id}> a répondu à ton courrier.\n\n"
                    f"**Réponse :**\n{text}"
                ),
                COLOR_INFO,
            ),
        )

        entry["reply"] = text
        entry["replied_at"] = datetime.now(timezone.utc).isoformat()
        await save_state_immediately()

        await interaction.response.send_message(
            "✅ René a transmis ta réponse."
            if sent
            else "⚠️ Réponse enregistrée, mais René n'a pas pu envoyer le MP.",
            ephemeral=True,
        )


class CourrierView(discord.ui.View):
    def __init__(self, mail_id: str):
        super().__init__(timeout=None)
        self.mail_id = mail_id

        read_button = discord.ui.Button(
            label="J'ai lu",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"rene:courrier:read:{mail_id}",
        )
        reply_button = discord.ui.Button(
            label="Répondre",
            style=discord.ButtonStyle.primary,
            emoji="↩️",
            custom_id=f"rene:courrier:reply:{mail_id}",
        )

        read_button.callback = self.mark_read
        reply_button.callback = self.reply

        self.add_item(read_button)
        self.add_item(reply_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        entry = store().get(self.mail_id)
        if not isinstance(entry, dict):
            await interaction.response.send_message(
                "Ce courrier n'existe plus.",
                ephemeral=True,
            )
            return False

        if interaction.user.id != int(entry["recipient_id"]):
            await interaction.response.send_message(
                "Ce courrier ne t'est pas destiné.",
                ephemeral=True,
            )
            return False

        return True

    async def mark_read(self, interaction: discord.Interaction):
        entry = store().get(self.mail_id)
        if not isinstance(entry, dict):
            return

        if not entry.get("read_at"):
            entry["read_at"] = datetime.now(timezone.utc).isoformat()
            await save_state_immediately()

            await safe_dm(
                int(entry["sender_id"]),
                embed=build_embed(
                    "✅ Courrier lu",
                    f"<@{entry['recipient_id']}> a lu ton courrier.",
                    COLOR_SUCCESS,
                ),
            )

        await interaction.response.send_message(
            "✅ René a confirmé la lecture à l'expéditeur.",
            ephemeral=True,
        )

    async def reply(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ReplyModal(self.mail_id))


@app_commands.command(
    name="courrier",
    description="Envoyer un courrier privé à un membre avec René.",
)
@app_commands.describe(
    membre="Destinataire",
    message="Contenu du courrier",
)
@app_commands.guild_only()
async def courrier_command(
    interaction: discord.Interaction,
    membre: discord.Member,
    message: str,
):
    if membre.bot:
        await interaction.response.send_message(
            "❌ René ne livre pas de courrier aux bots.",
            ephemeral=True,
        )
        return

    if membre.id == interaction.user.id:
        await interaction.response.send_message(
            "❌ Tu peux déjà te parler sans passer par René.",
            ephemeral=True,
        )
        return

    text = message.strip()
    if not text:
        await interaction.response.send_message("❌ Le courrier est vide.", ephemeral=True)
        return

    if len(text) > 1800:
        await interaction.response.send_message(
            "❌ Limite : 1800 caractères.",
            ephemeral=True,
        )
        return

    latest = latest_sent_time(interaction.user.id)
    if latest is not None:
        remaining = COOLDOWN_SECONDS - (time.time() - latest)
        if remaining > 0:
            await interaction.response.send_message(
                f"⏳ Attends encore {int(remaining) + 1}s avant un nouveau courrier.",
                ephemeral=True,
            )
            return

    mail_id = uuid.uuid4().hex[:10].upper()
    entry = {
        "id": mail_id,
        "guild_id": interaction.guild_id,
        "sender_id": interaction.user.id,
        "recipient_id": membre.id,
        "message": text,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "read_at": None,
        "reply": None,
        "replied_at": None,
        "dm_message_id": None,
    }
    store()[mail_id] = entry
    await save_state_immediately()

    view = CourrierView(mail_id)

    dm = await safe_dm(
        membre.id,
        embed=build_embed(
            "📬 Courrier de René",
            (
                f"Tu as reçu un courrier de <@{interaction.user.id}> "
                f"depuis **{interaction.guild.name}**.\n\n"
                f"**Message :**\n{text}\n\n"
                "Tu peux confirmer la lecture ou répondre directement."
            ),
            COLOR_INFO,
        ),
        view=view,
    )

    if dm is None:
        store().pop(mail_id, None)
        await save_state_immediately()
        await interaction.response.send_message(
            f"📪 René ne peut pas envoyer de MP à {membre.mention}.",
            ephemeral=True,
        )
        return

    entry["dm_message_id"] = dm.id
    await save_state_immediately()

    bot.add_view(view, message_id=dm.id)
    views[mail_id] = view

    logger.info(
        "COURRIER : %s -> %s (%s)",
        interaction.user.id,
        membre.id,
        mail_id,
    )

    await interaction.response.send_message(
        f"📨 René a livré ton courrier à {membre.mention}.",
        ephemeral=True,
    )


async def restore_after_ready():
    global restore_registered
    if restore_registered:
        return
    restore_registered = True

    for _ in range(60):
        if bot.remote_state_loaded:
            break
        import asyncio
        await asyncio.sleep(0.5)

    for mail_id, entry in list(store().items()):
        if not isinstance(entry, dict):
            continue
        message_id = entry.get("dm_message_id")
        if isinstance(message_id, int) and mail_id not in views:
            view = CourrierView(mail_id)
            bot.add_view(view, message_id=message_id)
            views[mail_id] = view


async def setup(client: commands.Bot):
    client.tree.add_command(courrier_command)
    client.add_listener(restore_after_ready, "on_ready")


async def teardown(client: commands.Bot):
    client.tree.remove_command(courrier_command.name)
    client.remove_listener(restore_after_ready, "on_ready")
    for view in list(views.values()):
        try:
            client.remove_view(view)
        except Exception:
            pass
    views.clear()