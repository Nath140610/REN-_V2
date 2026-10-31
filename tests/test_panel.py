import os
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from rene import ai, analytics, core
from rene import panel
from rene.panel import install_panel


class PanelSecurityTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'PANEL_PASSWORD': 'un-mot-de-passe-de-test',
            'PANEL_SECRET': 'x' * 48,
            'PANEL_INSECURE_LOCAL': '1',
        })
        self.env.start()
        install_panel(core.web_app)
        self.client = core.web_app.test_client()

    def tearDown(self):
        self.env.stop()

    def test_login_and_csrf_protect_a_ban(self):
        self.assertEqual(self.client.get('/api/guild/123/overview').status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={'password': 'faux'}).status_code, 401)
        login = self.client.post('/api/login', json={'password': 'un-mot-de-passe-de-test'})
        self.assertEqual(login.status_code, 200)
        self.assertIn('HttpOnly', login.headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', login.headers['Set-Cookie'])
        def fake_run(coro, *args):
            coro.close()
            return {'ok': True}
        with patch('rene.panel.run', side_effect=fake_run) as run:
            body = {'user_id': '123', 'reason': 'Un motif précis'}
            self.assertEqual(self.client.post('/api/guild/123/ban', json=body).status_code, 403)
            run.assert_not_called()
            result = self.client.post('/api/guild/123/ban', json=body,
                headers={'X-CSRF-Token': login.json['csrf']})
            self.assertEqual(result.status_code, 200)
            run.assert_called_once()

    def test_protected_assets_and_http_headers(self):
        self.assertEqual(self.client.get('/assets/config.json').status_code, 404)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="device-gate"', response.data)
        self.assertIn(b'id="install-guide"', response.data)
        for path in ('/assets/SLEEP.png', '/static/manifest.webmanifest'):
            asset = self.client.get(path)
            self.assertEqual(asset.status_code, 200)
            asset.close()
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])


class AnalyticsTest(unittest.TestCase):
    def test_daily_and_user_aggregation(self):
        with patch.object(core.bot, 'config_data', {}):
            analytics.record(123, 'joins')
            analytics.record(123, 'messages', 456)
            analytics.record(123, 'messages', 456)
            analytics.record(123, 'voice_seconds', 456, 120)
            result = analytics.summary(123)
            self.assertEqual(result['totals']['joins'], 1)
            self.assertEqual(result['totals']['messages'], 2)
            self.assertEqual(result['users']['456']['voice_seconds'], 120)
            self.assertEqual(result['users']['456']['active_days'], 1)

    def test_presence_ranking_uses_last_observed_connection(self):
        older = Mock(id=1, bot=False, display_name='Ancien', status=core.discord.Status.offline)
        recent = Mock(id=2, bot=False, display_name='Récent', status=core.discord.Status.offline)
        guild = Mock(id=123, members=[older, recent])
        fake_bot = Mock(intents=Mock(presences=True), config_data={})
        with patch.object(core, 'bot', fake_bot):
            analytics.store(123)['last_online'] = {
                '1': '2026-10-25T09:00:00+00:00',
                '2': '2026-10-30T09:00:00+00:00',
            }
            result = analytics.presence_ranking(guild)
        self.assertEqual(result['mode'], 'presence')
        self.assertEqual([item['id'] for item in result['members']], ['2', '1'])


class AITest(unittest.TestCase):
    def test_prompt_fits_nathgpt_discord_limit(self):
        context = {
            'guild': {'name': 'Serveur de test'}, 'since': '2026-10-01',
            'totals_30_days': {'messages': 1200, 'joins': 25},
            'daily_30_days': [{'date': f'2026-10-{day:02}', 'messages': 50,
                               'joins': 2, 'leaves': 0, 'voice_seconds': 3000}
                              for day in range(1, 31)],
            'top_members_30_days': [{'name': 'Membre très présent ' * 3,
                                      'messages': 100, 'voice_seconds': 6000}
                                     for _ in range(12)],
        }
        prompt = ai.build_prompt('Résume les tendances du serveur.', context)
        self.assertLessEqual(len(prompt), 1800)
        self.assertIn('Résume les tendances', prompt)


class PanelActionsTest(unittest.IsolatedAsyncioTestCase):
    async def test_gift_qr_is_sent_to_owner_and_can_only_be_used_once(self):
        member = Mock(id=456, bot=False, display_name='Destinataire')
        guild = Mock(id=123, name='Serveur')
        guild.get_member.return_value = member
        owner = Mock()
        owner.send = AsyncMock()
        panel.gift_challenges.clear()
        with patch.object(panel, 'guild_for', return_value=guild), \
             patch.object(panel.core.bot, 'get_user', return_value=owner) as get_user, \
             patch.object(panel, 'send_gift', new_callable=AsyncMock,
                          return_value={'ok': True}) as send_gift:
            result = await panel.start_gift_challenge('123', '456', 'Merci', 'session-a')
            get_user.assert_called_once_with(panel.OWNER_DISCORD_ID)
            owner.send.assert_awaited_once()
            challenge = panel.gift_challenges[result['challenge_id']]
            self.assertGreater(challenge['expires_at'], time.time())
            with self.assertRaises(ValueError):
                await panel.confirm_gift_challenge('123', result['challenge_id'],
                                                    'rene-gift:wrong:secret', 'session-a')
            send_gift.assert_not_awaited()
            import hashlib
            secret = 'test-secret'
            challenge['token_hash'] = hashlib.sha256(secret.encode()).digest()
            token = f'rene-gift:{result["challenge_id"]}:{secret}'
            with self.assertRaises(ValueError):
                await panel.confirm_gift_challenge('123', result['challenge_id'],
                                                    token, 'session-b')
            self.assertEqual((await panel.confirm_gift_challenge(
                '123', result['challenge_id'], token, 'session-a'))['ok'], True)
            send_gift.assert_awaited_once_with('123', '456', 'Merci')
            with self.assertRaises(ValueError):
                await panel.confirm_gift_challenge('123', result['challenge_id'],
                                                    token, 'session-a')
        panel.gift_challenges.clear()

    async def test_gift_is_reserved_then_delivered(self):
        member = Mock(id=456, bot=False, display_name='Membre')
        member.__str__ = Mock(return_value='Membre')
        guild = Mock(id=123, name='Serveur')
        guild.get_member.return_value = member
        entries = {}
        with patch.object(panel, 'guild_for', return_value=guild), \
             patch.object(panel, 'gift_store', return_value=entries), \
             patch.object(panel, 'generate_unique_code', return_value='VOID-ABCD-EFGH-JKLM'), \
             patch.object(panel.core, 'save_state_immediately', new_callable=AsyncMock) as save, \
             patch.object(panel, 'send_gift_dm', new_callable=AsyncMock, return_value=True) as dm, \
             patch.object(panel.analytics, 'audit'):
            result = await panel.send_gift('123', '456', 'Merci pour ton aide')
            self.assertTrue(result['delivered'])
            self.assertEqual(entries[result['code']]['delivery_status'], 'delivered')
            self.assertEqual(save.await_count, 2)
            dm.assert_awaited_once()

    async def test_ban_denied_if_bot_lacks_permission(self):
        member = Mock(id=456, bot=False, top_role=1)
        guild = Mock(id=123, owner_id=999, me=Mock(top_role=2))
        guild.get_member.return_value = member
        guild.me.guild_permissions.ban_members = False
        with patch.object(panel, 'guild_for', return_value=guild):
            with self.assertRaises(ValueError):
                await panel.ban_member('123', '456', 'Motif de test')
            member.ban.assert_not_called()


if __name__ == '__main__':
    unittest.main()
