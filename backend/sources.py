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
        self.ocr_pending = 0
        self.ocr_lock = threading.Lock()
        self.seek_event = threading.Event()
        self.seek_lock = threading.Lock()
        self.seek_target = None
        self.generation = 0
        self.track_lock = threading.Lock()
        self.tracks = []
        self.next_track_id = 1
        self.thread = None
        self.frames, self.media_seconds, self.duration_seconds = 0, 0, 0
        self.seen = {}

    def public(self):
        # Camera URLs can contain passwords. Never return them to clients or logs.
        return dict(id=self.id, name=self.name, kind=self.kind, status=self.status, error=self.error,
                    frames=self.frames, media_seconds=round(self.media_seconds, 2),
                    duration_seconds=round(self.duration_seconds, 2),
                    processing=self.pending.is_set() or self.ocr_count() > 0, ocr_queue=self.ocr_count(),
                    tracking=len(self.track_snapshot()))

    def request_seek(self, seconds):
        with self.seek_lock:
            target = max(0.0, float(seconds))
            if self.duration_seconds:
                target = min(target, self.duration_seconds)
            self.seek_target = target
            self.generation += 1
            self.seen.clear()
            with self.track_lock:
                self.tracks = []
            self.error = None
            self.status = 'seeking'
            self.seek_event.set()
            return target

    def take_seek(self):
        with self.seek_lock:
            if not self.seek_event.is_set():
                return None
            target = self.seek_target
            self.seek_event.clear()
            return target

    def current_generation(self):
        with self.seek_lock:
            return self.generation

    @staticmethod
    def box_iou(first, second):
        x1, y1 = max(first[0], second[0]), max(first[1], second[1])
        x2, y2 = min(first[2], second[2]), min(first[3], second[3])
        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
        second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
        union = first_area + second_area - intersection
        return intersection / union if union else 0

    def update_tracks(self, detections):
        with self.track_lock:
            previous = list(self.tracks)
            available = set(range(len(previous)))
            updated = []
            for detection in detections:
                box = list(map(int, detection['box']))
                match = max(available, key=lambda index: self.box_iou(box, previous[index]['box']), default=None)
                if match is not None and self.box_iou(box, previous[match]['box']) >= .25:
                    track_id = previous[match]['id']
                    available.remove(match)
                else:
                    track_id = self.next_track_id
                    self.next_track_id += 1
                updated.append(dict(id=track_id, box=box,
                                    confidence=float(detection.get('detector_probability', 0))))
            self.tracks = updated
            return list(updated)

    def track_snapshot(self):
        with self.track_lock:
            return [dict(track) for track in self.tracks]

    def annotate(self, frame):
        output = frame.copy()
        for track in self.track_snapshot():
            x1, y1, x2, y2 = track['box']
            label = f"PLATE #{track['id']} {track['confidence']:.2f}"
            cv2.rectangle(output, (x1, y1), (x2, y2), (80, 220, 130), 2)
            (width, height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, .55, 1)
            top = max(0, y1 - height - 10)
            cv2.rectangle(output, (x1, top), (x1 + width + 8, y1), (20, 70, 45), -1)
            cv2.putText(output, label, (x1 + 4, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX,
                        .55, (235, 255, 240), 1, cv2.LINE_AA)
        return output

    def ocr_count(self):
        with self.ocr_lock:
            return self.ocr_pending

    def ocr_started(self):
        with self.ocr_lock:
            self.ocr_pending += 1

    def ocr_finished(self):
        with self.ocr_lock:
            self.ocr_pending = max(0, self.ocr_pending - 1)

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
        self.vision_jobs = queue.Queue(maxsize=16)
        self.ocr_jobs = queue.Queue(maxsize=64)
        self.shutdown = threading.Event()
        self.vision_worker = threading.Thread(target=self.detect, daemon=True)
        self.ocr_worker = threading.Thread(target=self.ocr, daemon=True)
        self.vision_worker.start()
        self.ocr_worker.start()

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
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            source.duration_seconds = frame_count / fps if frame_count > 0 else 0
            target = source.take_seek()
            if target is not None:
                cap.set(cv2.CAP_PROP_POS_MSEC, target * 1000)
                source.media_seconds = target
            source.status, source.error = 'running', None
            next_sample = target or 0
            reopen = False
            try:
                while not source.stop.is_set() and not self.shutdown.is_set():
                    target = source.take_seek()
                    if target is not None:
                        cap.set(cv2.CAP_PROP_POS_MSEC, target * 1000)
                        source.media_seconds = target
                        next_sample = target
                        source.status, source.error = 'running', None
                        continue
                    start = time.monotonic()
                    ok, frame = cap.read()
                    if not ok:
                        if source.kind == 'video':
                            while (source.pending.is_set() or source.ocr_count()) and not source.stop.wait(.1):
                                if source.seek_event.is_set():
                                    reopen = True
                                    break
                            if reopen:
                                break
                            source.status = 'finished'
                            while not source.stop.is_set() and not self.shutdown.is_set():
                                if source.seek_event.wait(.25):
                                    reopen = True
                                    break
                            if reopen:
                                break
                            return
                        source.status, source.error = 'reconnecting', 'การเชื่อมต่อขาด กำลังเชื่อมต่อใหม่'
                        break
                    source.frames += 1
                    source.media_seconds = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000 if source.kind == 'video' else 0
                    with source.frame_lock:
                        source.frame = source.annotate(frame)
                    clock = source.media_seconds if source.kind == 'video' else start
                    if clock >= next_sample and not source.pending.is_set():
                        source.pending.set()
                        stamp = datetime.now(ZoneInfo('Asia/Bangkok')).isoformat(timespec='milliseconds')
                        try:
                            self.vision_jobs.put_nowait((source, frame.copy(), stamp, source.media_seconds,
                                                        source.current_generation()))
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
            if reopen:
                continue
            if source.stop.wait(2):
                break
        source.status = 'stopped'

    def detect(self):
        while not self.shutdown.is_set():
            try:
                source, frame, stamp, media_seconds, generation = self.vision_jobs.get(timeout=.5)
            except queue.Empty:
                continue
            try:
                if source.stop.is_set() or generation != source.current_generation():
                    continue
                detections = self.pipeline.detect(frame)
                if generation != source.current_generation():
                    continue
                source.update_tracks([vision for vision, _ in detections])
                evidence_frame = source.annotate(frame)
                with source.frame_lock:
                    source.frame = evidence_frame
                for vision, crop in detections:
                    if (source.stop.is_set() or self.shutdown.is_set()
                            or generation != source.current_generation()):
                        break
                    source.ocr_started()
                    job = (source, evidence_frame, crop, vision, stamp,
                           media_seconds if source.kind == 'video' else None, generation)
                    queued = False
                    while not self.shutdown.is_set() and not source.stop.is_set():
                        try:
                            self.ocr_jobs.put(job, timeout=.5)
                            queued = True
                            break
                        except queue.Full:
                            continue
                    if not queued:
                        source.ocr_finished()
                if self.pipeline.vision_error:
                    source.error = self.pipeline.vision_error
            except Exception as exc:
                source.error = f'ตรวจหาป้ายไม่ได้: {type(exc).__name__}: {exc}'
                # Avoid repeated heavyweight model initialization when setup is incomplete.
                source.stop.wait(3)
            finally:
                source.pending.clear()
                self.vision_jobs.task_done()

    def ocr(self):
        while not self.shutdown.is_set():
            try:
                source, frame, crop, vision, stamp, media_seconds, generation = self.ocr_jobs.get(timeout=.5)
            except queue.Empty:
                continue
            try:
                if source.stop.is_set() or generation != source.current_generation():
                    continue
                result = self.pipeline.recognize(crop)
                if generation != source.current_generation():
                    continue
                if not result:
                    source.error = self.pipeline.ocr_error
                    continue
                result.update(vision)
                key = (result['plate_number'].replace(' ', ''), result['province'])
                now = time.monotonic()
                if now - source.seen.get(key, -float('inf')) < COOLDOWN:
                    continue
                # Both images belong to this queued detection; publish only after the event is complete.
                self.storage.save(result, frame, crop, source, stamp, media_seconds)
                source.seen[key] = now
                source.error = None
            except Exception as exc:
                source.error = f'OCR ไม่สำเร็จ: {type(exc).__name__}: {exc}'
            finally:
                source.ocr_finished()
                self.ocr_jobs.task_done()

    def seek(self, source, seconds):
        if source.kind != 'video':
            raise ValueError('เลื่อนเวลาได้เฉพาะวิดีโอ')
        return source.request_seek(seconds)

    def close(self):
        self.shutdown.set()
        for source in list(self.sources.values()):
            source.stop.set()
        for source in list(self.sources.values()):
            source.thread.join(timeout=6)
        self.vision_worker.join(timeout=2)
        self.ocr_worker.join(timeout=2)
