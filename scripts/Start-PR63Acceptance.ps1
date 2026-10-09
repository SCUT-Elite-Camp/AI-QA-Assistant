param(
  [Parameter(Mandatory=$true)][string]$BaseEnvironment,
  [Parameter(Mandatory=$true)][string]$Python,
  [Parameter(Mandatory=$true)][string]$Runtime,
  [switch]$Prepare,
  [switch]$ResumeVectors,
  [switch]$Start,
  [string]$Sources,
  [string]$Metadata,
  [string]$WebBuild,
  [switch]$WebOnly,
  [switch]$AgentOnly,
  [switch]$AttachmentOnly
)
$ErrorActionPreference = 'Stop'
$integrationRepo = Split-Path $PSScriptRoot -Parent
. $BaseEnvironment
$runtimePath = [IO.Path]::GetFullPath($Runtime)
if ($runtimePath -eq $integrationRepo -or $runtimePath.StartsWith($integrationRepo + [IO.Path]::DirectorySeparatorChar)) { throw 'Runtime must be outside the checkout' }
New-Item -ItemType Directory -Force -Path $runtimePath | Out-Null
Get-Content -LiteralPath (Join-Path $integrationRepo 'agent/.integration-runtime.env.local') | ForEach-Object {
  if ($_ -match '^([A-Z_]+)=(.+)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2]) }
}
$env:WEB_SQLITE_PATH = Join-Path $runtimePath 'permissions.db'
$env:TURSO_DATABASE_URL = 'file:' + ($env:WEB_SQLITE_PATH -replace '\\','/')
$env:CONFLUENCE_AUTH_ENV_FILE = Join-Path $integrationRepo 'agent/.source-access.env.local'
$env:SOURCE_ACCESS_MODE = 'native'
$env:RESEARCH_DOCUMENTS_DIR = Join-Path $runtimePath 'documents'
$env:AI_QA_DATA_DIR = $runtimePath
$env:TOPICS_DATA_DIR = Join-Path $runtimePath 'topics'
$env:BM25_INDEX_PATH = Join-Path $runtimePath 'bm25.pkl'
$env:MILVUS_COLLECTION = 'pr63_access_evidence_20261009'
$env:MILVUS_HOST = '127.0.0.1'
$env:MILVUS_PORT = '19539'
$env:RESEARCH_DATABASE_PATH = Join-Path $runtimePath 'research.db'
$env:RESEARCH_CHECKPOINT_PATH = Join-Path $runtimePath 'research.checkpoints.db'
$env:LOG_FILE = Join-Path $runtimePath 'agent.log'
$env:ATTACHMENT_DATA_DIR = Join-Path $runtimePath 'attachments'
$env:ATTACHMENT_SERVICE_URL = 'http://127.0.0.1:8219'
$env:ATTACHMENT_PORT = '8219'
$env:ATTACHMENT_VECTOR_INDEX_ENABLED = 'true'
$env:ATTACHMENT_MILVUS_COLLECTION = 'pr63_private_evidence_20261009'
$env:ATTACHMENTS_ENABLED = 'true'
$env:PERSONAL_LIBRARY_ENABLED = 'true'
$env:ALLOW_FAKE_ATTACHMENT_SCANNER = 'false'
$env:PERSISTENT_MEMORY_ENABLED = 'true'
$env:SESSION_FACT_ENABLED = 'true'
$env:SESSION_COOKIE_SECURE = 'false'
$env:PYTHONPATH = @($integrationRepo,(Join-Path $integrationRepo 'agent'),(Join-Path $integrationRepo 'data-pipeline'),(Join-Path $integrationRepo 'data-persistence'),(Join-Path $integrationRepo 'attachment-service'),(Join-Path $integrationRepo 'toolset')) -join ';'
$env:AGENT_BASE_URL = 'http://127.0.0.1:8109'
$env:ALLOW_DEV_LOGIN = 'true'
$env:NODE_ENV = 'development'
$nodePath = 'C:/Program Files/nodejs/node.exe'
if ($Prepare) {
  Push-Location (Join-Path $integrationRepo 'frontend')
  try { & $nodePath scripts/migrate-acceptance-db.mjs; if ($LASTEXITCODE -ne 0) { throw 'migration_failed' } } finally { Pop-Location }
  & $Python (Join-Path $integrationRepo 'agent/eval/prepare_integration_runtime.py') --sources $Sources --metadata $Metadata --runtime $runtimePath --collection $env:MILVUS_COLLECTION
  if ($LASTEXITCODE -ne 0) { throw 'fixture_preparation_failed' }
}
if ($ResumeVectors) {
  & $Python (Join-Path $integrationRepo 'agent/eval/prepare_integration_runtime.py') --sources $Sources --metadata $Metadata --runtime $runtimePath --collection $env:MILVUS_COLLECTION --resume-vectors
  if ($LASTEXITCODE -ne 0) { throw 'vector_preparation_failed' }
}
if ($Start -or $WebOnly -or $AgentOnly -or $AttachmentOnly) {
  if (@($Start,$WebOnly,$AgentOnly,$AttachmentOnly).Where({ $_ }).Count -ne 1) { throw 'Choose one start mode' }
  foreach ($port in $(if ($WebOnly) { @(3019) } elseif ($AgentOnly) { @(8109) } elseif ($AttachmentOnly) { @(8219) } else { @(8109,8219,3019) })) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "Port $port is already in use; no existing service will be stopped" }
  }
  if ($Start -or $AttachmentOnly) {
    $attachment = Start-Process -FilePath $Python -ArgumentList @('-m','attachment_service') -WorkingDirectory (Join-Path $integrationRepo 'attachment-service') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'attachment.stdout.log') -RedirectStandardError (Join-Path $runtimePath 'attachment.stderr.log')
  }
  if ($Start -or $AgentOnly) {
    $agent = Start-Process -FilePath $Python -ArgumentList @('-m','uvicorn','app:app','--host','127.0.0.1','--port','8109') -WorkingDirectory (Join-Path $integrationRepo 'agent') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'agent.stdout.log') -RedirectStandardError (Join-Path $runtimePath 'agent.stderr.log')
  }
  if ($Start -or $WebOnly) {
    $env:PORT = '3019'
    $env:HOST = '127.0.0.1'
    $webArgs = if ($WebBuild) { @((Join-Path $WebBuild 'server/index.mjs')) } else { @('node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','3019') }
    $web = Start-Process -FilePath $nodePath -ArgumentList $webArgs -WorkingDirectory (Join-Path $integrationRepo 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimePath 'web.stdout.log') -RedirectStandardError (Join-Path $runtimePath 'web.stderr.log')
  }
  [pscustomobject]@{agentPid=$agent.Id; webPid=$web.Id; attachmentPid=$attachment.Id; runtime=$runtimePath}
}
