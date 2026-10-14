param([int]$HttpPort=6752,[string]$PostgresBin='C:\Program Files\PostgreSQL\18\bin')
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$taskWork=Join-Path $taskRoot 'work'
New-Item -ItemType Directory -Force -Path $taskWork | Out-Null
Set-Location -LiteralPath $taskRoot
if (!(Test-Path -LiteralPath '.env')) { py -3.12 infra/scripts/prepare-env.py }
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) { py -3.12 -m venv .venv }
$taskPython=Join-Path $taskRoot '.venv\Scripts\python.exe'
& $taskPython -m pip install -r backend/requirements.txt
if ($LASTEXITCODE) { throw 'Python dependency installation failed' }
if (!(Test-Path -LiteralPath 'frontend\node_modules')) {
 Push-Location frontend
 npm.cmd ci --no-audit --no-fund
 Pop-Location
 if ($LASTEXITCODE) { throw 'Frontend installation failed' }
}
if (!(Test-Path -LiteralPath (Join-Path $PostgresBin 'pg_ctl.exe'))) { throw 'Set -PostgresBin to an installed PostgreSQL bin directory.' }
$taskPgData=Join-Path $taskWork 'pgdata'
if (!$taskPgData.StartsWith($taskRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected database path' }
if (!(Test-Path -LiteralPath $taskPgData)) {
 & $taskPython -c "from dotenv import dotenv_values;from pathlib import Path;v=dotenv_values('.env');Path('work/pg-password').write_text(v['POSTGRES_PASSWORD'],encoding='utf8')"
 & (Join-Path $PostgresBin 'initdb.exe') -D $taskPgData -U cyber_digest --pwfile=(Join-Path $taskWork 'pg-password') --auth=scram-sha-256 --encoding=UTF8 --locale=C
 if ($LASTEXITCODE) { throw 'PostgreSQL init failed' }
}
$taskDbListener=Get-NetTCPConnection -LocalPort 55432 -State Listen -ErrorAction SilentlyContinue
if ($taskDbListener) {
 $taskPidFile=Join-Path $taskPgData 'postmaster.pid'
 if (!(Test-Path -LiteralPath $taskPidFile)) { throw 'Port 55432 is occupied by another PostgreSQL instance.' }
 $taskPgPid=[int](Get-Content -LiteralPath $taskPidFile -TotalCount 1)
 if ($taskDbListener.OwningProcess -notcontains $taskPgPid) { throw 'Port 55432 is not owned by this project.' }
} else {
 & (Join-Path $PostgresBin 'pg_ctl.exe') -D $taskPgData -l (Join-Path $taskWork 'postgres.log') -o '-p 55432 -h 127.0.0.1' start
 if ($LASTEXITCODE) { throw 'PostgreSQL startup failed' }
}
& $taskPython infra/scripts/native-db.py
if ($LASTEXITCODE) { throw 'Project database setup failed' }
Push-Location backend
& $taskPython -m alembic upgrade head
Pop-Location
if ($LASTEXITCODE) { throw 'Migration failed' }

$taskProcesses=@()
function Start-TaskService([string]$Name,[string]$Exe,[string[]]$Arguments,[string]$Directory,[int]$Port=0) {
 $taskListener=if($Port){Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue}else{$null}
 if ($taskListener) {
  $taskExisting=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskListener[0].OwningProcess)"
  if ($taskExisting.CommandLine -notlike "*$taskRoot*") {
   # Uvicorn reloader children inherit module arguments; verify its parent too.
   $taskParent=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskExisting.ParentProcessId)"
   if ($taskParent.CommandLine -notlike "*$taskRoot*") { throw "Port $Port is occupied; inspect process $($taskExisting.ProcessId)." }
  }
  Write-Host "$Name already running on $Port"
  $taskRunningProcess=Get-Process -Id $taskExisting.ProcessId
  $script:taskProcesses+=@{id=$taskRunningProcess.Id;name=$Name;started=$taskRunningProcess.StartTime.ToUniversalTime().ToString('o')}
  if ($taskParent -and $taskParent.CommandLine -like "*$taskRoot*") {
   $taskRunningParent=Get-Process -Id $taskParent.ProcessId
   $script:taskProcesses+=@{id=$taskRunningParent.Id;name="$Name-parent";started=$taskRunningParent.StartTime.ToUniversalTime().ToString('o')}
  }
  return
 }
 $taskProcess=Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory $Directory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskWork "$Name.stdout.log") -RedirectStandardError (Join-Path $taskWork "$Name.stderr.log")
 $script:taskProcesses+=@{id=$taskProcess.Id;name=$Name;started=$taskProcess.StartTime.ToUniversalTime().ToString('o')}
}
Start-TaskService 'api' $taskPython @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000') (Join-Path $taskRoot 'backend') 8000
$taskWorker=Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $taskPython -and $_.CommandLine -match '-m app.worker' }
if (!$taskWorker) { Start-TaskService 'worker' $taskPython @('-m','app.worker') (Join-Path $taskRoot 'backend') } else {
 foreach ($taskRunning in $taskWorker) {
  $taskExistingWorker=Get-Process -Id $taskRunning.ProcessId
  $taskProcesses+=@{id=$taskRunning.ProcessId;name='worker';started=$taskExistingWorker.StartTime.ToUniversalTime().ToString('o')}
 }
}
$taskNode=(Get-Command node.exe).Source
Start-TaskService 'frontend' $taskNode @((Join-Path $taskRoot 'frontend\node_modules\next\dist\bin\next'),'dev','--hostname','127.0.0.1') (Join-Path $taskRoot 'frontend') 3000
$taskNginx=Join-Path $taskWork 'runtime\nginx-1.30.6\nginx.exe'
if (!(Test-Path -LiteralPath $taskNginx)) {
 Invoke-WebRequest -Uri 'https://nginx.org/download/nginx-1.30.6.zip' -OutFile (Join-Path $taskWork 'nginx.zip')
 Expand-Archive -LiteralPath (Join-Path $taskWork 'nginx.zip') -DestinationPath (Join-Path $taskWork 'runtime') -Force
}
$taskPrefix=Join-Path $taskWork 'nginx-prefix'
New-Item -ItemType Directory -Force -Path (Join-Path $taskPrefix 'logs'),(Join-Path $taskPrefix 'temp') | Out-Null
$taskConfig=Join-Path $taskWork 'nginx-local.conf'
(Get-Content -LiteralPath 'infra\nginx\local.conf' -Raw).Replace('127.0.0.1:6752',"127.0.0.1:$HttpPort") | Set-Content -LiteralPath $taskConfig -Encoding ascii
Start-TaskService 'nginx' $taskNginx @('-p',($taskPrefix.Replace('\','/')+'/'),'-c',$taskConfig.Replace('\','/'),'-g','"daemon off;"') $taskPrefix $HttpPort
$taskPidPath=Join-Path $taskWork 'local-processes.json'
if ((Test-Path -LiteralPath $taskPidPath) -and (Get-Item -LiteralPath $taskPidPath).Length -gt 0) {
 $taskPriorProcesses=Get-Content -LiteralPath $taskPidPath -Raw | ConvertFrom-Json
 $taskProcesses+=$taskPriorProcesses
}
$taskProcesses | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $taskPidPath -Encoding utf8
Write-Host "Local website: http://localhost:$HttpPort"
Write-Host 'Editor credentials are in .env. No server deployment performed.'
