param(
    [string]$OutDir = "packaging/tools/runtime"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Out = Join-Path $Root $OutDir
$Build = Join-Path $Root "packaging/tools/.build-win"
New-Item -ItemType Directory -Force -Path $Out, $Build | Out-Null

Write-Host "[tools] yt-dlp"
Invoke-WebRequest -UseBasicParsing `
    -Uri "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" `
    -OutFile (Join-Path $Out "yt-dlp.exe")
Invoke-WebRequest -UseBasicParsing `
    -Uri "https://raw.githubusercontent.com/yt-dlp/yt-dlp/master/LICENSE" `
    -OutFile (Join-Path $Out "YTDLP-LICENSE.txt")

Write-Host "[tools] deno"
$DenoZip = Join-Path $Build "deno.zip"
Invoke-WebRequest -UseBasicParsing `
    -Uri "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" `
    -OutFile $DenoZip
Expand-Archive -Force $DenoZip (Join-Path $Build "deno")
Copy-Item (Join-Path $Build "deno/deno.exe") (Join-Path $Out "deno.exe")
Invoke-WebRequest -UseBasicParsing `
    -Uri "https://raw.githubusercontent.com/denoland/deno/main/LICENSE.md" `
    -OutFile (Join-Path $Out "DENO-LICENSE.txt")

Write-Host "[tools] ffmpeg"
$FfmpegZip = Join-Path $Build "ffmpeg.zip"
Invoke-WebRequest -UseBasicParsing `
    -Uri "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-win64-gpl-8.1.zip" `
    -OutFile $FfmpegZip
Expand-Archive -Force $FfmpegZip (Join-Path $Build "ffmpeg")
$FfmpegRoot = Get-ChildItem (Join-Path $Build "ffmpeg") -Directory | Select-Object -First 1
Copy-Item (Join-Path $FfmpegRoot.FullName "bin/ffmpeg.exe") $Out
Copy-Item (Join-Path $FfmpegRoot.FullName "bin/ffprobe.exe") $Out
$License = Get-ChildItem $FfmpegRoot.FullName -Recurse -Filter "LICENSE*" | Select-Object -First 1
if ($License) { Copy-Item $License.FullName (Join-Path $Out "FFMPEG-LICENSE.txt") }

Write-Host "[tools] SomeDL (PyInstaller)"
$Venv = Join-Path $Build "venv"
if (-not (Test-Path (Join-Path $Venv "Scripts/python.exe"))) {
    python -m venv $Venv
}
& (Join-Path $Venv "Scripts/python.exe") -m pip install --quiet --upgrade pip
& (Join-Path $Venv "Scripts/python.exe") -m pip install --quiet somedl pyinstaller
$Pyi = Join-Path $Build "somedl"
Remove-Item -Recurse -Force $Pyi -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Pyi | Out-Null
Push-Location $Pyi
& (Join-Path $Venv "Scripts/pyinstaller.exe") --onefile --noconfirm --name somedl `
    --collect-all SomeDL --collect-all ytmusicapi --collect-all yt_dlp `
    (Join-Path $Root "packaging/tools/somedl_entry.py")
Pop-Location
Copy-Item (Join-Path $Pyi "dist/somedl.exe") $Out
Invoke-WebRequest -UseBasicParsing `
    -Uri "https://raw.githubusercontent.com/ChemistryGull/SomeDL/main/LICENSE" `
    -OutFile (Join-Path $Out "SOMEDL-LICENSE.txt")

Write-Host "[tools] done: $Out"
Get-ChildItem $Out | Format-Table Name, Length
