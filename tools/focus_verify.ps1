# tools/focus_verify.ps1 [-Dir C:\gta2\play] [-Settle 2] [-Window 6] [-Only "1 2 9"]
# Canonical FIX-FOCUS-HANG verify script (passed 9/9 on the 5090, 14 Nov; focus_watchdog=0 still froze). -Only runs
# just the listed steps (space/comma separated; the baseline always runs). The helper window is $OTHERH: PowerShell
# names are case-insensitive, so a handle in $OTHER overwrote the $other Form (the first draft's bug).
# FIX-FOCUS-HANG verification on native Windows (the 5090). Run in the owner's interactive session (rc_task.ps1),
# with GTA2 already running the fixed gta2dx9.dll/d3ddll.dll and in a level (third person is fine; the front end
# works too, it just has no 'view:' lines). Does not touch the ini or the game files.
#
# How "running" is judged: the DLL's stall sampler writes 'stall sampler: game thread idle' within 1.5 s of the
# game thread stopping and again every second (then every 5 s), and the fix writes 'focus: GTA2 paused itself' /
# 'focus: GTA2 resumed after'. A step PASSes when, in the -Window seconds after -Settle seconds of grace, the log
# has no new 'game thread idle' line (and, in a level, new 'view:' lines). Each step also saves a screenshot of the
# picture window to C:\gta2\rc\focus_verify\.
#
# Steps (the expected result after the fix in brackets):
#  1 our picture window made the foreground (rc_soak/rc_keys -Target present do this)      [runs]
#  2 the picture window focused, then a left click in it (rc_fclick.ps1, repro 2)          [runs]
#  3 another program takes the foreground for 5 s                                          [paused: original GTA2 behaviour]
#    3b ... then a left click on the picture                                               [runs]
#  4 another program again, back by focusing GTA2's own (small) window                     [runs]
#  5 another program again, back by focusing the picture window                            [runs]
#  6 real Alt+Tab away (SendInput), 4 s, Alt+Tab back                                      [runs]
#  7 a toast that takes the activation for 113 ms and closes (the 13 Nov 18.5 h hang)      [runs, or paused only if the
#                                                                                           shell gave the foreground to
#                                                                                           another program; then 7b click]
#  8 a topmost toast that does NOT activate, 3 s                                           [runs throughout]
#  9 the picture window focused, then 20 s of nothing                                      [runs; watchdog stays quiet]
# Before the fix steps 1, 2, 3b(often), 5, 9 freeze the game for good (GPU 0 %, no 'view:' lines).
param([string]$Dir = "C:\gta2\play", [int]$Settle = 2, [int]$Window = 6, [string]$Only = "")
$ErrorActionPreference = "Continue"
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @"
using System; using System.Runtime.InteropServices; using System.Windows.Forms; using System.Drawing;
public class FV {
  [DllImport("user32.dll")] public static extern uint SendInput(uint n, IN[] i, int sz);
  [StructLayout(LayoutKind.Sequential)] public struct KB { public ushort wVk, wScan; public uint dwFlags, time; public IntPtr x; public int p1, p2; }
  [StructLayout(LayoutKind.Sequential)] public struct IN { public uint type; public KB k; }
  public static void Vk(ushort vk, bool up) { IN[] a = new IN[1]; a[0].type = 1; a[0].k.wVk = vk; a[0].k.dwFlags = up ? 2u : 0u; SendInput(1, a, Marshal.SizeOf(typeof(IN))); }
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, int e);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  [DllImport("user32.dll")] public static extern bool SystemParametersInfo(uint a, uint b, IntPtr c, uint d);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
  // Same as rc_soak.ps1's SK.Focus: what a launcher or a test harness does (it ignores WS_EX_NOACTIVATE).
  public static void Focus(IntPtr h) { SystemParametersInfo(0x2001, 0, IntPtr.Zero, 3); uint fp; uint ft = GetWindowThreadProcessId(GetForegroundWindow(), out fp);
    uint me = GetCurrentThreadId(); AttachThreadInput(me, ft, true); ShowWindow(h, 5); BringWindowToTop(h); SetForegroundWindow(h); AttachThreadInput(me, ft, false); }
  public static void Click(int x, int y) { SetCursorPos(x, y); System.Threading.Thread.Sleep(150); mouse_event(2,0,0,0,0); System.Threading.Thread.Sleep(80); mouse_event(4,0,0,0,0); }
}
// A toast that never takes the activation (WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW).
public class QuietToast : Form {
  protected override bool ShowWithoutActivation { get { return true; } }
  protected override CreateParams CreateParams { get { CreateParams p = base.CreateParams; p.ExStyle |= 0x08000000 | 0x8 | 0x80; return p; } }
}
"@
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

$L = Join-Path $Dir "gta2dx9.log"
$OUT = "C:\gta2\rc\focus_verify"; New-Item -ItemType Directory -Force -Path $OUT | Out-Null
$results = New-Object System.Collections.Generic.List[string]
function Say($s) { $t = (Get-Date).ToUniversalTime().ToString("HH:mm:ss"); Write-Output "[$t] $s" }
function Pump($ms) { $end = (Get-Date).AddMilliseconds($ms); while ((Get-Date) -lt $end) { [System.Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 15 } }

$g = Get-Process gta2 -ea 0 | Select-Object -First 1
if (-not $g) { Say "FAIL: gta2.exe is not running"; exit 1 }
if (-not (Test-Path $L)) { Say "FAIL: no log at $L (pass -Dir)"; exit 1 }
# The fixed DLL carries this text; the old one does not.
$dll = Join-Path $Dir "d3ddll.dll"; if (-not (Test-Path $dll)) { $dll = Join-Path $Dir "gta2dx9.dll" }
$bytes = [IO.File]::ReadAllBytes($dll); $txt = [Text.Encoding]::ASCII.GetString($bytes)
if ($txt.IndexOf("GTA2 paused itself for focus loss") -lt 0) { Say "FAIL: $dll is not the FIX-FOCUS-HANG build"; exit 1 }
Say ("dll ok: $dll " + (Get-FileHash $dll -Algorithm MD5).Hash)

function Windows() {
  $w = New-Object System.Collections.Generic.List[object]
  [void][FV]::EnumWindows({ param($h,$l) $p = 0; [void][FV]::GetWindowThreadProcessId($h, [ref]$p); if ($p -eq $g.Id -and [FV]::IsWindowVisible($h)) { $r = New-Object FV+RECT; [void][FV]::GetWindowRect($h, [ref]$r); $w.Add(@($h, (($r.R-$r.L)*($r.B-$r.T)), $r)) }; return $true }, [IntPtr]::Zero)
  return ($w | Sort-Object { $_[1] })
}
$ws = @(Windows)
if ($ws.Count -lt 2) { Say "FAIL: expected GTA2's window and our picture window, found $($ws.Count) visible window(s)"; exit 1 }
$GAME = $ws[0][0]; $PRESENT = $ws[-1][0]; $PR = $ws[-1][2]
$CX = [int](($PR.L + $PR.R) / 2); $CY = [int](($PR.T + $PR.B) / 2)
Say "game window $GAME, picture window $PRESENT ($($PR.R-$PR.L)x$($PR.B-$PR.T)), click point $CX,$CY"

# The "other program": a plain window owned by this PowerShell process.
$other = New-Object System.Windows.Forms.Form
$other.Text = "focus_verify other app"; $other.Width = 520; $other.Height = 300; $other.StartPosition = "Manual"
$other.Left = 40; $other.Top = 40; $other.Show(); Pump 300
$OTHERH = $other.Handle

function LogLen() { (Get-Item $L).Length }
function NewLog($from) {
  $fs = [IO.File]::Open($L, 'Open', 'Read', 'ReadWrite'); try { [void]$fs.Seek($from, 'Begin'); $sr = New-Object IO.StreamReader($fs); $s = $sr.ReadToEnd() } finally { $fs.Close() }
  return $s
}
function Shot($name) {
  try { $r = $PR; $bmp = New-Object Drawing.Bitmap(($r.R-$r.L), ($r.B-$r.T)); $gr = [Drawing.Graphics]::FromImage($bmp)
        $gr.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size); $bmp.Save("$OUT\$name.png"); $gr.Dispose(); $bmp.Dispose() } catch { }
}
function Fg() { $f = [FV]::GetForegroundWindow(); if ($f -eq $GAME) { "game window" } elseif ($f -eq $PRESENT) { "picture window" } elseif ($f -eq $OTHERH) { "other app" } else { "$f" } }
# Judge the game over [Settle, Settle+Window] s from now; $expect = "runs" or "paused".
function Want($n) { return ($Only -eq "" -or (" " + ($Only -replace "[,_]"," ") + " ").Contains(" " + $n + " ")) }
function Judge($step, $what, $expect) {
  Pump ($Settle * 1000)
  $from = LogLen; Pump ($Window * 1000); $s = NewLog $from
  $idle = ([regex]::Matches($s, 'stall sampler: game thread idle')).Count
  $view = ([regex]::Matches($s, '\] view: ')).Count
  $runs = ($idle -eq 0)
  $state = if ($runs) { "runs" } else { "paused" }
  $ok = ($state -eq $expect)
  $line = "{0,-4} {1,-72} {2,-6} (expected {3}; idle lines {4}, view lines {5}; foreground {6})" -f $step, $what, $(if ($ok) {"PASS"} else {"FAIL"}), $expect, $idle, $view, (Fg)
  Say $line; $results.Add($line); Shot ("step_" + $step)

}
$focusFrom = LogLen

Say "baseline: GTA2's own window focused"
[FV]::Focus($GAME); Judge "0" "baseline, GTA2's own window has the focus" "runs"

if (Want "1") { Say "step 1"; [FV]::Focus($PRESENT)
Judge "1" "picture window made the foreground" "runs"

}
if (Want "2") { Say "step 2"; [FV]::Focus($PRESENT); Pump 300; [FV]::Click($CX, $CY)
Judge "2" "picture window focused + left click in it (rc_fclick)" "runs"

}
if (Want "3") { Say "step 3"; [FV]::Focus($OTHERH)
Judge "3" "another program has the foreground" "paused"
[FV]::Click($CX, $CY)
Judge "3b" "... then a left click on the picture" "runs"

}
if (Want "4") { Say "step 4"; [FV]::Focus($OTHERH); Pump 4000; [FV]::Focus($GAME)
Judge "4" "another program 4 s, back by focusing GTA2's own window" "runs"

}
if (Want "5") { Say "step 5"; [FV]::Focus($OTHERH); Pump 4000; [FV]::Focus($PRESENT)
Judge "5" "another program 4 s, back by focusing the picture window" "runs"

}
if (Want "6") { Say "step 6"; [FV]::Focus($OTHERH); Pump 500; [FV]::Focus($GAME); Pump 1000
# Alt+Tab goes to the most recent other window (the helper), Alt+Tab again comes back to GTA2's window.
[FV]::Vk(0x12, $false); Pump 60; [FV]::Vk(0x09, $false); Pump 60; [FV]::Vk(0x09, $true); Pump 60; [FV]::Vk(0x12, $true)
Pump 4000; $mid = Fg
[FV]::Vk(0x12, $false); Pump 60; [FV]::Vk(0x09, $false); Pump 60; [FV]::Vk(0x09, $true); Pump 60; [FV]::Vk(0x12, $true)
Say "  (foreground during the Alt+Tab away: $mid)"
Judge "6" "real Alt+Tab away 4 s and Alt+Tab back" "runs"

}
# The helper window goes away for 7 and 8, so the shell cannot simply hand the activation to it.
$other.Hide(); Pump 200
if (Want "7") { Say "step 7"; [FV]::Focus($GAME); Pump 1500
$toast = New-Object System.Windows.Forms.Form
$toast.FormBorderStyle = "None"; $toast.TopMost = $true; $toast.ShowInTaskbar = $false; $toast.StartPosition = "Manual"
$toast.Width = 360; $toast.Height = 100; $toast.Left = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Right - 380
$toast.Top = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Bottom - 120; $toast.BackColor = [Drawing.Color]::SteelBlue
$toast.Show(); $toast.Activate(); Pump 113; $toast.Close(); $toast.Dispose()
Pump 500; $after = Fg; Say "  (foreground after the toast closed: $after)"
if ($after -eq "game window" -or $after -eq "picture window") {
  Judge "7" "activating toast for 113 ms, foreground came back to us" "runs"
} else {
  Judge "7" "activating toast for 113 ms, foreground went to $after" "paused"
  [FV]::Click($CX, $CY); Judge "7b" "... then a left click on the picture" "runs"
}

}
if (Want "8") { Say "step 8"; [FV]::Focus($GAME); Pump 1500
$q = New-Object QuietToast
$q.FormBorderStyle = "None"; $q.ShowInTaskbar = $false; $q.StartPosition = "Manual"; $q.Width = 360; $q.Height = 100
$q.Left = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Right - 380; $q.Top = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Bottom - 120
$q.BackColor = [Drawing.Color]::DarkOrange; $q.Show()
Judge "8" "non-activating topmost toast on screen" "runs"
$q.Close(); $q.Dispose()

}
if (Want "9") { Say "step 9"; [FV]::Focus($PRESENT); Pump 20000
Judge "9" "picture window focused, then 20 s of nothing" "runs"

}
# Leave the game as the player would have it.
$other.Close(); $other.Dispose(); [FV]::Focus($GAME); Pump 500

$s = NewLog $focusFrom
$f = ($s -split "`n") | Where-Object { $_ -match 'focus:|stall sampler|FAULT|devtools: present' }
Set-Content "$OUT\focus_lines.txt" $f -Encoding Ascii
$faults = ([regex]::Matches($s, 'FAULT')).Count
Say "----- summary -----"
$results | ForEach-Object { Write-Output $_ }
$fails = ($results | Where-Object { $_ -match ' FAIL ' }).Count
Write-Output ("FAULT lines during the test: $faults; focus/stall log lines: $OUT\focus_lines.txt ($($f.Count) lines); screenshots: $OUT")
Write-Output ("watchdog asks: " + ([regex]::Matches($s, 'focus: watchdog: GTA2 paused')).Count + ", synthetic WM_SETFOCUS: " + ([regex]::Matches($s, 'posted WM_SETFOCUS')).Count + ", hand-overs from the picture window: " + ([regex]::Matches($s, 'handing it to the game window')).Count + ", pauses: " + ([regex]::Matches($s, 'GTA2 paused itself for focus loss')).Count + ", resumes: " + ([regex]::Matches($s, 'GTA2 resumed after')).Count)
if ($fails -eq 0 -and $faults -eq 0) { Write-Output "RESULT: PASS" } else { Write-Output "RESULT: FAIL ($fails step(s), $faults FAULT)" }
