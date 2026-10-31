"""Panel Render. Toutes les lectures Discord passent par la boucle du bot."""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
import hashlib
import hmac
import os
import secrets
import threading
import time
import uuid

from flask import abort, jsonify, make_response, render_template, request, send_from_directory
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
import discord

from rene import ai, analytics, core
from rene.commands.sendgiftcode import generate_unique_code, gift_store, send_gift_dm

SESSION_AGE = 8 * 3600
attempts = {}
jobs = {}
job_lock = threading.Lock()


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
            'bot': member.bot}


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


async def gifts(guild_id):
    guild_for(guild_id)
    entries = [entry for entry in gift_store().values() if isinstance(entry, dict) and str(entry.get('guild_id')) == str(guild_id)]
    entries.sort(key=lambda e: e.get('created_at', ''), reverse=True)
    return {'total': len(entries), 'items': entries[:100],
            'note': 'René suit la distribution et la livraison en MP. Il ne peut pas vérifier si un code a été utilisé sur Roblox.'}


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


async def send_gift(guild_id, user_id, reason):
    guild = guild_for(guild_id)
    member = guild.get_member(int(user_id))
    if member is None or member.bot:
        raise ValueError('Choisis un membre du serveur.')
    code = generate_unique_code()
    entry = {'code': code, 'guild_id': guild.id, 'recipient_id': member.id,
             'recipient_name': str(member), 'reason': reason,
             'distributed_by_id': 0, 'distributed_by_name': 'Panel René',
             'created_at': datetime.now(timezone.utc).isoformat(), 'delivery_status': 'pending'}
    gift_store()[code] = entry
    await core.save_state_immediately()
    delivered = await send_gift_dm(member, code=code, reason=reason, guild_name=guild.name)
    entry['delivery_status'] = 'delivered' if delivered else 'dm_failed'
    entry['delivery_updated_at'] = datetime.now(timezone.utc).isoformat()
    analytics.audit(guild.id, 'gift', f'Code {code} pour {member} ({member.id}) ; MP : {entry["delivery_status"]}')
    await core.save_state_immediately()
    return {'ok': True, 'code': code, 'delivered': delivered,
            'message': 'Code envoyé en MP.' if delivered else 'Code réservé, mais le MP a échoué.'}


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

    @app.get('/api/guild/<guild_id>/gifts')
    def list_gifts(guild_id):
        protected()
        return response(lambda: run(gifts(positive_id(guild_id))))

    @app.post('/api/guild/<guild_id>/ban')
    def ban(guild_id):
        protected()
        data = payload()
        reason = str(data.get('reason', '')).strip()[:400]
        if len(reason) < 5:
            return jsonify({'error': 'Indique un motif d’au moins cinq caractères.'}), 400
        return response(lambda: run(ban_member(positive_id(guild_id), positive_id(data.get('user_id')), reason), 30))

    @app.post('/api/guild/<guild_id>/gift')
    def gift(guild_id):
        protected()
        data = payload()
        reason = str(data.get('reason', '')).strip()[:1000]
        if not reason:
            return jsonify({'error': 'Indique la raison du cadeau.'}), 400
        return response(lambda: run(send_gift(positive_id(guild_id), positive_id(data.get('user_id')), reason), 40))

    @app.post('/api/guild/<guild_id>/ai')
    def start_ai(guild_id):
        user = protected()
        question = str(payload().get('question', '')).strip()
        if not 1 <= len(question) <= 4000:
            return jsonify({'error': 'Écris une question de 1 à 4 000 caractères.'}), 400
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
