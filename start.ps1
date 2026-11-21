# 一键启动（Windows / 真实数据演示）
#   .\start.ps1          使用 data/ 下的真实年报库直接启动
#   .\start.ps1 -Demo    在独立 DATA_DIR 里导入合成回归语料后再启动（仅用于回归测试）
param([switch]$Demo)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "backend")
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

if ($Demo) {
  $env:DATA_DIR = Join-Path $PSScriptRoot "data\regression"
  Write-Host "[demo] 合成回归语料 -> $env:DATA_DIR"
  & $py -m app.cli seed --pack beer-demo
}

& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
