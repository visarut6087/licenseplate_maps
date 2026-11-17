import csv
import io
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from .config import RESULTS


class Storage:
    fields = ['order', 'id', 'detected_at', 'source_id', 'source_name', 'plate_number', 'digits',
              'province', 'vehicle_type', 'vehicle_probability', 'media_seconds', 'full_image', 'crop_image', 'json_file']
    summary_fields = ['ลำดับ / เวลา', 'ทะเบียน / จังหวัด', 'ประเภทรถ', 'แหล่งภาพ']

    def __init__(self, root=RESULTS):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE, day TEXT, source TEXT, payload TEXT)')
        self.export_csv()

    def connect(self):
        return sqlite3.connect(self.root / 'index.sqlite3', timeout=30)

    def save(self, data, full, crop, source, detected_at=None, media_seconds=None):
        import cv2
        stamp = detected_at or datetime.now(ZoneInfo('Asia/Bangkok')).isoformat(timespec='milliseconds')
        day = stamp[:10]
        event_id = uuid4().hex
        relative = f'{day}/{event_id}'
        folder = self.root / relative
        folder.mkdir(parents=True)
        if not cv2.imwrite(str(folder / 'full.jpg'), full):
            raise OSError('Cannot save full image')
        crop.save(folder / 'crop.jpg', quality=95)
        record = dict(data, id=event_id, detected_at=stamp, source_id=source.id, source_name=source.name, source_kind=getattr(source, 'kind', 'camera'),
                      media_seconds=media_seconds, full_image=f'{relative}/full.jpg',
                      crop_image=f'{relative}/crop.jpg', json_file=f'{relative}/ocr.json')
        with self.lock, self.connect() as db:
            cur = db.execute('INSERT INTO events(id, day, source, payload) VALUES (?, ?, ?, ?)',
                             (event_id, day, source.id, '{}'))
            record['order'] = cur.lastrowid
            (folder / 'ocr.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            db.execute('UPDATE events SET payload=? WHERE id=?', (json.dumps(record, ensure_ascii=False), event_id))
            db.commit()
            self.export_csv(day)
        return record

    def list(self, source=None, limit=100):
        with self.connect() as db:
            if source:
                rows = db.execute('SELECT payload FROM events WHERE source=? ORDER BY sequence DESC LIMIT ?', (source, limit))
            else:
                rows = db.execute('SELECT payload FROM events ORDER BY sequence DESC LIMIT ?', (limit,))
            return [json.loads(r[0]) for r in rows]

    def csv_text(self, day=None):
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM events' + (' WHERE day=?' if day else '') + ' ORDER BY sequence', (day,) if day else ())
            buf = io.StringIO(newline='')
            writer = csv.DictWriter(buf, fieldnames=self.fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(json.loads(row[0]) for row in rows)
            return buf.getvalue()

    def export_csv(self, day=None):
        with self.lock:
            for path, selected in [(self.root / 'all.csv', None)] + ([(self.root / day / 'plates.csv', day)] if day else []):
                temp = path.with_suffix('.tmp')
                temp.write_text(self.csv_text(selected), encoding='utf-8-sig', newline='')
                temp.replace(path)
            summary = io.StringIO(newline='')
            writer = csv.DictWriter(summary, fieldnames=self.summary_fields)
            writer.writeheader()
            with self.connect() as db:
                rows = db.execute('SELECT payload FROM events ORDER BY sequence')
                for row in rows:
                    event = json.loads(row[0])
                    writer.writerow({
                        'ลำดับ / เวลา': f"#{event['order']} | {event['detected_at']}",
                        'ทะเบียน / จังหวัด': f"{event['plate_number']} | {event.get('province') or 'ไม่ทราบจังหวัด'}",
                        'ประเภทรถ': event['vehicle_type'],
                        'แหล่งภาพ': event['source_name'],
                    })
            path = self.root / 'summary.csv'
            temp = path.with_suffix('.tmp')
            temp.write_text(summary.getvalue(), encoding='utf-8-sig', newline='')
            temp.replace(path)
