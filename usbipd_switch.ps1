param (
  [Parameter(Mandatory = $true)]
  [string]$BusID
)

$usbipdStateJson = usbipd state | ConvertFrom-Json
$device = $usbipdStateJson.Devices | Where-Object { $_.BusId -eq $BusID }

if ($device -eq $null) {
    Write-Host "No device found on BusId $BusID"
    exit 1
}

if ($device.ClientIPAddress -ne $null) {
    usbipd detach --busid $BusID
    Write-Host "Detached BusId $BusID"
}
else {
    $evoProcess = Get-Process -Name 'EVO' -ErrorAction SilentlyContinue
    if ($evoProcess) {
        Stop-Process -Name 'EVO'
        Write-Host "Terminating EVO controller"
    }
    usbipd attach --wsl --busid $BusID
    Write-Host "Attached BusId $BusID"
}


