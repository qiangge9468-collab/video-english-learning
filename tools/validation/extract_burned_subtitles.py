"""Local-only OCR reference extraction. OCR output is NOT reviewed ground truth.

Use an isolated Python with rapidocr-onnxruntime + opencv-python + Pillow.
Every sample (including blank/error samples) is retained for coverage auditing.
No generated subtitle or ASR output is used to select or correct OCR text.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time


def packet_audit(path):
    import av
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stamps = sorted(float(p.pts * stream.time_base) for p in container.demux(stream)
                        if p.pts is not None)
        return {"name": path.name, "container_duration": container.duration / av.time_base,
                "packet_count": len(stamps), "first_pts": stamps[0], "last_pts": stamps[-1],
                "gaps_over_2_seconds": [[round(a, 3), round(b, 3)]
                    for a, b in zip(stamps, stamps[1:]) if b-a > 2]}


def video_info(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    info = {"name": path.name, "path": str(path.resolve()), "fps": fps,
            "duration": cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps,
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "bytes": path.stat().st_size}
    return cap, info


def preview(paths, output):
    import cv2
    from PIL import Image, ImageDraw
    sheet = Image.new("RGB", (960, len(paths) * 210), "#202020")
    draw = ImageDraw.Draw(sheet)
    inventory = []
    for row, path in enumerate(paths):
        cap, info = video_info(path)
        inventory.append(info)
        for col, second in enumerate((60, 180, 600)):
            cap.set(cv2.CAP_PROP_POS_MSEC, min(second, info["duration"] / 2) * 1000)
            ok, frame = cap.read()
            if ok:
                im = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                im.thumbnail((320, 180))
                sheet.paste(im, (col * 320, row * 210 + 30))
        draw.text((5, row * 210 + 5), f"{row}: {path.stem[:65]}", fill="white")
        cap.release()
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    output.with_suffix(".json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")


def decode_available_frames(container, errors):
    import av
    for packet in container.demux(video=0):
        try:
            yield from packet.decode()
        except av.error.InvalidDataError as exc:
            errors.append({"packet_pts": packet.pts, "error": str(exc)})


def extract(path, output, interval, crop_top, end=None, resume=False, rec_model=None):
    import av
    import cv2
    from rapidocr_onnxruntime import RapidOCR
    options = {"rec_model_path": str(rec_model)} if rec_model else {}
    engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1,
                      det_limit_type="max", det_limit_side_len=1280, **options)
    cap, info = video_info(path)
    cap.release()
    audit = packet_audit(path)
    info["nominal_frame_count_duration"] = info["duration"]
    info["duration"] = audit["container_duration"]
    info["packet_audit"] = audit
    stop = min(info["duration"], end) if end else info["duration"]
    output.mkdir(parents=True, exist_ok=True)
    picture_complete = audit["container_duration"] - audit["last_pts"] <= max(1, 2 / info["fps"])
    config = {**info, "interval": interval, "crop_top": crop_top,
              "ocr_engine": "rapidocr-onnxruntime", "reviewed": False,
              "recognition_model": str(rec_model.resolve()) if rec_model else "bundled",
              "complete_video_reference": picture_complete,
              "scope": "all_available_frames" if not end else "pilot_only"}
    if (output / "samples.jsonl").exists() and not resume:
        raise FileExistsError("Existing OCR samples: choose a new output directory or --resume")
    if resume:
        previous = json.loads((output/"source.json").read_text(encoding="utf-8"))
        for key in ("path", "bytes", "interval", "crop_top", "recognition_model"):
            if previous.get(key, "bundled") != config[key]:
                raise ValueError(f"Cannot resume with a different {key}")
    (output / "source.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    started = time.monotonic()
    next_time, frames, samples, nonempty = 0.0, 0, 0, 0
    errors = []
    if resume:
        old = [json.loads(line) for line in (output/"samples.jsonl").read_text(encoding="utf-8").splitlines()]
        samples = len(old)
        nonempty = sum(bool(item["lines"]) for item in old)
        next_time = old[-1]["time"] + interval - .001 if old else 0
    with av.open(str(path)) as container, (output / "samples.jsonl").open("a" if resume else "w", encoding="utf-8") as handle:
        container.streams.video[0].thread_type = "AUTO"
        if next_time:
            container.seek(int(next_time / container.streams.video[0].time_base), stream=container.streams.video[0])
        for decoded in decode_available_frames(container, errors):
            second = float(decoded.time)
            frames += 1
            if second >= stop:
                break
            if second + .0001 < next_time:
                continue
            frame = decoded.to_ndarray(format="bgr24")
            next_time = second + interval - .001
            h, w = frame.shape[:2]
            crop = frame[int(h * crop_top):h, :]
            if w > 1280:
                crop = cv2.resize(crop, (1280, round(crop.shape[0] * 1280 / w)))
            results, _ = engine(crop)
            lines = [{"box": item[0], "text": item[1], "confidence": float(item[2])}
                     for item in (results or [])]
            item = {"time": round(second, 3), "lines": lines}
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            samples += 1
            nonempty += bool(lines)
            if samples % 120 == 0:
                handle.flush()
                print(json.dumps({"video": path.name, "seconds": round(second),
                                  "duration": round(stop), "samples": samples,
                                  "nonempty": nonempty, "elapsed": round(time.monotonic()-started)}), flush=True)
    summary = {"sample_count": samples, "nonempty_samples": nonempty,
               "decoded_frames": frames, "duration": stop,
               "last_video_pts": audit["last_pts"],
               "complete_video_reference": picture_complete and not errors,
               "decode_errors": errors, "resumed": resume,
               "elapsed_seconds": time.monotonic()-started,
               "reviewed": False, "accuracy": None}
    (output / "extraction.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--interval", type=float, default=.5)
    parser.add_argument("--crop-top", type=float, default=.65)
    parser.add_argument("--end", type=float)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--rec-model", type=Path, help="Independent OCR model; never an ASR-derived dictionary")
    args = parser.parse_args()
    if args.interval <= 0 or not 0 <= args.crop_top < 1:
        parser.error("interval must be positive and crop-top must be in [0,1)")
    if args.audit:
        result = [packet_audit(path) for path in sorted(args.video.glob("*.mp4"))]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
    elif args.preview:
        preview(sorted(args.video.glob("*.mp4")), args.output)
    else:
        extract(args.video, args.output, args.interval, args.crop_top, args.end, args.resume, args.rec_model)


if __name__ == "__main__":
    main()
