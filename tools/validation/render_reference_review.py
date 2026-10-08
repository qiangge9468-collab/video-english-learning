"""Render local frame/OCR/ASR review sheets; never marks proposals reviewed."""
import argparse
import json
from pathlib import Path
import textwrap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("triage", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--times", required=True, help="Comma-separated seconds")
    args = parser.parse_args()
    import av
    from PIL import Image, ImageDraw, ImageFont
    report = json.loads(args.triage.read_text(encoding="utf-8"))
    times = [float(t) for t in args.times.split(",")]
    sheet = Image.new("RGB", (1000, 400*len(times)), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 19)
    with av.open(str(args.video)) as container:
        stream = container.streams.video[0]
        for row, second in enumerate(times):
            container.seek(int(second/stream.time_base), stream=stream)
            for frame in container.decode(stream):
                if float(frame.time) >= second:
                    image = frame.to_image()
                    image = image.crop((0, int(image.height*.65), image.width, image.height))
                    image.thumbnail((1000, 240))
                    sheet.paste(image, (0, row*400))
                    break
            nearest = min(report["items"], key=lambda cue: abs((cue["start"]+cue["end"])/2-second))
            text = f"Frame {second:.2f}s (UNREVIEWED proposal {nearest['id']})\nOCR: {nearest['text']}\nASR: {nearest.get('candidate_text', '(unmatched)')}"
            y = row*400+240
            for paragraph in text.splitlines():
                for line in textwrap.wrap(paragraph, width=95):
                    draw.text((8, y), line, font=font, fill="black")
                    y += 24
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output)


if __name__ == "__main__":
    main()
