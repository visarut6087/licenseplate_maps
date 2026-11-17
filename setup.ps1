param(
    [switch]$CoreOnly
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:UV_CACHE_DIR = "$PSScriptRoot/.cache/uv"
$env:UV_PYTHON_INSTALL_DIR = "$PSScriptRoot/.python"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' }
if (-not (Test-Path .venv/Scripts/python.exe)) {
    uv python install 3.11
    if ($LASTEXITCODE -ne 0) { throw 'Could not install Python' }
    uv venv --python 3.11 .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment' }
}
if ($CoreOnly) {
    uv pip install --python .venv/Scripts/python.exe -r backend/requirements-core.txt
} else {
    uv pip install --python .venv/Scripts/python.exe -r backend/requirements.txt
}
if ($LASTEXITCODE -ne 0) { throw 'Could not install dependencies' }
if ($CoreOnly) {
    Write-Host 'Core API/UI environment is ready (model packages and artifacts were skipped).'
    exit 0
}
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    Write-Host 'NVIDIA GPU detected: installing PyTorch CUDA 12.8 runtime.'
    uv pip install --python .venv/Scripts/python.exe --index-url https://download.pytorch.org/whl/cu128 `
        'torch==2.11.0+cu128' 'torchvision==0.26.0+cu128'
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the PyTorch CUDA runtime' }
} else {
    Write-Host 'No NVIDIA GPU detected: PyTorch will use CPU.'
}
& .venv/Scripts/python.exe -m backend.download_models
if ($LASTEXITCODE -ne 0) { throw 'Could not download the OCR base model' }
Write-Host 'Ready: run start-backend.ps1 and start-frontend.ps1 in separate terminals.'
