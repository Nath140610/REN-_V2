"""Salons de tickets : chaque salon de la catégorie des tickets porte le nom d'un membre.
Le panel lit la conversation et y envoie des messages (texte, embed, image) au nom de René."""
from __future__ import annotations

import base64
import binascii
import io
import re
import unicodedata
from datetime import datetime, timezone

import discord

from rene import analytics, core

DEFAULT_CATEGORY_ID = 1368244636082245783
MAX_FILE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif', 'image/webp': 'webp'}
URL_PATTERN = re.compile(r'^https://[^\s<>"]{3,1000}$')


def category_id(guild: discord.Guild) -> int:
    value = core.bot.get_guild_config(guild.id).get('ticket_category_id')
    try:
        return int(value) if value else DEFAULT_CATEGORY_ID
    except (TypeError, ValueError):
        return DEFAULT_CATEGORY_ID


def category(guild: discord.Guild) -> discord.CategoryChannel:
    found = guild.get_channel(category_id(guild))
    if not isinstance(found, discord.CategoryChannel):
        raise ValueError(f'Catégorie des tickets introuvable (ID {category_id(guild)}). '
                         'Vérifie l’ID dans Réglages et que René voit cette catégorie.')
    return found


def ticket_channel(guild: discord.Guild, channel_id) -> discord.TextChannel:
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel) or channel.category_id != category(guild).id:
        raise ValueError('Ce salon n’est pas un ticket.')
    return channel


def simplify(text: str) -> str:
    text = unicodedata.normalize('NFKD', text.lower())
    return ''.join(c for c in text if c.isalnum() and not unicodedata.combining(c))


def ticket_owner(channel: discord.TextChannel) -> discord.Member | None:
    """Le membre du ticket : d'abord une permission propre au salon, sinon le nom du salon."""
    guild = channel.guild
    for target in channel.overwrites:
        if isinstance(target, discord.Member) and not target.bot and not core.member_has_moderator_role(target):
            return target
    wanted = simplify(re.sub(r'^(ticket|support|aide)[-_]?', '', channel.name))
    if not wanted:
        return None
    for member in guild.members:
        if not member.bot and wanted in {simplify(member.name), simplify(member.display_name)}:
            return member
    return None


def member_brief(member: discord.abc.User | None) -> dict | None:
    if member is None:
        return None
    return {'id': str(member.id), 'name': getattr(member, 'display_name', member.name),
            'username': member.name, 'avatar': str(member.display_avatar.url)}


async def list_rooms(guild: discord.Guild) -> dict:
    parent = category(guild)
    me = guild.me
    rooms = []
    for channel in parent.text_channels:
        last = channel.last_message_id
        owner = ticket_owner(channel)
        rooms.append({
            'id': str(channel.id), 'name': channel.name, 'topic': channel.topic or '',
            'owner': member_brief(owner),
            'last_message_id': str(last) if last else None,
            'last_activity': discord.utils.snowflake_time(last).isoformat() if last
            else discord.utils.snowflake_time(channel.id).isoformat(),
            'created_at': channel.created_at.isoformat(),
            'readable': bool(me and channel.permissions_for(me).read_message_history),
            'writable': bool(me and channel.permissions_for(me).send_messages),
        })
    rooms.sort(key=lambda room: room['last_activity'], reverse=True)
    return {'category': {'id': str(parent.id), 'name': parent.name}, 'items': rooms}


def embed_json(embed: discord.Embed) -> dict:
    return {
        'title': embed.title, 'description': embed.description, 'url': embed.url,
        'color': f'#{embed.color.value:06x}' if embed.color else None,
        'author': embed.author.name if embed.author else None,
        'footer': embed.footer.text if embed.footer else None,
        'image': embed.image.url if embed.image else None,
        'thumbnail': embed.thumbnail.url if embed.thumbnail else None,
        'fields': [{'name': f.name, 'value': f.value, 'inline': f.inline} for f in embed.fields],
    }


def message_json(message: discord.Message) -> dict:
    author = message.author
    return {
        'id': str(message.id), 'created_at': message.created_at.isoformat(),
        'edited': bool(message.edited_at),
        'author': dict(member_brief(author), bot=author.bot,
                       is_rene=bool(core.bot.user and author.id == core.bot.user.id)),
        'content': message.clean_content,
        'embeds': [embed_json(embed) for embed in message.embeds],
        'attachments': [{'url': a.url, 'filename': a.filename, 'size': a.size,
                         'image': bool(a.content_type and a.content_type.startswith('image/'))}
                        for a in message.attachments],
    }


async def messages(guild: discord.Guild, channel_id, after_id: str | None = None) -> dict:
    channel = ticket_channel(guild, channel_id)
    try:
        if after_id:
            found = [m async for m in channel.history(limit=50, after=discord.Object(int(after_id)), oldest_first=True)]
        else:
            found = [m async for m in channel.history(limit=60)]
            found.reverse()
    except discord.Forbidden:
        raise ValueError('René n’a pas le droit de lire ce salon (Voir le salon + Lire l’historique).') from None
    owner = ticket_owner(channel)
    return {'channel': {'id': str(channel.id), 'name': channel.name, 'topic': channel.topic or '',
                        'owner': member_brief(owner)},
            'items': [message_json(m) for m in found if m.type in (discord.MessageType.default, discord.MessageType.reply)]}


def text(raw, limit: int) -> str:
    return str(raw or '').strip()[:limit]


def clean_url(raw) -> str | None:
    value = str(raw or '').strip()
    if not value:
        return None
    if not URL_PATTERN.match(value):
        raise ValueError('Les liens d’image doivent commencer par https://')
    return value


def clean_embed(raw, allow_empty: bool = False) -> discord.Embed | None:
    if not isinstance(raw, dict):
        return None
    title, description = text(raw.get('title'), 256), text(raw.get('description'), 4096)
    fields = [f for f in (raw.get('fields') or []) if isinstance(f, dict)][:25]
    if not title and not description and not fields and not allow_empty:
        raise ValueError('L’embed doit avoir au moins un titre, une description ou un champ.')
    color = str(raw.get('color') or '#0A84FF').strip()
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        raise ValueError('Couleur invalide.')
    embed = discord.Embed(title=title or None, description=description or None,
                          color=discord.Color(int(color[1:], 16)), url=clean_url(raw.get('url')))
    for field in fields:
        name, value = text(field.get('name'), 256), text(field.get('value'), 1024)
        if name and value:
            embed.add_field(name=name, value=value, inline=bool(field.get('inline')))
    if raw.get('author'):
        embed.set_author(name=text(raw.get('author'), 256))
    if raw.get('footer'):
        embed.set_footer(text=text(raw.get('footer'), 2048))
    if raw.get('timestamp'):
        embed.timestamp = datetime.now(timezone.utc)
    image, thumbnail = clean_url(raw.get('image')), clean_url(raw.get('thumbnail'))
    if image:
        embed.set_image(url=image)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if len(embed) > 6000:
        raise ValueError('L’embed dépasse 6 000 caractères au total.')
    return embed


def clean_file(raw) -> discord.File | None:
    if not isinstance(raw, dict) or not raw.get('data'):
        return None
    content_type = str(raw.get('type', ''))
    if content_type not in IMAGE_TYPES:
        raise ValueError('Seules les images PNG, JPG, GIF ou WebP peuvent être jointes.')
    try:
        data = base64.b64decode(str(raw['data']), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError('Image illisible.') from None
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError('L’image doit faire moins de 8 Mo.')
    name = re.sub(r'[^A-Za-z0-9._-]', '_', str(raw.get('name') or 'image'))[:60]
    extension = IMAGE_TYPES[content_type]
    if not name.lower().endswith(f'.{extension}'):
        name = f'{name.rsplit(".", 1)[0]}.{extension}'
    return discord.File(io.BytesIO(data), filename=name)


async def send(guild: discord.Guild, channel_id, payload: dict) -> dict:
    channel = ticket_channel(guild, channel_id)
    content = text(payload.get('content'), 2000)
    file = clean_file(payload.get('file'))
    image_in_embed = bool(file and payload.get('image_in_embed'))
    embed = clean_embed(payload.get('embed'), allow_empty=image_in_embed) if payload.get('embed') else None
    if embed and image_in_embed:
        embed.set_image(url=f'attachment://{file.filename}')
    mention = None
    if payload.get('mention_owner'):
        owner = ticket_owner(channel)
        if owner is None:
            raise ValueError('René ne trouve pas le membre de ce ticket à mentionner.')
        content = f'{owner.mention} {content}'.strip()
        mention = discord.AllowedMentions(everyone=False, roles=False, users=[owner])
    if not content and not embed and not file:
        raise ValueError('Écris un message, crée un embed ou joins une image.')
    kwargs = {'content': content or None, 'allowed_mentions': mention or discord.AllowedMentions.none()}
    if embed:
        kwargs['embed'] = embed
    if file:
        kwargs['file'] = file
    try:
        message = await channel.send(**kwargs)
    except discord.Forbidden:
        raise ValueError('René n’a pas le droit d’écrire dans ce salon.') from None
    analytics.audit(guild.id, 'ticket', f'Message de René dans #{channel.name}'
                    + (' (embed)' if embed else '') + (' (image)' if file else ''))
    return {'ok': True, 'message': f'Message envoyé dans #{channel.name}.', 'item': message_json(message)}


async def settings(guild: discord.Guild) -> dict:
    found = guild.get_channel(category_id(guild))
    return {'category_id': str(category_id(guild)), 'default': str(DEFAULT_CATEGORY_ID),
            'found': isinstance(found, discord.CategoryChannel),
            'name': found.name if isinstance(found, discord.CategoryChannel) else None}


async def save_settings(guild: discord.Guild, raw) -> dict:
    value = str(raw or '').strip()
    if not value.isdigit():
        raise ValueError('L’ID de catégorie ne contient que des chiffres.')
    found = guild.get_channel(int(value))
    if not isinstance(found, discord.CategoryChannel):
        raise ValueError('René ne trouve aucune catégorie avec cet ID sur ce serveur.')
    core.bot.get_guild_config(guild.id)['ticket_category_id'] = int(value)
    analytics.audit(guild.id, 'ticket', f'Catégorie des tickets : {found.name}')
    await core.save_state_immediately()
    return {'ok': True, 'message': f'Catégorie des tickets : {found.name}.', 'name': found.name}
