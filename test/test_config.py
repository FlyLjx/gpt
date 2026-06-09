import json
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ROOT_CONFIG_FILE = ROOT_DIR / "config.json"


class ConfigLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._created_root_config = False
        if not ROOT_CONFIG_FILE.exists():
            ROOT_CONFIG_FILE.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
            cls._created_root_config = True

        from services import config as config_module

        cls.config_module = config_module

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._created_root_config and ROOT_CONFIG_FILE.exists():
            ROOT_CONFIG_FILE.unlink()

    def test_load_settings_ignores_directory_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            data_dir = base_dir / "data"
            config_dir = base_dir / "config.json"
            os_auth_key = "env-auth"

            config_dir.mkdir()

            module = self.config_module
            old_base_dir = module.BASE_DIR
            old_data_dir = module.DATA_DIR
            old_config_file = module.CONFIG_FILE
            old_env_auth_key = module.os.environ.get("CHATGPT2API_AUTH_KEY")
            try:
                module.BASE_DIR = base_dir
                module.DATA_DIR = data_dir
                module.CONFIG_FILE = config_dir
                module.os.environ["CHATGPT2API_AUTH_KEY"] = os_auth_key

                settings = module._load_settings()

                self.assertEqual(settings.auth_key, os_auth_key)
                self.assertEqual(settings.refresh_account_interval_minute, 5)
            finally:
                module.BASE_DIR = old_base_dir
                module.DATA_DIR = old_data_dir
                module.CONFIG_FILE = old_config_file
                if old_env_auth_key is None:
                    module.os.environ.pop("CHATGPT2API_AUTH_KEY", None)
                else:
                    module.os.environ["CHATGPT2API_AUTH_KEY"] = old_env_auth_key

    def test_notification_settings_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            module = self.config_module
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(json.dumps({
                "auth-key": "test-auth",
                "notifications": {
                    "bark": {
                        "enabled": "true",
                        "server_url": "https://example.com/",
                        "device_key": "  bark-key  ",
                        "level": "unknown",
                        "timeout_secs": "999",
                        "min_interval_seconds": "-5",
                        "notify_register_errors_only": "yes",
                    }
                },
            }), encoding="utf-8")
            store = module.ConfigStore(config_file)

            settings = store.get_notification_settings()["bark"]

            self.assertTrue(settings["enabled"])
            self.assertEqual(settings["server_url"], "https://example.com")
            self.assertEqual(settings["device_key"], "bark-key")
            self.assertEqual(settings["level"], "active")
            self.assertEqual(settings["timeout_secs"], 60)
            self.assertEqual(settings["min_interval_seconds"], 0)
            self.assertTrue(settings["notify_register_errors_only"])

    def test_timezone_defaults_to_shanghai(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            module = self.config_module
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
            old_env_timezone = module.os.environ.pop("CHATGPT2API_TIMEZONE", None)
            old_tz = module.os.environ.pop("TZ", None)
            try:
                store = module.ConfigStore(config_file)
                self.assertEqual(store.timezone, "Asia/Shanghai")
                self.assertEqual(store.get()["timezone"], "Asia/Shanghai")
            finally:
                if old_env_timezone is not None:
                    module.os.environ["CHATGPT2API_TIMEZONE"] = old_env_timezone
                if old_tz is not None:
                    module.os.environ["TZ"] = old_tz

    def test_timezone_env_overrides_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            module = self.config_module
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(json.dumps({"auth-key": "test-auth", "timezone": "UTC"}), encoding="utf-8")
            old_env_timezone = module.os.environ.get("CHATGPT2API_TIMEZONE")
            try:
                module.os.environ["CHATGPT2API_TIMEZONE"] = "Asia/Tokyo"
                store = module.ConfigStore(config_file)
                self.assertEqual(store.timezone, "Asia/Tokyo")
                self.assertEqual(store.get()["timezone"], "Asia/Tokyo")
            finally:
                if old_env_timezone is None:
                    module.os.environ.pop("CHATGPT2API_TIMEZONE", None)
                else:
                    module.os.environ["CHATGPT2API_TIMEZONE"] = old_env_timezone

    def test_update_timezone_applies_process_timezone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            module = self.config_module
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
            old_env_timezone = module.os.environ.pop("CHATGPT2API_TIMEZONE", None)
            old_tz = module.os.environ.get("TZ")
            try:
                store = module.ConfigStore(config_file)
                updated = store.update({"timezone": "UTC"})
                self.assertEqual(updated["timezone"], "UTC")
                self.assertEqual(module.os.environ.get("TZ"), "UTC")
            finally:
                if old_env_timezone is not None:
                    module.os.environ["CHATGPT2API_TIMEZONE"] = old_env_timezone
                if old_tz is None:
                    module.os.environ.pop("TZ", None)
                else:
                    module.os.environ["TZ"] = old_tz
                    module._apply_process_timezone(old_tz)

    def test_local_time_text_uses_configured_timezone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            module = self.config_module
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(json.dumps({"auth-key": "test-auth", "timezone": "Asia/Shanghai"}), encoding="utf-8")
            old_config = module.config
            old_env_timezone = module.os.environ.pop("CHATGPT2API_TIMEZONE", None)
            try:
                module.config = module.ConfigStore(config_file)
                self.assertEqual(module.local_time_text(0), "1970-01-01 08:00:00")
                self.assertEqual(module.local_date_parts(0), ("1970", "01", "01"))
                module.config.update({"timezone": "UTC"})
                self.assertEqual(module.local_time_text(0), "1970-01-01 00:00:00")
            finally:
                module.config = old_config
                if old_env_timezone is not None:
                    module.os.environ["CHATGPT2API_TIMEZONE"] = old_env_timezone

    def test_enabled_bark_requires_device_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            module = self.config_module
            config_file = Path(tmp_dir) / "config.json"
            config_file.write_text(json.dumps({"auth-key": "test-auth"}), encoding="utf-8")
            store = module.ConfigStore(config_file)

            with self.assertRaises(ValueError):
                store.update({"notifications": {"bark": {"enabled": True, "device_key": ""}}})


if __name__ == "__main__":
    unittest.main()
