import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from rene import core, robloxapi, robloxstats
from rene.panel import install_panel

KEY = 'rene_cle-de-test'
PUBLIC = {'place_id': '111', 'universe_id': '222', 'error': None, 'name': 'ChristmasRun', 'playing': 7,
          'visits': 1500, 'favorites': 40, 'max_players': 20, 'likes': 90, 'dislikes': 10, 'like_rate': 90,
          'servers': [{'id': 'job-a', 'playing': 2, 'max_players': 20, 'fps': 60, 'ping': 80},
                      {'id': 'job-z', 'playing': 5, 'max_players': 20, 'fps': 59, 'ping': 95}]}


class RobloxStatsTest(unittest.TestCase):
    def setUp(self):
        self.config = {robloxstats.GAMES_KEY: {'christmasrun': {'place_id': '111', 'universe_id': '222'}}}
        self.clock = [1000.0]
        self.patches = [
            patch.dict(os.environ, {'PANEL_PASSWORD': 'pw', 'PANEL_SECRET': 'x' * 48,
                                    'PANEL_INSECURE_LOCAL': '1', 'ROBLOX_API_KEY': KEY}),
            patch.object(core.bot, 'config_data', self.config),
            patch.object(core, 'save_runtime_json'),
            patch.object(core, 'save_state_immediately', new_callable=AsyncMock),
            patch.object(robloxstats.time, 'time', side_effect=lambda: self.clock[0]),
            patch.object(robloxstats, 'fetch_public', new=AsyncMock(return_value=PUBLIC)),
            patch.object(robloxstats, 'avatars', new=AsyncMock(return_value={'1': 'https://tr.rbxcdn.com/a.png'})),
            patch('rene.panel.run', side_effect=lambda coro, *a: asyncio.run(coro)),
        ]
        for item in self.patches:
            item.start()
        robloxstats.live.clear()
        robloxapi.failures.clear()
        install_panel(core.web_app)
        self.client = core.web_app.test_client()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def beat(self, players, job='job-a', **extra):
        body = {'game': 'christmasrun', 'job_id': job, 'max_players': 20,
                'players': [{'id': uid, 'name': name} for uid, name in players], **extra}
        return self.client.post('/api/roblox/heartbeat', json=body, headers={'X-Rene-Key': KEY})

    def test_heartbeat_needs_key_and_known_game(self):
        self.assertEqual(self.client.post('/api/roblox/heartbeat', json={'game': 'christmasrun'}).status_code, 401)
        self.assertEqual(self.client.post('/api/roblox/heartbeat', json={'game': 'autre'},
                                          headers={'X-Rene-Key': KEY}).status_code, 400)

    def test_play_time_sessions_and_servers(self):
        self.assertEqual(self.beat([('1', 'Lea'), ('2', 'Hugo')]).status_code, 200)
        self.clock[0] += 60
        self.beat([('1', 'Lea')])                         # Hugo part
        self.clock[0] += 60
        self.beat([('1', 'Lea'), ('2', 'Hugo')])         # Hugo revient : nouvelle session
        self.beat([('3', 'Tom')], job='job-b', private=True)
        self.clock[0] += 140
        self.beat([('1', 'Lea')])

        data = robloxstats.game_store('christmasrun')
        day = data['players'][robloxstats.today()]
        self.assertEqual(day['1'], [260, 1])
        self.assertEqual(day['2'], [0, 2])
        bucket = data['days'][robloxstats.today()]
        self.assertEqual((bucket['unique'], bucket['new'], bucket['hb_peak']), (3, 3, 3))

        result = asyncio.run(robloxstats.build(30, 'christmasrun'))['items'][0]
        self.assertEqual(result['top'][0]['name'], 'Lea')
        self.assertEqual(result['top'][0]['avatar'], 'https://tr.rbxcdn.com/a.png')
        self.assertEqual(result['period']['unique'], 3)
        self.assertEqual(result['period']['new'], 3)
        # job-z vient seulement de la liste publique de Roblox.
        self.assertEqual([s['id'] for s in result['servers']], ['job-a', 'job-b', 'job-z'])
        self.assertTrue(result['servers'][1]['private'])
        self.clock[0] += robloxstats.SERVER_TIMEOUT + 1   # plus de nouvelles : serveurs fermés
        self.assertEqual(robloxstats.online('christmasrun'), {})
        self.assertEqual(result['servers'][0]['fps'], 60)
        self.assertEqual(result['online']['players'], 7)
        self.assertEqual(len(result['daily']), 30)

    def test_closing_server_disappears(self):
        self.beat([('1', 'Lea')], job='job-c')
        self.assertIn('job-c', robloxstats.online('christmasrun'))
        self.beat([('1', 'Lea')], job='job-c', closing=True)
        self.assertNotIn('job-c', robloxstats.online('christmasrun'))

    def test_public_samples_build_daily_peak(self):
        robloxstats.record_sample('christmasrun', {'playing': 4, 'visits': 100})
        robloxstats.record_sample('christmasrun', {'playing': 9, 'visits': 130})
        bucket = robloxstats.game_store('christmasrun')['days'][robloxstats.today()]
        self.assertEqual((bucket['peak'], bucket['n'], bucket['visits_end'] - bucket['visits_start']), (9, 2, 30))

    def test_unconfigured_game(self):
        with patch.object(robloxstats, 'fetch_public', new=AsyncMock(return_value=None)):
            result = asyncio.run(robloxstats.build(7, 'pointnemo'))['items'][0]
        self.assertFalse(result['configured'])


if __name__ == '__main__':
    unittest.main()
