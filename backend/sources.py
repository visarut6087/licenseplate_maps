import logging
import queue
import threading
import time
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import cv2

from .config import INTERVAL, COOLDOWN

log = logging.getLogger(__name__)


class Source:
    def __init__(self, name, uri, kind):
        self.id = uuid4().hex
        self.name, self.uri, self.kind = name, uri, kind
        self.status, self.error = 'starting', None
        self.frame = None
        self.frame_lock = threading.Lock()
        self.stop = threading.Event()
        self.pending = threading.Event()
        self.thread = None
        self.frames, self.media_seconds = 0, 0
        self.seen = {}

    def public(self):
        # Camera URLs can contain passwords. Never return them to clients or logs.
        return dict(id=self.id, name=self.name, kind=self.kind, status=self.status, error=self.error,
                    frames=self.frames, media_seconds=round(self.media_seconds, 2), processing=self.pending.is_set())

    def jpeg(self):
        with self.frame_lock:
            if self.frame is None:
                return None
            ok, data = cv2.imencode('.jpg', self.frame, [cv2.IMWRITE_JPEG_QUALITY, 78])
            return data.tobytes() if ok else None


class Manager:
    def __init__(self, pipeline, storage):
        self.pipeline, self.storage = pipeline, storage
        self.sources, self.lock = {}, threading.Lock()
        self.jobs = queue.Queue(maxsize=16)
        self.shutdown = threading.Event()
        self.worker = threading.Thread(target=self.infer, daemon=True)
        self.worker.start()

    def add(self, name, uri, kind):
        with self.lock:
            if sum(s.status not in ('stopped', 'finished', 'error') for s in self.sources.values()) >= 16:
                raise ValueError('รองรับแหล่งภาพที่ทำงานพร้อมกันสูงสุด 16 ตัว')
            source = Source(name, uri, kind)
            self.sources[source.id] = source
        source.thread = threading.Thread(target=self.capture, args=(source,), daemon=True)
        source.thread.start()
        return source

    def capture(self, source):
        while not source.stop.is_set() and not self.shutdown.is_set():
            cap = cv2.VideoCapture()
            try:
                cap.open(source.uri, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
            except cv2.error:
                cap.release()
                source.status, source.error = 'error', 'เปิดแหล่งภาพไม่ได้ กรุณาตรวจ URL หรือไฟล์วิดีโอ'
                return
            if not cap.isOpened():
                source.status, source.error = 'error', 'เปิดแหล่งภาพไม่ได้ กรุณาตรวจ URL หรือไฟล์วิดีโอ'
                cap.release()
                if source.kind == 'video' or source.stop.wait(3):
                    return
                source.status = 'reconnecting'
                continue
            fps = cap.get(cv2.CAP_PROP_FPS)
            fps = fps if 0 < fps <= 240 else 25
            source.status, source.error = 'running', None
            next_sample = 0
            try:
                while not source.stop.is_set() and not self.shutdown.is_set():
                    start = time.monotonic()
                    ok, frame = cap.read()
                    if not ok:
                        if source.kind == 'video':
                            while source.pending.is_set() and not source.stop.wait(.1):
                                pass
                            source.status = 'finished'
                            return
                        source.status, source.error = 'reconnecting', 'การเชื่อมต่อขาด กำลังเชื่อมต่อใหม่'
                        break
                    source.frames += 1
                    source.media_seconds = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000 if source.kind == 'video' else 0
                    with source.frame_lock:
                        source.frame = frame
                    clock = source.media_seconds if source.kind == 'video' else start
                    if clock >= next_sample and not source.pending.is_set():
                        source.pending.set()
                        stamp = datetime.now(ZoneInfo('Asia/Bangkok')).isoformat(timespec='milliseconds')
                        try:
                            self.jobs.put_nowait((source, frame.copy(), stamp, source.media_seconds))
                            next_sample = clock + INTERVAL
                        except queue.Full:
                            source.pending.clear()
                    if source.kind == 'video':
                        # Test video waits for inference; no sample is lost to a slow OCR.
                        while source.pending.is_set() and not source.stop.wait(.05):
                            pass
                        source.stop.wait(max(0, 1 / fps - (time.monotonic() - start)))
            except Exception:
                log.exception('Capture failed for source %s', source.id)
                source.status, source.error = 'error', 'อ่านภาพไม่สำเร็จ'
                return
            finally:
                cap.release()
            if source.stop.wait(2):
                break
        source.status = 'stopped'

    def infer(self):
        while not self.shutdown.is_set():
            try:
                source, frame, stamp, media_seconds = self.jobs.get(timeout=.5)
            except queue.Empty:
                continue
            try:
                if source.stop.is_set():
                    continue
                for data, crop in self.pipeline.run(frame):
                    if source.stop.is_set() or self.shutdown.is_set():
                        break
                    key = (data['plate_number'].replace(' ', ''), data['province'])
                    now = time.monotonic()
                    if now - source.seen.get(key, -float('inf')) < COOLDOWN:
                        continue
                    self.storage.save(data, frame, crop, source, stamp, media_seconds if source.kind == 'video' else None)
                    source.seen[key] = now
                source.error = self.pipeline.error
            except Exception as exc:
                source.error = f'ประมวลผลไม่ได้: {type(exc).__name__}: {exc}'
                # Avoid repeated heavyweight model initialization when setup is incomplete.
                source.stop.wait(3)
            finally:
                source.pending.clear()
                self.jobs.task_done()

    def close(self):
        self.shutdown.set()
        for source in list(self.sources.values()):
            source.stop.set()
        for source in list(self.sources.values()):
            source.thread.join(timeout=6)
        self.worker.join(timeout=2)
