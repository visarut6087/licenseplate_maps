"""Download the OCR base model and the ready-to-use TLPR adapter."""
from .config import BASE_MODEL_REPO, LOCAL_BASE_MODEL, MODEL, OCR_ADAPTER_REPO
from huggingface_hub import snapshot_download
from huggingface_hub import constants

if __name__ == '__main__':
    # Smaller chunks avoid stalled large-file transfers on some Windows networks.
    constants.DOWNLOAD_CHUNK_SIZE = 1024 * 1024
    LOCAL_BASE_MODEL.mkdir(parents=True, exist_ok=True)
    path = snapshot_download(BASE_MODEL_REPO, local_dir=LOCAL_BASE_MODEL, max_workers=1)
    print(f'OCR base model ready: {path}')
    adapter = snapshot_download(
        OCR_ADAPTER_REPO,
        local_dir=MODEL / 'ocr',
        allow_patterns=[
            'adapter_config.json', 'adapter_model.safetensors', 'added_tokens.json',
            'chat_template.jinja', 'merges.txt', 'special_tokens_map.json',
            'tokenizer.json', 'tokenizer_config.json', 'vocab.json', 'README.md',
        ],
        max_workers=1,
    )
    print(f'OCR adapter ready: {adapter}')
