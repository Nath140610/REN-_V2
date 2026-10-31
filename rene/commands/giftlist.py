from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from rene.core import (
    COLOR_INFO,
    bot,
    build_embed,
    member_has_moderator_role,
)

STORE_KEY = "_gift_codes"
CODES_PER_PAGE = 6


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


def parse_date(raw: str | None) -> datetime:
    if not raw:
        return datetime.min.replace(tzinfo=timezone.utc)

    try:
        value = datetime.fromisoformat(raw)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def sorted_entries() -> list[tuple[str, dict]]:
    entries = [
        (code, entry)
        for code, entry in gift_store().items()
        if isinstance(code, str) and isinstance(entry, dict)
    ]

    # Les plus récents d'abord.
    entries.sort(
        key=lambda item: parse_date(item[1].get("created_at")),
        reverse=True,
    )
    return entries


def page_embed(page: int) -> discord.Embed:
    entries = sorted_entries()
    total = len(entries)

    if total == 0:
        return build_embed(
            "🎁 Liste des codes cadeaux",
            "Aucun code cadeau n'a encore été distribué.",
            COLOR_INFO,
        )

    total_pages = max(1, (total + CODES_PER_PAGE - 1) // CODES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    start = page * CODES_PER_PAGE
    chunk = entries[start:start + CODES_PER_PAGE]

    blocks = []

    for index, (code, entry) in enumerate(chunk, start=start + 1):
        created_at = parse_date(entry.get("created_at"))
        timestamp = int(created_at.timestamp()) if created_at.year > 1970 else None

        recipient_id = int(entry.get("recipient_id", 0) or 0)
        staff_id = int(entry.get("distributed_by_id", 0) or 0)
        reason = str(entry.get("reason") or "Aucune raison")
        status = str(entry.get("delivery_status") or "inconnu")

        if len(reason) > 180:
            reason = reason[:177] + "..."

        status_icon = {
            "delivered": "✅ Livré",
            "dm_failed": "📪 MP impossible",
            "pending": "⏳ En cours",
        }.get(status, f"ℹ️ {status}")

        date_text = (
            f"<t:{timestamp}:f>"
            if timestamp is not None
            else "Date inconnue"
        )

        blocks.append(
            f"**#{index} — `{code}`**\n"
            f"👤 Destinataire : <@{recipient_id}>\n"
            f"🎀 Raison : {reason}\n"
            f"👮 Distribué par : <@{staff_id}>\n"
            f"🗓️ Date : {date_text}\n"
            f"📦 Statut : {status_icon}"
        )

    embed = build_embed(
        "🎁 Registre des codes cadeaux",
        "\n\n".join(blocks),
        COLOR_INFO,
    )

    embed.set_footer(
        text=(
            f"René L'Intérimaire • Page {page + 1}/{total_pages} "
            f"• {total} code(s) distribué(s)"
        )
    )

    return embed


class GiftListView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.page = 0
        self.refresh_buttons()

    def total_pages(self) -> int:
        total = len(sorted_entries())
        return max(1, (total + CODES_PER_PAGE - 1) // CODES_PER_PAGE)

    def refresh_buttons(self):
        pages = self.total_pages()
        self.previous.disabled = self.page <= 0
        self.next.disabled = self.page >= pages - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ Ce registre a été ouvert par un autre membre du staff.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Précédent",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary,
    )
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.page = max(0, self.page - 1)
        self.refresh_buttons()
        await interaction.response.edit_message(
            embed=page_embed(self.page),
            view=self,
        )

    @discord.ui.button(
        label="Suivant",
        emoji="➡️",
        style=discord.ButtonStyle.secondary,
    )
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.page = min(self.total_pages() - 1, self.page + 1)
        self.refresh_buttons()
        await interaction.response.edit_message(
            embed=page_embed(self.page),
            view=self,
        )

    @discord.ui.button(
        label="Actualiser",
        emoji="🔄",
        style=discord.ButtonStyle.primary,
    )
    async def refresh(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.page = min(self.page, self.total_pages() - 1)
        self.refresh_buttons()
        await interaction.response.edit_message(
            embed=page_embed(self.page),
            view=self,
        )


@app_commands.command(
    name="giftlist",
    description="Afficher tous les codes cadeaux distribués.",
)
@app_commands.guild_only()
async def giftlist_command(interaction: discord.Interaction) -> None:
    if not is_staff(interaction):
        await interaction.response.send_message(
            "❌ Cette commande est réservée au staff.",
            ephemeral=True,
        )
        return

    view = GiftListView(interaction.user.id)

    await interaction.response.send_message(
        embed=page_embed(0),
        view=view,
        ephemeral=True,
    )


async def setup(client: commands.Bot) -> None:
    client.tree.add_command(giftlist_command)


async def teardown(client: commands.Bot) -> None:
    client.tree.remove_command(giftlist_command.name)