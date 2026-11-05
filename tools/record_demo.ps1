<#
.SYNOPSIS
  Records a video of GTA2 starting in its classic top-down view and switching
  to first person (or third person) by itself a few seconds into a level.

.DESCRIPTION
  Runs on the Windows PC that has GTA2 + RTX Remix + this mod installed. It
  needs ffmpeg on the PATH (https://www.gyan.dev/ffmpeg/builds/ - any recent
  "full" build has the ddagrab desktop-duplication capture and NVENC).

  What it does:
    1. Sets [camera] mode=classic, demo_switch_seconds=<SwitchAfter> and
       demo_switch_to=<SwitchTo> in gta2dx9.ini beside gta2.exe (the file is
       backed up first and put back afterwards).
    2. Starts recording the whole display with ffmpeg's ddagrab, which sees the
       real path traced picture - plain GDI screen capture of a Remix window is
       black.
    3. Starts gta2.exe. You start a level as usual. <SwitchAfter> seconds
       after the level comes up, the renderer switches the view on its own,
       exactly as pressing the key would.
    4. Stops after <Seconds> seconds and writes the .mp4.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\record_demo.ps1 -GameDir "C:\Games\GTA2"
  powershell -ExecutionPolicy Bypass -File tools\record_demo.ps1 -GameDir "C:\Games\GTA2" -SwitchTo 1 -Seconds 90 -Output chase.mp4
#>
param(
    [Parameter(Mandatory = $true)] [string] $GameDir,
    [int] $Seconds = 75,          # length of the recording, from launch
    [int] $SwitchAfter = 12,      # seconds into the level before the view switches
    [int] $SwitchTo = 2,          # 1 = third person, 2 = first person
    [int] $Fps = 60,
    [string] $Output = "gta2_view_switch.mp4",
    [switch] $Cpu                 # encode with libx264 instead of NVENC
)

$ErrorActionPreference = "Stop"
$exe = Join-Path $GameDir "gta2.exe"
$ini = Join-Path $GameDir "gta2dx9.ini"
if (-not (Test-Path $exe)) { throw "gta2.exe not found in $GameDir" }
if (-not (Test-Path $ini)) { throw "gta2dx9.ini not found in $GameDir - is the mod installed?" }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "ffmpeg is not on the PATH" }

# --- 1. the ini -------------------------------------------------------------
$backup = "$ini.record_demo.bak"
Copy-Item $ini $backup -Force
$text = Get-Content $ini -Raw
function Set-Key([string] $t, [string] $key, [string] $value) {
    $pattern = "(?m)^\s*$key\s*=.*$"
    if ($t -match $pattern) { return [regex]::Replace($t, $pattern, "$key=$value", 1) }
    # Put it under [camera]; add the section if there is none.
    if ($t -match "(?m)^\[camera\]\s*$") { return [regex]::Replace($t, "(?m)^\[camera\]\s*$", "[camera]`r`n$key=$value", 1) }
    return $t + "`r`n[camera]`r`n$key=$value`r`n"
}
$text = Set-Key $text "mode" "classic"
$text = Set-Key $text "demo_switch_seconds" "$SwitchAfter"
$text = Set-Key $text "demo_switch_to" "$SwitchTo"
Set-Content -Path $ini -Value $text -NoNewline

try {
    # --- 2. the recorder --------------------------------------------------
    $out = if ([IO.Path]::IsPathRooted($Output)) { $Output } else { Join-Path (Get-Location) $Output }
    if ($Cpu) {
        $args = @("-y", "-f", "lavfi", "-i", "ddagrab=framerate=$Fps,hwdownload,format=bgra",
                  "-t", "$Seconds", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                  "-pix_fmt", "yuv420p", $out)
    } else {
        $args = @("-y", "-f", "lavfi", "-i", "ddagrab=framerate=$Fps", "-t", "$Seconds",
                  "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19", "-pix_fmt", "yuv420p", $out)
    }
    Write-Host "Recording the display for $Seconds s to $out ..."
    $rec = Start-Process -FilePath "ffmpeg" -ArgumentList $args -PassThru -WindowStyle Minimized

    # --- 3. the game ------------------------------------------------------
    Start-Sleep -Seconds 2
    Write-Host "Starting GTA2. Start a level as usual; $SwitchAfter s after it comes up the view switches by itself."
    $game = Start-Process -FilePath $exe -WorkingDirectory $GameDir -PassThru

    # --- 4. wait ----------------------------------------------------------
    $rec.WaitForExit()
    Write-Host "Done: $out"
    if (-not $game.HasExited) { Write-Host "GTA2 is still running; close it when you like." }
} finally {
    Copy-Item $backup $ini -Force
    Remove-Item $backup -Force
    Write-Host "gta2dx9.ini put back."
}
