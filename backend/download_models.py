"""Run from project root: python -m backend.download_models"""
from .config import BASE_MODEL
from huggingface_hub import snapshot_download
from huggingface_hub import constants

if __name__ == '__main__':
    # Smaller chunks avoid stalled large-file transfers on some Windows networks.
    constants.DOWNLOAD_CHUNK_SIZE = 1024 * 1024
    path = snapshot_download(BASE_MODEL, max_workers=1)
    print(f'OCR base model ready: {path}')
