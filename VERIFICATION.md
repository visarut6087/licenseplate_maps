# ผลการตรวจสอบ

## ระบบและโมเดล

- ชุดทดสอบ `backend/tests/test_system.py` ผ่าน 5 รายการ: REST API / จำกัด path, การจับคู่ภาพกับ JSON, ลำดับ CSV หลัง restart, ลำดับ detect → classify ภาพเต็ม → crop → OCR, และอ่าน MP4 จริงผ่าน capture worker (ใช้ stub OCR ใน test)
- โหลด `model/classify/best.pt` จริงและรัน MobileNetV3 ด้วยภาพว่างได้ โดยใช้ head แบบ Dropout → Linear ตาม checkpoint
- โหลด `model/weights/detector.pt` จริงและรัน YOLO ด้วยภาพว่างได้
- โหลด processor/tokenizer จาก `model/ocr` ได้ โดย override `extra_special_tokens` ให้เข้ากับ Transformers 4.x โดยไม่แก้ไฟล์โมเดลต้นฉบับ
- JavaScript syntax และ Python compilation ผ่าน
- Frontend ทั้ง 2 entry และ API health ตอบ HTTP 200 ใน local server
- ยังไม่มี URL กล้อง IP หรือวิดีโอรถจริงจากผู้ใช้ จึงยังไม่ได้ตรวจความแม่นยำ OCR, จังหวัด, ประเภทรถ หรือประสิทธิภาพกับกล้องจริง

## หน้าจอ

`GATE: ERROR (consistency.mjs could not walk 1440, 390; check.mjs could not run (exit 2: check: timed out))`

ตัวตรวจ browser ของ design skill ไม่สามารถเดินหน้าจอได้ การถ่าย screenshot ด้วย skill หมดเวลาเช่นกัน จึงยังไม่ยืนยันการตรวจภาพหน้าจอจริง, responsive layout หรือ performance จาก browser

Copy lint: 0 FAIL, 0 WARN ไม่มี waiver หรือข้อเท็จจริงทางธุรกิจที่สมมติ ไม่มีภาพสต็อกหรือแบรนด์ที่แต่งขึ้น ใช้หน้าจอ monitoring ตาม layout ที่ผู้ใช้ระบุ สีพื้นเข้มและสีเขียวสำหรับสถานะ/การกระทำ ข้อความไทยสั้นสำหรับผู้ควบคุมกล้อง
