$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$env:SAU_BUNDLE_BROWSER = '0'

if (-not (Test-Path -LiteralPath $Python)) { throw 'Missing .venv. Run uv venv first.' }

Push-Location (Join-Path $ProjectRoot 'sau_frontend')
try {
    npm install --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'frontend build failed' }
} finally { Pop-Location }

uv pip install --python $Python pyinstaller pillow
if ($LASTEXITCODE -ne 0) { throw 'packaging dependency installation failed' }
& $Python (Join-Path $PSScriptRoot 'make_icons.py')
if ($LASTEXITCODE -ne 0) { throw 'icon generation failed' }

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot 'daydream_dispatch.spec')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
} finally { Pop-Location }

Copy-Item -LiteralPath (Join-Path $ProjectRoot 'LICENSE') -Destination (Join-Path $ProjectRoot 'dist\DaydreamDispatch\LICENSE.txt') -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'THIRD_PARTY_NOTICES.txt') -Destination (Join-Path $ProjectRoot 'dist\DaydreamDispatch\THIRD_PARTY_NOTICES.txt') -Force

$Release = Join-Path $ProjectRoot 'release'
New-Item -ItemType Directory -Force -Path $Release | Out-Null
$Portable = Join-Path $Release 'DaydreamDispatch-0.1.0-Windows-x64-Portable.zip'
if (Test-Path -LiteralPath $Portable) { Remove-Item -LiteralPath $Portable -Force }
Compress-Archive -Path (Join-Path $ProjectRoot 'dist\DaydreamDispatch\*') -DestinationPath $Portable -CompressionLevel Optimal

$Iscc = @(
    (Join-Path ${env:LOCALAPPDATA} 'Programs\Inno Setup 6\ISCC.exe'),
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    'C:\Program Files\Inno Setup 6\ISCC.exe'
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($Iscc) {
    & $Iscc (Join-Path $PSScriptRoot 'windows-installer.iss')
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed' }
} else {
    Write-Warning 'Inno Setup 6 not found. Portable ZIP was created; install Inno Setup and rerun to create Setup.exe.'
}
