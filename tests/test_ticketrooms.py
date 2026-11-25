import base64
import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord

from rene import core, ticketrooms


def member(uid, name, display=None, bot=False):
    m = Mock(spec=discord.Member)
    m.id, m.name, m.display_name, m.bot = uid, name, display or name, bot
    m.mention = f'<@{uid}>'
    m.display_avatar.url = 'https://cdn.discordapp.com/a.png'
    return m


class TicketRoomsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.category = Mock(spec=discord.CategoryChannel)
        self.category.id = ticketrooms.DEFAULT_CATEGORY_ID
        self.lea = member(2, 'lea_builds', 'Léa')
        self.staff = member(3, 'staff')
        self.channel = Mock(spec=discord.TextChannel)
        self.channel.id, self.channel.name, self.channel.category_id = 50, 'léa', self.category.id
        self.channel.overwrites = {}
        self.channel.send = AsyncMock(return_value=Mock(spec=discord.Message, id=9, created_at=discord.utils.utcnow(),
                                                         edited_at=None, author=member(1, 'René', bot=True),
                                                         clean_content='Bonjour', embeds=[], attachments=[]))
        self.other = Mock(spec=discord.TextChannel)
        self.other.id, self.other.category_id = 60, 1
        self.guild = Mock(id=7, members=[self.lea, self.staff])
        self.channel.guild = self.guild
        channels = {self.category.id: self.category, 50: self.channel, 60: self.other}
        self.guild.get_channel.side_effect = channels.get
        self.patches = [
            patch.object(core.bot, 'get_guild_config', return_value={}),
            patch.object(core, 'member_has_moderator_role', side_effect=lambda m: m is self.staff),
            patch.object(ticketrooms.analytics, 'audit'),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def test_owner_found_by_overwrite_then_by_channel_name(self):
        self.assertIs(ticketrooms.ticket_owner(self.channel), self.lea)
        self.channel.overwrites = {self.staff: Mock(), self.lea: Mock()}
        self.assertIs(ticketrooms.ticket_owner(self.channel), self.lea)
        self.channel.overwrites = {}
        self.channel.name = 'ticket-lea_builds'
        self.assertIs(ticketrooms.ticket_owner(self.channel), self.lea)

    def test_only_channels_of_the_category_are_tickets(self):
        with self.assertRaises(ValueError):
            ticketrooms.ticket_channel(self.guild, 60)
        self.assertIs(ticketrooms.ticket_channel(self.guild, 50), self.channel)

    def test_embed_validation(self):
        embed = ticketrooms.clean_embed({'title': 'Ticket', 'description': 'Salut', 'color': '#FF46AA',
                                         'fields': [{'name': 'Code', 'value': 'VOID', 'inline': True}],
                                         'footer': 'René', 'image': 'https://cdn.discordapp.com/x.png'})
        self.assertEqual(embed.color.value, 0xFF46AA)
        self.assertEqual(len(embed.fields), 1)
        for bad in ({'title': ''}, {'title': 'x', 'color': 'rouge'}, {'title': 'x', 'image': 'http://site.com/a.png'}):
            with self.assertRaises(ValueError, msg=bad):
                ticketrooms.clean_embed(bad)
        self.assertIsNotNone(ticketrooms.clean_embed({'title': ''}, allow_empty=True))

    async def test_send_text_embed_image_and_mention_only_the_member(self):
        png = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0' * 20).decode()
        await ticketrooms.send(self.guild, 50, {'content': 'On regarde ça', 'mention_owner': True,
                                                'embed': {'title': 'Suivi'},
                                                'file': {'name': 'capture.png', 'type': 'image/png', 'data': png},
                                                'image_in_embed': True})
        kwargs = self.channel.send.await_args.kwargs
        self.assertTrue(kwargs['content'].startswith('<@2>'))
        self.assertEqual(kwargs['allowed_mentions'].users, [self.lea])
        self.assertFalse(kwargs['allowed_mentions'].everyone)
        self.assertEqual(kwargs['embed'].image.url, 'attachment://capture.png')
        self.assertEqual(kwargs['file'].filename, 'capture.png')
        with self.assertRaises(ValueError):
            await ticketrooms.send(self.guild, 50, {})
        with self.assertRaises(ValueError):
            await ticketrooms.send(self.guild, 50, {'file': {'name': 'x.exe', 'type': 'application/x-msdownload', 'data': png}})


if __name__ == '__main__':
    unittest.main()
