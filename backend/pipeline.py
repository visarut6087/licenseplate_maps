"""YOLO detect -> MobileNet(full frame) -> crop -> OCR. No synthetic results."""
import json
import re
import threading
from pathlib import Path

from .config import MODEL, BASE_MODEL, DEVICE, YOLO_CONF


def parse_ocr(raw):
    text = raw.strip()
    match = re.search(r'\{.*\}', text, re.S)
    if match:
        data = json.loads(match.group())
    else:
        data = {}
        fields = {
            'plate number': 'plate_number', 'plate_number': 'plate_number',
            'characters': 'characters', 'digits': 'digits', 'province': 'province',
        }
        for line in text.splitlines():
            clean = re.sub(r'[*#`]', '', line).strip()
            item = re.match(r'([^:]+):\s*(.*)', clean)
            if item and item.group(1).strip().lower() in fields:
                data[fields[item.group(1).strip().lower()]] = item.group(2).strip()
    plate = str(data.get('plate_number') or '').strip()
    digits = str(data.get('digits') or '').strip()
    characters = str(data.get('characters') or '').strip()
    province = str(data.get('province') or '').strip()
    if not plate:
        plate = (characters + digits).strip()
    if not plate:
        raise ValueError('OCR ไม่พบเลขทะเบียน')
    # Some releases place the province in `characters`. Only recover it when that
    # value is clearly not part of the returned plate number.
    if not province and characters and characters.replace(' ', '') not in plate.replace(' ', ''):
        province = characters
    trailing_digits = re.search(r'(\d+)\s*$', plate)
    return dict(plate_number=plate, digits=digits or (trailing_digits.group(1) if trailing_digits else ''),
                province=province, raw_text=raw)


class Pipeline:
    def __init__(self):
        self.ready = False
        self.vision_ready = False
        self.ocr_ready = False
        self.error = None
        self.vision_error = None
        self.ocr_error = None
        self.vision_load_lock = threading.Lock()
        self.ocr_load_lock = threading.Lock()
        self.vision_lock = threading.Lock()
        self.ocr_lock = threading.Lock()
        self.vision_loading = False
        self.ocr_loading = False

    def status(self):
        required = {
            'detector': MODEL / 'weights/detector.pt',
            'classifier': MODEL / 'classify/best.pt',
            'ocr_base_model': Path(BASE_MODEL) / 'config.json',
            'ocr_adapter_config': MODEL / 'ocr/adapter_config.json',
            'ocr_adapter_weights': MODEL / 'ocr/adapter_model.safetensors',
        }
        return dict(ready=self.ready, loading=self.vision_loading or self.ocr_loading, error=self.error,
                    stages={
                        'vision': {'ready': self.vision_ready, 'loading': self.vision_loading, 'error': self.vision_error},
                        'ocr': {'ready': self.ocr_ready, 'loading': self.ocr_loading, 'error': self.ocr_error},
                    }, artifacts={name: path.is_file() for name, path in required.items()})

    @staticmethod
    def _require(paths):
        missing = [path for path in paths if not path.is_file()]
        if missing:
            names = ', '.join(str(path.relative_to(MODEL.parent)) for path in missing)
            raise FileNotFoundError(f'ไฟล์โมเดลยังไม่ครบ: {names}')

    def validate_vision_artifacts(self):
        self._require((
            MODEL / 'weights/detector.pt',
            MODEL / 'classify/best.pt',
            MODEL / 'classify/class_map.json',
        ))

    def validate_ocr_artifacts(self):
        self._require((
            MODEL / 'ocr/adapter_config.json',
            MODEL / 'ocr/adapter_model.safetensors',
        ))
        if not (Path(BASE_MODEL) / 'config.json').is_file():
            raise FileNotFoundError('OCR base model ยังไม่อยู่ใน model/ocr-base')

    def load_vision(self):
        with self.vision_load_lock:
            if self.vision_ready:
                return
            self.vision_loading = True
            try:
                self.validate_vision_artifacts()
                import torch
                from torchvision import models, transforms
                from ultralytics import YOLO
                self.torch = torch
                self.device = ('cuda' if torch.cuda.is_available() else 'cpu') if DEVICE == 'auto' else DEVICE
                self.detector = YOLO(str(MODEL / 'weights/detector.pt'))
                checkpoint = torch.load(MODEL / 'classify/best.pt', map_location='cpu', weights_only=True)
                state = checkpoint
                if isinstance(checkpoint, dict):
                    for key in ('model_state_dict', 'state_dict', 'model'):
                        if key in checkpoint:
                            state = checkpoint[key]
                            break
                self.classifier = models.mobilenet_v3_small(weights=None)
                head = torch.nn.Linear(1024, 2)
                self.classifier.classifier[3] = (torch.nn.Sequential(torch.nn.Dropout(.2), head)
                    if 'classifier.3.1.weight' in state else head)
                self.classifier.load_state_dict({k.removeprefix('module.'): v for k, v in state.items()})
                self.classifier.to(self.device).eval()
                self.labels = json.loads((MODEL / 'classify/class_map.json').read_text(encoding='utf-8'))
                self.transform = transforms.Compose([transforms.Resize((224, 224)), transforms.ToTensor(),
                    transforms.Normalize([.485, .456, .406], [.229, .224, .225])])
                self.vision_ready, self.vision_error = True, None
                self.ready = self.vision_ready and self.ocr_ready
            except Exception as exc:
                self.vision_error = f'{type(exc).__name__}: {exc}'
                self.error = self.vision_error
                raise
            finally:
                self.vision_loading = False

    def load_ocr(self):
        with self.ocr_load_lock:
            if self.ocr_ready:
                return
            self.ocr_loading = True
            try:
                self.validate_ocr_artifacts()
                import torch
                from transformers import AutoModelForImageTextToText, AutoProcessor
                from peft import PeftModel
                self.torch = torch
                self.device = ('cuda' if torch.cuda.is_available() else 'cpu') if DEVICE == 'auto' else DEVICE
                self.processor = AutoProcessor.from_pretrained(BASE_MODEL, local_files_only=True,
                                                               use_fast=True, extra_special_tokens={})
                # The 2B base model does not fit in memory as float32 on typical Windows hosts.
                base = AutoModelForImageTextToText.from_pretrained(
                    BASE_MODEL, local_files_only=True, dtype=torch.float16, low_cpu_mem_usage=True)
                self.ocr = PeftModel.from_pretrained(base, str(MODEL / 'ocr')).to(self.device).eval()
                self.ocr_ready, self.ocr_error = True, None
                self.ready = self.vision_ready and self.ocr_ready
                if self.ready:
                    self.error = None
            except Exception as exc:
                self.ocr_error = f'{type(exc).__name__}: {exc}'
                self.error = self.ocr_error
                raise
            finally:
                self.ocr_loading = False

    def load(self):
        self.load_vision()
        self.load_ocr()
        self.ready = self.vision_ready and self.ocr_ready
        self.error = None if self.ready else self.error

    def detect(self, frame):
        import cv2
        from PIL import Image
        self.load_vision()
        with self.vision_lock, self.torch.inference_mode():
            self.vision_error = None
            boxes = self.detector.predict(frame, conf=YOLO_CONF, device=self.device, verbose=False)[0].boxes
            if boxes is None or len(boxes) == 0:
                return []
            full = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            # Classification receives the FULL frame exactly once, never the plate crop.
            probs = self.classifier(self.transform(full).unsqueeze(0).to(self.device)).softmax(dim=1)[0]
            index = int(probs.argmax())
            vehicle_type, probability = self.labels[str(index)], float(probs[index])
            results = []
            for box, confidence in zip(boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist()):
                x1, y1, x2, y2 = map(int, box)
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(full.width, x2), min(full.height, y2)
                if x2 <= x1 or y2 <= y1:
                    continue
                crop = full.crop((x1, y1, x2, y2))
                results.append((dict(vehicle_type=vehicle_type, vehicle_probability=probability,
                                     detector_probability=confidence, box=[x1, y1, x2, y2]), crop))
            return results

    def recognize(self, crop):
        self.load_ocr()
        with self.ocr_lock, self.torch.inference_mode():
            self.ocr_error = None
            prompt = 'อ่านป้ายทะเบียนรถในภาพ ตอบ JSON เท่านั้น: {"plate_number":"", "characters":"", "digits":"", "province":""} ห้ามเดาข้อมูลที่มองไม่เห็น'
            messages = [{'role': 'user', 'content': [{'type': 'image', 'image': crop}, {'type': 'text', 'text': prompt}]}]
            inputs = self.processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                return_dict=True, return_tensors='pt').to(self.device)
            tokens = self.ocr.generate(**inputs, max_new_tokens=192, do_sample=False,
                                       temperature=None, top_p=None, top_k=None)
            raw = self.processor.batch_decode(tokens[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)[0]
            try:
                return parse_ocr(raw)
            except (ValueError, TypeError):
                self.ocr_error = 'OCR อ่านผลลัพธ์ไม่ได้: ' + raw[:160]
                self.error = self.ocr_error
                return None

    def run(self, frame):
        results = []
        for vision, crop in self.detect(frame):
            ocr = self.recognize(crop)
            if ocr:
                ocr.update(vision)
                results.append((ocr, crop))
        self.ready = self.vision_ready and self.ocr_ready
        if results:
            self.error = None
        return results
