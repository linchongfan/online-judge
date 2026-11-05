# Install (or remove) the XinbaoyanJudgeWatchdog scheduled task.
#
# The task starts at boot, runs as SYSTEM with highest privileges, and its
# action is: python scripts/judge_watchdog.py start
#
# Usage (elevated PowerShell):
#   install_judge_watchdog.ps1            # install
#   install_judge_watchdog.ps1 -Remove    # uninstall
#
# To run as a specific Administrators account instead of SYSTEM, pass:
#   -RunAsUser "DOMAIN\username"

param(
    [switch]$Remove,
    [string]$RunAsUser = "SYSTEM"
)

$ErrorActionPreference = "Stop"

$TaskName = "XinbaoyanJudgeWatchdog"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}
$Arguments = "`"$ProjectRoot\scripts\judge_watchdog.py`" start"

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        Write-Host "Scheduled task '$TaskName' does not exist; nothing to remove."
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Scheduled task '$TaskName' removed."
    exit 0
}

if ($RunAsUser -eq "SYSTEM") {
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
} else {
    # S4U runs without storing a password; fine for a local watchdog that only
    # needs local resources (loopback Redis, local files).
    $principal = New-ScheduledTaskPrincipal -UserId $RunAsUser -LogonType S4U -RunLevel Highest
}

$action = New-ScheduledTaskAction -Execute "`"$PythonExe`"" -Argument $Arguments -WorkingDirectory "$ProjectRoot"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    Write-Host "Scheduled task '$TaskName' already exists; re-registering."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Watchdog for the Xinbaoyan judge Celery worker (start at boot)."
Write-Host "Scheduled task '$TaskName' installed (runs as $RunAsUser, starts at boot)."
Write-Host "Action: $PythonExe scripts\judge_watchdog.py start"
Write-Host "Start now with: Start-ScheduledTask -TaskName '$TaskName'"
