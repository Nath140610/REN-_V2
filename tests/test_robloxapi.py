import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from rene import core, robloxapi
from rene.commands import sendgiftcode as gifts
from rene.panel import install_panel

KEY = 'rene_cle-de-test'


def future(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class RobloxApiTest(unittest.TestCase):
    def setUp(self):
        self.store = {
            'VOID-AAAA-AAAA-AAAA': {'code': 'VOID-AAAA-AAAA-AAAA', 'guild_id': 1, 'recipient_id': 2,
                                    'card_token': 't' * 32, 'delivery_status': 'delivered'},
            'VOID-BBBB-BBBB-BBBB': {'code': 'VOID-BBBB-BBBB-BBBB', 'guild_id': 1, 'recipient_id': 2,
                                    'card_token': 'u' * 32, 'scratched_at': future(-1), 'expires_at': future(23),
                                    'reward': {'game': 'christmasrun', 'type': 'glings', 'glings': 500, 'gamepass': False, 'label': 'ChristmasRun · 500 glings'}},
            'VOID-EEEE-EEEE-EEEE': {'code': 'VOID-EEEE-EEEE-EEEE', 'guild_id': 1, 'recipient_id': 2,
                                    'card_token': 'w' * 32, 'scratched_at': future(-1), 'expires_at': future(23)},
            'VOID-CCCC-CCCC-CCCC': {'code': 'VOID-CCCC-CCCC-CCCC', 'guild_id': 1, 'recipient_id': 2,
                                    'card_token': 'v' * 32, 'scratched_at': future(-30), 'expires_at': future(-6)},
            'VOID-DDDD-DDDD-DDDD': {'code': 'VOID-DDDD-DDDD-DDDD', 'guild_id': 1, 'recipient_id': 2,
                                    'replaced_by': 'VOID-AAAA-AAAA-AAAA'},
        }
        self.patches = [
            patch.dict(os.environ, {'PANEL_PASSWORD': 'pw', 'PANEL_SECRET': 'x' * 48,
                                    'PANEL_INSECURE_LOCAL': '1', 'ROBLOX_API_KEY': KEY}),
            patch.object(gifts, 'gift_store', return_value=self.store),
            patch.object(core, 'save_state_immediately', new_callable=AsyncMock),
            patch.object(core.bot, 'roblox_links', {'1': {'2': 'LeaRoblox'}}),
            patch.object(robloxapi.analytics, 'audit'),
            patch('rene.panel.run', side_effect=lambda coro, *a: asyncio.run(coro)),
        ]
        for item in self.patches:
            item.start()
        robloxapi.failures.clear()
        install_panel(core.web_app)
        self.client = core.web_app.test_client()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def check(self, code, key=KEY):
        return self.client.get(f'/api/roblox/code/{code}', headers={'X-Rene-Key': key})

    def test_key_is_required(self):
        self.assertEqual(self.client.get('/api/roblox/code/VOID-AAAA-AAAA-AAAA').status_code, 401)
        self.assertEqual(self.check('VOID-AAAA-AAAA-AAAA', 'mauvaise').status_code, 401)

    def test_statuses(self):
        self.assertEqual(self.check('VOID-AAAA-AAAA-AAAA').json['status'], 'inactive')
        available = self.check('voidbbbbbbbbbbbb').json
        self.assertEqual(available['status'], 'available')
        self.assertTrue(available['activated'])
        self.assertEqual(available['recipient_roblox_name'], 'LeaRoblox')
        self.assertEqual(available['reward']['glings'], 500)
        self.assertEqual(available['game'], 'christmasrun')
        self.assertEqual(self.check('VOID-EEEE-EEEE-EEEE').json['status'], 'no_reward')
        self.assertFalse(self.check('VOID-EEEE-EEEE-EEEE').json['available'])
        wrong = self.client.get('/api/roblox/code/VOID-BBBB-BBBB-BBBB?game=PointNemo', headers={'X-Rene-Key': KEY})
        self.assertEqual(wrong.json['status'], 'wrong_game')
        right = self.client.get('/api/roblox/code/VOID-BBBB-BBBB-BBBB?game=christmasrun', headers={'X-Rene-Key': KEY})
        self.assertEqual(right.json['status'], 'available')
        self.assertEqual(self.check('VOID-CCCC-CCCC-CCCC').json['status'], 'expired')
        self.assertEqual(self.check('VOID-DDDD-DDDD-DDDD').json['status'], 'replaced')
        self.assertEqual(self.check('VOID-ZZZZ-ZZZZ-ZZZZ').json['status'], 'unknown')

    def test_code_can_only_be_redeemed_once(self):
        other_game = {'code': 'VOID-BBBB-BBBB-BBBB', 'roblox_user_id': '123', 'game': 'pointnemo'}
        self.assertEqual(self.client.post('/api/roblox/redeem', json=other_game, headers={'X-Rene-Key': KEY}).status_code, 409)
        no_reward = {'code': 'VOID-EEEE-EEEE-EEEE', 'roblox_user_id': '123', 'game': 'christmasrun'}
        self.assertEqual(self.client.post('/api/roblox/redeem', json=no_reward, headers={'X-Rene-Key': KEY}).status_code, 409)
        body = {'code': 'VOID-BBBB-BBBB-BBBB', 'roblox_user_id': '123', 'roblox_username': 'Lea', 'place_id': '99',
                'game': 'christmasrun'}
        first = self.client.post('/api/roblox/redeem', json=body, headers={'X-Rene-Key': KEY})
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json['redeemed'])
        second = self.client.post('/api/roblox/redeem', json=body, headers={'X-Rene-Key': KEY})
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json['status'], 'used')
        self.assertEqual(self.store['VOID-BBBB-BBBB-BBBB']['used_by_roblox_name'], 'Lea')
        self.assertEqual(self.store['VOID-BBBB-BBBB-BBBB']['used_place_id'], '99')
        inactive = dict(body, code='VOID-AAAA-AAAA-AAAA')
        self.assertEqual(self.client.post('/api/roblox/redeem', json=inactive,
                                          headers={'X-Rene-Key': KEY}).status_code, 409)


if __name__ == '__main__':
    unittest.main()
