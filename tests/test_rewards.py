import unittest
from unittest.mock import AsyncMock, Mock, patch

from rene import core, panel, rewards


class RewardsTest(unittest.IsolatedAsyncioTestCase):
    def test_catalog_and_validation(self):
        self.assertEqual(rewards.clean({'game': 'PointNemo', 'type': 'server_slot'})['label'],
                         'PointNemo · Un emplacement de serveur en plus')
        both = rewards.clean({'game': 'christmasrun', 'type': 'glings_gifts', 'glings': '1500', 'gifts': 3})
        self.assertEqual((both['glings'], both['gifts']), (1500, 3))
        self.assertEqual(both['label'], 'ChristmasRun · 1 500 glings et 3 cadeaux')
        for bad in ({'game': 'christmasrun', 'type': 'glings'}, {'game': 'christmasrun', 'type': 'glings', 'glings': 0},
                    {'game': 'pointnemo', 'type': 'glings', 'glings': 5}, {'game': 'autre', 'type': 'glings'}, None):
            with self.assertRaises(ValueError, msg=bad):
                rewards.clean(bad)
        self.assertTrue(rewards.clean({'game': 'pointnemo', 'type': 'gamepass_random'})['gamepass'])
        with self.assertRaises(ValueError):
            rewards.clean({'game': 'pointnemo', 'type': 'gamepass_random'}, allow_gamepass=False)
        names = [r['id'] for g in rewards.catalog(allow_gamepass=False) for r in g['rewards']]
        self.assertNotIn('gamepass_random', names)

    async def test_existing_code_gets_reward_without_any_message(self):
        entry = {'code': 'VOID-AAAA-AAAA-AAAA', 'guild_id': 1, 'recipient_id': 2, 'card_token': 't' * 32}
        guild = Mock(id=1)
        with patch.object(panel, 'guild_for', return_value=guild), \
             patch.object(panel, 'gift_store', return_value={'VOID-AAAA-AAAA-AAAA': entry}), \
             patch.object(panel, 'send_gift_dm', new_callable=AsyncMock) as dm, \
             patch.object(core, 'save_state_immediately', new_callable=AsyncMock), \
             patch.object(panel.analytics, 'audit'):
            reward = rewards.clean({'game': 'christmasrun', 'type': 'gifts', 'gifts': 4})
            await panel.set_gift_reward('1', 'VOID-AAAA-AAAA-AAAA', reward)
        self.assertEqual(entry['reward']['gifts'], 4)
        dm.assert_not_awaited()
        guild.get_member.assert_not_called()


if __name__ == '__main__':
    unittest.main()
