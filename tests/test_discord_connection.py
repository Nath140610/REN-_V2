import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main import retry_delay
from rene import core


class DiscordConnectionTest(unittest.TestCase):
    def test_retry_after_never_shortens_backoff(self):
        error = SimpleNamespace(response=SimpleNamespace(headers={"Retry-After": "1800"}))
        self.assertEqual(retry_delay(error, 900), 1800)
        error.response.headers["Retry-After"] = "10"
        self.assertEqual(retry_delay(error, 900), 900)
        error.response.headers["Retry-After"] = "invalid"
        self.assertEqual(retry_delay(error, 900), 900)

    def test_health_reports_rate_limit_without_exposing_credentials(self):
        with patch.object(core, "bot_is_ready", return_value=False):
            core.set_discord_connection(
                "rate_limited", retry_at="2026-10-31T12:00:00+00:00",
                cf_ray="example-ray", scope="global",
            )
            try:
                with core.web_app.app_context():
                    response, status = core.web_health()
                    payload = response.get_json()
                self.assertEqual(status, 200)
                self.assertEqual(payload["status"], "rate_limited")
                self.assertFalse(payload["discord_ready"])
                self.assertEqual(payload["cf_ray"], "example-ray")
                self.assertEqual(payload["retry_at"], "2026-10-31T12:00:00+00:00")
            finally:
                core.set_discord_connection("starting")


if __name__ == "__main__":
    unittest.main()
