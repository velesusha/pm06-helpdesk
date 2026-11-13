param([switch]$Clean, [switch]$Http)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) { $taskPython = $venvPython }
elseif (Test-Path -LiteralPath $bundledPython) { $taskPython = $bundledPython }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $taskPython = 'py' }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $taskPython = 'python' }
else { throw 'Python 3.10+ is required. Install Python, then run START.bat again.' }
if (-not $Http) {
  & $taskPython -c 'import cryptography' 2>$null
  if ($LASTEXITCODE -ne 0) { throw 'Install HTTPS dependency: python -m pip install cryptography; or run start.ps1 -Http for localhost preview.' }
}
$appArgs = @('-X','utf8','app.py')
if ($Http) { $appArgs += @('--http','--port','8096'); $appUrl = 'http://localhost:8096' }
else { $appUrl = 'https://localhost:8443' }
if ($Clean) { $env:HELPDESK_DATA = Join-Path $PSScriptRoot 'data\clean-demo' }
else { $appArgs += '--seed' }
Write-Host "Open $appUrl in your browser. Ctrl+C stops the server."
Write-Host 'Accounts: operator, engineer, engineer2, admin. Password: Practice2026!'
Write-Host 'HTTPS uses a self-signed localhost certificate generated on first launch.'
& $taskPython @appArgs
