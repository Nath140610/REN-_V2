from __future__ import annotations

import secrets
from datetime import datetime, timezone

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


async def send_gift_dm(
    member: discord.Member,
    *,
    code: str,
    reason: str,
    guild_name: str,
) -> bool:
    embed = build_embed(
        "🎁 Tu as reçu un code cadeau !",
        (
            f"René vient de déposer un cadeau à ton nom depuis "
            f"**{guild_name}**.\n\n"
            f"🎀 **Raison du don**\n"
            f"{reason}\n\n"
            f"🎟️ **TON CODE CADEAU**\n"
            f"```{code}```\n"
            "🔐 Ce code est **unique**. Garde-le précieusement."
        ),
        COLOR_SUCCESS,
    )

    file = image_attachment(IMAGE_GIFT, "GIFT.png")
    kwargs = {"embed": embed}

    if file is not None:
        # Image complète en bas de l'embed.
        embed.set_image(url="attachment://GIFT.png")
        kwargs["file"] = file

    try:
        await member.send(**kwargs)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


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