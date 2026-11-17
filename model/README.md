# model/

โมเดลสำเร็จพร้อมใช้งาน (finished artifacts). ทุก path อ้างอิงแบบ relative กับ project root (`trainocr/`).

## weights/detector.pt
- YOLO detector, 1 class `license` — ใช้หากรอบป้ายทะเบียนเพื่อ crop (Stage 1 ของ pipeline)
- เรียก: `model/weights/detector.pt`

## classify/
โมเดล 2 — vehicle-type classifier (MobileNetV3-Small, 2 คลาส)

| ไฟล์ | หน้าที่ |
|---|---|
| `model.pt` | weight ชุดสุดท้าย (final epoch) |
| `best.pt` | weight ของ epoch ที่ val ดีที่สุด |
| `class_map.json` | `{"0": "รถยนต", "1": "รถจักรยานยนต"}` |
| `metrics.json` | ประวัติการเทรน + test metrics |
| `confusion_test.csv` | confusion matrix ชุด test |

- คลาส: `0 = รถยนต`, `1 = รถจักรยานยนต`
- train/valid/test crops มาจาก `dataset_vehicle/` (สร้างด้วย `scripts/build_vehicle_cls_dataset.py`)
- เทรนซ้ำ: `python scripts/train_vehicle_classifier.py --data dataset_vehicle --out-dir model/classify --epochs 20`
- ใช้งานตรง: `python scripts/classify_vehicle.py --image path.jpg` (default `--model-dir model/classify`)
- ใช้ใน pipeline: `scripts/run_pipeline.py` (default `--cls-dir model/classify`)

> หมายเหตุ: ไฟล์ในโฟลเดอร์นี้เป็น **copy สำเนา** ของ `outputs/vehicle-cls/` (ผลจากการเทรน) — ถ้าเทรนซ้ำด้วย `--out-dir model/classify` จะเขียนทับที่นี่โดยตรง

## ocr/
โมเดล 3 — Hurricane OCR v5 (LoRA adapter บน Typhoon-OCR1.5-2B) อ่านเลขป้าย+จังหวัด

| ไฟล์ | จำเป็น | หน้าที่ |
|---|---|---|
| `adapter_model.safetensors` | ✅ | LoRA weights ของ v5 (66 MB) |
| `adapter_config.json` | ✅ | r=16, alpha=32, dropout=0.05, target modules |
| `tokenizer.json` / `tokenizer_config.json` | ✅ | tokenizer (โหลดพร้อม adapter) |
| `chat_template.jinja` | ✅ | multimodal chat template |
| `processor_config.json` | ✅ | image preprocessing |

- **base model ไม่ได้เก็บไว้ในโฟลเดอร์นี้** — `adapter_config.json` ชี้ `base_model_name_or_path = scb10x/typhoon-ocr1.5-2b` → เครื่องอื่นโหลดเองจาก HF (~4 GB) หรือ download ล่วงหน้าไว้
- ใช้ใน pipeline: `scripts/run_pipeline.py` (default `--adapter model/ocr`)
- ใช้ตรง: `python scripts/inference.py --adapter model/ocr --image path.jpg`
- ต้นฉบับการเทรน (docs/info) ยังอยู่ที่ `outputs/hurricane-v5/final_adapter/` (README + training_info.json)

## ลำดับ stage ใน `scripts/run_pipeline.py`
```
--order classify-first (default):
  1. classify ภาพเต็ม      → vehicle_type + prob
  2. yolo detector         → กรอบป้าย
  3. crop                  → region ป้าย
  4. OCR (adapter ใน ocr/) → plate_number / characters / digits / province
```
