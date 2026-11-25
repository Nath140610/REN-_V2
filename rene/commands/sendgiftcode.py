from __future__ import annotations

import asyncio
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from rene.core import (
    COLOR_DANGER,
    COLOR_SUCCESS,
    bot,
    build_embed,
    image_attachment,
    asset_path,
    member_has_moderator_role,
    save_state_immediately,
    logger,
)

STORE_KEY = "_gift_codes"
CARD_LIFETIME = timedelta(hours=24)
IMAGE_GIFT = asset_path("GIFT.png")

# On retire les caractères faciles à confondre :
# 0/O, 1/I/L.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def gift_store() -> dict[str, dict]:
    data = bot.config_data.setdefault(STORE_KEY, {})
    if not isinstance(data, dict):
        data = {}
        bot.config_data[STORE_KEY] = data
    return data


def is_staff(interaction: discord.Interaction) -> bool:
    return (
        isinstance(interaction.user, discord.Member)
        and member_has_moderator_role(interaction.user)
    )


def generate_unique_code() -> str:
    """
    Génère un code du type :
    VOID-AB7K-MP4X-9TQH

    La fonction vérifie TOUS les codes déjà distribués avant de
    retourner le nouveau code. Un code enregistré ne sera donc
    jamais redistribué une seconde fois.
    """
    existing_codes = set(gift_store().keys())

    # L'espace de codes est gigantesque, mais on garde une boucle
    # sans limite artificielle : en cas de collision, René regénère.
    while True:
        groups = [
            "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
            for _ in range(3)
        ]
        code = "VOID-" + "-".join(groups)

        if code not in existing_codes:
            return code


def public_base_url() -> str:
    """URL publique du service. Render fournit RENDER_EXTERNAL_URL automatiquement."""
    base = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    return base if base.startswith(("https://", "http://")) else ""


def ensure_card_token(entry: dict) -> str:
    token = entry.get("card_token")
    if not token:
        token = secrets.token_urlsafe(24)
        entry["card_token"] = token
    return token


def card_url(entry: dict) -> str:
    return f"{public_base_url()}/cadeau/{ensure_card_token(entry)}"


def find_card(token: str) -> dict | None:
    for entry in gift_store().values():
        stored = entry.get("card_token") if isinstance(entry, dict) else None
        if stored and hmac.compare_digest(str(stored), token):
            return entry
    return None


def parse_utc(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def card_status(entry: dict, now: datetime | None = None) -> str:
    """legacy, replaced, used, dm_failed, sent, opened, scratched, expired."""
    now = now or datetime.now(timezone.utc)
    if entry.get("replaced_by"):
        return "replaced"
    if entry.get("used_at"):
        return "used"
    if not entry.get("card_token") and entry.get("source") != "assistance":
        return "legacy"
    if entry.get("delivery_status") == "dm_failed":
        return "dm_failed"
    expires = parse_utc(entry.get("expires_at"))
    if expires is not None:
        return "expired" if expires <= now else "scratched"
    if entry.get("opened_at"):
        return "opened"
    return "sent"


async def delete_code_messages(user: discord.abc.User, codes: set[str], limit: int = 200) -> int:
    """Supprime les anciens MP de René qui affichent un de ces codes en clair."""
    if not codes or bot.user is None:
        return 0
    try:
        channel = user.dm_channel or await user.create_dm()
    except discord.HTTPException:
        return 0
    deleted = 0
    try:
        async for message in channel.history(limit=limit):
            if message.author.id != bot.user.id:
                continue
            text = message.content + " ".join(
                f"{embed.title or ''} {embed.description or ''}" for embed in message.embeds
            )
            if any(code in text for code in codes):
                try:
                    await message.delete()
                    deleted += 1
                except discord.HTTPException:
                    pass
    except (discord.Forbidden, discord.HTTPException):
        logger.warning("GIFTCODE : historique MP illisible pour %s.", user.id)
    return deleted


class CardLinkView(discord.ui.View):
    def __init__(self, url: str) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Ouvrir ma carte", emoji="🎁", url=url))


async def send_gift_dm(
    member: discord.abc.User,
    *,
    code: str,
    reason: str,
    guild_name: str,
) -> bool:
    """Envoie le lien unique vers la carte à gratter. Le code n'apparaît jamais dans le MP."""
    entry = gift_store().get(code)
    if not isinstance(entry, dict) or not public_base_url():
        logger.error("GIFTCODE : URL publique absente (PUBLIC_URL / RENDER_EXTERNAL_URL).")
        return False

    embed = build_embed(
        "🎁 Une carte cadeau t'attend",
        (
            f"René a déposé une carte cadeau à ton nom sur **{guild_name}**.\n\n"
            f"🎀 **Raison**\n{reason}\n\n"
            "Ouvre-la, retourne-la et gratte la zone argentée pour découvrir ton code.\n"
            "⏳ Une fois gratté, le code est valable **24 heures**.\n\n"
            "🔐 Ce lien est personnel : ne le partage pas."
        ),
        COLOR_SUCCESS,
    )
    file = image_attachment(IMAGE_GIFT, "GIFT.png")
    kwargs = {"embed": embed, "view": CardLinkView(card_url(entry))}
    if file is not None:
        embed.set_image(url="attachment://GIFT.png")
        kwargs["file"] = file

    previous = entry.get("card_message_id")
    try:
        message = await member.send(**kwargs)
    except (discord.Forbidden, discord.HTTPException):
        return False

    if previous:
        try:
            channel = member.dm_channel or await member.create_dm()
            await channel.get_partial_message(int(previous)).delete()
        except (discord.HTTPException, ValueError):
            pass
    entry["card_message_id"] = message.id
    entry["card_sent_at"] = datetime.now(timezone.utc).isoformat()
    return True


async def replace_legacy_codes(guild: discord.Guild) -> dict[str, int]:
    """Remplace chaque ancien code affiché en clair par une carte à gratter."""
    result = {"replaced": 0, "deleted_messages": 0, "dm_failed": 0, "absent": 0}
    store = gift_store()
    for old_code, old in list(store.items()):
        if (not isinstance(old, dict) or str(old.get("guild_id")) != str(guild.id)
                or card_status(old) != "legacy"):
            continue
        member = guild.get_member(int(old.get("recipient_id") or 0))
        if member is None:
            result["absent"] += 1
            continue

        new_code = generate_unique_code()
        now = datetime.now(timezone.utc).isoformat()
        entry = {
            "code": new_code, "guild_id": guild.id, "recipient_id": member.id,
            "recipient_name": str(member), "reason": old.get("reason", ""),
            "distributed_by_id": old.get("distributed_by_id", 0),
            "distributed_by_name": old.get("distributed_by_name", "René"),
            "created_at": now, "delivery_status": "pending", "replaces": old_code,
        }
        store[new_code] = entry
        await save_state_immediately()

        if not await send_gift_dm(member, code=new_code, reason=entry["reason"], guild_name=guild.name):
            # On garde l'ancien code tant que le nouveau n'est pas livré.
            store.pop(new_code, None)
            await save_state_immediately()
            result["dm_failed"] += 1
            continue

        entry["delivery_status"] = "delivered"
        entry["delivery_updated_at"] = now
        old["replaced_by"] = new_code
        old["replaced_at"] = now
        result["deleted_messages"] += await delete_code_messages(member, {old_code})
        result["replaced"] += 1
        await save_state_immediately()
        await asyncio.sleep(0.8)
    return result


@app_commands.command(
    name="sendgiftcode",
    description="Générer et envoyer un code cadeau unique à un membre.",
)
@app_commands.describe(
    membre="Personne qui recevra le code cadeau",
    raison="Raison du don",
)
@app_commands.guild_only()
async def sendgiftcode_command(
    interaction: discord.Interaction,
    membre: discord.Member,
    raison: str,
) -> None:
    assert interaction.guild is not None

    if not is_staff(interaction):
        await interaction.response.send_message(
            "❌ Cette commande est réservée au staff.",
            ephemeral=True,
        )
        return

    if membre.bot:
        await interaction.response.send_message(
            "❌ René ne peut pas donner un code cadeau à un bot.",
            ephemeral=True,
        )
        return

    reason_text = raison.strip()

    if not reason_text:
        await interaction.response.send_message(
            "❌ Indique la raison du don.",
            ephemeral=True,
        )
        return

    if len(reason_text) > 1000:
        await interaction.response.send_message(
            "❌ La raison est trop longue. Maximum : 1000 caractères.",
            ephemeral=True,
        )
        return

    # IMPORTANT :
    # Le code est créé ET réservé dans la mémoire avant le premier await.
    # Deux staffs utilisant la commande presque au même moment ne peuvent
    # donc pas recevoir le même code dans cette instance de René.
    code = generate_unique_code()

    entry = {
        "code": code,
        "guild_id": interaction.guild.id,
        "recipient_id": membre.id,
        "recipient_name": str(membre),
        "reason": reason_text,
        "distributed_by_id": interaction.user.id,
        "distributed_by_name": str(interaction.user),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "delivery_status": "pending",
    }

    gift_store()[code] = entry

    # Sauvegarde immédiatement dans le système persistant de René.
    # Le code restera réservé après un redémarrage / redeploy Render.
    await save_state_immediately()

    delivered = await send_gift_dm(
        membre,
        code=code,
        reason=reason_text,
        guild_name=interaction.guild.name,
    )

    entry["delivery_status"] = "delivered" if delivered else "dm_failed"
    entry["delivery_updated_at"] = datetime.now(timezone.utc).isoformat()
    await save_state_immediately()

    if not delivered:
        await interaction.response.send_message(
            embed=build_embed(
                "📪 Livraison impossible",
                (
                    f"Le code **{code}** a bien été généré et réservé, "
                    f"mais René n'arrive pas à envoyer de MP à {membre.mention}.\n\n"
                    "Le code reste enregistré dans `/giftlist` et ne sera "
                    "jamais redistribué."
                ),
                COLOR_DANGER,
            ),
            ephemeral=True,
        )
        return

    logger.info(
        "GIFTCODE : %s distribué à %s (%s) par %s (%s)",
        code,
        membre,
        membre.id,
        interaction.user,
        interaction.user.id,
    )

    confirmation = build_embed(
        "🎁 Code cadeau envoyé",
        (
            f"René a livré un code cadeau à {membre.mention}.\n\n"
            f"🎟️ **Code :** `{code}`\n"
            f"🎀 **Raison :** {reason_text}\n\n"
            "✅ Le code est maintenant enregistré définitivement dans "
            "`/giftlist`."
        ),
        COLOR_SUCCESS,
    )

    file = image_attachment(IMAGE_GIFT, "GIFT.png")
    kwargs = {
        "embed": confirmation,
        "ephemeral": True,
    }

    if file is not None:
        confirmation.set_thumbnail(url="attachment://GIFT.png")
        kwargs["file"] = file

    await interaction.response.send_message(**kwargs)


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(sendgiftcode_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(sendgiftcode_command.name)