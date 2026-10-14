[CmdletBinding(SupportsShouldProcess)]
param([string]$PostgresBin='C:\Program Files\PostgreSQL\18\bin')
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$taskPidPath=Join-Path $taskRoot 'work\local-processes.json'
if (Test-Path -LiteralPath $taskPidPath) {
 foreach ($taskEntry in (Get-Content -LiteralPath $taskPidPath -Raw | ConvertFrom-Json)) {
  $taskProcess=Get-Process -Id $taskEntry.id -ErrorAction SilentlyContinue
  if (!$taskProcess) { continue }
  if ($taskEntry.started -is [datetime]) {
   $taskRecordedStart=$taskEntry.started.ToUniversalTime()
  } else {
   $taskRecordedStart=([datetime]::Parse([string]$taskEntry.started,[cultureinfo]::InvariantCulture,[System.Globalization.DateTimeStyles]::RoundtripKind)).ToUniversalTime()
  }
  if ([Math]::Abs(($taskProcess.StartTime.ToUniversalTime()-$taskRecordedStart).TotalSeconds) -gt 1) { continue }
  $taskInfo=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskEntry.id)"
  if ($taskInfo.CommandLine -notlike "*$taskRoot*") { continue }
  if ($PSCmdlet.ShouldProcess("Owned process $($taskEntry.id) $($taskEntry.name)",'Stop')) {
   Get-CimInstance Win32_Process -Filter "ParentProcessId=$($taskEntry.id)" | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
   Stop-Process -Id $taskEntry.id -ErrorAction SilentlyContinue
  }
 }
}
$taskData=Join-Path $taskRoot 'work\pgdata'
if (!$taskData.StartsWith($taskRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected database path' }
if (Test-Path -LiteralPath (Join-Path $taskData 'postmaster.pid')) {
 if ($PSCmdlet.ShouldProcess($taskData,'Stop project PostgreSQL')) { & (Join-Path $PostgresBin 'pg_ctl.exe') -D $taskData stop -m fast }
}
if ($WhatIfPreference) { Write-Host 'Preview only. Local services remain running.' } else { Write-Host 'Owned local services stopped. Project data preserved.' }
