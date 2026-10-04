$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Venv = Join-Path $ProjectRoot '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $Python)) {
  # Prefer the Codex-bundled interpreter. A venv created from a user-installed
  # Python under AppData may be runnable in this terminal but inaccessible to
  # the sandboxed Codex Hook process on Windows.
  $BundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
  if (Test-Path -LiteralPath $BundledPython) { $BasePythonPath = $BundledPython }
  else {
    $BasePython = Get-Command python -ErrorAction SilentlyContinue
    if ($BasePython) { $BasePythonPath = $BasePython.Source }
    else {
      $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
      if ($PyLauncher) { $BasePythonPath = $PyLauncher.Source }
      else {
        throw 'Python 3 was not found. Install Python or open/update the Codex desktop app.'
      }
    }
  }
  & $BasePythonPath -m venv $Venv
  if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed with exit code $LASTEXITCODE." }
}

& $Python -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed with exit code $LASTEXITCODE." }
& $Python -c "import importlib.metadata; print('CredSweeper ' + importlib.metadata.version('credsweeper') + ' ready')"
if ($LASTEXITCODE -ne 0) { throw "CredSweeper verification failed with exit code $LASTEXITCODE." }
