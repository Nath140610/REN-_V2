"""Catalogue des gains par jeu. Seule source de vérité pour le panel, l'assistance, Discord et Roblox."""
from __future__ import annotations

MAX_AMOUNT = 1_000_000

GAMES = {
    'pointnemo': {
        'name': 'PointNemo',
        'rewards': {
            'gamepass_random': {'label': '1 gamepass au hasard', 'gamepass': True, 'amounts': []},
            'raft_extension': {'label': 'Une extension de radeau', 'gamepass': False, 'amounts': []},
            'server_slot': {'label': 'Un emplacement de serveur en plus', 'gamepass': False, 'amounts': []},
        },
    },
    'christmasrun': {
        'name': 'ChristmasRun',
        'rewards': {
            'glings': {'label': 'Des glings', 'gamepass': False, 'amounts': ['glings']},
            'gifts': {'label': 'Des cadeaux', 'gamepass': False, 'amounts': ['gifts']},
            'glings_gifts': {'label': 'Des glings et des cadeaux', 'gamepass': False, 'amounts': ['glings', 'gifts']},
            'gamepass_random': {'label': '1 gamepass au hasard', 'gamepass': True, 'amounts': []},
        },
    },
}
AMOUNT_NAMES = {'glings': 'glings', 'gifts': 'cadeaux'}


def catalog(allow_gamepass: bool = True) -> list[dict]:
    """Catalogue envoyé aux interfaces."""
    return [{'id': game_id, 'name': game['name'],
             'rewards': [{'id': reward_id, 'label': reward['label'], 'gamepass': reward['gamepass'],
                          'amounts': reward['amounts']}
                         for reward_id, reward in game['rewards'].items()
                         if allow_gamepass or not reward['gamepass']]}
            for game_id, game in GAMES.items()]


def describe(reward: dict) -> str:
    game = GAMES.get(reward.get('game'), {})
    definition = game.get('rewards', {}).get(reward.get('type'), {})
    if definition.get('amounts'):
        what = ' et '.join(f'{reward.get(key, 0):,} {AMOUNT_NAMES[key]}'.replace(',', ' ')
                           for key in definition['amounts'])
    else:
        what = definition.get('label', reward.get('type', '?'))
    return f'{game.get("name", reward.get("game", "?"))} · {what}'


def clean(raw, allow_gamepass: bool = True) -> dict:
    """Valide un gain venu d'un formulaire ; lève ValueError avec un message clair."""
    if not isinstance(raw, dict):
        raise ValueError('Choisis le jeu et le gain.')
    game_id = str(raw.get('game', '')).strip().lower()
    game = GAMES.get(game_id)
    if game is None:
        raise ValueError('Choisis le jeu du cadeau.')
    reward_id = str(raw.get('type', '')).strip()
    definition = game['rewards'].get(reward_id)
    if definition is None:
        raise ValueError(f'Choisis ce que le cadeau donne dans {game["name"]}.')
    if definition['gamepass'] and not allow_gamepass:
        raise ValueError('L’assistance ne peut pas donner de gamepass.')
    reward = {'game': game_id, 'type': reward_id, 'gamepass': definition['gamepass']}
    for key in definition['amounts']:
        try:
            amount = int(raw.get(key))
        except (TypeError, ValueError):
            raise ValueError(f'Indique le nombre de {AMOUNT_NAMES[key]}.') from None
        if not 1 <= amount <= MAX_AMOUNT:
            raise ValueError(f'Le nombre de {AMOUNT_NAMES[key]} doit être entre 1 et 1 000 000.')
        reward[key] = amount
    reward['label'] = describe(reward)
    return reward


def public(reward: dict | None) -> dict | None:
    """Ce que Roblox reçoit."""
    if not isinstance(reward, dict):
        return None
    return {key: reward.get(key) for key in ('game', 'type', 'glings', 'gifts', 'gamepass', 'label')
            if reward.get(key) is not None}
