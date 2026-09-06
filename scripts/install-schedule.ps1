param(
    [string]$At = "18:30"
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "run-daily.ps1"
$taskName = "ShortsFactoryDaily"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Generate one original YouTube Short per day" -Force
Write-Host "Task $taskName created. Daily start time: $At"
