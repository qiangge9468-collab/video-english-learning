import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request


SERVICE_PATH = Path(__file__).with_name("local_whisper_service_v2.0.5.py")


def load_service(temp_dir):
    os.environ["VIDEO_ENGLISH_DATA_DIR"] = str(Path(temp_dir) / "data")
    os.environ["WHISPER_RUNTIME_STATUS"] = str(Path(temp_dir) / "runtime_status.json")
    os.environ["WHISPER_RUNTIME_CONFIG"] = str(Path(temp_dir) / "runtime_config.json")
    spec = importlib.util.spec_from_file_location("local_whisper_service_v205_dashboard_test", SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DashboardV205Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="video_english_dashboard_v205_")
        cls.service = load_service(cls.temp.name)
        cls.service.gpu_status = lambda: {
            "available": True,
            "name": "Test GPU",
            "utilization_percent": 42,
            "memory_used_mb": 1024,
            "memory_total_mb": 4096,
            "temperature_c": 55,
        }

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        for job_id in self.service.JOB_STORE.list_job_ids():
            job_dir = Path(self.service.JOB_STORE.jobs_dir) / job_id
            for item in job_dir.iterdir():
                item.unlink()
            job_dir.rmdir()
        self.service.AUTH_TOKEN = ""
        self.service.write_runtime_status(
            current_job_id="",
            video_title="",
            job_status="idle",
            stage="idle",
            progress=0,
            message="Waiting for a phone request",
        )

    def make_job(self, title, status="queued", position=1):
        audio_hash = ("%064x" % (len(self.service.JOB_STORE.list_job_ids()) + 1))
        job = self.service.JOB_STORE.create_job(audio_hash, "test.m4a", title)
        changes = {
            "status": status,
            "stage": "transcribing" if status == "running" else status,
            "progress": 35 if status == "running" else 0,
            "queue_position": position,
        }
        if status == "running":
            changes.update(
                started_at=time.time() - 120,
                processed_seconds=60,
                total_seconds=180,
                message="faster-whisper-large-v3: 01:00 / 03:00",
            )
        return self.service.JOB_STORE.update_job(job["job_id"], **changes)

    def test_snapshot_exposes_current_title_queue_counts_and_eta(self):
        current = self.make_job("Current hiking video.mp4", "running")
        self.make_job("Next tutorial.mp4", "queued", 1)
        self.service.write_runtime_status(
            current_job_id=current["job_id"],
            video_title=current["video_title"],
            job_status="running",
            stage="transcribing",
            progress=35,
        )

        snapshot = self.service.dashboard_snapshot()

        self.assertEqual("2.0.5", snapshot["service"]["service_version"])
        self.assertEqual("Current hiking video.mp4", snapshot["current_job"]["video_title"])
        self.assertEqual("Next tutorial.mp4", snapshot["queue"][0]["video_title"])
        self.assertEqual(1, snapshot["counts"]["running"])
        self.assertEqual(1, snapshot["counts"]["queued"])
        self.assertGreater(snapshot["eta_seconds"], 0)
        self.assertNotIn("audio_path", snapshot["current_job"])

    def test_dashboard_routes_require_token_and_return_html_and_json(self):
        self.make_job("Visible title.mp4", "running")
        self.service.AUTH_TOKEN = "test-token"
        server = self.service.ThreadingHTTPServer(("127.0.0.1", 0), self.service.TranscribeHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f"{base}/dashboard", timeout=5)
            self.assertEqual(401, error.exception.code)

            html = urllib.request.urlopen(f"{base}/dashboard?token=test-token", timeout=5).read().decode("utf-8")
            self.assertIn("电脑端处理仪表盘", html)
            self.assertIn("/api/dashboard", html)

            payload = json.load(urllib.request.urlopen(f"{base}/api/dashboard?token=test-token", timeout=5))
            self.assertEqual("2.0.5", payload["service"]["service_version"])
            self.assertEqual("Test GPU", payload["system"]["gpu"]["name"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_dashboard_asset_is_self_contained_and_names_key_panels(self):
        html = Path(self.service.DASHBOARD_PATH).read_text(encoding="utf-8")
        for label in ("当前任务", "等待队列", "最近任务", "模型与服务", "连接地址", "预计剩余"):
            self.assertIn(label, html)
        self.assertNotIn("https://", html)


    def test_launcher_opens_dashboard_and_keeps_v205_isolated(self):
        launcher = Path(__file__).with_name("start_video_english_service_v2.0.5.ps1").read_text(encoding="utf-8-sig")
        for expected in (
            "[switch]$NoDashboard",
            "Start-Process $dashboardUrl",
            "local_whisper_service_v2.0.5.py",
            "service_data_v2.0.5",
            "runtime_status_v2.0.5.json",
        ):
            self.assertIn(expected, launcher)
if __name__ == "__main__":
    unittest.main()
