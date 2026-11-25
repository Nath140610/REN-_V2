"""Panel Render. Toutes les lectures Discord passent par la boucle du bot."""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import io
import os
import re
import secrets
import threading
import time
import uuid

from flask import abort, jsonify, make_response, render_template, request, send_from_directory
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
import discord
import qrcode

from rene import ai, analytics, core
from rene.commands import rdvexpress
from rene.commands import rendevous as rdv
from rene.commands import sendgiftcode as giftcodes
from rene.commands.sendgiftcode import generate_unique_code, gift_store, send_gift_dm
from rene import assistance, broadcast, polls, rewards, robloxapi, stats
from rene.giftcard import install_giftcard

SESSION_AGE = 8 * 3600
attempts = {}
jobs = {}
job_lock = threading.Lock()
OWNER_DISCORD_ID = 1362876245381091471
gift_challenges = {}


def configured():
    return bool(os.getenv('PANEL_PASSWORD') and len(os.getenv('PANEL_SECRET', '')) >= 32)


def serializer():
    return URLSafeTimedSerializer(os.environ['PANEL_SECRET'], salt='rene-panel-v1')


def password_tag():
    return hmac.new(os.environ['PANEL_SECRET'].encode(),
                    os.environ['PANEL_PASSWORD'].encode(), hashlib.sha256).hexdigest()[:24]


def account():
    if not configured():
        abort(503, 'Configure PANEL_PASSWORD et PANEL_SECRET sur Render.')
    raw = request.cookies.get('rene_session', '')
    try:
        value = serializer().loads(raw, max_age=SESSION_AGE)
        if (value.get('version') != 1 or not value.get('csrf') or
                not hmac.compare_digest(value.get('auth', ''), password_tag())):
            raise BadSignature('invalid session')
        return value
    except (BadSignature, SignatureExpired):
        abort(401, 'Connecte-toi au panel.')


def protected():
    user = account()
    if request.method not in ('GET', 'HEAD'):
        if not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), user['csrf']):
            abort(403, 'Session invalide. Recharge la page.')
        if request.mimetype != 'application/json':
            abort(415, 'JSON requis.')
    return user


def run(coro, timeout=20):
    if not core.bot.is_ready() or core.bot.is_closed():
        coro.close()
        abort(503, 'René se connecte à Discord. Réessaie dans un instant.')
    future = asyncio.run_coroutine_threadsafe(coro, core.bot.loop)
    try:
        return future.result(timeout)
    except FutureTimeout:
        future.cancel()
        abort(504, 'Discord ne répond pas assez vite.')


def guild_for(guild_id):
    allowed = os.getenv('PANEL_GUILD_ID', '').strip()
    if allowed and str(guild_id) != allowed:
        raise ValueError('Ce serveur n’est pas autorisé dans le panel.')
    guild = core.bot.get_guild(int(guild_id))
    if guild is None:
        raise ValueError('Serveur Discord introuvable.')
    return guild


def member_json(member, stats=None):
    stats = stats or {}
    return {'id': str(member.id), 'name': member.display_name, 'username': str(member),
            'avatar': str(member.display_avatar.url), 'joined_at': member.joined_at.isoformat() if member.joined_at else None,
            'messages': stats.get('messages', 0),
            'voice_seconds': round(stats.get('voice_seconds', 0)),
            'active_days': stats.get('active_days', 0),
            'warnings': core.get_warning_count(member.guild.id, member.id),
            'bot': member.bot,
            'roles': [str(role.id) for role in member.roles if not role.is_default()]}


async def snapshot(guild_id):
    guild = guild_for(guild_id)
    result = analytics.summary(guild.id)
    users = result.pop('users')
    active = [(uid, value) for uid, value in users.items() if guild.get_member(int(uid))]
    active.sort(key=lambda item: (item[1]['messages'] + item[1]['voice_seconds'] / 60), reverse=True)
    result['top'] = [member_json(guild.get_member(int(uid)), value) for uid, value in active[:12]]
    result['guild'] = {'id': str(guild.id), 'name': guild.name, 'members': guild.member_count or len(guild.members),
                       'humans': sum(not m.bot for m in guild.members),
                       'online': sum(m.status != discord.Status.offline and not m.bot for m in guild.members),
                       'voice_now': sum(not m.bot for c in guild.voice_channels + guild.stage_channels for m in c.members)}
    result['audit'] = analytics.store(guild.id).get('audit', [])[-20:][::-1]
    result['ai_enabled'] = bool(ai.api_key())
    return result


async def members(guild_id, query, page):
    guild = guild_for(guild_id)
    user_stats = analytics.summary(guild.id)['users']
    matching = [m for m in guild.members if not m.bot and
                (not query or query in m.display_name.casefold() or query in str(m).casefold() or query in str(m.id))]
    matching.sort(key=lambda m: m.joined_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    start = page * 25
    return {'total': len(matching), 'page': page,
            'items': [member_json(m, user_stats.get(str(m.id))) for m in matching[start:start + 25]]}


async def search_members(guild_id, query):
    guild = guild_for(guild_id)
    needle = query.casefold().strip()
    matches = [member for member in guild.members if not member.bot and
               (not needle or needle in member.display_name.casefold() or
                needle in str(member).casefold() or needle in str(member.id))]
    matches.sort(key=lambda member: member.display_name.casefold())
    return {'items': [member_json(member) for member in matches[:30]],
            'total': len(matches)}


GIFT_FIELDS = ('code', 'recipient_id', 'recipient_name', 'reason', 'created_at', 'delivery_status',
               'card_sent_at', 'opened_at', 'last_seen_at', 'views', 'scratched_at', 'expires_at',
               'replaced_by', 'replaces', 'used_at', 'used_by_roblox_id', 'used_by_roblox_name',
               'used_place_id', 'used_manually', 'reward', 'source', 'distributed_by_name')


async def gifts(guild_id):
    guild_for(guild_id)
    now = datetime.now(timezone.utc)
    entries = [entry for entry in gift_store().values() if isinstance(entry, dict) and str(entry.get('guild_id')) == str(guild_id)]
    entries.sort(key=lambda e: e.get('created_at', ''), reverse=True)
    items = []
    counts = {}
    for entry in entries:
        status = giftcodes.card_status(entry, now)
        counts[status] = counts.get(status, 0) + 1
        item = {key: entry.get(key) for key in GIFT_FIELDS}
        item['recipient_id'] = str(item['recipient_id'] or '')
        item['status'] = status
        items.append(item)
    missing = sum(1 for e in entries if not isinstance(e.get('reward'), dict) and not e.get('replaced_by'))
    return {'total': len(entries), 'counts': counts, 'items': items[:300], 'missing_reward': missing,
            'public_url': bool(giftcodes.public_base_url()),
            'note': 'Le code s’affiche sur la carte après grattage et reste valable 24 h. René ne peut pas vérifier son utilisation sur Roblox.'}


async def replace_legacy_gifts(guild_id):
    guild = guild_for(guild_id)
    if not giftcodes.public_base_url():
        raise ValueError('Ajoute PUBLIC_URL sur Render pour créer les liens des cartes.')
    result = await giftcodes.replace_legacy_codes(guild)
    analytics.audit(guild.id, 'gift', f'Anciens codes remplacés : {result["replaced"]}, MP fermés : {result["dm_failed"]}, '
                                      f'absents : {result["absent"]}, anciens MP supprimés : {result["deleted_messages"]}')
    message = f'{result["replaced"]} carte(s) envoyée(s), {result["deleted_messages"]} ancien(s) MP supprimé(s).'
    if result['dm_failed']:
        message += f' {result["dm_failed"]} MP fermé(s).'
    if result['absent']:
        message += f' {result["absent"]} membre(s) parti(s).'
    return dict(result, ok=True, message=message)


async def set_gift_used(guild_id, code, used):
    guild = guild_for(guild_id)
    entry = gift_store().get(code)
    if not isinstance(entry, dict) or str(entry.get('guild_id')) != str(guild.id):
        raise ValueError('Code introuvable.')
    if used:
        if robloxapi.roblox_status(entry) != 'available':
            raise ValueError('Ce code n’est pas disponible.')
        entry.update({'used_at': datetime.now(timezone.utc).isoformat(), 'used_manually': True,
                      'used_by_roblox_name': 'Panel', 'used_by_roblox_id': None})
        detail = f'Code {code} marqué utilisé depuis le panel'
    else:
        for key in ('used_at', 'used_by_roblox_id', 'used_by_roblox_name', 'used_place_id', 'used_manually'):
            entry.pop(key, None)
        detail = f'Utilisation du code {code} annulée'
    analytics.audit(guild.id, 'gift', detail)
    await core.save_state_immediately()
    return {'ok': True, 'message': 'Code marqué utilisé.' if used else 'Code de nouveau disponible.'}


async def resend_gift(guild_id, code):
    guild = guild_for(guild_id)
    entry = gift_store().get(code)
    if not isinstance(entry, dict) or str(entry.get('guild_id')) != str(guild.id):
        raise ValueError('Code introuvable.')
    if giftcodes.card_status(entry) in {'legacy', 'replaced', 'expired'}:
        raise ValueError('Cette carte ne peut pas être renvoyée.')
    if not giftcodes.public_base_url():
        raise ValueError('Ajoute PUBLIC_URL sur Render pour créer les liens des cartes.')
    member = guild.get_member(int(entry.get('recipient_id') or 0))
    if member is None:
        raise ValueError('Ce membre n’est plus sur le serveur.')
    delivered = await send_gift_dm(member, code=code, reason=entry.get('reason', ''), guild_name=guild.name)
    entry['delivery_status'] = 'delivered' if delivered else 'dm_failed'
    entry['delivery_updated_at'] = datetime.now(timezone.utc).isoformat()
    await core.save_state_immediately()
    if not delivered:
        raise ValueError('Cette personne refuse les MP du bot.')
    analytics.audit(guild.id, 'gift', f'Carte {code} renvoyée à {member} ({member.id})')
    return {'ok': True, 'message': f'Carte renvoyée à {member.display_name}.'}


async def appointments(guild_id):
    guild = guild_for(guild_id)
    entries = [entry for entry in rdv.get_store().values()
               if isinstance(entry, dict) and str(entry.get('guild_id')) == str(guild_id)]
    entries.sort(key=lambda entry: entry.get('scheduled_at', ''), reverse=True)
    express = []
    for entry in rdvexpress.store().values():
        if isinstance(entry, dict) and str(entry.get('guild_id')) == str(guild_id):
            target = guild.get_member(int(entry.get('target_id') or 0))
            express.append(dict(entry, target_name=entry.get('target_name') or (target.display_name if target else None)))
    express.sort(key=lambda entry: entry.get('created_at', ''), reverse=True)
    return {'items': entries[:100], 'express': express[:50]}


async def schedule_appointment(guild_id, user_id, scheduled_at):
    guild = guild_for(guild_id)
    try:
        scheduled = datetime.fromisoformat(scheduled_at.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Date de rendez-vous invalide.') from None
    result = await rdv.create_from_panel(guild, int(user_id), scheduled, OWNER_DISCORD_ID)
    analytics.audit(guild.id, 'appointment',
                    f'Rendez-vous {result["id"]} pour {result["recipient"]} ({user_id})')
    return result


async def send_private_message(guild_id, user_id, message):
    guild = guild_for(guild_id)
    member = guild.get_member(int(user_id))
    if member is None or member.bot:
        raise ValueError('Choisis un membre du serveur dans la recherche.')
    text = message.strip()
    if not 1 <= len(text) <= 1800:
        raise ValueError('Le MP doit contenir entre 1 et 1 800 caractères.')
    try:
        await member.send(
            f'📬 Message du staff de **{guild.name}**, transmis par René :\n\n{text}',
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.Forbidden:
        raise ValueError('Cette personne refuse les MP du bot.') from None
    analytics.audit(guild.id, 'dm', f'MP envoyé à {member} ({member.id})')
    return {'ok': True, 'message': f'MP envoyé à {member.display_name}.'}


async def set_bot_presence(status, text):
    if status not in {'auto', 'online', 'idle', 'dnd', 'invisible'}:
        raise ValueError('Statut invalide.')
    if status == 'auto':
        core.bot.config_data.pop('_panel_presence', None)
    else:
        core.bot.config_data['_panel_presence'] = {'status': status, 'text': text[:100]}
    await core.apply_panel_presence()
    await core.save_state_immediately()
    return {'ok': True, 'status': status, 'text': text[:100] if status != 'auto' else '',
            'message': 'Statut de René mis à jour.'}


async def ban_member(guild_id, user_id, reason):
    guild = guild_for(guild_id)
    member = guild.get_member(int(user_id))
    if member is None or member.bot or member.id == guild.owner_id:
        raise ValueError('Membre introuvable ou non autorisé.')
    if guild.me is None or not guild.me.guild_permissions.ban_members or member.top_role >= guild.me.top_role:
        raise ValueError('René n’a pas la permission ou le rang nécessaire pour bannir ce membre.')
    await member.ban(reason=f'Panel René : {reason}', delete_message_seconds=0)
    analytics.audit(guild.id, 'ban', f'{member} ({member.id}) : {reason}')
    return {'ok': True, 'message': f'{member.display_name} a été banni.'}


async def set_gift_reward(guild_id, code, reward):
    guild = guild_for(guild_id)
    entry = gift_store().get(code)
    if not isinstance(entry, dict) or str(entry.get('guild_id')) != str(guild.id):
        raise ValueError('Code introuvable.')
    if entry.get('replaced_by'):
        raise ValueError('Ce code a été remplacé : règle le gain sur le nouveau code.')
    previous = entry.get('reward', {}).get('label') if isinstance(entry.get('reward'), dict) else None
    entry['reward'] = reward
    entry['reward_set_at'] = datetime.now(timezone.utc).isoformat()
    # Aucun MP : le gain est seulement lié au code, pour le jeu.
    analytics.audit(guild.id, 'gift', f'Gain du code {code} : {reward["label"]}'
                                      + (f' (avant : {previous})' if previous else ''))
    await core.save_state_immediately()
    return {'ok': True, 'reward': reward, 'message': f'Gain enregistré : {reward["label"]}.'}


async def send_gift(guild_id, user_id, reason, reward=None):
    guild = guild_for(guild_id)
    member = guild.get_member(int(user_id))
    if member is None or member.bot:
        raise ValueError('Choisis un membre du serveur.')
    if not giftcodes.public_base_url():
        raise ValueError('Ajoute PUBLIC_URL sur Render pour créer le lien de la carte.')
    code = generate_unique_code()
    entry = {'code': code, 'guild_id': guild.id, 'recipient_id': member.id,
             'recipient_name': str(member), 'reason': reason,
             'distributed_by_id': 0, 'distributed_by_name': 'Panel René',
             'created_at': datetime.now(timezone.utc).isoformat(), 'delivery_status': 'pending',
             'reward': reward}
    if reward is None:
        raise ValueError('Choisis le jeu et le gain du cadeau.')
    gift_store()[code] = entry
    await core.save_state_immediately()
    delivered = await send_gift_dm(member, code=code, reason=reason, guild_name=guild.name)
    entry['delivery_status'] = 'delivered' if delivered else 'dm_failed'
    entry['delivery_updated_at'] = datetime.now(timezone.utc).isoformat()
    analytics.audit(guild.id, 'gift', f'Code {code} pour {member} ({member.id}) ; MP : {entry["delivery_status"]}')
    await core.save_state_immediately()
    return {'ok': True, 'code': code, 'delivered': delivered,
            'message': 'Carte à gratter envoyée en MP.' if delivered else 'Code réservé, mais le MP a échoué.'}


async def start_gift_challenge(guild_id, user_id, reason, session_id, reward=None):
    guild = guild_for(guild_id)
    member = guild.get_member(int(user_id))
    if member is None or member.bot:
        raise ValueError('Choisis un membre du serveur dans la recherche.')
    now = time.time()
    for challenge_id, value in list(gift_challenges.items()):
        if value['expires_at'] <= now:
            del gift_challenges[challenge_id]
        elif value['session_id'] == session_id and now - value['created_at'] < 30:
            raise ValueError('Un QR vient déjà d’être envoyé. Patiente quelques secondes.')

    challenge_id = secrets.token_urlsafe(12)
    secret = secrets.token_urlsafe(32)
    qr_text = f'rene-gift:{challenge_id}:{secret}'
    image = qrcode.make(qr_text)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    buffer.seek(0)
    owner = core.bot.get_user(OWNER_DISCORD_ID) or await core.bot.fetch_user(OWNER_DISCORD_ID)
    try:
        await owner.send(
            content=(f'🔐 Vérification cadeau René\n'
                     f'Pour : {member.display_name} sur {guild.name}\n'
                     f'Raison : {reason[:200]}\n'
                     f'Gain : {reward["label"] if reward else "?"}\n'
                     'Scanne ce QR depuis le panel René. Il expire dans 5 minutes.'),
            file=discord.File(buffer, filename='verification-cadeau.png'),
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except (discord.Forbidden, discord.HTTPException):
        raise ValueError('René ne peut pas envoyer le QR en MP à Nathlepesant.') from None
    gift_challenges[challenge_id] = {
        'token_hash': hashlib.sha256(secret.encode()).digest(),
        'guild_id': str(guild_id), 'user_id': str(user_id), 'reason': reason, 'reward': reward,
        'session_id': session_id, 'created_at': now, 'expires_at': now + 300,
        'attempts': 0,
    }
    return {'challenge_id': challenge_id, 'expires_in': 300,
            'message': 'Attends, je veux juste vérifier que tu es bien Nathlepesant. Le QR est envoyé en MP.'}


async def confirm_gift_challenge(guild_id, challenge_id, qr_text, session_id):
    challenge = gift_challenges.get(challenge_id)
    if not challenge:
        raise ValueError('Ce QR a expiré. Recommence la vérification.')
    if challenge['expires_at'] <= time.time():
        gift_challenges.pop(challenge_id, None)
        raise ValueError('Ce QR a expiré. Recommence la vérification.')
    if challenge['session_id'] != session_id or challenge['guild_id'] != str(guild_id):
        raise ValueError('Ce QR ne correspond pas à ta session.')
    pieces = qr_text.split(':')
    if (len(pieces) != 3 or pieces[0] != 'rene-gift' or pieces[1] != challenge_id or
            not hmac.compare_digest(hashlib.sha256(pieces[2].encode()).digest(),
                                    challenge['token_hash'])):
        challenge['attempts'] += 1
        if challenge['attempts'] >= 5:
            gift_challenges.pop(challenge_id, None)
        raise ValueError('Ce QR ne correspond pas à la demande de cadeau.')
    # Le jeton est consommé avant l'envoi : un second scan ne peut pas créer
    # un deuxième code cadeau, même si Discord répond lentement.
    gift_challenges.pop(challenge_id, None)
    return await send_gift(guild_id, challenge['user_id'], challenge['reason'], challenge.get('reward'))


def moderatable(guild, user_id):
    member = guild.get_member(int(user_id))
    if member is None or member.bot or member.id == guild.owner_id:
        raise ValueError('Membre introuvable ou non autorisé.')
    return member


def staff_channel_id(guild):
    value = core.bot.get_guild_config(guild.id).get('staff_records_channel_id')
    return int(value) if value else 0


async def soft_dm(member, title, description, color):
    try:
        await member.send(embed=core.build_embed(title, description, color),
                          allowed_mentions=discord.AllowedMentions.none())
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def apply_temp_ban(guild, member, reason, hours):
    me = guild.me
    if me is None or not me.guild_permissions.ban_members or member.top_role >= me.top_role:
        raise ValueError('René n’a pas la permission ou le rang nécessaire pour bannir ce membre.')
    unban_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    label = f'{hours} h' if hours < 48 else f'{round(hours / 24)} jours'
    await soft_dm(member, '⏳ Bannissement temporaire',
                  f'Tu es banni de **{guild.name}** pendant **{label}**.\n\n'
                  f'📝 **Motif :** {reason}\nTu pourras revenir <t:{int(unban_at.timestamp())}:R>.',
                  core.COLOR_DANGER)
    await member.ban(reason=f'Panel René ({label}) : {reason}', delete_message_seconds=0)
    core.register_temporary_ban(guild.id, member.id, unban_at)
    case = core.create_case(guild.id, member.id, OWNER_DISCORD_ID, case_type='Bannissement temporaire',
                            reason=f'Panel René ({label}) : {reason}',
                            warning_count=core.get_warning_count(guild.id, member.id),
                            channel_id=staff_channel_id(guild),
                            deleted_content='Aucun message supprimé — action du panel.')
    await core.send_case_to_staff(guild, case)
    analytics.audit(guild.id, 'tempban', f'{member} ({member.id}) banni {label} : {reason}')
    return label


async def warn_member(guild_id, user_id, reason):
    guild = guild_for(guild_id)
    member = moderatable(guild, user_id)
    count = min(core.get_warning_count(guild.id, member.id) + 1, core.MAX_WARNINGS)
    core.set_warning_count(guild.id, member.id, count)
    case = core.create_case(guild.id, member.id, OWNER_DISCORD_ID, case_type='Avertissement',
                            reason=f'Panel René : {reason}', warning_count=count,
                            channel_id=staff_channel_id(guild),
                            deleted_content='Aucun message supprimé — avertissement du panel.')
    await core.send_case_to_staff(guild, case)
    delivered = await soft_dm(member, '⚠️ Avertissement',
                              f'Tu as reçu un avertissement sur **{guild.name}**.\n\n'
                              f'📝 **Motif :** {reason}\n'
                              f'📂 **Total :** {count}/{core.MAX_WARNINGS}',
                              core.COLOR_WARNING)
    analytics.audit(guild.id, 'warn', f'{member} ({member.id}) : {count}/{core.MAX_WARNINGS} — {reason}')
    message = f'{member.display_name} : {count}/{core.MAX_WARNINGS} avertissements.'
    if count >= core.MAX_WARNINGS:
        try:
            await apply_temp_ban(guild, member, f'{core.MAX_WARNINGS} avertissements atteints', 24)
            core.set_warning_count(guild.id, member.id, 0)
            message += ' Limite atteinte : banni 24 h.'
        except ValueError as error:
            message += f' Limite atteinte, mais {error}'
    elif not delivered:
        message += ' MP fermé.'
    await core.save_state_immediately()
    return {'ok': True, 'count': count, 'message': message}


async def temp_ban_member(guild_id, user_id, reason, hours):
    guild = guild_for(guild_id)
    member = moderatable(guild, user_id)
    label = await apply_temp_ban(guild, member, reason, hours)
    await core.save_state_immediately()
    return {'ok': True, 'message': f'{member.display_name} est banni pour {label}.'}


async def temp_bans(guild_id):
    guild = guild_for(guild_id)
    items = []
    for user_id, until in core.bot.temporary_bans.get(str(guild.id), {}).items():
        user = core.bot.get_user(int(user_id))
        items.append({'id': str(user_id), 'name': user.display_name if user else f'Membre {user_id}',
                      'avatar': str(user.display_avatar.url) if user else None, 'until': until})
    items.sort(key=lambda item: item['until'])
    return {'items': items}


async def lift_temp_ban(guild_id, user_id):
    guild = guild_for(guild_id)
    try:
        await guild.unban(discord.Object(id=int(user_id)), reason='Levé depuis le panel René')
    except discord.NotFound:
        pass
    core.remove_temporary_ban(guild.id, int(user_id))
    analytics.audit(guild.id, 'unban', f'Bannissement levé pour {user_id}')
    await core.save_state_immediately()
    return {'ok': True, 'message': 'Bannissement levé.'}


async def guild_roles(guild_id):
    guild = guild_for(guild_id)
    me = guild.me
    can_manage = bool(me and me.guild_permissions.manage_roles)
    roles = [role for role in guild.roles if not role.is_default()]
    roles.sort(key=lambda role: role.position, reverse=True)
    return {'items': [{'id': str(role.id), 'name': role.name,
                       'color': f'#{role.color.value:06x}' if role.color.value else None,
                       'members': len(role.members),
                       'editable': can_manage and not role.managed and role < me.top_role}
                      for role in roles]}


async def set_member_role(guild_id, user_id, role_id, enabled):
    guild = guild_for(guild_id)
    member = guild.get_member(int(user_id))
    role = guild.get_role(int(role_id))
    if member is None or member.bot or role is None or role.is_default():
        raise ValueError('Membre ou rôle introuvable.')
    me = guild.me
    if me is None or not me.guild_permissions.manage_roles or role.managed or role >= me.top_role:
        raise ValueError('René ne peut pas gérer ce rôle. Place son rôle plus haut.')
    if enabled:
        await member.add_roles(role, reason='Panel René')
    else:
        await member.remove_roles(role, reason='Panel René')
    verb = 'ajouté à' if enabled else 'retiré de'
    analytics.audit(guild.id, 'role', f'Rôle {role.name} {verb} {member} ({member.id})')
    return {'ok': True, 'roles': [str(r.id) for r in member.roles if not r.is_default()],
            'message': f'{role.name} {verb} {member.display_name}.'}


async def launch_express(guild_id, user_id):
    guild = guild_for(guild_id)
    member = guild.get_member(int(user_id))
    if member is None or member.bot or member.id == OWNER_DISCORD_ID:
        raise ValueError('Choisis une autre personne du serveur.')
    entry = await rdvexpress.create_express(guild.id, OWNER_DISCORD_ID, member)
    if entry['status'] == 'dm_failed':
        raise ValueError('Cette personne refuse les MP du bot.')
    analytics.audit(guild.id, 'express', f'RDV express {entry["id"]} pour {member} ({member.id})')
    return {'ok': True, 'id': entry['id'], 'message': f'Demande express envoyée à {member.display_name}.'}


NO_SHOW_ALLOWED = {'pending', 'accepted', 'accepted_now', 'accepted_5', 'accepted_10', 'expired'}


async def mark_no_show(guild_id, kind, entry_id):
    guild = guild_for(guild_id)
    source = rdv.get_store() if kind == 'rdv' else rdvexpress.store()
    entry = source.get(entry_id)
    if not isinstance(entry, dict) or str(entry.get('guild_id')) != str(guild.id):
        raise ValueError('Rendez-vous introuvable.')
    if entry.get('status') not in NO_SHOW_ALLOWED:
        raise ValueError('Ce rendez-vous est déjà clos.')
    entry['status'] = 'no_show'
    entry['no_show_at'] = datetime.now(timezone.utc).isoformat()
    (rdv.cancel_reminder if kind == 'rdv' else rdvexpress.cancel)(entry_id)
    name = entry.get('target_name') or f'Membre {entry.get("target_id")}'
    analytics.audit(guild.id, 'no_show', f'{name} n’est pas venu ({entry_id})')
    await core.save_state_immediately()
    return {'ok': True, 'message': f'Absence de {name} notée.'}


def question_json(guild, question_id, question):
    author = guild.get_member(int(question.get('author_id') or 0))
    answered_by = question.get('answered_by')
    if answered_by and core.bot.user and int(answered_by) == core.bot.user.id:
        responder = 'René'
    elif answered_by:
        staff = guild.get_member(int(answered_by))
        responder = staff.display_name if staff else 'Staff'
    else:
        responder = None
    return {'id': str(question_id), 'author': author.display_name if author else f'Membre {question.get("author_id")}',
            'avatar': str(author.display_avatar.url) if author else None,
            'content': question.get('content', ''), 'created_at': question.get('created_at'),
            'answered': bool(question.get('answered')), 'answer': question.get('answer'),
            'answered_by': responder, 'answered_at': question.get('answered_at'),
            'closed': bool(question.get('closed')),
            'url': f'https://discord.com/channels/{guild.id}/{question.get("channel_id")}/{question.get("question_message_id")}'}


async def tickets(guild_id):
    guild = guild_for(guild_id)
    entries = core.bot.questions.get(str(guild.id), {})
    items = [question_json(guild, qid, q) for qid, q in entries.items() if isinstance(q, dict)]
    open_items = sorted([i for i in items if not i['answered']], key=lambda i: i['created_at'] or '')
    done = sorted([i for i in items if i['answered']], key=lambda i: i['answered_at'] or '', reverse=True)
    return {'open': len(open_items), 'items': (open_items + done)[:100]}


async def answer_ticket(guild_id, question_id, text, close_only=False):
    guild = guild_for(guild_id)
    lock = core.bot.question_locks.setdefault((guild.id, question_id), asyncio.Lock())
    async with lock:
        question = core.bot.questions.get(str(guild.id), {}).get(question_id)
        if not isinstance(question, dict):
            raise ValueError('Ticket introuvable.')
        if question.get('answered'):
            raise ValueError('Ce ticket a déjà une réponse.')
        delivery = 'Ticket clos sans réponse.'
        if not close_only:
            try:
                user = core.bot.get_user(int(question['author_id'])) or await core.bot.fetch_user(int(question['author_id']))
                await core.send_embed_with_thumbnail(
                    user, title='Réponse à ta question',
                    description=(f'**Ta question :**\n{question.get("content", "")}\n\n'
                                 f'**Réponse de René :**\n{text}'),
                    color=core.COLOR_SUCCESS, image_path=core.IMAGE_READ)
                delivery = 'Réponse envoyée en MP.'
            except (discord.Forbidden, discord.NotFound):
                raise ValueError('Cette personne refuse les MP du bot.') from None
        question.update({'answered': True, 'answered_by': core.bot.user.id if core.bot.user else None,
                         'answer': None if close_only else text, 'closed': close_only,
                         'answered_at': datetime.now(timezone.utc).isoformat(),
                         'delivery_result': delivery})
        core.save_runtime_json(core.QUESTIONS_FILE, core.bot.questions)
    notification_id = question.get('staff_notification_message_id')
    channel = guild.get_channel(staff_channel_id(guild) or int(question.get('channel_id') or 0))
    if notification_id and isinstance(channel, discord.TextChannel):
        try:
            message = channel.get_partial_message(int(notification_id))
            await message.reply('✅ René a répondu depuis le panel.' if not close_only else '✅ Ticket clos depuis le panel.',
                                mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass
    analytics.audit(guild.id, 'ticket', f'Ticket {question_id} : {delivery}')
    await core.save_state_immediately()
    return {'ok': True, 'message': delivery}


async def text_channels(guild_id):
    guild = guild_for(guild_id)
    me = guild.me
    items = [{'id': str(c.id), 'name': c.name, 'category': c.category.name if c.category else ''}
             for c in guild.text_channels if me and c.permissions_for(me).send_messages]
    return {'items': items}


async def say_as_rene(guild_id, channel_id, text):
    guild = guild_for(guild_id)
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        raise ValueError('Choisis un salon textuel.')
    await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
    analytics.audit(guild.id, 'say', f'René a parlé dans #{channel.name}')
    return {'ok': True, 'message': f'Message publié dans #{channel.name}.'}


def clean_word(raw):
    word = ' '.join(str(raw or '').strip().lower().split())
    if not 2 <= len(word) <= 40 or not core.normalize_text(word):
        raise ValueError('Un mot ou une expression de 2 à 40 caractères.')
    return word


def words_json(guild):
    config = core.bot.config_data.get(str(guild.id))
    custom = isinstance(config, dict) and isinstance(config.get('bad_words'), list)
    return {'words': sorted(core.guild_bad_words(guild.id), key=str.casefold), 'custom': custom,
            'defaults': len(core.BAD_WORDS)}


async def bad_words(guild_id):
    return words_json(guild_for(guild_id))


async def change_bad_words(guild_id, action, raw=None):
    guild = guild_for(guild_id)
    config = core.bot.get_guild_config(guild.id)
    words = list(core.guild_bad_words(guild.id))
    if action == 'reset':
        config.pop('bad_words', None)
        detail, message = 'Liste des mots interdits rétablie', 'Liste par défaut rétablie.'
    else:
        word = clean_word(raw)
        existing = {core.normalize_text(item) for item in words}
        if action == 'add':
            if core.normalize_text(word) in existing:
                raise ValueError('Ce mot est déjà dans la liste.')
            if len(words) >= 500:
                raise ValueError('La liste est limitée à 500 mots.')
            words.append(word)
            detail, message = f'Mot interdit ajouté : {word}', f'« {word} » ajouté.'
        else:
            words = [item for item in words if core.normalize_text(item) != core.normalize_text(word)]
            detail, message = f'Mot interdit retiré : {word}', f'« {word} » retiré.'
        config['bad_words'] = sorted(words, key=str.casefold)
    analytics.audit(guild.id, 'words', detail)
    await core.save_state_immediately()
    return dict(words_json(guild), ok=True, message=message)


async def test_bad_words(guild_id, text):
    guild = guild_for(guild_id)
    found = core.find_bad_word(text, guild.id)
    return {'blocked': found is not None, 'word': found,
            'message': f'René supprimerait ce message (« {found} »).' if found else 'René laisserait passer ce message.'}


async def ask_ai(guild_id, question, actor):
    data = await snapshot(guild_id)
    context = {'guild': data['guild'], 'since': data['since'], 'totals_30_days': data['totals'],
               'daily_30_days': data['daily'], 'top_members_30_days': [
                   {k: m[k] for k in ('name', 'messages', 'voice_seconds', 'active_days')} for m in data['top']]}
    return await ai.answer(question, context, actor)


def payload():
    return request.get_json(silent=True) or {}


def positive_id(value):
    if not str(value).isdigit() or int(value) <= 0:
        raise ValueError('Identifiant Discord invalide.')
    return str(value)


def response(call):
    try:
        return jsonify(call())
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    except discord.Forbidden:
        return jsonify({'error': 'Discord refuse cette action : vérifie les permissions de René.'}), 403
    except discord.HTTPException:
        core.logger.exception('Erreur Discord dans le panel')
        return jsonify({'error': 'Discord ne répond pas. Réessaie.'}), 502


def install_panel(app):
    if getattr(app, '_rene_panel_installed', False):
        return
    app._rene_panel_installed = True
    install_giftcard(app, lambda coro, timeout=20: run(coro, timeout))
    robloxapi.install_roblox_api(app, lambda coro, timeout=20: run(coro, timeout))
    assistance.install_assistance(app, lambda coro, timeout=20: run(coro, timeout))

    @app.after_request
    def security_headers(resp):
        resp.headers['Cache-Control'] = 'no-store'
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['Referrer-Policy'] = 'same-origin'
        resp.headers['X-Frame-Options'] = 'DENY'
        resp.headers['Content-Security-Policy'] = ("default-src 'self'; img-src 'self' https://cdn.discordapp.com "
            "https://*.discordapp.net data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
            "font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return resp

    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(415)
    @app.errorhandler(503)
    @app.errorhandler(504)
    def error_json(error):
        if request.path.startswith('/api/'):
            return jsonify({'error': error.description}), error.code
        return error

    @app.get('/')
    def home():
        return render_template('panel.html')

    @app.get('/assets/<path:filename>')
    def asset(filename):
        if filename not in {'IDLE.png', 'REFLECHIS.png', 'GIFT.png', 'HAMMER.png', 'NEW.png', 'READ.png', 'SLEEP.png'}:
            abort(404)
        return send_from_directory(core.BASE_DIR, filename, max_age=3600)

    @app.get('/api/session')
    def session():
        if not configured():
            return jsonify({'configured': False, 'authenticated': False})
        try:
            user = account()
            return jsonify({'configured': True, 'authenticated': True, 'csrf': user['csrf']})
        except Exception as error:
            if getattr(error, 'code', None) == 401:
                return jsonify({'configured': True, 'authenticated': False})
            raise

    @app.post('/api/login')
    def login():
        if not configured():
            abort(503, 'Configure PANEL_PASSWORD et PANEL_SECRET sur Render.')
        address = request.remote_addr or 'unknown'
        now = time.monotonic()
        recent = [t for t in attempts.get(address, []) if now - t < 600]
        if len(recent) >= 8:
            return jsonify({'error': 'Trop de tentatives. Réessaie dans dix minutes.'}), 429
        attempted = str(payload().get('password', ''))
        if not hmac.compare_digest(attempted, os.environ['PANEL_PASSWORD']):
            attempts[address] = recent + [now]
            return jsonify({'error': 'Mot de passe incorrect.'}), 401
        attempts.pop(address, None)
        csrf = secrets.token_urlsafe(32)
        sid = secrets.token_urlsafe(16)
        result = make_response(jsonify({'authenticated': True, 'csrf': csrf}))
        result.set_cookie('rene_session', serializer().dumps({'version': 1, 'csrf': csrf, 'sid': sid,
                          'auth': password_tag()}),
                          max_age=SESSION_AGE, secure=os.getenv('PANEL_INSECURE_LOCAL') != '1',
                          httponly=True, samesite='Strict', path='/')
        return result

    @app.post('/api/logout')
    def logout():
        protected()
        result = make_response(jsonify({'ok': True}))
        result.delete_cookie('rene_session', path='/')
        return result

    @app.get('/api/guilds')
    def guilds():
        protected()
        async def get():
            allowed = os.getenv('PANEL_GUILD_ID', '').strip()
            return [{'id': str(g.id), 'name': g.name} for g in core.bot.guilds if not allowed or str(g.id) == allowed]
        return jsonify(run(get()))

    @app.get('/api/guild/<guild_id>/overview')
    def overview(guild_id):
        protected()
        return response(lambda: run(snapshot(positive_id(guild_id))))

    @app.get('/api/guild/<guild_id>/members')
    def list_members(guild_id):
        protected()
        query = request.args.get('q', '').strip().casefold()[:100]
        try:
            page = min(max(int(request.args.get('page', '0')), 0), 1000)
        except ValueError:
            page = 0
        return response(lambda: run(members(positive_id(guild_id), query, page)))

    @app.get('/api/guild/<guild_id>/member-search')
    def member_search(guild_id):
        protected()
        query = request.args.get('q', '').strip()[:100]
        return response(lambda: run(search_members(positive_id(guild_id), query)))

    @app.get('/api/guild/<guild_id>/presence')
    def presence(guild_id):
        protected()
        async def get():
            return analytics.presence_ranking(guild_for(positive_id(guild_id)))
        return response(lambda: run(get()))

    @app.get('/api/guild/<guild_id>/gifts')
    def list_gifts(guild_id):
        protected()
        return response(lambda: run(gifts(positive_id(guild_id))))

    @app.post('/api/guild/<guild_id>/gifts/replace-legacy')
    def replace_legacy(guild_id):
        protected()
        return response(lambda: run(replace_legacy_gifts(positive_id(guild_id)), 600))

    @app.post('/api/guild/<guild_id>/gifts/<code>/resend')
    def resend(guild_id, code):
        protected()
        if not re.fullmatch(r'VOID-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}', code):
            abort(404)
        return response(lambda: run(resend_gift(positive_id(guild_id), code), 40))

    @app.get('/api/guild/<guild_id>/stats')
    def detailed_stats(guild_id):
        protected()
        try:
            days = int(request.args.get('days', '30'))
        except ValueError:
            days = 30
        days = days if days in (7, 30, 90) else 30
        return response(lambda: run(stats.build(guild_for(positive_id(guild_id)), days), 30))

    @app.get('/api/guild/<guild_id>/broadcast')
    def broadcast_status(guild_id):
        protected()
        async def get():
            return broadcast.status(guild_for(positive_id(guild_id)))
        return response(lambda: run(get()))

    @app.post('/api/guild/<guild_id>/broadcast')
    def broadcast_start(guild_id):
        protected()
        data = payload()
        role = str(data.get('role_id') or '')
        return response(lambda: run(broadcast.start(guild_for(positive_id(guild_id)), str(data.get('message', '')),
                                                    int(positive_id(role)) if role else None), 30))

    @app.post('/api/guild/<guild_id>/broadcast/cancel')
    def broadcast_cancel(guild_id):
        protected()
        return response(lambda: run(broadcast.cancel(guild_for(positive_id(guild_id)))))

    @app.get('/api/guild/<guild_id>/assistance')
    def assistance_requests(guild_id):
        protected()
        async def get():
            return assistance.list_requests(guild_for(positive_id(guild_id)).id)
        return response(lambda: run(get()))

    @app.get('/api/system/assistance')
    def assistance_settings():
        protected()
        return jsonify({'password': assistance.password(), 'from_env': assistance.password_from_env(),
                        'url': (giftcodes.public_base_url() or request.host_url.rstrip('/')) + '/assistance'})

    @app.post('/api/system/assistance')
    def assistance_regenerate():
        protected()
        if assistance.password_from_env():
            return jsonify({'error': 'Le mot de passe vient de ASSISTANCE_PASSWORD sur Render.'}), 400
        value = assistance.regenerate_password()
        if core.bot.is_ready() and not core.bot.is_closed():
            run(core.save_state_immediately(), 30)
        else:
            core.save_runtime_json(core.CONFIG_FILE, core.bot.config_data)
        return jsonify({'ok': True, 'password': value,
                        'message': 'Nouveau mot de passe créé. Les assistants connectés sont déconnectés.'})

    @app.get('/api/guild/<guild_id>/bad-words')
    def list_bad_words(guild_id):
        protected()
        return response(lambda: run(bad_words(positive_id(guild_id))))

    @app.post('/api/guild/<guild_id>/bad-words')
    def edit_bad_words(guild_id):
        protected()
        data = payload()
        action = str(data.get('action', ''))
        if action not in {'add', 'remove', 'reset'}:
            return jsonify({'error': 'Action inconnue.'}), 400
        return response(lambda: run(change_bad_words(positive_id(guild_id), action, data.get('word')), 30))

    @app.post('/api/guild/<guild_id>/bad-words/test')
    def try_bad_words(guild_id):
        protected()
        text = str(payload().get('text', ''))[:2000]
        return response(lambda: run(test_bad_words(positive_id(guild_id), text)))

    @app.get('/api/guild/<guild_id>/polls')
    def list_polls(guild_id):
        protected()
        return response(lambda: run(polls.list_polls(guild_for(positive_id(guild_id))), 30))

    @app.post('/api/guild/<guild_id>/polls')
    def create_poll(guild_id):
        protected()
        data = payload()
        try:
            hours = int(data.get('hours', 24))
        except (TypeError, ValueError):
            hours = 0
        return response(lambda: run(polls.create_poll(guild_for(positive_id(guild_id)),
            int(positive_id(data.get('channel_id'))), str(data.get('question', '')),
            polls.clean_answers(data.get('answers')), hours, bool(data.get('multiple'))), 30))

    @app.post('/api/guild/<guild_id>/polls/<poll_id>/end')
    def end_poll(guild_id, poll_id):
        protected()
        if not poll_id.isalnum() or len(poll_id) > 20:
            abort(404)
        return response(lambda: run(polls.end_poll(guild_for(positive_id(guild_id)), poll_id), 30))

    @app.post('/api/guild/<guild_id>/gifts/<code>/used')
    def gift_used(guild_id, code):
        protected()
        if not re.fullmatch(r'VOID-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}', code):
            abort(404)
        return response(lambda: run(set_gift_used(positive_id(guild_id), code, bool(payload().get('used'))), 30))

    @app.get('/api/system/roblox')
    def roblox_settings():
        protected()
        key = robloxapi.api_key()
        return jsonify({'configured': bool(key), 'from_env': robloxapi.key_from_env(), 'key': key,
                        'base_url': giftcodes.public_base_url() or request.host_url.rstrip('/')})

    @app.get('/api/system/roblox/script')
    def roblox_script():
        protected()
        text = (core.BASE_DIR / 'roblox' / 'ReneGiftCodes.lua').read_text(encoding='utf-8')
        base = giftcodes.public_base_url() or request.host_url.rstrip('/')
        return jsonify({'script': text.replace('https://ton-service.onrender.com', base)})

    @app.post('/api/system/roblox')
    def roblox_regenerate():
        protected()
        if robloxapi.key_from_env():
            return jsonify({'error': 'La clé vient de ROBLOX_API_KEY sur Render : change-la là-bas.'}), 400
        key = robloxapi.regenerate_key()
        if core.bot.is_ready() and not core.bot.is_closed():
            run(core.save_state_immediately(), 30)
        else:
            core.save_runtime_json(core.CONFIG_FILE, core.bot.config_data)
        return jsonify({'ok': True, 'key': key, 'message': 'Nouvelle clé créée. Mets-la à jour dans Roblox.'})

    @app.get('/api/guild/<guild_id>/appointments')
    def list_appointments(guild_id):
        protected()
        return response(lambda: run(appointments(positive_id(guild_id))))

    @app.post('/api/guild/<guild_id>/appointments')
    def create_appointment(guild_id):
        protected()
        data = payload()
        return response(lambda: run(schedule_appointment(positive_id(guild_id),
            positive_id(data.get('user_id')), str(data.get('scheduled_at', ''))), 45))

    @app.post('/api/guild/<guild_id>/dm')
    def send_dm(guild_id):
        protected()
        data = payload()
        return response(lambda: run(send_private_message(positive_id(guild_id),
            positive_id(data.get('user_id')), str(data.get('message', ''))), 35))

    @app.get('/api/system/presence')
    def current_presence():
        protected()
        setting = core.bot.config_data.get('_panel_presence')
        return jsonify(setting if isinstance(setting, dict) else {'status': 'auto', 'text': ''})

    @app.post('/api/system/presence')
    def update_presence():
        protected()
        data = payload()
        return response(lambda: run(set_bot_presence(str(data.get('status', 'auto')),
            str(data.get('text', '')).strip()), 30))

    @app.post('/api/system/restart')
    def restart_service():
        protected()
        if core.bot.is_ready() and not core.bot.is_closed():
            run(core.save_state_immediately(), 30)
        else:
            core.save_runtime_json(core.CONFIG_FILE, core.bot.config_data)
        timer = threading.Timer(2, lambda: os._exit(1))
        timer.daemon = True
        timer.start()
        return jsonify({'ok': True, 'message': 'Redémarrage de René lancé. Reviens dans une minute.'})

    @app.post('/api/guild/<guild_id>/ban')
    def ban(guild_id):
        protected()
        data = payload()
        reason = str(data.get('reason', '')).strip()[:400]
        if len(reason) < 5:
            return jsonify({'error': 'Indique un motif d’au moins cinq caractères.'}), 400
        return response(lambda: run(ban_member(positive_id(guild_id), positive_id(data.get('user_id')), reason), 30))

    @app.post('/api/guild/<guild_id>/warn')
    def warn(guild_id):
        protected()
        data = payload()
        reason = str(data.get('reason', '')).strip()[:400]
        if len(reason) < 3:
            return jsonify({'error': 'Indique un motif.'}), 400
        return response(lambda: run(warn_member(positive_id(guild_id), positive_id(data.get('user_id')), reason), 40))

    @app.post('/api/guild/<guild_id>/tempban')
    def tempban(guild_id):
        protected()
        data = payload()
        reason = str(data.get('reason', '')).strip()[:400]
        try:
            hours = int(data.get('hours', 0))
        except (TypeError, ValueError):
            hours = 0
        if len(reason) < 3:
            return jsonify({'error': 'Indique un motif.'}), 400
        if not 1 <= hours <= 24 * 90:
            return jsonify({'error': 'Durée entre 1 heure et 90 jours.'}), 400
        return response(lambda: run(temp_ban_member(positive_id(guild_id), positive_id(data.get('user_id')), reason, hours), 40))

    @app.get('/api/guild/<guild_id>/tempbans')
    def list_tempbans(guild_id):
        protected()
        return response(lambda: run(temp_bans(positive_id(guild_id))))

    @app.post('/api/guild/<guild_id>/tempbans/<user_id>/lift')
    def lift_tempban(guild_id, user_id):
        protected()
        return response(lambda: run(lift_temp_ban(positive_id(guild_id), positive_id(user_id)), 30))

    @app.get('/api/guild/<guild_id>/roles')
    def list_roles(guild_id):
        protected()
        return response(lambda: run(guild_roles(positive_id(guild_id))))

    @app.post('/api/guild/<guild_id>/roles')
    def change_role(guild_id):
        protected()
        data = payload()
        return response(lambda: run(set_member_role(positive_id(guild_id), positive_id(data.get('user_id')),
            positive_id(data.get('role_id')), bool(data.get('enabled'))), 30))

    @app.post('/api/guild/<guild_id>/express')
    def express(guild_id):
        protected()
        data = payload()
        return response(lambda: run(launch_express(positive_id(guild_id), positive_id(data.get('user_id'))), 35))

    @app.post('/api/guild/<guild_id>/appointments/<kind>/<entry_id>/no-show')
    def no_show(guild_id, kind, entry_id):
        protected()
        if kind not in {'rdv', 'express'} or not entry_id.isalnum() or len(entry_id) > 20:
            abort(404)
        return response(lambda: run(mark_no_show(positive_id(guild_id), kind, entry_id), 30))

    @app.get('/api/guild/<guild_id>/tickets')
    def list_tickets(guild_id):
        protected()
        return response(lambda: run(tickets(positive_id(guild_id))))

    @app.post('/api/guild/<guild_id>/tickets/<question_id>/reply')
    def reply_ticket(guild_id, question_id):
        protected()
        text = str(payload().get('message', '')).strip()
        if not 1 <= len(text) <= 1800:
            return jsonify({'error': 'La réponse doit contenir entre 1 et 1 800 caractères.'}), 400
        return response(lambda: run(answer_ticket(positive_id(guild_id), positive_id(question_id), text), 35))

    @app.post('/api/guild/<guild_id>/tickets/<question_id>/close')
    def close_ticket(guild_id, question_id):
        protected()
        return response(lambda: run(answer_ticket(positive_id(guild_id), positive_id(question_id), '', True), 30))

    @app.get('/api/guild/<guild_id>/channels')
    def list_channels(guild_id):
        protected()
        return response(lambda: run(text_channels(positive_id(guild_id))))

    @app.post('/api/guild/<guild_id>/say')
    def say(guild_id):
        protected()
        data = payload()
        text = str(data.get('message', '')).strip()
        if not 1 <= len(text) <= 1800:
            return jsonify({'error': 'Le message doit contenir entre 1 et 1 800 caractères.'}), 400
        return response(lambda: run(say_as_rene(positive_id(guild_id), positive_id(data.get('channel_id')), text), 30))

    @app.post('/api/guild/<guild_id>/gift/challenge')
    def gift_challenge(guild_id):
        user = protected()
        data = payload()
        reason = str(data.get('reason', '')).strip()[:1000]
        if not reason:
            return jsonify({'error': 'Indique la raison du cadeau.'}), 400
        return response(lambda: run(start_gift_challenge(positive_id(guild_id),
            positive_id(data.get('user_id')), reason, user['sid'], rewards.clean(data.get('reward'))), 40))

    @app.get('/api/rewards')
    def reward_catalog():
        protected()
        return jsonify({'games': rewards.catalog()})

    @app.post('/api/guild/<guild_id>/gifts/<code>/reward')
    def gift_reward(guild_id, code):
        protected()
        if not re.fullmatch(r'VOID-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}', code):
            abort(404)
        return response(lambda: run(set_gift_reward(positive_id(guild_id), code,
                                                    rewards.clean(payload().get('reward'))), 30))

    @app.post('/api/guild/<guild_id>/gift/confirm')
    def gift_confirm(guild_id):
        user = protected()
        data = payload()
        challenge_id = str(data.get('challenge_id', ''))[:60]
        qr_text = str(data.get('qr_text', ''))[:200]
        return response(lambda: run(confirm_gift_challenge(positive_id(guild_id),
            challenge_id, qr_text, user['sid']), 45))

    @app.post('/api/guild/<guild_id>/ai')
    def start_ai(guild_id):
        user = protected()
        question = str(payload().get('question', '')).strip()
        if not 1 <= len(question) <= 600:
            return jsonify({'error': 'Écris une question de 1 à 600 caractères.'}), 400
        if not ai.api_key():
            return jsonify({'error': 'Ajoute NATHGPT_API_KEY ou token dans Render.'}), 503
        gid = positive_id(guild_id)
        run(snapshot(gid))
        actor = user['sid']
        with job_lock:
            for key, job in list(jobs.items()):
                if time.time() - job['created'] > 900:
                    del jobs[key]
            if sum(job['actor'] == actor and not job['future'].done() for job in jobs.values()) >= 1:
                return jsonify({'error': 'Une demande est déjà en cours.'}), 429
            job_id = uuid.uuid4().hex
            future = asyncio.run_coroutine_threadsafe(ask_ai(gid, question, actor), core.bot.loop)
            jobs[job_id] = {'actor': actor, 'future': future, 'created': time.time()}
        return jsonify({'job_id': job_id}), 202

    @app.get('/api/ai/<job_id>')
    def ai_result(job_id):
        user = protected()
        with job_lock:
            job = jobs.get(job_id)
        if not job or job['actor'] != user['sid']:
            abort(404)
        if not job['future'].done():
            return jsonify({'status': 'thinking'})
        try:
            answer = job['future'].result()
            return jsonify({'status': 'done', 'answer': answer})
        except ValueError as error:
            return jsonify({'status': 'error', 'error': str(error)})
        except Exception:
            core.logger.exception('Erreur IA dans le panel')
            return jsonify({'status': 'error', 'error': 'La demande à NathGPT a échoué.'})
