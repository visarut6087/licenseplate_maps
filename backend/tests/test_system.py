import csv
import io
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from backend.pipeline import Pipeline, parse_ocr
from backend.storage import Storage


def test_evidence_pair_and_order_survive_restart(tmp_path):
    storage = Storage(tmp_path)
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    frame[20:40, 30:70] = [20, 100, 240]
    crop = Image.fromarray(cv2.cvtColor(frame[20:40, 30:70], cv2.COLOR_BGR2RGB))
    data = dict(plate_number='กข1234', digits='1234', province='กรุงเทพมหานคร',
                vehicle_type='รถยนต', vehicle_probability=.9, box=[30, 20, 70, 40])
    source = SimpleNamespace(id='camera1', name='ทางเข้า', kind='camera')
    first = storage.save(data, frame, crop, source, '2026-11-17T10:00:00+07:00')
    storage = Storage(tmp_path)
    second = storage.save(data, frame, crop, source, '2026-11-18T10:00:00+07:00')
    assert second['order'] > first['order']
    assert json.loads((tmp_path / first['json_file']).read_text(encoding='utf-8')) == first
    assert Image.open(tmp_path / first['full_image']).size == (120, 80)
    assert Image.open(tmp_path / first['crop_image']).size == (40, 20)
    rows = list(csv.DictReader(io.StringIO((tmp_path / 'all.csv').read_text(encoding='utf-8-sig'))))
    assert [r['id'] for r in rows] == [first['id'], second['id']]
    assert len(list(csv.DictReader(io.StringIO((tmp_path / '2026-11-17/plates.csv').read_text(encoding='utf-8-sig'))))) == 1


def test_ocr_rejects_prose_and_supports_fenced_json():
    with pytest.raises(ValueError):
        parse_ocr('อ่านไม่ได้')
    result = parse_ocr('```json\n{"plate_number":"กข1234", "province":"กรุงเทพมหานคร"}\n```')
    assert result['digits'] == '1234'
    assert parse_ocr('{"plate_number":"1กข 1234"}')['digits'] == '1234'


def test_api_and_path_guard(tmp_path, monkeypatch):
    import backend.app as module
    monkeypatch.setattr(module, 'RESULTS', tmp_path / 'results')
    monkeypatch.setattr(module, 'UPLOADS', tmp_path / 'uploads')
    monkeypatch.setattr(module, 'Storage', lambda: Storage(tmp_path / 'results'))
    with TestClient(module.app) as client:
        assert client.get('/api/health').json()['status'] == 'ok'
        assert client.get('/api/events').json() == []
        assert client.post('/api/cameras', json={'name':'test','url':'file:///secret'}).status_code == 422
        assert client.post('/api/videos', files={'file':('x.mp4', b'', 'video/mp4')}).status_code == 422
        assert client.post('/api/videos', files={'file':('x.exe', b'xx')}).status_code == 422
        assert client.get('/api/sources/nope/frame').status_code == 404
        assert client.get('/api/results/index.sqlite3').status_code == 404
        assert client.get('/api/results/..%2F..%2FREADME.md').status_code == 404
        assert client.get('/api/export.csv').content.startswith(b'\xef\xbb\xbf')


def test_pipeline_order_full_frame_and_crop():
    torch = pytest.importorskip('torch')
    calls = []
    pipeline = Pipeline()
    pipeline.ready = True
    pipeline.torch, pipeline.device = torch, 'cpu'
    pipeline.labels = {'0':'รถยนต','1':'รถจักรยานยนต'}
    boxes = SimpleNamespace(xyxy=torch.tensor([[30, 20, 70, 40]]), conf=torch.tensor([.95]))
    class Boxes:
        xyxy, conf = boxes.xyxy, boxes.conf
        def __len__(self):
            return 1
    class Detector:
        def predict(self, image, **kwargs):
            calls.append('detect')
            assert image.shape == (80, 120, 3)
            return [SimpleNamespace(boxes=Boxes())]
    pipeline.detector = Detector()
    def transform(image):
        calls.append('classify')
        assert image.size == (120, 80)
        return torch.zeros(3, 224, 224)
    pipeline.transform = transform
    pipeline.classifier = lambda tensor: torch.tensor([[5., 1.]])
    class Inputs(dict):
        input_ids = torch.zeros(1, 3, dtype=torch.long)
        def to(self, device):
            return self
    class Processor:
        def apply_chat_template(self, messages, **kwargs):
            calls.append('ocr')
            image = messages[0]['content'][0]['image']
            assert image.size == (40, 20)
            return Inputs()
        def batch_decode(self, *args, **kwargs):
            return ['{"plate_number":"กข1234", "digits":"1234", "province":"กรุงเทพมหานคร"}']
    pipeline.processor = Processor()
    pipeline.ocr = SimpleNamespace(generate=lambda **kwargs: torch.zeros(1, 10, dtype=torch.long))
    result = pipeline.run(np.zeros((80, 120, 3), dtype=np.uint8))
    assert calls == ['detect', 'classify', 'ocr']
    assert result[0][0]['box'] == [30, 20, 70, 40]
    assert result[0][0]['vehicle_type'] == 'รถยนต'
    calls.clear()
    class EmptyDetector:
        def predict(self, *args, **kwargs):
            calls.append('detect')
            return [SimpleNamespace(boxes=None)]
    pipeline.detector = EmptyDetector()
    assert pipeline.run(np.zeros((80, 120, 3), dtype=np.uint8)) == []
    assert calls == ['detect']


def test_mp4_capture_worker_and_evidence(tmp_path):
    import time
    from backend.sources import Manager
    filename = str(tmp_path / 'test.mp4')
    writer = cv2.VideoWriter(filename, cv2.VideoWriter_fourcc(*'mp4v'), 10, (120, 80))
    assert writer.isOpened()
    for _ in range(4):
        writer.write(np.full((80, 120, 3), 100, dtype=np.uint8))
    writer.release()
    class StubPipeline:
        error = None
        def run(self, frame):
            return [(dict(plate_number='ทด1234', digits='1234', province='กรุงเทพมหานคร',
                          vehicle_type='รถยนต', vehicle_probability=.9, box=[10, 10, 50, 30]),
                     Image.fromarray(cv2.cvtColor(frame[10:30, 10:50], cv2.COLOR_BGR2RGB)))]
    storage = Storage(tmp_path / 'results')
    manager = Manager(StubPipeline(), storage)
    try:
        source = manager.add('test.mp4', filename, 'video')
        deadline = time.monotonic() + 8
        while source.status not in ('finished', 'error') and time.monotonic() < deadline:
            time.sleep(.05)
        assert source.status == 'finished', source.error
        events = storage.list()
        assert len(events) == 1
        assert events[0]['source_id'] == source.id
        assert events[0]['source_kind'] == 'video'
        assert events[0]['media_seconds'] is not None
        assert source.jpeg().startswith(b'\xff\xd8')
    finally:
        manager.close()
