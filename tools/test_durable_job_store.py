import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from tools.durable_job_store import DurableJobStore


class DurableJobStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = DurableJobStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_resumable_upload_survives_store_restart(self):
        payload = (b"durable audio bytes\n" * 10000) + b"end"
        audio_hash = hashlib.sha256(payload).hexdigest()
        created = self.store.create_upload(audio_hash, len(payload), "audio/mp4", "video.mp4")
        halfway = len(payload) // 2
        first = self.store.append_upload(created["upload_id"], 0, halfway, io.BytesIO(payload[:halfway]))
        self.assertEqual(first["offset"], halfway)

        restarted = DurableJobStore(self.root)
        recovered = restarted.get_upload(created["upload_id"])
        self.assertEqual(recovered["offset"], halfway)
        restarted.append_upload(created["upload_id"], halfway, len(payload) - halfway, io.BytesIO(payload[halfway:]))
        finished = restarted.finalize_upload(created["upload_id"])

        self.assertTrue(finished["complete"])
        self.assertEqual(Path(finished["audio_path"]).read_bytes(), payload)
        reused = restarted.create_upload(audio_hash, len(payload), "audio/mp4", "video.mp4")
        self.assertTrue(reused["audio_cached"] if "audio_cached" in reused else reused["complete"])
        self.assertEqual(reused["offset"], len(payload))

    def test_offset_mismatch_does_not_corrupt_partial_file(self):
        payload = b"0123456789"
        audio_hash = hashlib.sha256(payload).hexdigest()
        upload = self.store.create_upload(audio_hash, len(payload), "audio/mp4")
        self.store.append_upload(upload["upload_id"], 0, 4, io.BytesIO(payload[:4]))
        with self.assertRaisesRegex(ValueError, "offset mismatch"):
            self.store.append_upload(upload["upload_id"], 2, 4, io.BytesIO(payload[2:6]))
        self.assertEqual(self.store.get_upload(upload["upload_id"])["offset"], 4)

    def test_jobs_and_subtitle_cache_survive_restart(self):
        payload = b"audio"
        audio_hash = hashlib.sha256(payload).hexdigest()
        source = self.root / "source.m4a"
        source.write_bytes(payload)
        upload = self.store.import_audio(source, "audio/mp4", "test.mp4")
        job = self.store.create_job(audio_hash, upload["audio_path"], "test.mp4")
        english = [{"start": 0.0, "end": 1.0, "text": "Hello", "translation": ""}]
        bilingual = [{"start": 0.0, "end": 1.0, "text": "Hello", "translation": "你好"}]
        self.store.save_english(audio_hash, english)
        self.store.save_bilingual(audio_hash, bilingual)
        self.store.finish_job(job["job_id"], bilingual)

        restarted = DurableJobStore(self.root)
        recovered = restarted.get_job(job["job_id"])
        self.assertEqual(recovered["status"], "done")
        self.assertEqual(recovered["result"], bilingual)
        self.assertEqual(restarted.load_english(audio_hash), english)
        self.assertEqual(restarted.load_bilingual(audio_hash), bilingual)


if __name__ == "__main__":
    unittest.main()
