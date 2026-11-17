import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

from rene import core, panel
from rene.panel import install_panel


class ModerationRoutesTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'PANEL_PASSWORD': 'un-mot-de-passe-de-test',
            'PANEL_SECRET': 'x' * 48,
            'PANEL_INSECURE_LOCAL': '1',
        })
        self.env.start()
        install_panel(core.web_app)
        self.client = core.web_app.test_client()
        self.csrf = self.client.post('/api/login', json={'password': 'un-mot-de-passe-de-test'}).json['csrf']

    def tearDown(self):
        self.env.stop()

    def test_new_actions_require_csrf_and_validate_input(self):
        def fake_run(coro, *args):
            coro.close()
            return {'ok': True}
        with patch('rene.panel.run', side_effect=fake_run) as run:
            for path, body in (('/api/guild/1/warn', {'user_id': '2', 'reason': 'Spam'}),
                               ('/api/guild/1/tempban', {'user_id': '2', 'reason': 'Spam', 'hours': 24}),
                               ('/api/guild/1/express', {'user_id': '2'}),
                               ('/api/guild/1/tickets/5/reply', {'message': 'Bonjour'}),
                               ('/api/guild/1/say', {'channel_id': '3', 'message': 'Salut'})):
                self.assertEqual(self.client.post(path, json=body).status_code, 403, path)
                ok = self.client.post(path, json=body, headers={'X-CSRF-Token': self.csrf})
                self.assertEqual(ok.status_code, 200, path)
            bad = self.client.post('/api/guild/1/tempban', json={'user_id': '2', 'reason': 'Spam', 'hours': 99999},
                                   headers={'X-CSRF-Token': self.csrf})
            self.assertEqual(bad.status_code, 400)
            wrong_kind = self.client.post('/api/guild/1/appointments/autre/ABC/no-show', json={},
                                          headers={'X-CSRF-Token': self.csrf})
            self.assertEqual(wrong_kind.status_code, 404)
            self.assertEqual(run.call_count, 5)


class ModerationActionsTest(unittest.IsolatedAsyncioTestCase):
    async def test_warn_increments_count_and_notifies(self):
        member = Mock(id=456, bot=False, display_name='Membre')
        member.send = AsyncMock()
        guild = Mock(id=123, owner_id=999)
        guild.name = 'Serveur'
        guild.get_member.return_value = member
        counts = {}
        with patch.object(panel, 'guild_for', return_value=guild), \
             patch.object(panel.core, 'get_warning_count', side_effect=lambda g, u: counts.get(u, 2)), \
             patch.object(panel.core, 'set_warning_count', side_effect=lambda g, u, c: counts.__setitem__(u, c)), \
             patch.object(panel.core, 'create_case', return_value={'id': 1}), \
             patch.object(panel.core, 'send_case_to_staff', new_callable=AsyncMock), \
             patch.object(panel.core, 'save_state_immediately', new_callable=AsyncMock), \
             patch.object(panel.core.bot, 'get_guild_config', return_value={}), \
             patch.object(panel.analytics, 'audit'):
            result = await panel.warn_member('123', '456', 'Langage')
        self.assertEqual(result['count'], 3)
        self.assertEqual(counts[456], 3)
        member.send.assert_awaited_once()

    async def test_no_show_marks_entry_and_cancels_reminder(self):
        guild = Mock(id=123)
        store = {'ABC': {'id': 'ABC', 'guild_id': 123, 'status': 'accepted', 'target_name': 'Léa'}}
        with patch.object(panel, 'guild_for', return_value=guild), \
             patch.object(panel.rdv, 'get_store', return_value=store), \
             patch.object(panel.rdv, 'cancel_reminder') as cancel, \
             patch.object(panel.core, 'save_state_immediately', new_callable=AsyncMock), \
             patch.object(panel.analytics, 'audit'):
            await panel.mark_no_show('123', 'rdv', 'ABC')
            self.assertEqual(store['ABC']['status'], 'no_show')
            cancel.assert_called_once_with('ABC')
            with self.assertRaises(ValueError):
                await panel.mark_no_show('123', 'rdv', 'ABC')

    async def test_ticket_reply_is_signed_rene_and_only_once(self):
        guild = Mock(id=123)
        guild.get_channel.return_value = None
        questions = {'123': {'77': {'author_id': 456, 'content': 'Question ?', 'answered': False}}}
        fake_bot = Mock(questions=questions, question_locks={}, user=Mock(id=1))
        fake_bot.get_user.return_value = Mock()
        with patch.object(panel, 'guild_for', return_value=guild), \
             patch.object(panel.core, 'bot', fake_bot), \
             patch.object(panel.core, 'send_embed_with_thumbnail', new_callable=AsyncMock) as send, \
             patch.object(panel.core, 'save_runtime_json'), \
             patch.object(panel.core, 'save_state_immediately', new_callable=AsyncMock), \
             patch.object(panel, 'staff_channel_id', return_value=0), \
             patch.object(panel.analytics, 'audit'):
            await panel.answer_ticket('123', '77', 'Voici la réponse')
            self.assertIn('Réponse de René', send.await_args.kwargs['description'])
            self.assertTrue(questions['123']['77']['answered'])
            with self.assertRaises(ValueError):
                await panel.answer_ticket('123', '77', 'Encore')


if __name__ == '__main__':
    unittest.main()
