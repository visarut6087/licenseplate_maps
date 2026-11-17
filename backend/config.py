import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('HF_HOME', str(ROOT / '.cache' / 'huggingface'))
MODEL = ROOT / 'model'
RESULTS = Path(os.getenv('RESULTS_DIR', ROOT / 'results')).resolve()
UPLOADS = ROOT / 'uploads'
BASE_MODEL_REPO = os.getenv('OCR_BASE_MODEL_REPO', 'scb10x/typhoon-ocr1.5-2b')
OCR_ADAPTER_REPO = os.getenv('OCR_ADAPTER_REPO', 'Rattatammanoon/hurricane-ocr-tlpr-v1-LoRA')
LOCAL_BASE_MODEL = MODEL / 'ocr-base'
BASE_MODEL = os.getenv('OCR_BASE_MODEL', str(LOCAL_BASE_MODEL))
DEVICE = os.getenv('MODEL_DEVICE', 'auto')
YOLO_CONF = float(os.getenv('YOLO_CONF', '0.50'))
INTERVAL = float(os.getenv('INFERENCE_INTERVAL', '0.5'))
COOLDOWN = float(os.getenv('PLATE_COOLDOWN', '15'))
MAX_UPLOAD = int(os.getenv('MAX_UPLOAD_MB', '2048')) * 1024 * 1024
