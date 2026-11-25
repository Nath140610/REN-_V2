"""Statistiques détaillées du panel, calculées à partir des données déjà enregistrées par René."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord

from rene import analytics, core, polls
from rene.commands import rdvexpress
from rene.commands import rendevous as rdv
from rene.commands import sendgiftcode as gifts

WEEKDAYS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']


def parse(raw) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def in_range(raw, start: datetime, end: datetime) -> bool:
    value = parse(raw)
    return value is not None and start <= value < end


def change(current: float, previous: float | None):
    """Évolution en % par rapport à la période précédente (None si inconnue)."""
    if previous is None:
        return None
    if previous == 0:
        return None if current == 0 else 100
    return round((current - previous) / previous * 100)


def window(guild_id: int, start_offset: int, days: int) -> dict:
    """Totaux de `days` jours, en commençant `start_offset` jours avant aujourd'hui."""
    data = analytics.store(guild_id)['days']
    today = analytics.now().date()
    totals = {'messages': 0, 'joins': 0, 'leaves': 0, 'voice_seconds': 0}
    daily, users = [], {}
    for offset in reversed(range(start_offset, start_offset + days)):
        key = (today - timedelta(days=offset)).isoformat()
        bucket = data.get(key, {})
        row = {'date': key, **{k: bucket.get(k, 0) for k in totals}}
        daily.append(row)
        for k in totals:
            totals[k] += row[k]
        for uid, values in bucket.get('users', {}).items():
            user = users.setdefault(uid, {'messages': 0, 'voice_seconds': 0, 'days': 0})
            user['messages'] += values.get('messages', 0)
            user['voice_seconds'] += values.get('voice_seconds', 0)
            user['days'] += 1
    return {'totals': totals, 'daily': daily, 'users': users}


def tracked_days(guild_id: int) -> int:
    since = parse(analytics.store(guild_id).get('since'))
    return (analytics.now().date() - since.date()).days + 1 if since else 0


def member_brief(guild: discord.Guild, uid: str, value: float, label: str) -> dict | None:
    member = guild.get_member(int(uid))
    if member is None or member.bot:
        return None
    return {'id': uid, 'name': member.display_name, 'avatar': str(member.display_avatar.url),
            'value': value, 'label': label}


async def build(guild: discord.Guild, days: int) -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    previous_start = start - timedelta(days=days)
    current = window(guild.id, 0, days)
    tracked = tracked_days(guild.id)
    has_previous = days * 2 <= 90 and tracked >= days * 2
    previous = window(guild.id, days, days) if has_previous else None

    humans = [m for m in guild.members if not m.bot]
    active_ids = {uid for uid, u in current['users'].items()
                  if guild.get_member(int(uid)) and (u['messages'] or u['voice_seconds'])}
    previous_active = (len({uid for uid, u in previous['users'].items() if u['messages'] or u['voice_seconds']})
                       if previous else None)
    t, p = current['totals'], previous['totals'] if previous else None

    busiest = max(current['daily'], key=lambda d: d['messages']) if current['daily'] else None
    weekday_sum, weekday_count = [0] * 7, [0] * 7
    for row in current['daily']:
        index = datetime.fromisoformat(row['date']).weekday()
        weekday_sum[index] += row['messages']
        weekday_count[index] += 1
    weekdays = [{'day': WEEKDAYS[i], 'messages': round(weekday_sum[i] / weekday_count[i]) if weekday_count[i] else 0}
                for i in range(7)]

    top_messages = sorted(current['users'].items(), key=lambda item: item[1]['messages'], reverse=True)
    top_voice = sorted(current['users'].items(), key=lambda item: item[1]['voice_seconds'], reverse=True)
    top_chat = [x for x in (member_brief(guild, uid, u['messages'], 'messages')
                            for uid, u in top_messages if u['messages']) if x][:5]
    top_talk = [x for x in (member_brief(guild, uid, round(u['voice_seconds']), 'vocal')
                            for uid, u in top_voice if u['voice_seconds']) if x][:5]

    # Modération
    cases = core.bot.moderation_cases.get(str(guild.id), [])
    period_cases = [c for c in cases if isinstance(c, dict) and in_range(c.get('created_at'), start, now)]
    previous_cases = [c for c in cases if isinstance(c, dict) and in_range(c.get('created_at'), previous_start, start)]
    warnings = [c for c in period_cases if c.get('type') == 'Avertissement']
    reasons = {'Langage': 0, 'Publicité': 0, 'Manuel / panel': 0}
    for case in warnings:
        reason = str(case.get('reason', ''))
        if reason.startswith('Langage'):
            reasons['Langage'] += 1
        elif reason.startswith('Publicité'):
            reasons['Publicité'] += 1
        else:
            reasons['Manuel / panel'] += 1
    bans = [c for c in period_cases if 'Bannissement' in str(c.get('type', ''))]
    warned_now = sum(1 for count in core.bot.warning_data.get(str(guild.id), {}).values() if int(count or 0) > 0)

    # Tickets
    questions = [q for q in core.bot.questions.get(str(guild.id), {}).values() if isinstance(q, dict)]
    received = [q for q in questions if in_range(q.get('created_at'), start, now)]
    answered = [q for q in received if q.get('answered') and not q.get('closed')]
    delays = []
    for q in answered:
        created, done = parse(q.get('created_at')), parse(q.get('answered_at'))
        if created and done and done >= created:
            delays.append((done - created).total_seconds())
    bot_id = core.bot.user.id if core.bot.user else None
    by_rene = sum(1 for q in answered if bot_id and q.get('answered_by') == bot_id)

    # Cartes cadeau et Roblox
    codes = [e for e in gifts.gift_store().values() if isinstance(e, dict) and str(e.get('guild_id')) == str(guild.id)]
    created_codes = [e for e in codes if in_range(e.get('created_at'), start, now) and not e.get('replaced_by')]
    cards = [e for e in created_codes if e.get('card_token')]
    opened = [e for e in cards if e.get('opened_at')]
    scratched = [e for e in cards if e.get('scratched_at')]
    used = [e for e in codes if in_range(e.get('used_at'), start, now)]
    expired_unused = [e for e in codes if gifts.card_status(e, now) == 'expired']
    scratch_delays = []
    for e in scratched:
        sent_at, scratched_at = parse(e.get('card_sent_at') or e.get('created_at')), parse(e.get('scratched_at'))
        if sent_at and scratched_at and scratched_at >= sent_at:
            scratch_delays.append((scratched_at - sent_at).total_seconds())
    assisted = [e for e in codes if e.get('source') == 'assistance' and in_range(e.get('created_at'), start, now)]

    # Sondages et rendez-vous
    guild_polls = [e for e in polls.store().values() if isinstance(e, dict)
                   and str(e.get('guild_id')) == str(guild.id) and in_range(e.get('created_at'), start, now)]
    appointments = [e for e in list(rdv.get_store().values()) + list(rdvexpress.store().values())
                    if isinstance(e, dict) and str(e.get('guild_id')) == str(guild.id)
                    and in_range(e.get('created_at'), start, now)]
    accepted = [e for e in appointments if str(e.get('status', '')).startswith('accepted') or e.get('status') == 'no_show']
    no_show = [e for e in appointments if e.get('status') == 'no_show']

    def rate(part, whole):
        return round(part / whole * 100) if whole else None

    def avg(values):
        return round(sum(values) / len(values)) if values else None

    return {
        'days': days, 'tracked_days': tracked, 'since': analytics.store(guild.id).get('since'),
        'has_previous': has_previous,
        'community': {
            'members': guild.member_count or len(guild.members), 'humans': len(humans),
            'bots': sum(1 for m in guild.members if m.bot),
            'online': sum(1 for m in humans if m.status != discord.Status.offline),
            'joins': t['joins'], 'joins_change': change(t['joins'], p and p['joins']),
            'leaves': t['leaves'], 'leaves_change': change(t['leaves'], p and p['leaves']),
            'net': t['joins'] - t['leaves'],
        },
        'activity': {
            'messages': t['messages'], 'messages_change': change(t['messages'], p and p['messages']),
            'per_day': round(t['messages'] / days, 1),
            'active': len(active_ids), 'active_change': change(len(active_ids), previous_active),
            'active_rate': rate(len(active_ids), len(humans)),
            'voice_hours': round(t['voice_seconds'] / 3600, 1),
            'voice_change': change(t['voice_seconds'], p and p['voice_seconds']),
            'voice_per_active_min': round(t['voice_seconds'] / 60 / len(active_ids)) if active_ids else 0,
            'busiest': busiest if busiest and busiest['messages'] else None,
            'weekdays': weekdays,
        },
        'daily': current['daily'],
        'top_messages': top_chat, 'top_voice': top_talk,
        'moderation': {
            'warnings': len(warnings),
            'warnings_change': change(len(warnings), len([c for c in previous_cases if c.get('type') == 'Avertissement'])
                                      if has_previous else None),
            'reasons': reasons, 'bans': len(bans),
            'tempbans_now': len(core.bot.temporary_bans.get(str(guild.id), {})),
            'members_with_warnings': warned_now,
        },
        'tickets': {
            'received': len(received), 'answered': len(answered),
            'open': sum(1 for q in questions if not q.get('answered')),
            'avg_response_seconds': avg(delays), 'by_rene': by_rene,
        },
        'gifts': {
            'cards': len(cards), 'opened': len(opened), 'scratched': len(scratched), 'used': len(used),
            'open_rate': rate(len(opened), len(cards)), 'scratch_rate': rate(len(scratched), len(cards)),
            'use_rate': rate(len([e for e in scratched if e.get('used_at')]), len(scratched)),
            'expired_unused': len(expired_unused), 'avg_scratch_seconds': avg(scratch_delays),
            'assistance': len(assisted),
        },
        'polls': {'count': len(guild_polls), 'votes': sum(int(e.get('total') or 0) for e in guild_polls)},
        'appointments': {'count': len(appointments), 'accepted': len(accepted), 'no_show': len(no_show),
                         'no_show_rate': rate(len(no_show), len(accepted))},
    }
