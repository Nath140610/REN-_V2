"""Compteurs agrégés, sans contenu des messages ; accès sur la boucle Discord."""
from datetime import datetime, timedelta, timezone

from rene import core


def now():
    return datetime.now(timezone.utc)


def store(guild_id):
    return core.bot.config_data.setdefault('_panel_stats', {}).setdefault(str(guild_id), {
        'since': now().isoformat(), 'days': {}, 'audit': [],
    })


def day(guild_id, at=None):
    data = store(guild_id)
    at = at or now()
    cutoff = (now() - timedelta(days=89)).date().isoformat()
    for key in list(data['days']):
        if key < cutoff:
            del data['days'][key]
    return data['days'].setdefault(at.date().isoformat(), {
        'messages': 0, 'joins': 0, 'leaves': 0, 'voice_seconds': 0, 'users': {},
    })


def record(guild_id, kind, member_id=None, amount=1, at=None):
    bucket = day(guild_id, at)
    bucket[kind] += amount
    if member_id is not None and kind in ('messages', 'voice_seconds'):
        user = bucket['users'].setdefault(str(member_id), {'messages': 0, 'voice_seconds': 0})
        user[kind] += amount


def voice_interval(guild_id, member_id, start, end):
    while start < end:
        midnight = (start + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        stop = min(end, midnight)
        record(guild_id, 'voice_seconds', member_id, (stop - start).total_seconds(), start)
        start = stop


def summary(guild_id, days=30):
    data = store(guild_id)
    daily, users = [], {}
    for offset in reversed(range(days)):
        date = (now() - timedelta(days=offset)).date().isoformat()
        bucket = data['days'].get(date, {})
        daily.append({'date': date, **{k: bucket.get(k, 0) for k in ('messages', 'joins', 'leaves', 'voice_seconds')}})
        for uid, values in bucket.get('users', {}).items():
            total = users.setdefault(uid, {'messages': 0, 'voice_seconds': 0, 'active_days': 0})
            total['messages'] += values['messages']
            total['voice_seconds'] += values['voice_seconds']
            total['active_days'] += 1
    return {'since': data['since'], 'daily': daily, 'users': users,
            'totals': {k: sum(d[k] for d in daily) for k in ('messages', 'joins', 'leaves', 'voice_seconds')}}


def audit(guild_id, action, detail):
    data = store(guild_id)
    data['audit'].append({'at': now().isoformat(), 'action': action, 'detail': detail, 'actor': 'Administrateur du panel'})
    data['audit'] = data['audit'][-200:]
    core.save_runtime_json(core.CONFIG_FILE, core.bot.config_data)
