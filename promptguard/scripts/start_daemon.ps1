param([int]$Port = 18765)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$BundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path -LiteralPath $BundledPython) { $Python = $BundledPython }
else { $Python = (Get-Command python -ErrorAction Stop).Source }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Python 3 was not found.' }
$Audit = Join-Path $ProjectRoot 'promptguard\runtime\audit.jsonl'
$Process = Start-Process -FilePath $Python -ArgumentList @('-m','promptguard.daemon.server','--port',"$Port",'--audit-log',$Audit) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
"PromptGuard daemon started: PID=$($Process.Id), URL=http://127.0.0.1:$Port"
