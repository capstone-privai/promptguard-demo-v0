$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Venv = Join-Path $ProjectRoot '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $Python)) {
  $BasePython = Get-Command python -ErrorAction SilentlyContinue
  if ($BasePython) { $BasePythonPath = $BasePython.Source }
  else {
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($PyLauncher) { $BasePythonPath = $PyLauncher.Source }
    else {
      $BundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
      if (-not (Test-Path -LiteralPath $BundledPython)) {
        throw 'Python 3 was not found. Install Python or open/update the Codex desktop app.'
      }
      $BasePythonPath = $BundledPython
    }
  }
  & $BasePythonPath -m venv $Venv
  if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed with exit code $LASTEXITCODE." }
}

& $Python -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed with exit code $LASTEXITCODE." }
& $Python -c "import importlib.metadata; print('CredSweeper ' + importlib.metadata.version('credsweeper') + ' ready')"
if ($LASTEXITCODE -ne 0) { throw "CredSweeper verification failed with exit code $LASTEXITCODE." }
