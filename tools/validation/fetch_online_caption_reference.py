"""Fetch publisher English references for evaluation, never for recognition."""
import argparse
import json
from pathlib import Path
import requests


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.trust_env = False
    for name, video_id in [('new_thirty_days','1183'),('new_movement','814'),('new_champion','1728')]:
        path = a.output/(name+'.json')
        if path.exists():
            raise FileExistsError(path)
        query = 'query($id:ID!){translation(videoId:$id,language:"en"){paragraphs{cues{text time}}}}'
        response = session.post('https://www.ted.com/graphql',json={'query':query,'variables':{'id':video_id}},timeout=30)
        response.raise_for_status()
        data = response.json()
        if not data.get('data',{}).get('translation'):
            raise ValueError(data)
        path.write_text(json.dumps({'source':'https://www.ted.com/graphql','video_id':video_id,
            'purpose':'evaluation_only_not_model_prompt','reference_kind':'publisher_caption_not_verbatim_audio_gold',
            'response':data},ensure_ascii=False,indent=2),encoding='utf-8')
        print(name+' official reference saved',flush=True)


if __name__ == '__main__':
    main()
