$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:UV_CACHE_DIR = "$PSScriptRoot/.cache/uv"
$env:UV_PYTHON_INSTALL_DIR = "$PSScriptRoot/.python"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'กรุณาติดตั้ง uv: https://docs.astral.sh/uv/getting-started/installation/' }
if (-not (Test-Path .venv/Scripts/python.exe)) {
    uv python install 3.11
    if ($LASTEXITCODE -ne 0) { throw 'ติดตั้ง Python ไม่สำเร็จ' }
    uv venv --python 3.11 .venv
    if ($LASTEXITCODE -ne 0) { throw 'สร้าง virtual environment ไม่สำเร็จ' }
}
uv pip install --python .venv/Scripts/python.exe -r backend/requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'ติดตั้ง dependencies ไม่สำเร็จ' }
& .venv/Scripts/python.exe -m backend.download_models
if ($LASTEXITCODE -ne 0) { throw 'ดาวน์โหลด OCR base model ไม่สำเร็จ' }
Write-Host 'พร้อมแล้ว: เปิด start-backend.ps1 และ start-frontend.ps1 ใน terminal แยกกัน'
