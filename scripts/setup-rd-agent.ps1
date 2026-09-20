param([switch]$Status)
$ErrorActionPreference = 'Stop'
$v3Root = Split-Path -Parent $PSScriptRoot
$v3Python = Join-Path $v3Root 'runtime/research-python/python.exe'
$v3Setup = Join-Path $PSScriptRoot 'setup-rd-agent.py'
if (-not (Test-Path -LiteralPath $v3Python)) { throw '请先准备 V3 Python 运行环境。' }
if ($Status) { & $v3Python -X utf8 $v3Setup --status }
else { & $v3Python -X utf8 $v3Setup }
if ($LASTEXITCODE -ne 0) { throw "RD-Agent 环境准备未完成，退出码 $LASTEXITCODE。" }
