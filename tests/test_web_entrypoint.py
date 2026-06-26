from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from sla_app.web import __main__ as web_main


class WebEntrypointTests(unittest.TestCase):
    def test_server_options_use_safe_local_defaults(self) -> None:
        options = web_main._server_options_from_env({})

        self.assertEqual(options["host"], "127.0.0.1")
        self.assertEqual(options["port"], 8000)
        self.assertEqual(options["proxy_headers"], True)
        self.assertEqual(options["forwarded_allow_ips"], "127.0.0.1")
        self.assertEqual(options["root_path"], "")
        self.assertEqual(options["log_level"], "info")
        self.assertNotIn("timeout_graceful_shutdown", options)

    def test_server_options_parse_reverse_proxy_environment(self) -> None:
        options = web_main._server_options_from_env(
            {
                "SLA_WEB_HOST": "0.0.0.0",
                "SLA_WEB_PORT": "8010",
                "SLA_PROXY_HEADERS": "false",
                "SLA_FORWARDED_ALLOW_IPS": "10.0.0.0/8,172.16.0.0/12",
                "SLA_ROOT_PATH": "/sla",
                "SLA_GRACEFUL_SHUTDOWN_TIMEOUT": "45",
                "SLA_LOG_LEVEL": "warning",
            }
        )

        self.assertEqual(options["host"], "0.0.0.0")
        self.assertEqual(options["port"], 8010)
        self.assertEqual(options["proxy_headers"], False)
        self.assertEqual(options["forwarded_allow_ips"], "10.0.0.0/8,172.16.0.0/12")
        self.assertEqual(options["root_path"], "/sla")
        self.assertEqual(options["log_level"], "warning")
        self.assertEqual(options["timeout_graceful_shutdown"], 45)

    def test_log_level_defaults_and_falls_back_to_info(self) -> None:
        self.assertEqual(web_main._log_level_from_env({}), logging.INFO)
        self.assertEqual(web_main._uvicorn_log_level_from_env({}), "info")
        self.assertEqual(web_main._log_level_from_env({"SLA_LOG_LEVEL": "debug"}), logging.DEBUG)
        self.assertEqual(web_main._uvicorn_log_level_from_env({"SLA_LOG_LEVEL": "debug"}), "debug")
        self.assertEqual(web_main._log_level_from_env({"SLA_LOG_LEVEL": "warn"}), logging.WARNING)
        self.assertEqual(web_main._uvicorn_log_level_from_env({"SLA_LOG_LEVEL": "warn"}), "warning")
        self.assertEqual(web_main._log_level_from_env({"SLA_LOG_LEVEL": "verbose"}), logging.INFO)
        self.assertEqual(web_main._uvicorn_log_level_from_env({"SLA_LOG_LEVEL": "verbose"}), "info")

    def test_main_passes_deployment_options_to_uvicorn(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "SLA_WEB_HOST": "0.0.0.0",
                    "SLA_WEB_PORT": "8010",
                    "SLA_PROXY_HEADERS": "true",
                    "SLA_FORWARDED_ALLOW_IPS": "10.1.2.3",
                    "SLA_ROOT_PATH": "/sla",
                    "SLA_LOG_LEVEL": "debug",
                },
                clear=True,
            ),
            patch.object(web_main.logging, "basicConfig") as basic_config,
            patch.object(web_main.uvicorn, "run") as run,
        ):
            web_main.main()

        basic_config.assert_called_once_with(
            level=logging.DEBUG,
            format="%(levelname)s:%(name)s:%(message)s",
        )
        run.assert_called_once_with(
            "sla_app.web.app:create_app",
            factory=True,
            host="0.0.0.0",
            port=8010,
            proxy_headers=True,
            forwarded_allow_ips="10.1.2.3",
            root_path="/sla",
            log_level="debug",
        )


if __name__ == "__main__":
    unittest.main()
