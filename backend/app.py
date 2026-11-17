import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, Field

from .config import RESULTS, UPLOADS, MAX_UPLOAD
from .pipeline import Pipeline
from .sources import Manager
from .storage import Storage


@asynccontextmanager
async def lifespan(app):
    UPLOADS.mkdir(parents=True, exist_ok=True)
    app.state.pipeline = Pipeline()
    app.state.storage = Storage()
    app.state.manager = Manager(app.state.pipeline, app.state.storage)
    yield
    app.state.manager.close()


app = FastAPI(title='License Plate API', version='1.0.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
                   allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Content-Type'])


class CameraRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2048)


class SeekRequest(BaseModel):
    seconds: float = Field(ge=0)


def get_source(source_id):
    source = app.state.manager.sources.get(source_id)
    if source is None:
        raise HTTPException(404, 'ไม่พบแหล่งภาพ')
    return source


@app.get('/api/health')
def health():
    return dict(status='ok', models=app.state.pipeline.status())


@app.post('/api/models/load')
async def load_models():
    try:
        await asyncio.to_thread(app.state.pipeline.load)
    except Exception:
        raise HTTPException(503, app.state.pipeline.error)
    return app.state.pipeline.status()


@app.get('/api/sources')
def sources():
    return [s.public() for s in list(app.state.manager.sources.values())]


@app.post('/api/cameras', status_code=201)
def cameras(body: CameraRequest):
    if urlsplit(body.url).scheme not in ('rtsp', 'rtsps', 'http', 'https'):
        raise HTTPException(422, 'ใช้ URL แบบ rtsp://, rtsps://, http:// หรือ https://')
    try:
        return app.state.manager.add(body.name.strip(), body.url, 'camera').public()
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post('/api/videos', status_code=201)
async def videos(file: UploadFile = File(...)):
    if Path(file.filename or '').suffix.lower() != '.mp4':
        raise HTTPException(422, 'รองรับไฟล์ .mp4 เท่านั้น')
    path = UPLOADS / f'{uuid4().hex}.mp4'
    size = 0
    try:
        with path.open('wb') as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, 'ไฟล์ใหญ่เกินกำหนด')
                await asyncio.to_thread(output.write, chunk)
        if size == 0:
            raise HTTPException(422, 'ไฟล์ว่าง')
        return app.state.manager.add(file.filename, str(path), 'video').public()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.delete('/api/sources/{source_id}')
def stop_source(source_id: str):
    source = get_source(source_id)
    source.stop.set()
    source.status = 'stopped'
    return source.public()


@app.post('/api/sources/{source_id}/seek')
def seek_source(source_id: str, body: SeekRequest):
    source = get_source(source_id)
    try:
        app.state.manager.seek(source, body.seconds)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return source.public()


@app.get('/api/sources/{source_id}/frame')
async def frame(source_id: str):
    data = await asyncio.to_thread(get_source(source_id).jpeg)
    if data is None:
        raise HTTPException(503, 'รอภาพจากแหล่งภาพ')
    return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})


@app.get('/api/events')
def events(source_id: str | None = None, limit: int = Query(100, ge=1, le=500)):
    return app.state.storage.list(source_id, limit)


@app.get('/api/export.csv')
def export(day: str | None = Query(None, pattern=r'^\d{4}-\d{2}-\d{2}$')):
    return Response('\ufeff' + app.state.storage.csv_text(day), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="plates.csv"'})


@app.get('/api/results/{file_path:path}')
def result_file(file_path: str):
    target = (RESULTS / file_path).resolve()
    if not target.is_relative_to(RESULTS) or target.suffix not in ('.jpg', '.json', '.csv') or not target.is_file():
        raise HTTPException(404, 'ไม่พบไฟล์')
    return FileResponse(target)
