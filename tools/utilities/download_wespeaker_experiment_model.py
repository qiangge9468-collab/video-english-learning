"""Download the public WeSpeaker English checkpoint, without accounts or tokens."""
import argparse
import hashlib
import json
from pathlib import Path
import requests

URL = "https://wespeaker-1256283475.cos.ap-shanghai.myqcloud.com/models/voxceleb/voxceleb_resnet34_LM.onnx"
SOURCE = "https://github.com/wenet-e2e/wespeaker/blob/master/examples/voxconverse/v2/run.sh"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--direct", action="store_true", help="Use direct HTTPS; certificate verification remains enabled")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output/"voxceleb_resnet34_LM.onnx"
    if target.exists():
        raise FileExistsError("Preserve the existing model")
    part = target.with_suffix(".onnx.partial")
    if part.exists():
        raise FileExistsError("Inspect prior partial download before retrying")
    sha = hashlib.sha256()
    size = 0
    session = requests.Session()
    if args.direct:
        session.trust_env = False
    with session.get(URL, stream=True, timeout=(20, 60)) as response:
        response.raise_for_status()
        with part.open("xb") as stream:
            for chunk in response.iter_content(1024*1024):
                if chunk:
                    stream.write(chunk)
                    sha.update(chunk)
                    size += len(chunk)
        if response.headers.get("Content-Length") and size != int(response.headers["Content-Length"]):
            raise ValueError("Incomplete model download")
    if size < 1024*1024:
        raise ValueError("Unexpected model response")
    part.rename(target)
    provenance = {"url": URL, "official_recipe": SOURCE, "bytes": size, "sha256": sha.hexdigest(),
                  "model_license": "CC-BY-4.0 (VoxCeleb), per WeSpeaker pretrained model documentation",
                  "license_source": "https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md",
                  "account_required": False, "user_audio_uploaded": False}
    (args.output/"provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(json.dumps(provenance))


if __name__ == "__main__":
    main()
