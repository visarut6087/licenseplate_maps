"""YOLO detect -> MobileNet(full frame) -> crop -> OCR. No synthetic results."""
import json
import re
import threading
from pathlib import Path

from .config import MODEL, BASE_MODEL, DEVICE


def parse_ocr(raw):
    text = raw.strip()
    match = re.search(r'\{.*\}', text, re.S)
    if not match:
        raise ValueError('OCR ไม่คืน JSON: ' + text[:160])
    data = json.loads(match.group())
    plate = str(data.get('plate_number') or '').strip()
    digits = str(data.get('digits') or '').strip()
    if not plate:
        plate = (str(data.get('characters') or '') + digits).strip()
    if not plate:
        raise ValueError('OCR ไม่พบเลขทะเบียน')
    trailing_digits = re.search(r'(\d+)\s*$', plate)
    return dict(plate_number=plate, digits=digits or (trailing_digits.group(1) if trailing_digits else ''),
                province=str(data.get('province') or '').strip(), raw_text=raw)


class Pipeline:
    def __init__(self):
        self.ready = False
        self.error = None
        self.lock = threading.Lock()
        self.loading = False

    def status(self):
        return dict(ready=self.ready, loading=self.loading, error=self.error)

    def load(self):
        with self.lock:
            if self.ready:
                return
            self.loading = True
            try:
                import torch
                from torchvision import models, transforms
                from ultralytics import YOLO
                from transformers import AutoModelForImageTextToText, AutoProcessor
                from peft import PeftModel
                from huggingface_hub import try_to_load_from_cache
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
                # No implicit multi-GB download during startup. Run download_models.py first.
                self.processor = AutoProcessor.from_pretrained(str(MODEL / 'ocr'), local_files_only=True,
                                                               use_fast=True, extra_special_tokens={})
                if not Path(BASE_MODEL).is_dir():
                    cached = [try_to_load_from_cache(BASE_MODEL, name) for name in
                              ('model.safetensors', 'model.safetensors.index.json')]
                    if not any(isinstance(path, str) and Path(path).is_file() for path in cached):
                        raise FileNotFoundError('OCR base model ยังดาวน์โหลดไม่ครบ กรุณารัน .venv/Scripts/python.exe -m backend.download_models')
                base = AutoModelForImageTextToText.from_pretrained(BASE_MODEL, local_files_only=True,
                    dtype=torch.float16 if self.device.startswith('cuda') else torch.float32)
                self.ocr = PeftModel.from_pretrained(base, str(MODEL / 'ocr')).to(self.device).eval()
                self.ready, self.error = True, None
            except Exception as exc:
                self.error = f'{type(exc).__name__}: {exc}'
                raise
            finally:
                self.loading = False

    def run(self, frame):
        import cv2
        from PIL import Image
        self.load()
        with self.lock, self.torch.inference_mode():
            self.error = None
            boxes = self.detector.predict(frame, conf=.45, device=self.device, verbose=False)[0].boxes
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
                prompt = 'อ่านป้ายทะเบียนรถในภาพ ตอบ JSON เท่านั้น: {"plate_number":"", "characters":"", "digits":"", "province":""} ห้ามเดาข้อมูลที่มองไม่เห็น'
                messages = [{'role': 'user', 'content': [{'type': 'image', 'image': crop}, {'type': 'text', 'text': prompt}]}]
                inputs = self.processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                    return_dict=True, return_tensors='pt').to(self.device)
                tokens = self.ocr.generate(**inputs, max_new_tokens=192, do_sample=False)
                raw = self.processor.batch_decode(tokens[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)[0]
                try:
                    result = parse_ocr(raw)
                    result.update(vehicle_type=vehicle_type, vehicle_probability=probability,
                                  detector_probability=confidence, box=[x1, y1, x2, y2])
                    results.append((result, crop))
                except (ValueError, TypeError):
                    # Report malformed OCR instead of turning model prose into a plate.
                    self.error = 'OCR อ่านผลลัพธ์ไม่ได้: ' + raw[:160]
            return results
