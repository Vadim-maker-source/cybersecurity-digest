param([int]$FrontendPort=6760,[string]$LinkFile='')
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
& (Join-Path $PSScriptRoot 'start-local.ps1') -FrontendPort $FrontendPort -Production
$taskPython=Join-Path $taskRoot '.venv\Scripts\python.exe'
if (!$LinkFile) { $LinkFile=Join-Path $taskRoot 'work\public-site-link.txt' }
Write-Host 'Keep this window open. The current public URL is saved in:'
Write-Host $LinkFile
& $taskPython (Join-Path $PSScriptRoot 'share-local.py') --link-file $LinkFile
