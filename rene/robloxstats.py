"""Statistiques des jeux Roblox : API publique de Roblox + battements envoyés par les serveurs du jeu.

Deux sources se complètent :
  * l'API publique de Roblox (sans clé) : joueurs en ligne, visites, favoris, votes, serveurs publics ;
    René la relève toutes les 10 minutes pour garder l'historique des joueurs connectés ;
  * le Script serveur Luau ReneStats : chaque serveur du jeu envoie toutes les minutes, à chaque arrivée
    et à chaque départ la liste de ses joueurs (POST /api/roblox/heartbeat). René en tire les joueurs uniques, le temps de jeu et les plus actifs.

Les données détaillées par joueur sont gardées 31 jours, les totaux par jour 100 jours.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import aiohttp

from rene import core, rewards

GAMES_KEY = '_roblox_games'
STATS_KEY = '_roblox_stats'
SAMPLE_SECONDS = 600
SERVER_TIMEOUT = 150          # un serveur sans battement depuis 2 min 30 est considéré fermé
MAX_GAP = SERVER_TIMEOUT       # temps compté au plus entre deux battements d'un même serveur
DAYS_KEPT = 100
PLAYER_DAYS_KEPT = 31
MAX_PLAYERS_PER_DAY = 3000
MAX_PLAYERS_PER_SERVER = 200
NAMES_KEPT_DAYS = 120

live: dict[str, dict[str, dict]] = {}
cache: dict[str, tuple[float, dict]] = {}
avatar_cache: dict[str, tuple[float, str]] = {}
state = {'last_save': 0.0, 'task': None}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today() -> str:
    return utcnow().date().isoformat()


# ---------- Réglages ----------

def games_config() -> dict[str, dict]:
    data = core.bot.config_data.setdefault(GAMES_KEY, {})
    if not isinstance(data, dict):
        data = {}
        core.bot.config_data[GAMES_KEY] = data
    return data


def settings() -> dict:
    config = games_config()
    return {'items': [{'id': game_id, 'name': game['name'],
                       'place_id': str((config.get(game_id) or {}).get('place_id') or ''),
                       'universe_id': str((config.get(game_id) or {}).get('universe_id') or '')}
                      for game_id, game in rewards.GAMES.items()]}


async def save_settings(raw: dict) -> dict:
    config = games_config()
    for game_id in rewards.GAMES:
        if game_id not in raw:
            continue
        value = str(raw.get(game_id) or '').strip()
        if not value:
            config.pop(game_id, None)
            continue
        if not value.isdigit() or len(value) > 20:
            raise ValueError(f'ID de place invalide pour {rewards.GAMES[game_id]["name"]}.')
        if (config.get(game_id) or {}).get('place_id') != value:
            universe = await universe_for(value)
            config[game_id] = {'place_id': value, 'universe_id': universe}
            cache.pop(game_id, None)
    core.save_runtime_json(core.CONFIG_FILE, core.bot.config_data)
    return dict(settings(), ok=True, message='Jeux Roblox enregistrés.')


# ---------- API publique Roblox ----------

async def get_json(session: aiohttp.ClientSession, url: str):
    async with session.get(url, headers={'Accept': 'application/json'}) as response:
        if response.status != 200:
            raise RuntimeError(f'Roblox a répondu {response.status}.')
        return await response.json(content_type=None)


def http_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12),
                                 headers={'User-Agent': 'Rene-Panel/1.0'})


async def universe_for(place_id: str) -> str:
    try:
        async with http_session() as session:
            data = await get_json(session, f'https://apis.roblox.com/universes/v1/places/{place_id}/universe')
    except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
        raise ValueError('Roblox ne trouve pas cette place. Vérifie l’ID (le nombre dans l’adresse du jeu).')
    universe = str((data or {}).get('universeId') or '')
    if not universe.isdigit():
        raise ValueError('Roblox ne trouve pas cette place. Vérifie l’ID (le nombre dans l’adresse du jeu).')
    return universe


async def fetch_public(game_id: str, max_age: float = 60) -> dict | None:
    """Infos publiques d'un jeu configuré, gardées en cache une minute."""
    entry = games_config().get(game_id) or {}
    place, universe = str(entry.get('place_id') or ''), str(entry.get('universe_id') or '')
    if not place or not universe:
        return None
    cached = cache.get(game_id)
    if cached and time.monotonic() - cached[0] < max_age:
        return cached[1]
    result: dict = {'place_id': place, 'universe_id': universe, 'error': None}
    try:
        async with http_session() as session:
            info, votes, icon, servers = await asyncio.gather(
                get_json(session, f'https://games.roblox.com/v1/games?universeIds={universe}'),
                get_json(session, f'https://games.roblox.com/v1/games/votes?universeIds={universe}'),
                get_json(session, f'https://thumbnails.roblox.com/v1/games/icons?universeIds={universe}'
                                  '&size=150x150&format=Png&isCircular=false'),
                get_json(session, f'https://games.roblox.com/v1/games/{place}/servers/Public'
                                  '?sortOrder=Desc&limit=100&excludeFullGames=false'),
                return_exceptions=True)
    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        info = votes = icon = servers = error
    if isinstance(info, dict) and info.get('data'):
        game = info['data'][0]
        result.update({'name': game.get('name'), 'playing': int(game.get('playing') or 0),
                       'visits': int(game.get('visits') or 0), 'favorites': int(game.get('favoritedCount') or 0),
                       'max_players': int(game.get('maxPlayers') or 0), 'created': game.get('created'),
                       'updated': game.get('updated'), 'genre': game.get('genre')})
    else:
        result['error'] = 'Roblox ne répond pas pour le moment.'
    if isinstance(votes, dict) and votes.get('data'):
        up, down = int(votes['data'][0].get('upVotes') or 0), int(votes['data'][0].get('downVotes') or 0)
        result.update({'likes': up, 'dislikes': down, 'like_rate': round(up / (up + down) * 100) if up + down else None})
    if isinstance(icon, dict) and icon.get('data'):
        result['icon'] = icon['data'][0].get('imageUrl')
    if isinstance(servers, dict):
        result['servers'] = [{'id': str(s.get('id')), 'playing': int(s.get('playing') or 0),
                              'max_players': int(s.get('maxPlayers') or 0),
                              'fps': round(float(s['fps'])) if s.get('fps') is not None else None,
                              'ping': int(s['ping']) if s.get('ping') is not None else None}
                             for s in servers.get('data') or []]
    cache[game_id] = (time.monotonic(), result)
    return result


async def avatars(user_ids: list[str]) -> dict[str, str]:
    now = time.monotonic()
    missing = [uid for uid in user_ids if uid not in avatar_cache or now - avatar_cache[uid][0] > 3600]
    if missing:
        try:
            async with http_session() as session:
                for start in range(0, len(missing), 100):
                    chunk = ','.join(missing[start:start + 100])
                    data = await get_json(session, 'https://thumbnails.roblox.com/v1/users/avatar-headshot'
                                                   f'?userIds={chunk}&size=48x48&format=Png&isCircular=false')
                    for item in data.get('data') or []:
                        if item.get('imageUrl'):
                            avatar_cache[str(item.get('targetId'))] = (now, item['imageUrl'])
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, AttributeError):
            pass
    return {uid: avatar_cache[uid][1] for uid in user_ids if uid in avatar_cache}


# ---------- Historique ----------

def game_store(game_id: str) -> dict:
    root = core.bot.config_data.setdefault(STATS_KEY, {})
    data = root.setdefault(game_id, {})
    data.setdefault('days', {})
    data.setdefault('players', {})
    data.setdefault('names', {})
    return data


def day_bucket(data: dict, day: str) -> dict:
    return data['days'].setdefault(day, {'peak': 0, 'sum': 0, 'n': 0, 'unique': 0, 'new': 0,
                                         'sessions': 0, 'seconds': 0, 'hb_peak': 0})


def prune(data: dict) -> None:
    now = utcnow().date()
    limit = (now - timedelta(days=DAYS_KEPT)).isoformat()
    for day in [d for d in data['days'] if d < limit]:
        del data['days'][day]
    limit = (now - timedelta(days=PLAYER_DAYS_KEPT)).isoformat()
    for day in [d for d in data['players'] if d < limit]:
        del data['players'][day]
    limit = (now - timedelta(days=NAMES_KEPT_DAYS)).isoformat()
    for uid in [u for u, v in data['names'].items() if not isinstance(v, list) or v[2] < limit]:
        del data['names'][uid]


def record_sample(game_id: str, info: dict) -> None:
    if 'playing' not in info:
        return
    data = game_store(game_id)
    bucket = day_bucket(data, today())
    bucket['peak'] = max(bucket['peak'], info['playing'])
    bucket['sum'] += info['playing']
    bucket['n'] += 1
    bucket.setdefault('visits_start', info['visits'])
    bucket['visits_end'] = info['visits']
    prune(data)


def save_soon(force: bool = False) -> None:
    if force or time.monotonic() - state['last_save'] > 300:
        state['last_save'] = time.monotonic()
        core.save_runtime_json(core.CONFIG_FILE, core.bot.config_data)


async def sample_all() -> None:
    for game_id in list(games_config()):
        if game_id not in rewards.GAMES:
            continue
        try:
            info = await fetch_public(game_id, max_age=30)
        except Exception:
            core.logger.exception('Relevé Roblox impossible pour %s', game_id)
            continue
        if info:
            record_sample(game_id, info)
    save_soon(force=True)


async def sampler() -> None:
    await asyncio.sleep(20)
    while not core.bot.is_closed():
        if games_config():
            await sample_all()
        await asyncio.sleep(SAMPLE_SECONDS)


def start_sampler() -> None:
    task = state.get('task')
    if task is None or task.done():
        state['task'] = asyncio.get_running_loop().create_task(sampler(), name='rene-roblox-stats')


# ---------- Battements des serveurs du jeu ----------

def clean_players(raw) -> dict[str, str]:
    players = {}
    for item in (raw if isinstance(raw, list) else [])[:MAX_PLAYERS_PER_SERVER]:
        if not isinstance(item, dict):
            continue
        uid = str(item.get('id', '')).strip()
        if uid.isdigit() and len(uid) <= 20:
            players[uid] = str(item.get('name', '')).strip()[:40] or uid
    return players


def online(game_id: str) -> dict[str, dict]:
    now = time.time()
    servers = live.setdefault(game_id, {})
    for job in [j for j, s in servers.items() if now - s['seen'] > SERVER_TIMEOUT]:
        del servers[job]
    return servers


async def heartbeat(raw: dict) -> dict:
    game_id = str(raw.get('game') or '').strip().lower()
    if game_id not in rewards.GAMES:
        raise ValueError('Jeu inconnu.')
    job = str(raw.get('job_id') or '').strip()[:64] or 'studio'
    players = clean_players(raw.get('players'))
    max_players = str(raw.get('max_players') or '0')
    max_players = min(int(max_players), 1000) if max_players.isdigit() else 0
    now = time.time()
    servers = online(game_id)
    previous = servers.get(job)
    elapsed = min(max(0.0, now - previous['seen']), MAX_GAP) if previous else 0
    data = game_store(game_id)
    day = today()
    bucket = day_bucket(data, day)
    per_day = data['players'].setdefault(day, {})
    for uid, name in players.items():
        known = data['names'].get(uid)
        if not isinstance(known, list):
            data['names'][uid] = [name, day, day]
            bucket['new'] += 1
        else:
            known[0], known[2] = name, day
        entry = per_day.get(uid)
        if entry is None:
            if len(per_day) >= MAX_PLAYERS_PER_DAY:
                continue
            entry = per_day[uid] = [0, 0]
            bucket['unique'] += 1
        if previous and uid in previous['players']:
            entry[0] += round(elapsed)
            bucket['seconds'] += round(elapsed)
        else:
            entry[1] += 1
            bucket['sessions'] += 1
    # Joueurs qui viennent de partir : leur temps depuis le dernier envoi est compté.
    left = raw.get('left') if isinstance(raw.get('left'), list) else []
    for uid in {str(u).strip() for u in left[:MAX_PLAYERS_PER_SERVER]}:
        if previous and uid in previous['players'] and uid not in players and uid in per_day:
            per_day[uid][0] += round(elapsed)
            bucket['seconds'] += round(elapsed)
    if raw.get('closing'):
        servers.pop(job, None)
    else:
        servers[job] = {'players': players, 'seen': now, 'started': previous['started'] if previous else now,
                        'max_players': max_players,
                        'private': bool(raw.get('private')), 'place_id': str(raw.get('place_id') or '')[:20],
                        'studio': job == 'studio'}
    bucket['hb_peak'] = max(bucket['hb_peak'], sum(len(s['players']) for s in servers.values()))
    data['last_heartbeat'] = utcnow().isoformat()
    prune(data)
    save_soon(force=bool(raw.get('closing')))
    return {'ok': True, 'players': len(players)}


# ---------- Panel ----------

async def build_game(game_id: str, days: int) -> dict:
    game = rewards.GAMES[game_id]
    public = await fetch_public(game_id)
    data = game_store(game_id)
    servers = online(game_id)
    start = utcnow().date() - timedelta(days=days - 1)
    keys = [(start + timedelta(days=i)).isoformat() for i in range(days)]

    daily = []
    for key in keys:
        bucket = data['days'].get(key, {})
        visits = (bucket['visits_end'] - bucket['visits_start']) if 'visits_end' in bucket else None
        daily.append({'date': key, 'peak': max(bucket.get('peak', 0), bucket.get('hb_peak', 0)),
                      'average': round(bucket['sum'] / bucket['n'], 1) if bucket.get('n') else 0,
                      'unique': bucket.get('unique', 0), 'new': bucket.get('new', 0),
                      'sessions': bucket.get('sessions', 0), 'minutes': round(bucket.get('seconds', 0) / 60),
                      'visits': visits})

    # Joueurs uniques et plus actifs : détail gardé 31 jours.
    detail_days = [k for k in keys[-PLAYER_DAYS_KEPT:] if k in data['players']]
    totals: dict[str, list[int]] = {}
    for key in detail_days:
        for uid, (seconds, sessions) in data['players'][key].items():
            total = totals.setdefault(uid, [0, 0, 0])
            total[0] += seconds
            total[1] += sessions
            total[2] += 1
    ranking = sorted(totals.items(), key=lambda item: (item[1][0], item[1][1]), reverse=True)[:10]
    pictures = await avatars([uid for uid, _ in ranking]) if ranking else {}
    names = data['names']
    top = [{'id': uid, 'name': (names.get(uid) or [uid])[0], 'avatar': pictures.get(uid),
            'seconds': value[0], 'sessions': value[1], 'days': value[2],
            'first_seen': (names.get(uid) or [None, None])[1]} for uid, value in ranking]

    seconds = sum(v[0] for v in totals.values())
    sessions = sum(v[1] for v in totals.values())
    returning = sum(1 for v in totals.values() if v[2] >= 2)
    new_players = sum(1 for uid in totals if (names.get(uid) or [None, '0000'])[1] >= keys[0])
    script_players = sum(len(s['players']) for s in servers.values())

    # Serveurs en ligne : ceux qui envoient un battement, complétés par la liste publique de Roblox.
    public_servers = {s['id']: s for s in (public or {}).get('servers') or []}
    listed = []
    for job, server in sorted(servers.items(), key=lambda item: -len(item[1]['players'])):
        extra = public_servers.pop(job, {})
        listed.append({'id': job, 'playing': len(server['players']),
                       'max_players': server['max_players'] or extra.get('max_players') or 0,
                       'players': [{'id': uid, 'name': name} for uid, name in server['players'].items()],
                       'uptime': round(time.time() - server['started']), 'private': server['private'],
                       'studio': server['studio'], 'fps': extra.get('fps'), 'ping': extra.get('ping'),
                       'source': 'script'})
    for server in public_servers.values():
        listed.append(dict(server, players=[], uptime=None, private=False, studio=False, source='roblox'))

    peaks = [d['peak'] for d in daily]
    best = max(daily, key=lambda d: d['peak']) if daily and max(peaks) else None
    visits_period = sum(d['visits'] or 0 for d in daily)
    return {
        'id': game_id, 'name': game['name'], 'configured': bool(public),
        'public': {k: v for k, v in (public or {}).items() if k != 'servers'},
        # ReneStats est en temps réel ; le chiffre public de Roblox a plusieurs minutes de retard
        # et ne compte pas les tests dans Studio. On garde le plus grand des deux.
        'online': {'players': max(script_players, int((public or {}).get('playing') or 0)),
                   'roblox_players': int((public or {}).get('playing') or 0),
                   'script_players': script_players, 'servers': len(listed),
                   'private_servers': sum(1 for s in listed if s['private'])},
        'servers': listed[:60],
        'daily': daily,
        'period': {'unique': len(totals), 'new': new_players, 'returning': returning, 'sessions': sessions,
                   'hours': round(seconds / 3600, 1),
                   'avg_session_minutes': round(seconds / sessions / 60) if sessions else None,
                   'avg_daily_unique': round(sum(d['unique'] for d in daily) / days, 1),
                   'peak': best['peak'] if best else 0, 'peak_date': best['date'] if best else None,
                   'visits': visits_period, 'detail_days': min(days, PLAYER_DAYS_KEPT)},
        'top': top,
        'last_heartbeat': data.get('last_heartbeat'),
    }


async def build(days: int, game_id: str | None = None) -> dict:
    ids = [g for g in rewards.GAMES if not game_id or g == game_id]
    if not ids:
        raise ValueError('Jeu inconnu.')
    return {'days': days, 'items': [await build_game(g, days) for g in ids]}


def install_roblox_stats(app, run, guard) -> None:
    from flask import jsonify, request

    @app.post('/api/roblox/heartbeat')
    def roblox_heartbeat():
        refused = guard()
        if refused:
            return refused
        try:
            return jsonify(run(heartbeat(request.get_json(silent=True) or {})))
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
