param([switch]$SkipWebBuild)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($env:OS -ne 'Windows_NT') { throw 'Windows x64 build runner required' }
Set-Location -LiteralPath $taskRoot
New-Item -ItemType Directory -Force -Path (Join-Path $taskRoot '.tmp') | Out-Null
$env:TEMP = Join-Path $taskRoot '.tmp'
$env:TMP = $env:TEMP
$env:RUNTIME_MODE = 'desktop'
$env:PYTHONDONTWRITEBYTECODE = '1'
if (-not $SkipWebBuild) {
    Push-Location (Join-Path $taskRoot 'apps/web')
    try { npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Web build failed' } }
    finally { Pop-Location }
}
python -c "import importlib.metadata as m; assert m.version('PySide6') == '6.12.0'; assert m.version('PyInstaller') == '6.22.3'"
if ($LASTEXITCODE -ne 0) { throw 'Use the GitHub Windows packaging job to install pinned build dependencies' }
python scripts/ci/windows_icon.py --web-icon apps/web/dist/favicon.ico --report reports/windows-icon-source.json
if ($LASTEXITCODE -ne 0) { throw 'Frontend brand icon verification failed' }
python -m PyInstaller packaging/windows/xianyu_portable.spec --clean --noconfirm --distpath dist/windows --workpath build/windows
if ($LASTEXITCODE -ne 0) { throw 'Portable EXE build failed' }
python scripts/ci/windows_icon.py --exe dist/windows/XianyuPilot/XianyuPilot.exe --exe dist/windows/XianyuPilot-Standalone.exe --report reports/windows-icon-build.json
if ($LASTEXITCODE -ne 0) { throw 'Built EXEs do not contain the Gemini Explorer icon' }
