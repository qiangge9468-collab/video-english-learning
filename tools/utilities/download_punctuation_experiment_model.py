"""Pinned isolated punctuation weights; no external code or training-state load."""
import argparse
import json
from pathlib import Path
import requests
from download_caption_validation_assets import download

REVISION='954108a105ef1f89f08b71c25d6e33bb89cde724'
SHA='fb8efcdafa21bf982d03fd1aa86f95227353e7ea624ca08afe2cac7d726a8cb2'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output',type=Path)
    a=p.parse_args()
    session=requests.Session()
    records=[]
    for name in ['config.json','vocab.txt','tokenizer_config.json','special_tokens_map.json','model_args.json','README.md','pytorch_model.bin']:
        url=f'https://huggingface.co/felflare/bert-restore-punctuation/resolve/{REVISION}/{name}'
        actual=download(session,url,a.output/name,SHA if name=='pytorch_model.bin' else None)
        records.append({'name':name,'source':url,'sha256':actual})
    (a.output/'provenance.json').write_text(json.dumps({'revision':REVISION,'files':records},indent=2),encoding='utf-8')
    print('Verified weights downloaded; no production model/config changes.',flush=True)


if __name__=='__main__':main()
