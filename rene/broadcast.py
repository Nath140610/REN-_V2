"""MP à tous les membres (ou à un rôle), envoyés lentement en arrière-plan."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import discord

from rene import analytics, core

STORE_KEY = '_broadcasts'
DELAY_SECONDS = 1.5
current: dict | None = None
task: asyncio.Task | None = None


def history(guild_id: int) -> list[dict]:
    data = core.bot.config_data.setdefault(STORE_KEY, [])
    if not isinstance(data, list):
        data = []
        core.bot.config_data[STORE_KEY] = data
    return [item for item in data if str(item.get('guild_id')) == str(guild_id)][-10:][::-1]


def recipients(guild: discord.Guild, role_id: int | None) -> list[discord.Member]:
    role = guild.get_role(role_id) if role_id else None
    if role_id and role is None:
        raise ValueError('Rôle introuvable.')
    return [m for m in guild.members if not m.bot and (role is None or role in m.roles)]


def status(guild: discord.Guild) -> dict:
    running = current if current and str(current['guild_id']) == str(guild.id) else None
    return {'running': bool(running and running['state'] == 'running'), 'job': running,
            'humans': sum(1 for m in guild.members if not m.bot), 'history': history(guild.id),
            'delay': DELAY_SECONDS}


async def worker(guild: discord.Guild, members: list[discord.Member], text: str) -> None:
    global current
    job = current
    embed = core.build_embed(f'📬 Message de {guild.name}', text, core.COLOR_PRIMARY)
    try:
        for member in members:
            if job['cancel']:
                break
            if guild.get_member(member.id) is None:
                job['skipped'] += 1
            else:
                try:
                    await member.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                    job['sent'] += 1
                except (discord.Forbidden, discord.HTTPException):
                    job['failed'] += 1
            job['done'] += 1
            await asyncio.sleep(DELAY_SECONDS)
    except asyncio.CancelledError:
        job['cancel'] = True
        raise
    except Exception:
        core.logger.exception('Erreur pendant le MP à tous les membres')
        job['error'] = True
    finally:
        job['state'] = 'cancelled' if job['cancel'] else 'error' if job.get('error') else 'finished'
        job['finished_at'] = datetime.now(timezone.utc).isoformat()
        summary = {k: job[k] for k in ('id', 'guild_id', 'role_name', 'preview', 'total', 'sent', 'failed',
                                        'skipped', 'state', 'started_at', 'finished_at')}
        data = core.bot.config_data.setdefault(STORE_KEY, [])
        if isinstance(data, list):
            data.append(summary)
            core.bot.config_data[STORE_KEY] = data[-40:]
        analytics.audit(guild.id, 'dm', f'MP à tous : {job["sent"]} envoyés, {job["failed"]} refusés '
                                        f'({job["state"]}) — {job["preview"]}')
        core.save_runtime_json(core.CONFIG_FILE, core.bot.config_data)


async def start(guild: discord.Guild, text: str, role_id: int | None) -> dict:
    global current, task
    if current and current['state'] == 'running':
        raise ValueError('Un envoi est déjà en cours. Attends la fin ou arrête-le.')
    text = text.strip()
    if not 1 <= len(text) <= 1800:
        raise ValueError('Le message doit contenir entre 1 et 1 800 caractères.')
    members = recipients(guild, role_id)
    if not members:
        raise ValueError('Personne ne recevrait ce message.')
    role = guild.get_role(role_id) if role_id else None
    current = {
        'id': datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S'), 'guild_id': str(guild.id),
        'role_name': role.name if role else 'Tous les membres', 'preview': text[:80],
        'total': len(members), 'done': 0, 'sent': 0, 'failed': 0, 'skipped': 0,
        'state': 'running', 'cancel': False, 'started_at': datetime.now(timezone.utc).isoformat(),
    }
    task = asyncio.create_task(worker(guild, members, text), name='rene-broadcast')
    minutes = max(1, round(len(members) * DELAY_SECONDS / 60))
    return {'ok': True, 'message': f'Envoi lancé à {len(members)} membre(s). Environ {minutes} min.'}


async def cancel(guild: discord.Guild) -> dict:
    if not current or current['state'] != 'running' or str(current['guild_id']) != str(guild.id):
        raise ValueError('Aucun envoi en cours.')
    current['cancel'] = True
    return {'ok': True, 'message': 'Envoi arrêté après le message en cours.'}
