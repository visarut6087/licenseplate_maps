# ระบบอ่านป้ายทะเบียนรถ

แยก `backend/` (Python FastAPI) และ `frontend/` (HTML/CSS/JavaScript) ใช้ REST API สำหรับคำสั่ง ข้อมูล และภาพ JPEG แบบ polling ไม่ต้อง build frontend

## เริ่มใช้งานบน Windows

ต้องมี Node.js 22+, uv, พื้นที่ว่างสำหรับ PyTorch และ OCR base model หลาย GB แนะนำ NVIDIA GPU; CPU ทำงานได้แต่ OCR จะช้า

`requirements.txt` ที่ project root รวม runtime dependencies ของ backend/model และเครื่องมือทดสอบทั้งหมด สามารถติดตั้งด้วย `uv pip install --python .venv/Scripts/python.exe -r requirements.txt`

```powershell
cd C:\patrick\licenseplate_maps
.\setup.ps1
```

หากต้องการพัฒนาหรือทดสอบเฉพาะโครง API/UI โดยยังไม่ติดตั้งหรือดาวน์โหลดโมเดล:

```powershell
cd C:\licenseplate_maps
.\setup.ps1 -CoreOnly
```

โหมดนี้เปิด backend/frontend และทดสอบ REST API, การอัปโหลด, การจัดเก็บผล และ UI ได้ แต่ยังประมวลผล inference จริงไม่ได้ `/api/health` จะแสดงสถานะ artifact ที่ยังขาดอยู่

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

หน้า MP4 มี timeline ใต้ภาพวิดีโอ สามารถลากเพื่อเลื่อนไปยังเวลาที่ต้องการได้ รวมถึงวิดีโอที่เล่นจบแล้ว งาน detect/OCR จากตำแหน่งเก่าจะไม่ถูกนำมาบันทึกปะปนกับตำแหน่งใหม่

ฝั่งซ้ายแสดงภาพจากทุกแหล่งภาพในโหมดนั้น (ร้องขอภาพล่าสุดทุก 200 ms ตามความเร็วเครือข่าย) ฝั่งขวาบนแสดงภาพเต็มและ crop จาก **event เดียวกัน** ฝั่งขวาล่างแสดงทะเบียนล่าสุด คลิกรายการย้อนหลังเพื่อตรึงภาพ คลิกรายการบนสุดเพื่อกลับไปติดตามผลล่าสุด

ปุ่ม **ล้างรายการ** ซ่อนทะเบียนที่แสดงอยู่เฉพาะในหน้าเว็บ ไม่ลบภาพ, JSON, SQLite หรือ CSV ฝั่ง backend และรายการที่ตรวจพบหลังจากกดจะแสดงต่อตามปกติ
ช่อง **ค้นหา** ในส่วนทะเบียนล่าสุดกรองรายการทันทีจากเลขทะเบียน, จังหวัด, ประเภทรถ, ชื่อแหล่งภาพ หรือลำดับ โดยไม่แก้ขข้อมูล backend

## ลำดับโมเดล

| ขั้นตอน | ชื่อในโปรเจกต์ | โมเดล/ไฟล์ | หน้าที่ |
|---|---|---|---|
| 1. ตรวจหาป้าย | `detector` | YOLO `model/weights/detector.pt` | ตรวจหาป้ายด้วย `YOLO_CONF` (ค่าเริ่มต้น `0.50`) และคืนกรอบ `box` |
| 2. จำแนกประเภทรถ | `classifier` | MobileNetV3-Small `model/classify/best.pt` | รับ **ภาพเต็มเท่านั้น** และคืน `vehicle_type`, `vehicle_probability` |
| 3. แปลชื่อคลาส | `class_map` | `model/classify/class_map.json` | แปลหมายเลขคลาสเป็นรถยนต์/รถจักรยานยนต์ |
| 4. ตัดภาพป้าย | `crop` | ไม่ใช้โมเดลเพิ่ม | ตัดภาพด้วย `box` จากข้อ 1 โดยไม่เรียก YOLO ซ้ำ |
| 5. OCR base | `ocr-base` | `scb10x/typhoon-ocr1.5-2b` ใน `model/ocr-base` | โมเดลภาษาและภาพพื้นฐานสำหรับ OCR |
| 6. OCR adapter | `ocr` | `Rattatammanoon/hurricane-ocr-tlpr-v1-LoRA` ใน `model/ocr` | LoRA สำเร็จรูปสำหรับอ่านป้ายทะเบียนไทย ไม่มีการเทรนเพิ่ม |
| 7. แปลผล OCR | `parse_ocr()` | `backend/pipeline.py` | แปล JSON/Markdown เป็น `plate_number`, `digits`, `province`, `raw_text` |
| 8. บันทึก event | `storage` | `results/`, SQLite และ CSV | บันทึกภาพเต็ม, crop และผล OCR ของงานเดียวกัน |

### Flow การประมวลผล

```text
ภาพเต็มจากกล้อง/MP4
  ↓
YOLO detector.pt ตรวจหากรอบป้าย (YOLO_CONF=0.50)
  ↓
จับคู่ tracking ID แยกต่อกล้อง/MP4 และวาดกรอบ `PLATE #ID confidence`
  ↓
MobileNetV3-Small จำแนกประเภทรถจากภาพเต็ม 1 ครั้ง
  รถยนต์ / รถจักรยานยนต์ + probability
  ↓
Crop ด้วยกรอบ YOLO เดิม (ไม่เรียก YOLO ซ้ำ)
  ↓
ส่งงานเข้า OCR queue
  ภาพเต็ม + crop + box + ประเภทรถ + เวลา + แหล่งภาพ
  ↓
Typhoon OCR 1.5 2B + Hurricane OCR TLPR v1 LoRA
  ↓
plate_number + digits + province + raw_text
  ↓
บันทึกภาพเต็ม, crop, JSON, SQLite และ CSV เป็น event เดียวกัน
  ↓
เผยแพร่ให้หน้าจอ "ทะเบียนล่าสุด"
```

ระบบแยก worker ตรวจจับกับ worker OCR: เมื่อ YOLO พบป้าย จะส่งภาพเต็ม, crop, box, ผลจำแนกรถ, เวลา และแหล่งภาพไปในงานคิวเดียวกัน และจะเผยแพร่ event ให้หน้าจอเมื่อ OCR และไฟล์หลักฐานของงานนั้นพร้อมครบแล้วเท่านั้น

กรอบ tracking แสดงทั้งภาพสดของกล้อง IP, ภาพ MP4 และภาพเต็มในหลักฐาน โดยแยกชุด track ID ของแต่ละแหล่งภาพออกจากกัน

ตัวโหลด OCR ใช้ Transformers ตาม [ตัวอย่างทางการของ Typhoon](https://huggingface.co/typhoon-ai/typhoon-ocr1.5-2b/blob/main/README.md) แล้วโหลด adapter ของโปรเจกต์เพิ่ม หากใช้ local base model ตั้ง `OCR_BASE_MODEL` เป็น path ก่อนเริ่ม backend

**ข้อจำกัด:** classifier รับภาพเต็มตามข้อกำหนด ดังนั้นหากภาพเดียวมีรถหลายคัน ประเภทรถเป็นผลระดับภาพเดียวกันสำหรับทุกป้ายในภาพนั้น ความถูกต้องของ OCR และจังหวัดต้องตรวจด้วยภาพจริง โมเดลจะไม่เติมจังหวัดเมื่ออ่านไม่ได้

## ผลลัพธ์

```text
results/
  index.sqlite3          # ลำดับถาวรและดัชนีสำหรับ REST API
  all.csv                # ทุกวัน เรียง order จากน้อยไปมาก, UTF-8 BOM เปิด Excel ได้
  summary.csv            # ตารางย่อ 4 คอลัมน์ตามหน้าจอทะเบียนล่าสุด
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
$env:YOLO_CONF = '0.50'             # confidence threshold ของ detector
$env:OCR_BASE_MODEL = 'C:\licenseplate_maps\model\ocr-base'
$env:OCR_BASE_MODEL_REPO = 'scb10x/typhoon-ocr1.5-2b'
$env:OCR_ADAPTER_REPO = 'Rattatammanoon/hurricane-ocr-tlpr-v1-LoRA'
$env:INFERENCE_INTERVAL = '1.0'     # ระยะห่างเฟรมตัวอย่าง วินาที
$env:PLATE_COOLDOWN = '15'          # ระยะงดบันทึกซ้ำ วินาที (0 = ไม่งด)
$env:MAX_UPLOAD_MB = '2048'
.\start-backend.ps1
```

`MODEL_DEVICE=auto` เป็นค่าเริ่มต้น: หาก `setup.ps1` พบ NVIDIA GPU จะติดตั้ง PyTorch CUDA 12.8 และใช้ `cuda` อัตโนมัติ ถ้าไม่พบ GPU หรือ CUDA ใช้ไม่ได้ โค้ดจะ fallback ไป `cpu`

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
| POST | `/api/sources/{id}/seek` | เลื่อน MP4 ด้วย JSON `{ "seconds": 120.5 }` |
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
