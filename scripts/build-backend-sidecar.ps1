param(
  [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Entry = Join-Path $Root "backend\uim_core\api_entry.py"
$BuildRoot = Join-Path $Root ".codex_tmp\pyinstaller-backend"
$DistRoot = Join-Path $BuildRoot "dist"
$WorkRoot = Join-Path $BuildRoot "build"
$SpecRoot = Join-Path $BuildRoot "spec"
$BundleDir = Join-Path $Root "src-tauri\binaries"
$ResourceDir = Join-Path $Root "src-tauri"
$SidecarBase = "uim-backend"
$SidecarExe = "$SidecarBase-$TargetTriple.exe"
$SupportDir = "$SidecarBase-support"

if (!(Test-Path $Python)) {
  throw "Python virtualenv was not found at $Python. Create .venv and install backend requirements first."
}

& $Python -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller is not installed in .venv. Install it with: .venv\Scripts\python.exe -m pip install pyinstaller"
}

New-Item -ItemType Directory -Force -Path $BuildRoot, $DistRoot, $WorkRoot, $SpecRoot, $BundleDir, $ResourceDir | Out-Null

& $Python -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --name $SidecarBase `
  --distpath $DistRoot `
  --workpath $WorkRoot `
  --specpath $SpecRoot `
  --contents-directory $SupportDir `
  --paths (Join-Path $Root "backend") `
  --hidden-import uvicorn.lifespan.on `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uim_core.api `
  --hidden-import uim_core.mcp_server `
  --exclude-module torch `
  --exclude-module torchvision `
  --exclude-module sam2 `
  $Entry

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller backend sidecar build failed."
}

$BuiltDir = Join-Path $DistRoot $SidecarBase
$BuiltExe = Join-Path $BuiltDir "$SidecarBase.exe"
$BuiltSupport = Join-Path $BuiltDir $SupportDir
$TargetExe = Join-Path $BundleDir $SidecarExe
$LocalTargetSupport = Join-Path $BundleDir $SupportDir
$BundleTargetSupport = Join-Path $ResourceDir $SupportDir

if (!(Test-Path $BuiltExe)) {
  throw "PyInstaller did not create $BuiltExe"
}
if (!(Test-Path $BuiltSupport)) {
  throw "PyInstaller did not create $BuiltSupport"
}

if (Test-Path $TargetExe) {
  Remove-Item -LiteralPath $TargetExe -Force
}
if (Test-Path $LocalTargetSupport) {
  Remove-Item -LiteralPath $LocalTargetSupport -Recurse -Force
}
if (Test-Path $BundleTargetSupport) {
  Remove-Item -LiteralPath $BundleTargetSupport -Recurse -Force
}

Copy-Item -LiteralPath $BuiltExe -Destination $TargetExe
Copy-Item -LiteralPath $BuiltSupport -Destination $LocalTargetSupport -Recurse
Copy-Item -LiteralPath $BuiltSupport -Destination $BundleTargetSupport -Recurse

Write-Host "Backend sidecar ready:"
Write-Host "  $TargetExe"
Write-Host "  $LocalTargetSupport"
Write-Host "  $BundleTargetSupport"
