param([int]$Port = 18765)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Run .\promptguard\scripts\setup.ps1 first.' }
$Audit = Join-Path $ProjectRoot 'promptguard\runtime\audit.jsonl'
$Process = Start-Process -FilePath $Python -ArgumentList @('-m','promptguard.daemon.server','--port',"$Port",'--audit-log',$Audit) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
"PromptGuard daemon started: PID=$($Process.Id), URL=http://127.0.0.1:$Port"
