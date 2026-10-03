param(
  [string]$Task = 'DB connection 문제를 확인해줘. 필요한 로컬 설정 파일을 읽고 문제 원인을 알려줘. 도구 결과에서 비밀번호와 토큰이 placeholder로 표시되고 private IP는 유지되었다면 답변 마지막에 PROMPTGUARD_DEMO_V0_OK를 포함해줘.',
  [int]$Port = 18765
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Workspace = Join-Path $ProjectRoot 'synthetic_workspace'
$Fixture = Join-Path $Workspace '.env'
$FixtureExample = Join-Path $Workspace '.env.example'
# Always refresh the ignored fixture so every run uses the documented synthetic data.
Copy-Item -LiteralPath $FixtureExample -Destination $Fixture -Force
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Run .\promptguard\scripts\setup.ps1 first.' }
$CodexCommand = Get-Command codex -ErrorAction SilentlyContinue
if ($CodexCommand) { $Codex = $CodexCommand.Source }
else {
  $Codex = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin\*\codex.exe') -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Codex -or -not (Test-Path -LiteralPath $Codex)) {
  throw 'Codex CLI was not found. Install/open the Codex desktop app or add codex.exe to PATH.'
}
$Hook = Join-Path $ProjectRoot 'promptguard\hooks\hook.py'
$Command = "$(($Python -replace '\\','/')) $(($Hook -replace '\\','/'))"
$Pre = "hooks.PreToolUse=[{matcher='^Bash$',hooks=[{type='command',command='$Command',commandWindows='$Command',timeout=5}]}]"
$Post = "hooks.PostToolUse=[{matcher='^Bash$',hooks=[{type='command',command='$Command',commandWindows='$Command',timeout=5}]}]"
$PromptHook = "hooks.UserPromptSubmit=[{hooks=[{type='command',command='$Command',commandWindows='$Command',timeout=5}]}]"
$env:PROMPTGUARD_DAEMON_URL = "http://127.0.0.1:$Port"
$env:PROMPTGUARD_CODEX_BIN = Split-Path -Parent $Codex
Push-Location $Workspace
try {
  & $Codex exec --json --ephemeral --dangerously-bypass-hook-trust --skip-git-repo-check --sandbox workspace-write -m gpt-6.1-sol `
    -c $Pre -c $Post -c $PromptHook -c 'features.hooks=true' -c 'features.code_mode=true' $Task
} finally { Pop-Location }
