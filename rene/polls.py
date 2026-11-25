"""Sondages Discord natifs publiés par René depuis le panel."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import discord

from rene import analytics, core

STORE_KEY = '_polls'
CACHE_SECONDS = 4
MAX_ANSWERS = 10
cache: dict[str, tuple[float, dict]] = {}


def store() -> dict[str, dict]:
    data = core.bot.config_data.setdefault(STORE_KEY, {})
    if not isinstance(data, dict):
        data = {}
        core.bot.config_data[STORE_KEY] = data
    return data


def clean_answers(raw) -> list[str]:
    answers = []
    for item in raw if isinstance(raw, list) else []:
        text = str(item).strip()[:55]
        if text and text.casefold() not in {a.casefold() for a in answers}:
            answers.append(text)
    return answers[:MAX_ANSWERS]


async def create_poll(guild: discord.Guild, channel_id: int, question: str, answers: list[str],
                      hours: int, multiple: bool) -> dict:
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise ValueError('Choisis un salon textuel.')
    me = guild.me
    permissions = channel.permissions_for(me) if me else None
    if permissions is None or not permissions.send_messages or not getattr(permissions, 'send_polls', True):
        raise ValueError('René ne peut pas publier de sondage dans ce salon.')
    question = question.strip()[:300]
    if len(question) < 3:
        raise ValueError('Écris une question.')
    if len(answers) < 2:
        raise ValueError('Ajoute au moins deux réponses différentes.')
    if not 1 <= hours <= 768:
        raise ValueError('Durée entre 1 heure et 32 jours.')

    poll = discord.Poll(question=question, duration=timedelta(hours=hours), multiple=multiple)
    for answer in answers:
        poll.add_answer(text=answer)
    message = await channel.send(content='📊 **Sondage de René**', poll=poll,
                                 allowed_mentions=discord.AllowedMentions.none())

    poll_id = uuid.uuid4().hex[:10].upper()
    now = datetime.now(timezone.utc)
    store()[poll_id] = {
        'id': poll_id, 'guild_id': guild.id, 'channel_id': channel.id, 'channel_name': channel.name,
        'message_id': message.id, 'question': question, 'answers': answers, 'multiple': multiple,
        'created_at': now.isoformat(), 'expires_at': (now + timedelta(hours=hours)).isoformat(),
        'results': [0] * len(answers), 'total': 0, 'finished': False,
    }
    # On garde les 60 sondages les plus récents.
    for old_id in sorted(store(), key=lambda key: store()[key].get('created_at', ''))[:-60]:
        store().pop(old_id, None)
    analytics.audit(guild.id, 'poll', f'Sondage publié dans #{channel.name} : {question}')
    await core.save_state_immediately()
    return {'ok': True, 'id': poll_id, 'message': f'Sondage publié dans #{channel.name}.'}


async def refresh(entry: dict, force: bool = False) -> dict:
    """Relit les votes sur Discord (au plus toutes les quatre secondes par sondage)."""
    if entry.get('finished') and not force:
        return entry
    cached = cache.get(entry['id'])
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS and not force:
        return cached[1]
    guild = core.bot.get_guild(int(entry['guild_id']))
    channel = guild.get_channel(int(entry['channel_id'])) if guild else None
    if not isinstance(channel, discord.TextChannel):
        return entry
    try:
        message = await channel.fetch_message(int(entry['message_id']))
    except discord.NotFound:
        entry['finished'] = True
        entry['deleted'] = True
        return entry
    except discord.HTTPException:
        return entry
    poll = message.poll
    if poll is not None:
        counts = {answer.text: answer.vote_count for answer in poll.answers}
        entry['results'] = [counts.get(text, 0) for text in entry['answers']]
        entry['total'] = poll.total_votes
        entry['finished'] = poll.is_finalised() or (
            poll.expires_at is not None and poll.expires_at <= datetime.now(timezone.utc))
    cache[entry['id']] = (time.monotonic(), entry)
    return entry


async def list_polls(guild: discord.Guild) -> dict:
    entries = [entry for entry in store().values()
               if isinstance(entry, dict) and str(entry.get('guild_id')) == str(guild.id)]
    entries.sort(key=lambda entry: entry.get('created_at', ''), reverse=True)
    changed = False
    for entry in entries[:12]:
        was_finished = entry.get('finished')
        await refresh(entry)
        changed |= entry.get('finished') != was_finished
    if changed:
        core.save_runtime_json(core.CONFIG_FILE, core.bot.config_data)
    return {'items': entries[:30]}


async def end_poll(guild: discord.Guild, poll_id: str) -> dict:
    entry = store().get(poll_id)
    if not isinstance(entry, dict) or str(entry.get('guild_id')) != str(guild.id):
        raise ValueError('Sondage introuvable.')
    if entry.get('finished'):
        raise ValueError('Ce sondage est déjà terminé.')
    channel = guild.get_channel(int(entry['channel_id']))
    if not isinstance(channel, discord.TextChannel):
        raise ValueError('Le salon du sondage n’existe plus.')
    message = await channel.fetch_message(int(entry['message_id']))
    await message.end_poll()
    entry['finished'] = True
    entry['ended_early'] = True
    cache.pop(poll_id, None)
    await refresh(entry, force=True)
    entry['finished'] = True
    analytics.audit(guild.id, 'poll', f'Sondage terminé : {entry["question"]}')
    await core.save_state_immediately()
    return {'ok': True, 'message': 'Sondage terminé.'}
