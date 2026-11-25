import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import discord

from rene import core, nathgpt, ticketassistant as tka


def member(uid, name, staff=False):
    m = Mock(spec=discord.Member)
    m.id, m.name, m.display_name, m.bot = uid, name, name, False
    m.mention = f'<@{uid}>'
    m.staff = staff
    return m


def history(messages):
    async def gen(*args, **kwargs):
        for message in messages:
            yield message
    return gen


class TicketAssistantTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.lea = member(2, 'Léa')
        self.nath = member(3, 'Nath', staff=True)
        self.role = Mock(spec=discord.Role)
        self.role.id, self.role.name, self.role.mention = 40, 'Support', '<@&40>'
        self.guild = Mock(spec=discord.Guild)
        self.guild.id, self.guild.name, self.guild.owner_id = 7, 'VoidLoop', 3
        self.guild.get_member.side_effect = {2: self.lea, 3: self.nath}.get
        self.guild.get_role.side_effect = {40: self.role}.get
        self.guild.roles, self.guild.members = [], [self.lea, self.nath]
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id, self.channel.name, self.channel.guild, self.channel.topic = 50, 'léa', self.guild, None
        self.channel.send = AsyncMock(return_value=Mock(id=99))
        self.channel.set_permissions = AsyncMock()
        self.channel.permissions_for.return_value = Mock(view_channel=False)
        self.config = {}
        self.guild_config = {}
        self.patches = [
            patch.object(core.bot, 'config_data', self.config),
            patch.object(core.bot, 'get_guild_config', return_value=self.guild_config),
            patch.object(core, 'member_has_moderator_role', side_effect=lambda m: getattr(m, 'staff', False)),
            patch.object(core, 'save_runtime_json'),
            patch.object(core, 'save_state_immediately', new_callable=AsyncMock),
            patch.object(tka.analytics, 'audit'),
            patch.object(tka, 'FIRST_DELAY', 0),
            patch.object(tka.ticketrooms, 'ticket_owner', return_value=self.lea),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    async def test_reason_comes_from_ticket_form_and_member(self):
        form = Mock(author=Mock(id=9, bot=True), content='',
                    embeds=[discord.Embed(title='Ticket').add_field(name='Raison du ticket', value='**Code cadeau** refusé')])
        own = Mock(author=self.lea, content='VOID-AAAA-AAAA-AAAA ne marche pas', embeds=[])
        other = Mock(author=self.nath, content='salut', embeds=[])
        self.channel.history = history([form, own, other])
        with patch.object(core.bot, '_connection', Mock(user=Mock(id=1))):
            reason = await tka.read_reason(self.channel, self.lea)
        self.assertEqual(reason, 'Raison du ticket: Code cadeau refusé VOID-AAAA-AAAA-AAAA ne marche pas')

    async def test_welcome_asks_nathgpt_then_offers_buttons(self):
        self.guild_config['ticket_assistant'] = {'targets': [
            {'kind': 'role', 'id': '40', 'label': 'Support codes', 'description': 'Codes cadeau'},
            {'kind': 'user', 'id': '3', 'label': 'Nath', 'description': ''}]}
        self.channel.history = history([Mock(author=self.lea, content='Mon code ne marche pas', embeds=[])])
        ask = AsyncMock(return_value={'text': 'Salut Léa, envoie-moi une capture.'})
        with patch.object(nathgpt, 'configured', return_value=True), \
                patch.object(nathgpt.NathGPTClient, 'ask', ask):
            await tka.welcome(self.channel)
        self.assertIn('Mon code ne marche pas', ask.await_args.args[0])
        self.assertEqual(ask.await_args.kwargs['conversation_id'], 'ticket_50')
        first, second = self.channel.send.await_args_list
        self.assertEqual(first.args[0], 'Salut Léa, envoie-moi une capture.')
        view = second.kwargs['view']
        self.assertEqual([b.item.label for b in view.children], ['Support codes', 'Nath'])
        self.assertEqual(view.children[0].item.custom_id, 'rene_tkt:r40')
        self.assertEqual(self.config[tka.STATE_KEY]['50']['owner_id'], '2')

    async def test_without_ai_a_simple_message_is_sent(self):
        self.channel.history = history([Mock(author=self.lea, content='Bug dans PointNemo', embeds=[])])
        with patch.object(nathgpt, 'configured', return_value=False):
            await tka.welcome(self.channel)
        self.assertIn('Bug dans PointNemo', self.channel.send.await_args_list[0].args[0])
        # Pas de réglage : le fondateur est proposé par défaut.
        self.assertEqual(self.channel.send.await_args_list[1].kwargs['view'].children[0].item.label, 'Le fondateur')

    async def test_choice_mentions_only_the_chosen_person(self):
        self.config[tka.STATE_KEY] = {'50': {'owner_id': '2', 'reason': 'Code refusé', 'question': 'À qui ?',
                                             'targets': [{'kind': 'user', 'id': '3', 'label': 'Nath'}]}}
        stranger = member(8, 'Intrus')
        interaction = Mock(channel=self.channel, guild=self.guild, user=stranger)
        interaction.response.send_message = AsyncMock()
        interaction.response.edit_message = AsyncMock()
        await tka.choose(interaction, 'u', '3')
        interaction.response.send_message.assert_awaited()
        self.channel.send.assert_not_awaited()

        interaction.user = self.lea
        await tka.choose(interaction, 'u', '3')
        sent = self.channel.send.await_args
        self.assertTrue(sent.args[0].startswith('<@3> : **Léa**'))
        self.assertEqual(sent.kwargs['allowed_mentions'].users, [self.nath])
        self.assertFalse(sent.kwargs['allowed_mentions'].everyone)
        self.channel.set_permissions.assert_awaited()
        self.assertTrue(all(b.item.disabled for b in interaction.response.edit_message.await_args.kwargs['view'].children))
        self.assertEqual(self.config[tka.STATE_KEY]['50']['chosen']['id'], '3')

    async def test_settings_validation(self):
        with self.assertRaises(ValueError):
            await tka.save_settings(self.guild, {'targets': [{'kind': 'user', 'id': '999', 'label': 'X'}]})
        result = await tka.save_settings(self.guild, {'enabled': True, 'targets': [{'kind': 'role', 'id': '40', 'label': ''}]})
        self.assertEqual(result['targets'][0]['label'], 'Support')


if __name__ == '__main__':
    unittest.main()
