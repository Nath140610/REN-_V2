"""Panel Assistance : un assistant active un code cadeau perdu pendant 24 h, sans accès au panel principal."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

import discord
from flask import abort, jsonify, make_response, render_template, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from rene import analytics, core, robloxapi
from rene.commands import sendgiftcode as gifts

PASSWORD_KEY = '_assistance_password'
REQUESTS_KEY = '_assistance_requests'
COOKIE = 'rene_assist'
SESSION_AGE = 8 * 3600
attempts: dict[str, list[float]] = {}
submissions: dict[str, list[float]] = {}

REFUSALS = {
    'available': 'ce code existe déjà et il est actif. Il n’y a rien à réactiver.',
    'used': 'ce code existe déjà et il a été utilisé.',
    'inactive': 'ce code existe déjà : il a été envoyé mais pas encore gratté.',
    'expired': 'ce code existe déjà et il a expiré.',
    'replaced': 'ce code existe déjà et il a été remplacé par une nouvelle carte.',
}


def password() -> str:
    return (os.getenv('ASSISTANCE_PASSWORD') or str(core.bot.config_data.get(PASSWORD_KEY) or '')).strip()


def password_from_env() -> bool:
    return bool(os.getenv('ASSISTANCE_PASSWORD', '').strip())


def regenerate_password() -> str:
    value = '-'.join(secrets.token_urlsafe(4).replace('_', 'x').replace('-', 'y') for _ in range(4))
    core.bot.config_data[PASSWORD_KEY] = value
    return value


def configured() -> bool:
    return bool(password() and len(os.getenv('PANEL_SECRET', '')) >= 32)


def serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(os.environ['PANEL_SECRET'], salt='rene-assistance-v1')


def password_tag() -> str:
    return hmac.new(os.environ['PANEL_SECRET'].encode(), password().encode(), hashlib.sha256).hexdigest()[:24]


def session_or_abort(check_csrf: bool = True) -> dict:
    if not configured():
        abort(503, 'L’assistance n’est pas encore ouverte.')
    try:
        value = serializer().loads(request.cookies.get(COOKIE, ''), max_age=SESSION_AGE)
        if not hmac.compare_digest(value.get('auth', ''), password_tag()):
            raise BadSignature('old password')
    except (BadSignature, SignatureExpired):
        abort(401, 'Connecte-toi à l’assistance.')
    if check_csrf and request.method not in ('GET', 'HEAD'):
        if not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), value.get('csrf', '')):
            abort(403, 'Session invalide. Recharge la page.')
        if request.mimetype != 'application/json':
            abort(415, 'JSON requis.')
    return value


def requests_store() -> list[dict]:
    data = core.bot.config_data.setdefault(REQUESTS_KEY, [])
    if not isinstance(data, list):
        data = []
        core.bot.config_data[REQUESTS_KEY] = data
    return data


def allowed_guilds() -> list[discord.Guild]:
    allowed = os.getenv('PANEL_GUILD_ID', '').strip()
    return [g for g in core.bot.guilds if not allowed or str(g.id) == allowed]


def guild_or_error(guild_id) -> discord.Guild:
    for guild in allowed_guilds():
        if str(guild.id) == str(guild_id):
            return guild
    raise ValueError('Serveur introuvable.')


async def search(guild_id, query: str) -> dict:
    guild = guild_or_error(guild_id)
    needle = query.casefold().strip()
    matches = [m for m in guild.members if not m.bot and needle and (
        needle in m.display_name.casefold() or needle in m.name.casefold() or needle == str(m.id))]
    matches.sort(key=lambda m: (not m.name.casefold().startswith(needle), m.display_name.casefold()))
    return {'items': [{'id': str(m.id), 'name': m.display_name, 'username': m.name,
                       'avatar': str(m.display_avatar.url)} for m in matches[:20]]}


def clean_fields(data: dict) -> dict:
    code = robloxapi.normalize(data.get('code'))
    if not robloxapi.CODE_PATTERN.match(code):
        raise ValueError('Le code doit ressembler à VOID-XXXX-XXXX-XXXX.')
    reason = ' '.join(str(data.get('reason', '')).split())
    if not 5 <= len(reason) <= 500:
        raise ValueError('Explique le problème (5 à 500 caractères).')
    signature = ' '.join(str(data.get('signature', '')).split())
    if not 2 <= len(signature) <= 60:
        raise ValueError('Signe la demande avec ton nom (2 à 60 caractères).')
    try:
        incident = datetime.fromisoformat(str(data.get('incident_at', '')).replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Indique la date et l’heure.') from None
    if incident.tzinfo is None:
        raise ValueError('Indique la date et l’heure.')
    now = datetime.now(timezone.utc)
    if incident > now + timedelta(hours=1) or incident < now - timedelta(days=365):
        raise ValueError('La date doit être passée et dater de moins d’un an.')
    user_id = str(data.get('user_id', ''))
    if not user_id.isdigit():
        raise ValueError('Choisis la personne dans la liste des membres.')
    return {'code': code, 'reason': reason, 'signature': signature,
            'incident_at': incident.astimezone(timezone.utc).isoformat(), 'user_id': int(user_id)}


async def submit(guild_id, fields: dict, session_id: str) -> dict:
    guild = guild_or_error(guild_id)
    member = guild.get_member(fields['user_id'])
    if member is None or member.bot:
        raise ValueError('Cette personne n’est pas sur le serveur. Choisis-la dans la liste.')
    now = datetime.now(timezone.utc)
    code = fields['code']
    store = gifts.gift_store()
    existing = store.get(code)
    record = {
        'id': uuid.uuid4().hex[:10].upper(), 'guild_id': str(guild.id), 'created_at': now.isoformat(),
        'member_id': str(member.id), 'member_name': member.display_name, 'member_username': member.name,
        'code': code, 'reason': fields['reason'], 'incident_at': fields['incident_at'],
        'signature': fields['signature'], 'session': session_id[:8],
    }
    if existing is not None:
        status = robloxapi.roblox_status(existing, now)
        record.update(outcome='refused', code_status=status,
                      same_member=str(existing.get('recipient_id')) == str(member.id),
                      detail=f'Impossible : {REFUSALS.get(status, "ce code existe déjà.")}')
        result = {'ok': False, 'outcome': 'refused', 'message': record['detail']}
    else:
        expires = now + gifts.CARD_LIFETIME
        store[code] = {
            'code': code, 'guild_id': guild.id, 'recipient_id': member.id, 'recipient_name': str(member),
            'reason': f'Assistance : {fields["reason"]}', 'distributed_by_id': 0,
            'distributed_by_name': f'Assistance — {fields["signature"]}', 'created_at': now.isoformat(),
            'delivery_status': 'assistance', 'source': 'assistance', 'assistance_request': record['id'],
            'scratched_at': now.isoformat(), 'expires_at': expires.isoformat(),
        }
        record.update(outcome='accepted', code_status='available', expires_at=expires.isoformat(),
                      detail=f'Code ajouté et activé jusqu’au {expires.isoformat()}.')
        result = {'ok': True, 'outcome': 'accepted', 'expires_at': expires.isoformat(),
                  'message': f'Code activé pour {member.display_name} pendant 24 h.'}
    data = requests_store()
    data.append(record)
    core.bot.config_data[REQUESTS_KEY] = data[-1000:]
    analytics.audit(guild.id, 'assistance',
                    f'{record["signature"]} : {code} pour {member} — {"activé" if record["outcome"] == "accepted" else "refusé"}')
    await core.save_state_immediately()
    return dict(result, request_id=record['id'])


def list_requests(guild_id) -> dict:
    items = [r for r in requests_store() if str(r.get('guild_id')) == str(guild_id)]
    items.sort(key=lambda r: r.get('created_at', ''), reverse=True)
    today = datetime.now(timezone.utc).date().isoformat()
    return {'items': items[:200], 'total': len(items),
            'accepted': sum(r.get('outcome') == 'accepted' for r in items),
            'refused': sum(r.get('outcome') == 'refused' for r in items),
            'today': sum(str(r.get('created_at', '')).startswith(today) for r in items)}


def install_assistance(app, run) -> None:
    def respond(call):
        try:
            return jsonify(call())
        except ValueError as error:
            return jsonify({'error': str(error)}), 400

    @app.get('/assistance')
    def assistance_page():
        return render_template('assistance.html')

    @app.get('/api/assist/session')
    def assist_session():
        if not configured():
            return jsonify({'configured': False, 'authenticated': False})
        try:
            value = session_or_abort(check_csrf=False)
        except Exception as error:
            if getattr(error, 'code', None) == 401:
                return jsonify({'configured': True, 'authenticated': False})
            raise
        return jsonify({'configured': True, 'authenticated': True, 'csrf': value['csrf']})

    @app.post('/api/assist/login')
    def assist_login():
        if not configured():
            abort(503, 'L’assistance n’est pas encore ouverte.')
        address = request.remote_addr or 'unknown'
        now = time.monotonic()
        recent = [t for t in attempts.get(address, []) if now - t < 600]
        if len(recent) >= 8:
            return jsonify({'error': 'Trop de tentatives. Réessaie dans dix minutes.'}), 429
        given = str((request.get_json(silent=True) or {}).get('password', ''))
        if not hmac.compare_digest(given, password()):
            attempts[address] = recent + [now]
            return jsonify({'error': 'Mot de passe incorrect.'}), 401
        attempts.pop(address, None)
        csrf = secrets.token_urlsafe(32)
        result = make_response(jsonify({'authenticated': True, 'csrf': csrf}))
        result.set_cookie(COOKIE, serializer().dumps({'csrf': csrf, 'sid': secrets.token_urlsafe(12),
                                                      'auth': password_tag()}),
                          max_age=SESSION_AGE, secure=os.getenv('PANEL_INSECURE_LOCAL') != '1',
                          httponly=True, samesite='Strict', path='/')
        return result

    @app.post('/api/assist/logout')
    def assist_logout():
        session_or_abort()
        result = make_response(jsonify({'ok': True}))
        result.delete_cookie(COOKIE, path='/')
        return result

    @app.get('/api/assist/guilds')
    def assist_guilds():
        session_or_abort()
        async def get():
            return [{'id': str(g.id), 'name': g.name} for g in allowed_guilds()]
        return jsonify(run(get()))

    @app.get('/api/assist/members')
    def assist_members():
        session_or_abort()
        query = request.args.get('q', '')[:100]
        guild_id = request.args.get('guild', '')
        return respond(lambda: run(search(guild_id, query)))

    @app.post('/api/assist/requests')
    def assist_submit():
        user = session_or_abort()
        now = time.monotonic()
        recent = [t for t in submissions.get(user['sid'], []) if now - t < 3600]
        if len(recent) >= 30:
            return jsonify({'error': 'Trop de demandes cette heure-ci. Réessaie plus tard.'}), 429
        data = request.get_json(silent=True) or {}

        def call():
            fields = clean_fields(data)
            submissions[user['sid']] = recent + [now]
            return run(submit(data.get('guild_id'), fields, user['sid']), 30)
        return respond(call)
