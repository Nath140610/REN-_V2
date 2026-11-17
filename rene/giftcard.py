"""Carte cadeau à gratter : page publique, un lien secret par code."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from flask import abort, jsonify, render_template, request

from rene import core
from rene.commands import sendgiftcode as gifts

TOKEN_PATTERN = re.compile(r'^[A-Za-z0-9_-]{20,64}$')
misses: dict[str, list[float]] = {}


def too_many_misses(address: str) -> bool:
    now = time.monotonic()
    recent = [t for t in misses.get(address, []) if now - t < 600]
    misses[address] = recent
    return len(recent) >= 30


def note_miss(address: str) -> None:
    misses.setdefault(address, []).append(time.monotonic())


def public_state(entry: dict) -> dict:
    now = datetime.now(timezone.utc)
    status = gifts.card_status(entry, now)
    guild = core.bot.get_guild(int(entry.get('guild_id') or 0))
    member = guild.get_member(int(entry.get('recipient_id') or 0)) if guild else None
    expires = gifts.parse_utc(entry.get('expires_at'))
    state = {
        'status': status,
        'recipient': member.display_name if member else str(entry.get('recipient_name', '')).split('#')[0],
        'guild': guild.name if guild else "VoidLoop's Studio",
        'reason': entry.get('reason', ''),
        'scratched': expires is not None,
        'remaining': max(0, int((expires - now).total_seconds())) if expires else None,
        'lifetime': int(gifts.CARD_LIFETIME.total_seconds()),
    }
    if status == 'scratched':
        state['code'] = entry['code']
    return state


async def open_card(token: str) -> dict | None:
    entry = gifts.find_card(token)
    if entry is None or entry.get('replaced_by'):
        return None
    now = datetime.now(timezone.utc).isoformat()
    entry.setdefault('opened_at', now)
    entry['last_seen_at'] = now
    entry['views'] = int(entry.get('views', 0)) + 1
    core.save_runtime_json(core.CONFIG_FILE, core.bot.config_data)
    return public_state(entry)


async def scratch_card(token: str) -> dict | None:
    entry = gifts.find_card(token)
    if entry is None or entry.get('replaced_by'):
        return None
    if not entry.get('expires_at'):
        now = datetime.now(timezone.utc)
        entry.setdefault('opened_at', now.isoformat())
        entry['scratched_at'] = now.isoformat()
        entry['expires_at'] = (now + gifts.CARD_LIFETIME).isoformat()
        await core.save_state_immediately()
        core.logger.info('GIFTCARD : carte grattée pour %s.', entry.get('recipient_id'))
    return public_state(entry)


def install_giftcard(app, run) -> None:
    def call(token: str, action):
        address = request.remote_addr or 'unknown'
        if too_many_misses(address):
            return jsonify({'error': 'Trop d’essais. Réessaie plus tard.'}), 429
        if not TOKEN_PATTERN.match(token):
            note_miss(address)
            return jsonify({'error': 'Cette carte n’existe pas.'}), 404
        result = run(action(token))
        if result is None:
            note_miss(address)
            return jsonify({'error': 'Cette carte n’existe pas ou a été remplacée.'}), 404
        return jsonify(result)

    @app.get('/cadeau/<token>')
    def gift_page(token):
        if not TOKEN_PATTERN.match(token):
            abort(404)
        return render_template('gift.html')

    @app.get('/api/cadeau/<token>')
    def gift_state(token):
        return call(token, open_card)

    @app.post('/api/cadeau/<token>/scratch')
    def gift_scratch(token):
        if request.mimetype != 'application/json':
            abort(415, 'JSON requis.')
        return call(token, scratch_card)
