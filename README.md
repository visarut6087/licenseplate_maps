# ระบบอ่านป้ายทะเบียนรถ

แยก `backend/` (Python FastAPI) และ `frontend/` (HTML/CSS/JavaScript) ใช้ REST API สำหรับคำสั่ง ข้อมูล และภาพ JPEG แบบ polling ไม่ต้อง build frontend

## เริ่มใช้งานบน Windows

ต้องมี Node.js 22+, uv, พื้นที่ว่างสำหรับ PyTorch และ OCR base model หลาย GB แนะนำ NVIDIA GPU; CPU ทำงานได้แต่ OCR จะช้า

```powershell
cd C:\patrick\licenseplate_maps
.\setup.ps1
```

คำสั่งนี้สร้าง `.venv` ติดตั้ง dependencies และดาวน์โหลด base model จาก Hugging Face ครั้งแรก ต้องเชื่อมต่ออินเทอร์เน็ต (น้ำหนัก adapter ใช้จาก `model/ocr` เดิม)

เปิด 2 terminal:

```powershell
.\start-backend.ps1
```

```powershell
.\start-frontend.ps1
```

- **Main 1 กล้อง IP:** http://127.0.0.1:5173/index.html เพิ่มได้หลายกล้อง RTSP/HTTP สูงสุด 16 แหล่งภาพพร้อมกัน
- **Main 2 วิดีโอ MP4:** http://127.0.0.1:5173/video.html เลือกไฟล์จากเครื่อง
- **API docs:** http://127.0.0.1:8000/docs

กด “โหลด / ตรวจสอบโมเดล” ก่อนใช้งาน หรือระบบจะโหลดเมื่อเริ่มประมวลผลภาพแรก หากขาด base model หน้าจอจะแสดงข้อผิดพลาดโดยไม่มีการสร้างผล OCR จำลอง

ฝั่งซ้ายแสดงภาพจากทุกแหล่งภาพในโหมดนั้น (ร้องขอภาพล่าสุดทุก 200 ms ตามความเร็วเครือข่าย) ฝั่งขวาบนแสดงภาพเต็มและ crop จาก **event เดียวกัน** ฝั่งขวาล่างแสดงทะเบียนล่าสุด คลิกรายการย้อนหลังเพื่อตรึงภาพ คลิกรายการบนสุดเพื่อกลับไปติดตามผลล่าสุด

## ลำดับโมเดล

1. YOLO `model/weights/detector.pt` ตรวจหากรอบป้าย
2. MobileNetV3-Small `model/classify/best.pt` รับ **ภาพเต็มเท่านั้น** → vehicle_type และ vehicle_probability
3. ตัดป้ายด้วย box จากข้อ 1 ไม่มีการเรียก detector ซ้ำ
4. OCR: base model ใน `model/ocr/adapter_config.json` + LoRA `model/ocr` อ่านภาพ crop → plate_number, digits, province พร้อมเก็บ raw_text

ตัวโหลด OCR ใช้ Transformers ตาม [ตัวอย่างทางการของ Typhoon](https://huggingface.co/typhoon-ai/typhoon-ocr1.5-2b/blob/main/README.md) แล้วโหลด adapter ของโปรเจกต์เพิ่ม หากใช้ local base model ตั้ง `OCR_BASE_MODEL` เป็น path ก่อนเริ่ม backend

**ข้อจำกัด:** classifier รับภาพเต็มตามข้อกำหนด ดังนั้นหากภาพเดียวมีรถหลายคัน ประเภทรถเป็นผลระดับภาพเดียวกันสำหรับทุกป้ายในภาพนั้น ความถูกต้องของ OCR และจังหวัดต้องตรวจด้วยภาพจริง โมเดลจะไม่เติมจังหวัดเมื่ออ่านไม่ได้

## ผลลัพธ์

```text
results/
  index.sqlite3          # ลำดับถาวรและดัชนีสำหรับ REST API
  all.csv                # ทุกวัน เรียง order จากน้อยไปมาก, UTF-8 BOM เปิด Excel ได้
  2026-11-17/
    plates.csv           # CSV ของวันนั้น
    <event-id>/
      full.jpg
      crop.jpg
      ocr.json
```

JSON เก็บเลขทะเบียน, digits, จังหวัด, ประเภทรถ, ความน่าจะเป็น, box, เวลา ISO 8601 (+07:00), ชื่อแหล่งภาพ, order, path ภาพ และเวลาของเฟรมใน MP4 (`media_seconds`) เวลา `detected_at` คือเวลารับเฟรม ไม่ใช่เวลาที่ OCR เสร็จ ลำดับ `order` เป็นลำดับบันทึกจริงและคงอยู่หลัง restart

ภาพจาก IP ส่งเข้า inference ได้ครั้งละหนึ่งงานต่อกล้อง กล้องยังแสดงภาพสดขณะ OCR ทำงาน วิดีโอจะรอ OCR เมื่อถึงเฟรมตัวอย่างเพื่อไม่ข้ามตัวอย่างเพราะ OCR ช้า จึงอาจเล่นช้ากว่าเวลาจริง ไม่ได้ประมวลผลทุกเฟรม ลดการบันทึกป้ายเดิมซ้ำจากกล้องเดียวกันภายใน 15 วินาที

## ตั้งค่าเพิ่มเติม

ตั้ง environment ใน terminal backend ก่อนเรียก script:

```powershell
$env:MODEL_DEVICE = 'auto'          # auto / cpu / cuda / cuda:0
$env:OCR_BASE_MODEL = 'scb10x/typhoon-ocr1.5-2b'
$env:INFERENCE_INTERVAL = '1.0'     # ระยะห่างเฟรมตัวอย่าง วินาที
$env:PLATE_COOLDOWN = '15'          # ระยะงดบันทึกซ้ำ วินาที (0 = ไม่งด)
$env:MAX_UPLOAD_MB = '2048'
.\start-backend.ps1
```

ไฟล์อัปโหลดอยู่ `uploads/` กล้องที่เพิ่มอยู่ในหน่วยความจำ ต้องเพิ่มใหม่หลัง restart ผล OCR เก่าคงอยู่ใน results กดหยุดเพื่อเลิกอ่านแหล่งภาพ ไม่มีการลบผลเดิม

ระบบนี้ผูกกับ localhost ไม่มีระบบล็อกอิน ไม่ควรเปิดพอร์ตสู่เครือข่ายสาธารณะโดยตรง หากเปลี่ยน API URL ตั้ง `localStorage.setItem('plate_api_url', 'http://127.0.0.1:8000')` ใน browser console แล้ว refresh และตั้ง CORS ให้ตรง origin ใน backend

## REST API

| Method | Path | ใช้งาน |
|---|---|---|
| GET | `/api/health` | สถานะระบบ / โมเดล |
| POST | `/api/models/load` | โหลดโมเดล / ลองโหลดใหม่ |
| POST | `/api/cameras` | JSON `{ "name": "ทางเข้า", "url": "rtsp://..." }` |
| POST | `/api/videos` | multipart field `file` (.mp4) |
| GET | `/api/sources` | แหล่งภาพและสถานะ ไม่คืนรหัสผ่านกล้อง |
| DELETE | `/api/sources/{id}` | หยุดแหล่งภาพ |
| GET | `/api/sources/{id}/frame` | JPEG ล่าสุด |
| GET | `/api/events?source_id=...&limit=100` | รายการใหม่ก่อน |
| GET | `/api/results/{path}` | ภาพ / JSON หลักฐาน |
| GET | `/api/export.csv?day=2026-11-17` | CSV รายวัน หรือทั้งหมดเมื่อไม่ระบุวัน |

## ทดสอบ

```powershell
uv pip install --python .venv/Scripts/python.exe pytest httpx
.venv/Scripts/python.exe -m pytest backend/tests -q
```

Tests ใช้ภาพและโมเดลจำลองใน test เท่านั้น เพื่อตรวจลำดับ pipeline, ภาพเต็มที่เข้า classifier, box ที่ใช้ crop, การจับคู่หลักฐาน, ลำดับ CSV หลัง restart และ REST API ไม่ใช่การรับรองความแม่นยำของน้ำหนักโมเดลจริง
