# =============================================================================
# SandhiNaad one-shot setup for Windows
#   Installs: Python 3.12, UI packages, ML packages, Arduino IDE, arduino-cli,
#             ESP32 board core 2.0.17, Adafruit BNO055 libraries
#   Then:     compiles the firmware to prove everything works
#   Optional: uploads it:   .\setup.ps1 -Upload -Port COM5
#
# Run from PowerShell:
#   cd $HOME\Desktop\sandhinaad
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
# =============================================================================
param(
    [switch]$Upload,
    [string]$Port = "",
    [switch]$SkipArduinoIDE
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Log  = Join-Path $Root "setup_log.txt"
Start-Transcript -Path $Log -Force | Out-Null

function Step($msg)  { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Ok($msg)    { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Fail($msg)  { Write-Host "  [FAIL] $msg" -ForegroundColor Red }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path","User")
}
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function WingetInstall($id, $name) {
    Write-Host "  installing $name via winget ..."
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements | Out-Host
    Refresh-Path
}

$results = [ordered]@{}

# ---------------------------------------------------------------- 0. winget
Step "Checking winget"
if (-not (Have winget)) {
    Fail "winget not found. Install 'App Installer' from the Microsoft Store, then re-run."
    Stop-Transcript | Out-Null; exit 1
}
Ok "winget available"

# ---------------------------------------------------------------- 1. Python
Step "Python 3.12"
$py = $null
Refresh-Path
if (Have py) {
    $v = & py -3.12 --version 2>$null
    if ($LASTEXITCODE -eq 0) { $py = @("py","-3.12") }
    else {
        $v = & py -3.11 --version 2>$null
        if ($LASTEXITCODE -eq 0) { $py = @("py","-3.11") }
    }
}
if (-not $py) {
    WingetInstall "Python.Python.3.12" "Python 3.12"
    if (Have py) { $py = @("py","-3.12") }
    else {
        $cand = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
        if (Test-Path $cand) { $py = @($cand) }
    }
}
if ($py) {
    $pyExe = $py[0]; $pyArgs = @(); if ($py.Count -gt 1) { $pyArgs = $py[1..($py.Count-1)] }
    Ok ("Using " + (& $pyExe @pyArgs --version))
    $results["Python"] = "OK"
} else {
    Fail "Python install failed. Install Python 3.12 from python.org (tick 'Add to PATH') and re-run."
    $results["Python"] = "FAILED"
}

# ---------------------------------------------------------------- 2. pip packages
if ($py) {
    Step "Python packages (UI + ML)"
    & $pyExe @pyArgs -m pip install --upgrade pip | Out-Host
    & $pyExe @pyArgs -m pip install -r (Join-Path $Root "host\requirements.txt") | Out-Host
    $uiOk = ($LASTEXITCODE -eq 0)
    & $pyExe @pyArgs -m pip install pandas matplotlib | Out-Host
    & $pyExe @pyArgs -c "import PySide6, pyqtgraph, serial, numpy, scipy, sklearn, joblib; print('imports ok')"
    if ($uiOk -and $LASTEXITCODE -eq 0) { Ok "UI packages installed"; $results["UI packages"] = "OK" }
    else { Fail "Some packages failed - see log"; $results["UI packages"] = "FAILED" }

    Step "Host self-test (simulator -> parser -> model, 5 s)"
    Push-Location (Join-Path $Root "host")
    $test = @"
import time
from serial_link import SerialLink
from model import OAScreeningModel
L = SerialLink('SIMULATOR'); L.connect(); L.send_command('START')
t = time.time(); n = 0
while time.time() - t < 5:
    n += len(L.get_packets()); time.sleep(0.05)
s = L.stats; L.disconnect()
m = OAScreeningModel()
print('packets', n, 'crc', s['crc_errors'], 'drops', s['drops'], 'model_loaded', m.loaded)
assert n > 500 and s['crc_errors'] == 0 and m.loaded
print('HOST SELFTEST PASS')
"@
    $test | & $pyExe @pyArgs -
    if ($LASTEXITCODE -eq 0) { Ok "Host pipeline works"; $results["Host self-test"] = "PASS" }
    else { Fail "Host self-test failed - see log"; $results["Host self-test"] = "FAILED" }
    Pop-Location
}

# ---------------------------------------------------------------- 3. Arduino IDE (GUI)
if (-not $SkipArduinoIDE) {
    Step "Arduino IDE 2"
    $ide = Get-ChildItem "$env:LOCALAPPDATA\Programs\Arduino IDE\Arduino IDE.exe","$env:ProgramFiles\Arduino IDE\Arduino IDE.exe" -ErrorAction SilentlyContinue
    if ($ide) { Ok "Arduino IDE already installed" }
    else { WingetInstall "ArduinoSA.IDE.stable" "Arduino IDE" }
    $results["Arduino IDE"] = "installed (optional)"
}

# ---------------------------------------------------------------- 4. arduino-cli + ESP32 core + libs
Step "arduino-cli"
Refresh-Path
if (-not (Have arduino-cli)) { WingetInstall "ArduinoSA.CLI" "arduino-cli" }
if (-not (Have arduino-cli)) {
    $c = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter arduino-cli.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { $env:Path += ";" + $c.DirectoryName }
}
if (Have arduino-cli) {
    Ok (arduino-cli version)
    Step "ESP32 board core 2.0.17 (large download, several minutes)"
    arduino-cli config init --overwrite | Out-Null
    arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
    arduino-cli core update-index | Out-Host
    arduino-cli core install esp32:esp32@2.0.17 | Out-Host
    if ($LASTEXITCODE -eq 0) { Ok "esp32 core 2.0.17"; $results["ESP32 core"] = "OK" } else { Fail "core install failed"; $results["ESP32 core"] = "FAILED" }

    Step "Libraries"
    arduino-cli lib install "Adafruit BNO055" "Adafruit Unified Sensor" "Adafruit BusIO" | Out-Host
    if ($LASTEXITCODE -eq 0) { Ok "Adafruit libraries"; $results["Libraries"] = "OK" } else { Fail "library install failed"; $results["Libraries"] = "FAILED" }

    Step "Compiling firmware (ESP32 Dev Module, Core Debug Level = None)"
    $fqbn = "esp32:esp32:esp32:DebugLevel=none,UploadSpeed=921600"
    $sketch = Join-Path $Root "firmware\SandhiNaad"
    arduino-cli compile --fqbn $fqbn $sketch | Out-Host
    if ($LASTEXITCODE -eq 0) { Ok "Firmware compiles"; $results["Firmware compile"] = "PASS" }
    else { Fail "Compile failed - copy the error above to Claude"; $results["Firmware compile"] = "FAILED" }

    if ($Upload) {
        Step "Uploading firmware"
        if (-not $Port) {
            arduino-cli board list | Out-Host
            Warn "Pass the port, e.g.  .\setup.ps1 -Upload -Port COM5"
        } else {
            arduino-cli upload -p $Port --fqbn $fqbn $sketch | Out-Host
            if ($LASTEXITCODE -eq 0) { Ok "Uploaded to $Port"; $results["Upload"] = "OK" }
            else { Fail "Upload failed (hold BOOT while it says Connecting...)"; $results["Upload"] = "FAILED" }
        }
    }
} else {
    Fail "arduino-cli not available"
    $results["arduino-cli"] = "FAILED"
}

# ---------------------------------------------------------------- summary
Step "Summary"
$results.GetEnumerator() | ForEach-Object { "{0,-20} {1}" -f $_.Key, $_.Value } | Out-Host
Write-Host "`nSerial ports seen now:"
if (Have arduino-cli) { arduino-cli board list | Out-Host }
Write-Host "`nNext:"
Write-Host "  UI:      cd `"$Root\host`"; py app.py      (pick SIMULATOR or your COM port)"
Write-Host "  Upload:  .\setup.ps1 -SkipArduinoIDE -Upload -Port COMx"
Write-Host "Full log: $Log"
Stop-Transcript | Out-Null
