import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

from rene import assistance, broadcast, core, robloxapi, stats
from rene.commands import sendgiftcode as gifts
from rene.panel import install_panel


def member(uid=2, name='Léa'):
    m = Mock(id=uid, bot=False, display_name=name, status=core.discord.Status.online)
    m.name = name.lower()
    m.display_avatar.url = 'https://cdn.discordapp.com/a.png'
    m.__str__ = Mock(return_value=name.lower())
    return m


class AssistanceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {}
        self.store = {'VOID-USED-USED-USED': {'code': 'VOID-USED-USED-USED', 'guild_id': 1, 'recipient_id': 3,
                                              'card_token': 'x' * 32, 'used_at': '2026-11-20T10:00:00+00:00'}}
        self.guild = Mock(id=1, members=[member()])
        self.guild.name = 'Serveur'
        self.guild.get_member.side_effect = lambda uid: self.guild.members[0] if uid == 2 else None
        self.patches = [
            patch.object(core.bot, 'config_data', self.config),
            patch.object(gifts, 'gift_store', return_value=self.store),
            patch.object(assistance, 'allowed_guilds', return_value=[self.guild]),
            patch.object(core, 'save_state_immediately', new_callable=AsyncMock),
            patch.object(assistance.analytics, 'audit'),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def fields(self, **changes):
        data = {'code': 'void-new1-new1-new1', 'reason': 'Le code ne passe pas en jeu', 'signature': 'Sam',
                'incident_at': (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(), 'user_id': '2',
                'reward': {'game': 'pointnemo', 'type': 'raft_extension'}}
        data.update(changes)
        return data

    async def test_missing_code_is_added_and_active_24h(self):
        result = await assistance.submit('1', assistance.clean_fields(self.fields(code='VOIDNEW1NEW1NEW1')), 'sid')
        self.assertTrue(result['ok'])
        entry = self.store['VOID-NEW1-NEW1-NEW1']
        self.assertEqual(robloxapi.roblox_status(entry), 'available')
        self.assertEqual(gifts.card_status(entry), 'scratched')
        self.assertEqual(entry['recipient_id'], 2)
        self.assertEqual(entry['reward']['type'], 'raft_extension')
        self.assertEqual(robloxapi.game_status(entry, 'pointnemo'), 'available')
        record = self.config['_assistance_requests'][0]
        self.assertEqual((record['outcome'], record['signature']), ('accepted', 'Sam'))

    async def test_existing_code_is_always_refused(self):
        result = await assistance.submit('1', assistance.clean_fields(self.fields(code='VOID-USED-USED-USED')), 'sid')
        self.assertFalse(result['ok'])
        self.assertIn('utilisé', result['message'])
        self.assertNotIn('expires_at', self.store['VOID-USED-USED-USED'])
        await assistance.submit('1', assistance.clean_fields(self.fields(code='VOID-AAAA-BBBB-CCCC')), 'sid')
        again = await assistance.submit('1', assistance.clean_fields(self.fields(code='VOID-AAAA-BBBB-CCCC')), 'sid')
        self.assertFalse(again['ok'])
        self.assertIn('actif', again['message'])
        listing = assistance.list_requests(1)
        self.assertEqual((listing['accepted'], listing['refused']), (1, 2))

    async def test_every_field_is_required(self):
        for change in ({'reward': {'game': 'pointnemo', 'type': 'gamepass_random'}},
                       {'reward': {'game': 'christmasrun', 'type': 'gamepass_random'}},
                       {'reward': {'game': 'christmasrun', 'type': 'glings'}},
                       {'reward': None}, {'signature': ''}, {'reason': 'x'}, {'incident_at': ''}, {'user_id': ''}, {'code': 'ABC'},
                       {'incident_at': (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}):
            with self.assertRaises(ValueError, msg=change):
                assistance.clean_fields(self.fields(**change))
        with self.assertRaises(ValueError):
            await assistance.submit('1', assistance.clean_fields(self.fields(user_id='99')), 'sid')

    def test_legacy_replacement_ignores_assistance_codes(self):
        entry = {'code': 'VOID-A', 'source': 'assistance', 'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
        self.assertEqual(gifts.card_status(entry), 'scratched')


class AssistanceAccessTest(unittest.TestCase):
    def setUp(self):
        self.patches = [patch.dict(os.environ, {'PANEL_PASSWORD': 'mdp-panel', 'PANEL_SECRET': 'x' * 48,
                                                'PANEL_INSECURE_LOCAL': '1', 'ASSISTANCE_PASSWORD': 'mdp-assist'})]
        for item in self.patches:
            item.start()
        assistance.attempts.clear()
        install_panel(core.web_app)
        self.client = core.web_app.test_client()

    def tearDown(self):
        for item in self.patches:
            item.stop()

    def test_assistant_cannot_reach_owner_panel(self):
        self.assertEqual(self.client.get('/assistance').status_code, 200)
        self.assertEqual(self.client.post('/api/assist/login', json={'password': 'mdp-panel'}).status_code, 401)
        login = self.client.post('/api/assist/login', json={'password': 'mdp-assist'})
        self.assertEqual(login.status_code, 200)
        self.assertTrue(self.client.get('/api/assist/session').json['authenticated'])
        self.assertEqual(self.client.get('/api/guild/1/overview').status_code, 401)
        self.assertEqual(self.client.get('/api/guild/1/assistance').status_code, 401)
        refused = self.client.post('/api/assist/requests', json={}, headers={'X-CSRF-Token': 'faux'})
        self.assertEqual(refused.status_code, 403)


class BroadcastAndStatsTest(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_sends_to_every_human_and_can_be_cancelled(self):
        humans = [member(i, f'M{i}') for i in range(1, 4)]
        for m in humans:
            m.send = AsyncMock()
        humans[1].send.side_effect = core.discord.Forbidden(Mock(status=403), 'closed')
        bot_member = Mock(bot=True)
        guild = Mock(id=1, members=humans + [bot_member])
        guild.name = 'Serveur'
        guild.get_member.side_effect = lambda uid: next((m for m in humans if m.id == uid), None)
        with patch.object(core.bot, 'config_data', {}), patch.object(broadcast, 'DELAY_SECONDS', 0), \
             patch.object(core, 'save_runtime_json'), patch.object(broadcast.analytics, 'audit'):
            broadcast.current = None
            await broadcast.start(guild, 'Bonjour à tous', None)
            with self.assertRaises(ValueError):
                await broadcast.start(guild, 'Encore', None)
            await broadcast.task
            job = broadcast.current
            self.assertEqual((job['total'], job['sent'], job['failed'], job['state']), (3, 2, 1, 'finished'))
            bot_member.send.assert_not_called()
            self.assertEqual(broadcast.status(guild)['history'][0]['sent'], 2)

    async def test_stats_build(self):
        guild = Mock(id=1, members=[member()], member_count=1)
        config = {}
        with patch.object(core.bot, 'config_data', config), patch.object(core.bot, 'moderation_cases', {}), \
             patch.object(core.bot, 'questions', {}), patch.object(core.bot, 'warning_data', {}), \
             patch.object(core.bot, 'temporary_bans', {}):
            stats.analytics.record(1, 'messages', 2)
            stats.analytics.record(1, 'joins')
            data = await stats.build(guild, 7)
        self.assertEqual(data['activity']['messages'], 1)
        self.assertEqual(data['activity']['active'], 1)
        self.assertEqual(data['community']['joins'], 1)
        self.assertEqual(len(data['daily']), 7)
        self.assertEqual(len(data['activity']['weekdays']), 7)


if __name__ == '__main__':
    unittest.main()
