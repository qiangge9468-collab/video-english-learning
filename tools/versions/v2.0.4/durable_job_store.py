import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class DurableJobStore:
    """Disk-backed uploads, audio cache, jobs, and subtitle results."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.uploads_dir = os.path.join(self.root, "uploads")
        self.audio_dir = os.path.join(self.root, "audio")
        self.jobs_dir = os.path.join(self.root, "jobs")
        self.cache_dir = os.path.join(self.root, "cache")
        self._lock = threading.RLock()
        for path in (self.uploads_dir, self.audio_dir, self.jobs_dir, self.cache_dir):
            os.makedirs(path, exist_ok=True)

    @staticmethod
    def validate_hash(audio_hash):
        value = str(audio_hash or "").strip().lower()
        if not _HASH_RE.fullmatch(value):
            raise ValueError("audio_hash must be a 64-character SHA-256 hex string")
        return value

    @staticmethod
    def _extension(mime_type):
        value = str(mime_type or "").lower()
        if "wav" in value:
            return ".wav"
        if "mpeg" in value or "mp3" in value:
            return ".mp3"
        return ".m4a"

    @staticmethod
    def sha256_file(path):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _read_json(path, default=None):
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                value = json.load(handle)
                return value
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default

    @staticmethod
    def _write_json(path, value):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp = f"{path}.{uuid.uuid4().hex}.tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)

    def _upload_meta_path(self, upload_id):
        return os.path.join(self.uploads_dir, f"{upload_id}.json")

    def _upload_part_path(self, upload_id):
        return os.path.join(self.uploads_dir, f"{upload_id}.part")

    def _job_dir(self, job_id):
        return os.path.join(self.jobs_dir, job_id)

    def _job_status_path(self, job_id):
        return os.path.join(self._job_dir(job_id), "status.json")

    def _job_result_path(self, job_id):
        return os.path.join(self._job_dir(job_id), "result.json")

    def _cache_path(self, audio_hash, name):
        return os.path.join(self.cache_dir, audio_hash, name)

    def create_upload(self, audio_hash, total_bytes, mime_type, video_title=""):
        audio_hash = self.validate_hash(audio_hash)
        total_bytes = int(total_bytes)
        if total_bytes <= 0:
            raise ValueError("total_bytes must be positive")
        if total_bytes > 2 * 1024 * 1024 * 1024:
            raise ValueError("upload is larger than 2048 MB")
        upload_id = audio_hash
        meta_path = self._upload_meta_path(upload_id)
        part_path = self._upload_part_path(upload_id)
        with self._lock:
            existing = self._read_json(meta_path, {}) or {}
            if existing and int(existing.get("total_bytes", total_bytes)) != total_bytes:
                raise ValueError("audio hash already exists with a different size")
            extension = existing.get("extension") or self._extension(mime_type)
            audio_path = os.path.join(self.audio_dir, f"{audio_hash}{extension}")
            complete = os.path.isfile(audio_path) and os.path.getsize(audio_path) == total_bytes
            if complete:
                offset = total_bytes
            else:
                offset = os.path.getsize(part_path) if os.path.isfile(part_path) else 0
                if offset > total_bytes:
                    os.remove(part_path)
                    offset = 0
            now = time.time()
            meta = {
                "upload_id": upload_id,
                "audio_hash": audio_hash,
                "total_bytes": total_bytes,
                "offset": offset,
                "mime_type": mime_type or "application/octet-stream",
                "extension": extension,
                "video_title": video_title or existing.get("video_title", ""),
                "complete": complete,
                "audio_path": audio_path if complete else "",
                "created_at": existing.get("created_at", now),
                "updated_at": now,
            }
            self._write_json(meta_path, meta)
            return dict(meta)

    def get_upload(self, upload_id):
        with self._lock:
            meta = self._read_json(self._upload_meta_path(upload_id))
            if not isinstance(meta, dict):
                return None
            if meta.get("complete") and os.path.isfile(meta.get("audio_path", "")):
                meta["offset"] = int(meta.get("total_bytes", 0))
            else:
                part_path = self._upload_part_path(upload_id)
                meta["offset"] = os.path.getsize(part_path) if os.path.isfile(part_path) else 0
            return meta

    def append_upload(self, upload_id, start, content_length, source):
        content_length = int(content_length)
        start = int(start)
        if content_length <= 0:
            raise ValueError("empty upload chunk")
        with self._lock:
            meta = self.get_upload(upload_id)
            if meta is None:
                raise KeyError("upload not found")
            if meta.get("complete"):
                return meta
            expected = int(meta.get("offset", 0))
            if start != expected:
                raise ValueError(f"offset mismatch: expected {expected}, got {start}")
            total = int(meta["total_bytes"])
            if start + content_length > total:
                raise ValueError("chunk exceeds declared upload size")
            part_path = self._upload_part_path(upload_id)
            remaining = content_length
            with open(part_path, "ab") as output:
                while remaining > 0:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ConnectionError(f"chunk ended with {remaining} bytes missing")
                    output.write(chunk)
                    remaining -= len(chunk)
                output.flush()
                os.fsync(output.fileno())
            meta["offset"] = start + content_length
            meta["updated_at"] = time.time()
            self._write_json(self._upload_meta_path(upload_id), meta)
            return dict(meta)

    def finalize_upload(self, upload_id):
        with self._lock:
            meta = self.get_upload(upload_id)
            if meta is None:
                raise KeyError("upload not found")
            if meta.get("complete"):
                return meta
            if int(meta.get("offset", 0)) != int(meta.get("total_bytes", 0)):
                raise ValueError(f"upload incomplete: {meta.get('offset', 0)}/{meta.get('total_bytes', 0)}")
            part_path = self._upload_part_path(upload_id)
            actual_hash = self.sha256_file(part_path)
            if actual_hash != meta["audio_hash"]:
                os.remove(part_path)
                meta["offset"] = 0
                self._write_json(self._upload_meta_path(upload_id), meta)
                raise ValueError("uploaded audio SHA-256 does not match")
            audio_path = os.path.join(self.audio_dir, f"{meta['audio_hash']}{meta['extension']}")
            os.replace(part_path, audio_path)
            meta["complete"] = True
            meta["offset"] = int(meta["total_bytes"])
            meta["audio_path"] = audio_path
            meta["updated_at"] = time.time()
            self._write_json(self._upload_meta_path(upload_id), meta)
            return dict(meta)

    def import_audio(self, source_path, mime_type="audio/mp4", video_title=""):
        audio_hash = self.sha256_file(source_path)
        total = os.path.getsize(source_path)
        meta = self.create_upload(audio_hash, total, mime_type, video_title)
        if not meta.get("complete"):
            target = os.path.join(self.audio_dir, f"{audio_hash}{meta['extension']}")
            shutil.move(source_path, target)
            meta.update(complete=True, offset=total, audio_path=target, updated_at=time.time())
            self._write_json(self._upload_meta_path(audio_hash), meta)
        elif os.path.abspath(source_path) != os.path.abspath(meta["audio_path"]):
            try:
                os.remove(source_path)
            except OSError:
                pass
        return dict(meta)

    def find_active_job(self, audio_hash, mode):
        for job_id in self.list_job_ids():
            status = self._read_json(self._job_status_path(job_id), {}) or {}
            if status.get("audio_hash") == audio_hash and status.get("mode") == mode and status.get("status") in ("queued", "running"):
                return status
        return None

    def create_job(self, audio_hash, audio_path, video_title="", mode="generate", force=False, input_payload=None):
        audio_hash = self.validate_hash(audio_hash)
        if mode not in ("generate", "retranslate"):
            raise ValueError("unsupported job mode")
        job_id = uuid.uuid4().hex
        now = time.time()
        status = {
            "id": job_id,
            "job_id": job_id,
            "audio_hash": audio_hash,
            "audio_path": audio_path or "",
            "video_title": video_title or "",
            "mode": mode,
            "force": bool(force),
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "stage_progress": 0,
            "processed_seconds": 0,
            "total_seconds": 0,
            "message": "Queued on computer",
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._write_json(self._job_status_path(job_id), status)
            if input_payload is not None:
                self._write_json(os.path.join(self._job_dir(job_id), "input.json"), input_payload)
        return dict(status)

    def get_job(self, job_id, include_result=True):
        with self._lock:
            status = self._read_json(self._job_status_path(job_id))
            if not isinstance(status, dict):
                return None
            if include_result and status.get("status") == "done":
                status["result"] = self._read_json(self._job_result_path(job_id), []) or []
            return status

    def update_job(self, job_id, **changes):
        with self._lock:
            status = self.get_job(job_id, include_result=False)
            if status is None:
                return None
            status.update({key: value for key, value in changes.items() if value is not None})
            status["updated_at"] = time.time()
            self._write_json(self._job_status_path(job_id), status)
            return dict(status)

    def finish_job(self, job_id, result):
        with self._lock:
            self._write_json(self._job_result_path(job_id), result)
            return self.update_job(
                job_id,
                status="done",
                stage="done",
                progress=100,
                stage_progress=100,
                message=f"Generated {len(result)} bilingual subtitles",
                error=None,
            )

    def fail_job(self, job_id, error):
        return self.update_job(job_id, status="error", stage="error", message=str(error), error=str(error))

    def save_english(self, audio_hash, segments):
        clean = [dict(item, translation="") for item in segments]
        self._write_json(self._cache_path(audio_hash, "english.json"), clean)

    def load_english(self, audio_hash):
        return self._read_json(self._cache_path(audio_hash, "english.json"))

    def save_bilingual(self, audio_hash, segments):
        self._write_json(self._cache_path(audio_hash, "bilingual.json"), segments)

    def load_bilingual(self, audio_hash):
        return self._read_json(self._cache_path(audio_hash, "bilingual.json"))

    def save_artifact(self, audio_hash, name, value):
        """Persist a versioned diagnostic artifact beside subtitle caches."""
        audio_hash = self.validate_hash(audio_hash)
        safe_name = str(name or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+\.json", safe_name):
            raise ValueError("artifact name must be a simple .json filename")
        self._write_json(self._cache_path(audio_hash, safe_name), value)

    def load_artifact(self, audio_hash, name, default=None):
        audio_hash = self.validate_hash(audio_hash)
        safe_name = str(name or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+\.json", safe_name):
            raise ValueError("artifact name must be a simple .json filename")
        return self._read_json(self._cache_path(audio_hash, safe_name), default)

    def job_input(self, job_id):
        return self._read_json(os.path.join(self._job_dir(job_id), "input.json"), {}) or {}

    def list_job_ids(self):
        try:
            return [name for name in os.listdir(self.jobs_dir) if os.path.isdir(os.path.join(self.jobs_dir, name))]
        except OSError:
            return []

    def recoverable_jobs(self):
        jobs = []
        for job_id in self.list_job_ids():
            status = self.get_job(job_id, include_result=False)
            if status and status.get("status") in ("queued", "running"):
                jobs.append(status)
        return sorted(jobs, key=lambda item: item.get("created_at", 0))
