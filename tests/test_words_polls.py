import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from rene import core, panel, polls


class BadWordsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {}
        self.patches = [
            patch.object(core.bot, 'config_data', self.config),
            patch.object(panel, 'guild_for', return_value=Mock(id=1)),
            patch.object(core, 'save_state_immediately', new_callable=AsyncMock),
            patch.object(panel.analytics, 'audit'),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    async def test_default_list_until_edited(self):
        self.assertTrue(core.contains_bad_word('Espèce de CONNARD', 1))
        self.assertFalse((await panel.bad_words('1'))['custom'])

    async def test_add_remove_and_reset(self):
        self.assertFalse(core.contains_bad_word('quel noob', 1))
        result = await panel.change_bad_words('1', 'add', 'Noob')
        self.assertTrue(result['custom'])
        self.assertTrue(core.contains_bad_word('Quel NOOB !', 1))
        self.assertFalse(core.contains_bad_word('noobie', 1))
        with self.assertRaises(ValueError):
            await panel.change_bad_words('1', 'add', 'nOOb')
        await panel.change_bad_words('1', 'remove', 'connard')
        self.assertFalse(core.contains_bad_word('connard', 1))
        self.assertTrue(core.contains_bad_word('connard', 2))
        await panel.change_bad_words('1', 'reset')
        self.assertTrue(core.contains_bad_word('connard', 1))
        self.assertFalse(core.contains_bad_word('noob', 1))

    async def test_expression_and_tester(self):
        await panel.change_bad_words('1', 'add', 'gros nul')
        result = await panel.test_bad_words('1', 'T’es un GROS   nul')
        self.assertTrue(result['blocked'])
        self.assertEqual(result['word'], 'gros nul')
        self.assertFalse((await panel.test_bad_words('1', 'gros nuage'))['blocked'])
        with self.assertRaises(ValueError):
            await panel.change_bad_words('1', 'add', 'x')


class PollsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {}
        self.patches = [
            patch.object(core.bot, 'config_data', self.config),
            patch.object(core, 'save_state_immediately', new_callable=AsyncMock),
            patch.object(core, 'save_runtime_json'),
            patch.object(polls.analytics, 'audit'),
        ]
        for item in self.patches:
            item.start()
        polls.cache.clear()
        self.channel = Mock(spec=core.discord.TextChannel)
        self.channel.id = 5
        self.channel.name = 'annonces'
        self.channel.permissions_for.return_value = Mock(send_messages=True, send_polls=True)
        self.channel.send = AsyncMock(return_value=Mock(id=77))
        self.guild = Mock(id=1, me=Mock())
        self.guild.get_channel.return_value = self.channel

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    async def test_validation(self):
        with self.assertRaises(ValueError):
            await polls.create_poll(self.guild, 5, 'Question ?', ['Oui'], 24, False)
        with self.assertRaises(ValueError):
            await polls.create_poll(self.guild, 5, 'Question ?', ['Oui', 'Non'], 0, False)
        self.assertEqual(polls.clean_answers(['Oui', ' oui ', 'Non', '']), ['Oui', 'Non'])

    async def test_publish_then_read_live_results(self):
        result = await polls.create_poll(self.guild, 5, 'Prochain event ?', ['Course', 'Cache-cache'], 24, False)
        sent_poll = self.channel.send.await_args.kwargs['poll']
        self.assertEqual([a.text for a in sent_poll.answers], ['Course', 'Cache-cache'])
        live = Mock(total_votes=7, expires_at=None,
                    answers=[SimpleNamespace(text='Course', vote_count=5), SimpleNamespace(text='Cache-cache', vote_count=2)])
        live.is_finalised.return_value = False
        self.channel.fetch_message = AsyncMock(return_value=Mock(poll=live))
        with patch.object(core.bot, 'get_guild', return_value=self.guild):
            data = await polls.list_polls(self.guild)
        entry = data['items'][0]
        self.assertEqual(entry['id'], result['id'])
        self.assertEqual(entry['results'], [5, 2])
        self.assertEqual(entry['total'], 7)
        self.assertFalse(entry['finished'])


if __name__ == '__main__':
    unittest.main()
