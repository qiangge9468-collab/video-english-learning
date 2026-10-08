"""Download publisher-provided media into an isolated holdout directory.

Never burns captions into a video or uses reference text as an ASR prompt.
Sources must be explicitly selected before inference; partial downloads survive.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import requests


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('sources', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--ffmpeg', required=True)
    p.add_argument('--ffprobe', required=True)
    a = p.parse_args()
    sources = json.loads(a.sources.read_text(encoding='utf-8-sig'))
    a.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.trust_env = False
    manifest = []
    for item in sources:
        name = item['name']
        if not name.replace('_', '').isalnum():
            raise ValueError('Unsafe item name')
        folder = a.output/name
        folder.mkdir(exist_ok=True)
        video, audio = folder/'video.mp4', folder/'audio.wav'
        if not video.exists():
            partial = folder/'video.mp4.partial'
            print('DOWNLOAD '+name, flush=True)
            with session.get(item['download_url'], stream=True, timeout=(20, 60)) as r:
                r.raise_for_status()
                total = 0
                with partial.open('xb') as f:
                    for block in r.iter_content(1024*1024):
                        total += len(block)
                        if total > 350*1024*1024:
                            raise ValueError('Per-file download size cap exceeded')
                        f.write(block)
                if r.headers.get('Content-Length') and total != int(r.headers['Content-Length']):
                    raise ValueError('Incomplete download')
            partial.rename(video)
        probe = json.loads(subprocess.check_output([a.ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(video)]))
        if not audio.exists():
            subprocess.run([a.ffmpeg, '-v', 'error', '-n', '-i', str(video), '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(audio)], check=True)
        import av
        from PIL import Image, ImageDraw
        duration = float(probe['format']['duration'])
        sheet = Image.new('RGB', (1280, 760), '#202020')
        draw = ImageDraw.Draw(sheet)
        with av.open(str(video)) as container:
            stream = container.streams.video[0]
            for index, fraction in enumerate((.1, .3, .6, .85)):
                second = duration*fraction
                container.seek(int(second/stream.time_base), stream=stream)
                frame = next(f for f in container.decode(video=0) if f.time >= second)
                im = frame.to_image()
                im.thumbnail((640, 350))
                x, y = (index%2)*640, (index//2)*380
                sheet.paste(im, (x, y+25))
                draw.text((x+5,y+5), f'{name} {frame.time:.2f}s', fill='white')
        sheet.save(folder/'hardcaption-preview.jpg')
        record = {**item, 'video': str(video.resolve()), 'audio': str(audio.resolve()),
                  'cache': str((folder/'no_prior_cache').resolve()), 'duration': duration,
                  'video_sha256': digest(video), 'audio_sha256': digest(audio),
                  'hardcaption_verified': False, 'scope': 'complete_publisher_video',
                  'probe': probe}
        (folder/'provenance.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        manifest.append(record)
        (a.output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(f'PREPARED {name}: {duration:.3f}s', flush=True)


if __name__ == '__main__':
    main()
