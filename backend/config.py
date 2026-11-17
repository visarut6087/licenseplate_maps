import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('HF_HOME', str(ROOT / '.cache' / 'huggingface'))
MODEL = ROOT / 'model'
RESULTS = Path(os.getenv('RESULTS_DIR', ROOT / 'results')).resolve()
UPLOADS = ROOT / 'uploads'
BASE_MODEL = os.getenv('OCR_BASE_MODEL', 'scb10x/typhoon-ocr1.5-2b')
DEVICE = os.getenv('MODEL_DEVICE', 'auto')
INTERVAL = float(os.getenv('INFERENCE_INTERVAL', '1.0'))
COOLDOWN = float(os.getenv('PLATE_COOLDOWN', '15'))
MAX_UPLOAD = int(os.getenv('MAX_UPLOAD_MB', '2048')) * 1024 * 1024
