$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
node frontend/server.mjs
