# One-time setup of the Sheerr Weather graphics on Windows. In PowerShell, from the project folder:
#   powershell -ExecutionPolicy Bypass -File tools\setup-windows.ps1
# Safe to run again: it skips what is already installed.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
Write-Host "== Sheerr Weather graphics setup (Windows) =="

# 1. Tools via winget (built into Windows 10/11)
foreach ($id in "Git.Git", "OpenJS.NodeJS.LTS", "Python.Python.3.12", "Gyan.FFmpeg") {
  winget install --id $id -e --accept-source-agreements --accept-package-agreements --silent
  if ($LASTEXITCODE -ne 0) { Write-Host "  ($id already installed or skipped)" }
}
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

# 2. Python packages in a project-local environment (.venv)
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install pygrib
if ($LASTEXITCODE -ne 0) { Write-Host "  (pygrib skipped: only the Euro wind / wave animations need it)" }

# 3. Playwright + its Chrome, used to turn pages into PNG/MP4
npm install
npx playwright install chromium

# 4. Map layers (~100 MB, not in git)
.venv\Scripts\python tools\get_data.py

# 5. API keys, saved as user environment variables
foreach ($key in "MAPBOX_ACCESS_TOKEN", "TWC_API_KEY") {
  if (-not [Environment]::GetEnvironmentVariable($key, "User")) {
    $val = Read-Host "Paste your $key (Enter to skip)"
    if ($val) { [Environment]::SetEnvironmentVariable($key, $val, "User") }
  }
}

# 6. Quick check: render a static graphic
.venv\Scripts\python -c "import numpy, scipy, matplotlib, PIL, shapefile; print('python ok')"
node tools\shot.js "graphics/storm-types/index.html?export&fmt=social" "$env:TEMP\sheerr-test.png"
Write-Host "render ok: $env:TEMP\sheerr-test.png"
Write-Host "== Done. Restart the Claude app (or open a new PowerShell) so the keys load. =="
