import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
V210 = ROOT / "tools" / "versions" / "v2.1.0"
V206 = ROOT / "tools" / "versions" / "v2.0.6"


class PrivatePairingV210Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = (V210 / "start_service.ps1").read_text(encoding="utf-8-sig")
        cls.service = (V210 / "service.py").read_text(encoding="utf-8")
        cls.dashboard = (V210 / "dashboard.html").read_text(encoding="utf-8")
        cls.manifest = (ROOT / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
        cls.receiver = (ROOT / "app" / "src" / "main" / "java" / "com" / "codex" /
                        "videolearnenglish" / "ServiceConfigReceiver.kt").read_text(encoding="utf-8")
        cls.activity = (ROOT / "app" / "src" / "main" / "java" / "com" / "codex" /
                        "videolearnenglish" / "LearningActivity.kt").read_text(encoding="utf-8")

    def test_v210_is_independent_and_v206_is_preserved(self):
        self.assertTrue((V210 / "service.py").is_file())
        self.assertTrue((V206 / "service.py").is_file())
        self.assertIn('SERVICE_VERSION = "2.1.0"', self.service)
        self.assertIn("v2.0.6", (V206 / "service.py").read_text(encoding="utf-8"))

    def test_private_network_is_default_and_public_is_opt_in(self):
        self.assertIn("[switch]$EnablePublicTunnel", self.launcher)
        self.assertNotIn("[switch]$NoPublicTunnel", self.launcher)
        self.assertIn("serve --bg $Port", self.launcher)
        self.assertIn('privacy_mode = $(if ($PublicBase) { "public_opt_in" } else { "private" })', self.launcher)
        self.assertIn("Tailscale 私网", self.dashboard)

    def test_token_is_persistent_and_runtime_data_is_not_shared(self):
        self.assertIn('service_data_v2.1.0', self.launcher)
        self.assertIn('service_auth_token.txt', self.launcher)
        self.assertIn('service_data_v2.1.0', self.service)

    def test_usb_pairing_is_permission_protected(self):
        self.assertIn('android:permission="android.permission.DUMP"', self.manifest)
        self.assertIn("com.codex.videolearnenglish.APPLY_SERVICE_CONFIG", self.manifest)
        self.assertIn("config_base64", self.launcher)
        self.assertIn("ServiceConfigReceiver", self.launcher)
        self.assertIn("SCHEMA_VERSION", self.receiver)

    def test_usb_lan_tailscale_and_public_candidates_are_published(self):
        for marker in ("transcribe_urls", "lan_urls", "tailscale_url", "public_url"):
            self.assertIn(marker, self.launcher)
        self.assertIn("saved.get(\"tailscale_url\")", self.service)

    def test_phone_keeps_manual_public_address_entry(self):
        self.assertIn("Whisper 服务地址", self.activity)
        self.assertIn('.setPositiveButton("保存")', self.activity)
        self.assertIn('.setNeutralButton("测试")', self.activity)
        self.assertIn("手动填写", self.activity)


if __name__ == "__main__":
    unittest.main()
