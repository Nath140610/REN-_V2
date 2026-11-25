"""API appelée par les serveurs Roblox pour vérifier et consommer un code cadeau.

Statuts renvoyés (champ ``status``) :
  inactive  : carte envoyée mais pas encore grattée, le code n'est pas encore activé
  available : code activé (gratté) et encore valable, ou ancien code pas encore remplacé
  used      : déjà utilisé dans Roblox
  expired   : gratté il y a plus de 24 h
  replaced  : ancien code remplacé par une carte
  unknown   : code inexistant
"""
from __future__ import annotations

import hmac
import os
import re
import secrets
import time
from datetime import datetime, timezone

from flask import jsonify, request

from rene import analytics, core
from rene.commands import sendgiftcode as gifts

KEY_STORE = '_roblox_api_key'
CODE_PATTERN = re.compile(r'^VOID-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$')
LABELS = {
    'inactive': 'Pas encore activé : la carte n’a pas été grattée.',
    'available': 'Disponible : le code peut être utilisé.',
    'used': 'Déjà utilisé.',
    'expired': 'Expiré : plus de 24 h après le grattage.',
    'replaced': 'Remplacé par une nouvelle carte.',
    'unknown': 'Code inconnu.',
}
failures: dict[str, list[float]] = {}


def api_key() -> str:
    return (os.getenv('ROBLOX_API_KEY') or str(core.bot.config_data.get(KEY_STORE) or '')).strip()


def key_from_env() -> bool:
    return bool(os.getenv('ROBLOX_API_KEY', '').strip())


def regenerate_key() -> str:
    key = 'rene_' + secrets.token_urlsafe(32)
    core.bot.config_data[KEY_STORE] = key
    return key


def normalize(raw) -> str:
    text = re.sub(r'[^A-Za-z0-9]', '', str(raw or '')).upper()
    if len(text) == 16 and text.startswith('VOID'):
        return f'{text[:4]}-{text[4:8]}-{text[8:12]}-{text[12:]}'
    return str(raw or '').strip().upper()


def roblox_status(entry: dict | None, now: datetime | None = None) -> str:
    if not isinstance(entry, dict):
        return 'unknown'
    card = gifts.card_status(entry, now)
    return {'legacy': 'available', 'scratched': 'available', 'sent': 'inactive', 'opened': 'inactive',
            'dm_failed': 'inactive'}.get(card, card)


def describe(code: str, entry: dict | None) -> dict:
    now = datetime.now(timezone.utc)
    status = roblox_status(entry, now)
    result = {'code': code, 'status': status, 'label': LABELS[status],
              'activated': status in {'available', 'used', 'expired'},
              'available': status == 'available', 'used': status == 'used'}
    if not entry:
        return result
    expires = gifts.parse_utc(entry.get('expires_at'))
    linked = core.bot.roblox_links.get(str(entry.get('guild_id')), {}).get(str(entry.get('recipient_id')))
    result.update({
        'remaining_seconds': max(0, int((expires - now).total_seconds())) if expires else None,
        'expires_at': entry.get('expires_at'), 'scratched_at': entry.get('scratched_at'),
        'recipient_discord_id': str(entry.get('recipient_id') or ''),
        'recipient_roblox_name': linked,
        'used_at': entry.get('used_at'), 'used_by_roblox_id': entry.get('used_by_roblox_id'),
        'used_by_roblox_name': entry.get('used_by_roblox_name'),
    })
    return result


async def check_code(code: str) -> dict:
    return describe(code, gifts.gift_store().get(code))


async def redeem_code(code: str, roblox_id: str, roblox_name: str, place_id: str) -> tuple[dict, bool]:
    # Exécuté sur la boucle du bot : deux serveurs Roblox ne peuvent pas consommer le même code.
    entry = gifts.gift_store().get(code)
    if roblox_status(entry) != 'available':
        return describe(code, entry), False
    now = datetime.now(timezone.utc).isoformat()
    entry.update({'used_at': now, 'used_by_roblox_id': roblox_id, 'used_by_roblox_name': roblox_name,
                  'used_place_id': place_id})
    try:
        analytics.audit(int(entry['guild_id']), 'gift',
                        f'Code {code} utilisé dans Roblox par {roblox_name or roblox_id}')
    except Exception:
        core.logger.exception('Audit Roblox impossible')
    await core.save_state_immediately()
    core.logger.info('ROBLOX : code %s utilisé par %s (%s).', code, roblox_name, roblox_id)
    return describe(code, entry), True


def install_roblox_api(app, run) -> None:
    def authorized() -> bool:
        address = request.remote_addr or 'unknown'
        now = time.monotonic()
        recent = [t for t in failures.get(address, []) if now - t < 600]
        failures[address] = recent
        if len(recent) >= 20:
            return False
        key = api_key()
        given = request.headers.get('X-Rene-Key', '')
        if key and given and hmac.compare_digest(given, key):
            return True
        failures[address] = recent + [now]
        return False

    def guard():
        if not api_key():
            return jsonify({'error': 'Clé Roblox non configurée dans le panel.'}), 503
        if not authorized():
            return jsonify({'error': 'Clé Roblox invalide.'}), 401
        return None

    @app.get('/api/roblox/code/<path:raw>')
    def roblox_check(raw):
        refused = guard()
        if refused:
            return refused
        code = normalize(raw)
        if not CODE_PATTERN.match(code):
            return jsonify(describe(code, None))
        return jsonify(run(check_code(code)))

    @app.post('/api/roblox/redeem')
    def roblox_redeem():
        refused = guard()
        if refused:
            return refused
        data = request.get_json(silent=True) or {}
        code = normalize(data.get('code'))
        roblox_id = str(data.get('roblox_user_id', '')).strip()[:20]
        roblox_name = str(data.get('roblox_username', '')).strip()[:40]
        if not roblox_id.isdigit():
            return jsonify({'error': 'roblox_user_id manquant.'}), 400
        if not CODE_PATTERN.match(code):
            return jsonify(dict(describe(code, None), redeemed=False)), 404
        result, redeemed = run(redeem_code(code, roblox_id, roblox_name, (str(data.get('place_id', '')) or request.headers.get('Roblox-Id', ''))[:20]))
        return jsonify(dict(result, redeemed=redeemed)), 200 if redeemed else 409
