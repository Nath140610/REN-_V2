import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

from rene import core, giftcard, panel
from rene.commands import sendgiftcode as gifts
from rene.panel import install_panel


class GiftCardTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = {'VOID-AAAA-BBBB-CCCC': {
            'code': 'VOID-AAAA-BBBB-CCCC', 'guild_id': 1, 'recipient_id': 2,
            'recipient_name': 'lea#0', 'reason': 'Merci', 'card_token': 't' * 32,
            'delivery_status': 'delivered',
        }}
        self.patches = [
            patch.object(gifts, 'gift_store', return_value=self.store),
            patch.object(core, 'save_state_immediately', new_callable=AsyncMock),
            patch.object(core, 'save_runtime_json'),
            patch.object(core.bot, 'get_guild', return_value=None),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()

    async def test_code_is_hidden_until_scratched_then_valid_24h(self):
        opened = await giftcard.open_card('t' * 32)
        self.assertNotIn('code', opened)
        self.assertEqual(opened['status'], 'opened')
        scratched = await giftcard.scratch_card('t' * 32)
        self.assertEqual(scratched['code'], 'VOID-AAAA-BBBB-CCCC')
        self.assertGreater(scratched['remaining'], 24 * 3600 - 5)
        first_expiry = self.store['VOID-AAAA-BBBB-CCCC']['expires_at']
        await giftcard.scratch_card('t' * 32)
        self.assertEqual(self.store['VOID-AAAA-BBBB-CCCC']['expires_at'], first_expiry)

    async def test_expired_card_no_longer_shows_code(self):
        entry = self.store['VOID-AAAA-BBBB-CCCC']
        entry['expires_at'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        state = await giftcard.open_card('t' * 32)
        self.assertEqual(state['status'], 'expired')
        self.assertNotIn('code', state)

    async def test_unknown_or_replaced_card_is_refused(self):
        self.assertIsNone(await giftcard.open_card('x' * 32))
        self.store['VOID-AAAA-BBBB-CCCC']['replaced_by'] = 'VOID-ZZZZ-ZZZZ-ZZZZ'
        self.assertIsNone(await giftcard.scratch_card('t' * 32))

    async def test_legacy_code_kept_when_new_card_cannot_be_delivered(self):
        legacy = {'VOID-OLDD-OLDD-OLDD': {'code': 'VOID-OLDD-OLDD-OLDD', 'guild_id': 1,
                                          'recipient_id': 2, 'reason': 'Merci'}}
        guild = Mock(id=1)
        guild.name = 'Serveur'
        guild.get_member.return_value = Mock(id=2)
        with patch.object(gifts, 'gift_store', return_value=legacy), \
             patch.object(gifts, 'send_gift_dm', new_callable=AsyncMock, return_value=False), \
             patch.object(gifts, 'save_state_immediately', new_callable=AsyncMock):
            result = await gifts.replace_legacy_codes(guild)
        self.assertEqual(result['dm_failed'], 1)
        self.assertEqual(list(legacy), ['VOID-OLDD-OLDD-OLDD'])
        self.assertNotIn('replaced_by', legacy['VOID-OLDD-OLDD-OLDD'])

    async def test_legacy_code_replaced_and_old_dm_deleted(self):
        legacy = {'VOID-OLDD-OLDD-OLDD': {'code': 'VOID-OLDD-OLDD-OLDD', 'guild_id': 1,
                                          'recipient_id': 2, 'reason': 'Merci'}}
        guild = Mock(id=1)
        guild.name = 'Serveur'
        guild.get_member.return_value = Mock(id=2)
        with patch.object(gifts, 'gift_store', return_value=legacy), \
             patch.object(gifts, 'send_gift_dm', new_callable=AsyncMock, return_value=True), \
             patch.object(gifts, 'delete_code_messages', new_callable=AsyncMock, return_value=1) as delete, \
             patch.object(gifts, 'save_state_immediately', new_callable=AsyncMock), \
             patch.object(gifts.asyncio, 'sleep', new_callable=AsyncMock):
            result = await gifts.replace_legacy_codes(guild)
        self.assertEqual(result['replaced'], 1)
        new_code = legacy['VOID-OLDD-OLDD-OLDD']['replaced_by']
        self.assertEqual(legacy[new_code]['replaces'], 'VOID-OLDD-OLDD-OLDD')
        delete.assert_awaited_once()
        self.assertEqual(delete.await_args.args[1], {'VOID-OLDD-OLDD-OLDD'})


class GiftRoutesTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'PANEL_PASSWORD': 'pw-de-test', 'PANEL_SECRET': 'x' * 48,
                                           'PANEL_INSECURE_LOCAL': '1'})
        self.env.start()
        install_panel(core.web_app)
        self.client = core.web_app.test_client()

    def tearDown(self):
        self.env.stop()

    def test_public_page_and_bad_tokens(self):
        page = self.client.get('/cadeau/' + 'a' * 32)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'foil-canvas', page.data)
        self.assertEqual(self.client.get('/cadeau/court').status_code, 404)
        self.assertEqual(self.client.get('/api/cadeau/court').status_code, 404)
        self.assertEqual(self.client.post('/api/cadeau/' + 'a' * 32 + '/scratch', data='x').status_code, 415)

    def test_panel_never_exposes_card_token(self):
        entry = {'code': 'VOID-AAAA-BBBB-CCCC', 'guild_id': 1, 'card_token': 'secret-token' * 3}
        with patch.object(panel, 'guild_for'), patch.object(panel, 'gift_store', return_value={'x': entry}):
            import asyncio
            data = asyncio.run(panel.gifts('1'))
        self.assertNotIn('secret-token', str(data))
        self.assertEqual(data['items'][0]['status'], 'sent')


if __name__ == '__main__':
    unittest.main()
