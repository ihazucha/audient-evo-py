# User config:
# -------------------------------------------------------------------------------------------------
$hardwareId = 'USB\VID_2708&PID_0006'
$devconExePath = "C:\Program Files (x86)\AMD\Chipset_Software\Prerequisites\devcon.exe"
$winUsbInfPath = "C:\Windows\INF\oem146.inf"
$audientInfPath = "C:\Windows\INF\oem161.inf"


# Config check
# -------------------------------------------------------------------------------------------------
$isConfigOk = $true
if (-not (Test-Path $devconExePath)) {
  Write-Host "[E] devcon.exe not found at: $devconExePath" -BackgroundColor Red
  $isConfigOk = $false
}
if (-not (Test-Path $winUsbInfPath)) {
  Write-Host "[E] WinUSB .inf not found at: $winUsbInfPath" -BackgroundColor Red
  $isConfigOk = $false
}
if (-not (Test-Path $audientInfPath)) {
  Write-Host "[E] Audient .inf not found at: $audientInfPath" -BackgroundColor Red
  $isConfigOk = $false
}

# Check file contents for keywords
if ($isConfigOk) {
  if (-not (Get-Content $winUsbInfPath | Select-String -Pattern 'winusb' -SimpleMatch -CaseSensitive:$false)) {
    Write-Host "[E] Keyword 'winusb' not found in $winUsbInfPath. Possibly wrong driver selected." -BackgroundColor Red
    $isConfigOk = $false
  }
  if (-not (Get-Content $audientInfPath | Select-String -Pattern 'audient' -SimpleMatch -CaseSensitive:$false)) {
    Write-Host "[E] Required keyword 'audient' not found in $audientInfPath. Possibly wrong driver selected." -BackgroundColor Red
    $isConfigOk = $false
  }
}

$instanceId = (Get-PnpDevice | Where-Object {
  $_.InstanceId -like "$hardwareId`\*" -and $_.Status -like 'OK'
}).InstanceId
if (-not $instanceId) {
  Write-Host "[E] Unable to get instance ID for device $hardwareId." -BackgroundColor Red
  $isConfigOk = $false
}

if (-not $isConfigOk) { exit 1 }


# Helpers
# -------------------------------------------------------------------------------------------------
function setDriver {
  param([string]$InfPath)
  Write-Host "Setting to $InfPath driver..."
  $result = & $devconExePath update $InfPath $hardwareID 2>&1 | Out-String
  $exitCode = $LASTEXITCODE
  Write-Host "${devconExePath}:`n$result" -ForegroundColor DarkGray
  if ($exitCode -ne 0) {
    Write-Host "[E]: devcon.exe returned with code $exitCode" -ForegroundColor Red
  }
  else {
    Write-Host "Driver $InfPath set" -ForegroundColor Green
  }
}

function isUsingEvoDriver {
  Write-Host "Checking active driver..."
  $currentDriver = & $devconExePath driverfiles $hardwareId | Out-String
  Write-Host "${devconExePath}:`n$currentDriver" -ForegroundColor DarkGray
  # driverfiles output contains hw ID if driver is attached
  if (-not ($currentDriver -like "*$hardwareId*")) {
    Write-Host "[E] Driver for device $hardwareId not found - exiting..." -BackgroundColor Red
    exit 1
  }
  if ($currentDriver -like "*audientusbaudio.sys*") {
      Write-Host "Current driver: audientusbaudio.sys"
      return $true
  }
  Write-Host "Current driver: audientusbaudio.sys"
  return $false
}

function stopEvoApp {
  $evoProcess = Get-Process -Name 'EVO' -ErrorAction SilentlyContinue
  if ($evoProcess) {
      Stop-Process -Name 'EVO'
      Write-Host "Stopped EVO app"
  }
}


# Main
# -------------------------------------------------------------------------------------------------
if (isUsingEvoDriver) {
  # EVO -> WinUSB
  stopEvoApp
  Disable-PnpDevice -InstanceId $instanceId -Confirm:$false
  setDriver -InfPath $winUsbInfPath
}
else {
  # WinUSB -> EVO
  Disable-PnpDevice -InstanceId $instanceId -Confirm:$false
  setDriver -InfPath $audientInfPath
}
