"""Isolated loopback service for emulator tests; never uses production jobs/tokens."""
import argparse
import os
from pathlib import Path
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--port', type=int, default=18790)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    root = a.model_root.resolve()
    os.environ.update(VIDEO_ENGLISH_DATA_DIR=str(a.output.resolve()/'data'),
        WHISPER_HOST='127.0.0.1', WHISPER_PORT=str(a.port), WHISPER_AUTH_TOKEN='context-emulator-test-only',
        WHISPER_RUNTIME_CONFIG=str(a.output.resolve()/'config.json'),
        WHISPER_RUNTIME_STATUS=str(a.output.resolve()/'status.json'),
        WHISPER_DEVICE='cuda', WHISPER_COMPUTE_TYPE='int8_float16',
        WHISPERX_MODEL_DIR=str(root/'whisperx'),
        TRANSLATION_CONTEXT_MODE='auto', TRANSLATION_STYLE='generic',
        TRANSLATION_PROVIDER='transformers', TRANSLATION_MODEL=str(root/'nllb-200-distilled-600M'),
        SAT_MODEL_DIR=str(root/'sat-12l-sm'), SAT_TOKENIZER_DIR=str(root/'xlm-roberta-base'))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'versions/v2.1.0'))
    import service
    # The test checkout has no model copy. Reuse weights read-only, not cached jobs.
    for key, value in list(vars(service).items()):
        if key.startswith('LOCAL_') and key.endswith('_MODEL_DIR'):
            setattr(service, key, str(root/Path(value).name))
    service.MODELS_DIR = str(root)
    try:
        service.main()
    finally:
        if service._context_translator:
            service._context_translator.unload()
            service._context_translator.close()


if __name__ == '__main__':
    main()
