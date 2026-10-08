"""Download isolated, pinned Parakeet comparison assets; never upload media.

Uses HTTPS verification and checks published SHA-256 digests. No installation,
service configuration changes, or remote Python/model code execution.
"""
import argparse
import hashlib
import json
from pathlib import Path

import requests

REPO = 'csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8'
REVISION = '1ab9323565ddb038682214b292f588070a538ce2'
MODELS = {
    'encoder.int8.onnx': 'a32b12d17bbbc309d0686fbbcc2987b5e9b8333a7da83fa6b089f0a2acd651ab',
    'decoder.int8.onnx': 'b6bb64963457237b900e496ee9994b59294526439fbcc1fecf705b31a15c6b4e',
    'joiner.int8.onnx': '7946164367946e7f9f29a122407c3252b680dbae9a51343eb2488d057c3c43d2',
    'tokens.txt': None,
    'README.md': None,
}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def download(session, url, destination, expected=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        actual = digest(destination)
        if expected and actual != expected:
            raise ValueError(f'Existing file digest mismatch: {destination}')
        return actual
    partial = destination.with_name(destination.name+'.partial')
    if partial.exists():
        raise FileExistsError(f'Preserve interrupted download before retry: {partial}')
    print('DOWNLOAD '+destination.name, flush=True)
    with session.get(url, stream=True, timeout=(15, 60)) as response:
        response.raise_for_status()
        size, next_notice = 0, 32*1024*1024
        with partial.open('xb') as stream:
            for block in response.iter_content(1024*1024):
                stream.write(block)
                size += len(block)
                if size >= next_notice:
                    print(f'{destination.name}: {size//1024//1024} MiB', flush=True)
                    next_notice += 32*1024*1024
    actual = digest(partial)
    if expected and expected != actual:
        raise ValueError(f'Download digest mismatch; partial retained: {partial}')
    partial.rename(destination)
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    records = []
    session = requests.Session()
    for name, sha in MODELS.items():
        url = f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}'
        destination = args.output/'models/parakeet-tdt-v2-int8'/name
        actual = download(session, url, destination, sha)
        records.append({'path': str(destination), 'source': url, 'sha256': actual,
                        'upstream_sha256_verified': sha is not None})
    for package in ('sherpa-onnx', 'sherpa-onnx-core'):
        response = session.get(f'https://pypi.org/pypi/{package}/1.13.8/json', timeout=15)
        response.raise_for_status()
        files = [f for f in response.json()['urls'] if 'win_amd64' in f['filename'] and
                 ('cp311' in f['filename'] or 'py3-none' in f['filename'])]
        if len(files) != 1:
            raise ValueError(f'Expected one Windows Python 3.11 wheel for {package}')
        artifact = files[0]
        destination = args.output/'wheels'/artifact['filename']
        actual = download(session, artifact['url'], destination, artifact['digests']['sha256'])
        records.append({'path': str(destination), 'source': artifact['url'], 'sha256': actual,
                        'upstream_sha256_verified': True})
    (args.output/'parakeet-downloads.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print('Downloads verified. Nothing installed or enabled in the live service.', flush=True)


if __name__ == '__main__':
    main()
