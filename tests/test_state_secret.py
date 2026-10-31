import os
import unittest
from unittest.mock import patch

from rene import core


class StateSecretRotationTest(unittest.IsolatedAsyncioTestCase):
    async def test_previous_key_reads_backup_written_with_old_key(self):
        snapshot = {'version': 3, 'config': {'example': {'value': 1}}}
        with patch.dict(os.environ, {'STATE_SECRET': 'ancienne-cle-de-test'}, clear=False):
            payload = core.encode_state_snapshot(snapshot)
        with patch.dict(os.environ, {
            'STATE_SECRET': 'nouvelle-cle-de-test',
            'STATE_SECRET_PREVIOUS': 'ancienne-cle-de-test',
        }, clear=False):
            self.assertEqual(core.decode_state_snapshot(payload), snapshot)
            self.assertNotEqual(core.encode_state_snapshot(snapshot), payload)

    async def test_unreadable_backup_cannot_be_overwritten(self):
        with patch.object(core.bot._connection, 'user', object()), \
             patch.object(core.bot, 'remote_state_unreadable', True), \
             patch.object(core, 'get_persistence_channel') as channel:
            self.assertFalse(await core.persist_state_to_discord())
            channel.assert_not_called()


if __name__ == '__main__':
    unittest.main()
