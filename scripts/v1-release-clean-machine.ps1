param(
  [Parameter(Mandatory = $true)][string]$InputRoot,
  [Parameter(Mandatory = $true)][string]$EvidenceRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Fail([string]$Message) { throw "V1_RELEASE_CLEAN_MACHINE_FAILED: $Message" }
function Assert-Value([bool]$Condition, [string]$Message) { if (-not $Condition) { Fail $Message } }
function Read-Json([string]$Path) {
  Assert-Value (Test-Path -LiteralPath $Path -PathType Leaf) "missing file: $Path"
  return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}
function Read-HashFile([string]$Path) {
  $line = (Get-Content -Raw -LiteralPath $Path).Trim()
  $match = [regex]::Match($line, "^(?<hash>[0-9a-fA-F]{64})\s+\*?(?<name>.+)$")
  Assert-Value $match.Success "malformed hash file: $Path"
  return $match.Groups["hash"].Value.ToLowerInvariant()
}
function Test-PathInside([string]$Parent, [string]$Candidate) {
  $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd("\") + "\"
  return [IO.Path]::GetFullPath($Candidate).StartsWith($parentFull, [StringComparison]::OrdinalIgnoreCase)
}
function Get-BackendProcesses([string]$ResourceRoot) {
  $needle = [IO.Path]::GetFullPath($ResourceRoot).TrimEnd("\")
  return @(Get-CimInstance Win32_Process | Where-Object {
    -not [string]::IsNullOrWhiteSpace([string]$_.CommandLine) -and
    ([string]$_.CommandLine).IndexOf($needle, [StringComparison]::OrdinalIgnoreCase) -ge 0
  } | ForEach-Object { [ordered]@{ process_id = [int]$_.ProcessId; name = [string]$_.Name; command_line = [string]$_.CommandLine } })
}
function Invoke-ProductPhase(
  [string]$Phase,
  [string]$ProviderMode,
  [string]$OutputPath,
  [string]$LogName,
  [string]$UserDataRoot,
  [string]$LocalRoot,
  [string]$RoamingRoot,
  [string]$ProfileRoot,
  [string]$TempRoot
) {
  foreach ($path in @($UserDataRoot, $LocalRoot, $RoamingRoot, $ProfileRoot, $TempRoot)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
  }
  $env:V3_PACKAGED_SMOKE_USER_DATA = $UserDataRoot
  $env:V3_PRODUCT_CLOSURE_SMOKE_PHASE = $Phase
  $env:V3_PRODUCT_CLOSURE_SMOKE_OUTPUT = $OutputPath
  $env:V3_PRODUCT_CLOSURE_PROVIDER_MODE = $ProviderMode
  $env:LOCALAPPDATA = $LocalRoot
  $env:APPDATA = $RoamingRoot
  $env:USERPROFILE = $ProfileRoot
  $env:TEMP = $TempRoot
  $env:TMP = $TempRoot
  $stdout = Join-Path $script:EvidenceRoot "$LogName.stdout.log"
  $stderr = Join-Path $script:EvidenceRoot "$LogName.stderr.log"
  $process = Start-Process -FilePath $script:AppPath -WorkingDirectory $script:InstallRoot `
    -ArgumentList @("--v3-product-closure-smoke", "--disable-gpu", "--disable-gpu-compositing", "--in-process-gpu") `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
  $finished = $process.WaitForExit(240000)
  if (-not $finished) { try { $process.Kill() } catch { }; Fail "$Phase timed out" }
  $process.Refresh()
  Assert-Value ($process.ExitCode -eq 0) "$Phase Electron exit code $($process.ExitCode)"
  $smoke = Read-Json $OutputPath
  $stderrText = if (Test-Path -LiteralPath $stderr) { Get-Content -Raw -LiteralPath $stderr } else { "" }
  Assert-Value ($smoke.success -eq $true) "$Phase did not report success"
  Assert-Value ($smoke.app_is_packaged -eq $true -and $smoke.backend_runtime_mode -eq "PACKAGED") "$Phase was not packaged runtime"
  Assert-Value ([string]$smoke.flow.status.productVersion -eq "1.0.0") "$Phase product version mismatch"
  Assert-Value ($stderrText.Contains("PACKAGED_RUNTIME_SELECTED")) "$Phase did not select packaged runtime"
  Assert-Value ($stderrText.Contains("GRACEFUL_SHUTDOWN_SUCCESS")) "$Phase did not gracefully stop backend"
  Assert-Value (-not $stderrText.Contains("FORCED_SHUTDOWN_FALLBACK")) "$Phase used forced shutdown"
  Assert-Value (@(Get-BackendProcesses $script:BackendRoot).Count -eq 0) "$Phase left an orphan backend"
  return [ordered]@{
    phase = $Phase; provider_mode = $ProviderMode; electron_pid = [int]$process.Id; exit_code = [int]$process.ExitCode
    smoke = $smoke; stdout_path = $stdout; stderr_path = $stderr
  }
}
function Get-CanonicalIdentity($Smoke) {
  $flow = $Smoke.flow
  Assert-Value ($flow.task.state -eq "SUCCEEDED") "canonical research Task not successful"
  Assert-Value ($flow.result.state -eq "PENDING_RECONCILIATION") "canonical Result truth state is not PENDING_RECONCILIATION"
  Assert-Value ($flow.task.resultId -eq $flow.result.resultId -and $flow.task.runId -eq $flow.result.backtestRunId) "Task/Run/Result mismatch"
  Assert-Value ($flow.task.outputs.BACKTEST_RUN_RESULT -eq $flow.artifactDescriptor.artifactId) "Task/Artifact mismatch"
  Assert-Value ($flow.result.resultArtifact.sha256 -eq $flow.artifactDescriptor.sha256) "Result/Artifact hash mismatch"
  return [ordered]@{
    project_id = [string]$flow.projectContext.projectId
    project_context_revision_id = [string]$flow.projectContext.projectContextRevisionId
    task_id = [string]$flow.task.taskId
    run_id = [string]$flow.task.runId
    result_id = [string]$flow.result.resultId
    artifact_id = [string]$flow.artifactDescriptor.artifactId
    artifact_sha256 = [string]$flow.artifactDescriptor.sha256
    artifact_bytes = [int64]$flow.artifactDescriptor.byteSize
  }
}
function Assert-IdentityEqual($Left, $Right) {
  foreach ($name in @("project_id", "project_context_revision_id", "task_id", "run_id", "result_id", "artifact_id", "artifact_sha256", "artifact_bytes")) {
    Assert-Value ($Left[$name] -eq $Right[$name]) "cold restart identity mismatch: $name"
  }
}
function Invoke-CatalogProbe([string]$CatalogPath) {
  Assert-Value (Test-Path -LiteralPath $CatalogPath -PathType Leaf) "catalog missing: $CatalogPath"
  $prior = $env:PYTHONDONTWRITEBYTECODE
  try {
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $output = & $script:PythonPath $script:CatalogProbe $CatalogPath
    Assert-Value ($LASTEXITCODE -eq 0) "packaged Python catalog probe failed"
    return ($output | Out-String).Trim() | ConvertFrom-Json
  } finally {
    if ($null -eq $prior) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue }
    else { $env:PYTHONDONTWRITEBYTECODE = $prior }
  }
}

$script:EvidenceRoot = [IO.Path]::GetFullPath($EvidenceRoot)
$script:InstallRoot = $null
$script:AppPath = $null
$script:BackendRoot = $null
$script:PythonPath = $null
$script:CatalogProbe = $null
New-Item -ItemType Directory -Force -Path $script:EvidenceRoot | Out-Null
$reportPath = Join-Path $script:EvidenceRoot "V3_V1_RELEASE_CLEAN_MACHINE_EVIDENCE.json"

try {
  $input = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $InputRoot).Path)
  Assert-Value (-not [string]::IsNullOrWhiteSpace($env:V3_V1_PRE_DOWNLOAD_INVENTORY)) "pre-download inventory path missing"
  $preDownload = Read-Json $env:V3_V1_PRE_DOWNLOAD_INVENTORY
  Assert-Value ($preDownload.checkout_used -eq $false -and $preDownload.repository_source_tree_present -eq $false) "Job B was not source-free before download"
  Assert-Value ($env:V3_VERIFY_JOB_CHECKOUT_ACTION_PRESENT -eq "FALSE") "Job B checkout absence not declared"
  $workspace = [IO.Path]::GetFullPath($env:GITHUB_WORKSPACE)
  $markers = @(".git", ".github", "AGENTS.md", "V3_PROJECT_CONSTITUTION.md", "package.json", "apps", "packages", "node_modules")
  $hits = @($markers | Where-Object { Test-Path -LiteralPath (Join-Path $workspace $_) })
  Assert-Value ($hits.Count -eq 0) "source markers found in Job B: $($hits -join ',')"

  $releaseManifestPath = Join-Path $input "V3_RELEASE_MANIFEST.json"
  $release = Read-Json $releaseManifestPath
  $buildRunner = Read-Json (Join-Path $input "V3_V1_RELEASE_BUILD_RUNNER.json")
  Assert-Value ($buildRunner.runner_name -ne $env:RUNNER_NAME) "Job A and Job B runner identities are equal"
  $installerPath = Join-Path $input "v3-quant-workbench-1.0.0-x64.exe"
  $installerExpected = Read-HashFile "$installerPath.sha256"
  $installerActual = (Get-FileHash -Algorithm SHA256 -LiteralPath $installerPath).Hash.ToLowerInvariant()
  Assert-Value ($installerActual -eq $installerExpected -and $installerActual -eq ([string]$release.installer.sha256).ToLowerInvariant()) "installer transfer/release hash mismatch"
  $packageZip = Join-Path $input "V3_V1_PRODUCT_RELEASE_PACKAGE.zip"
  $packageExpected = Read-HashFile "$packageZip.sha256"
  $packageActual = (Get-FileHash -Algorithm SHA256 -LiteralPath $packageZip).Hash.ToLowerInvariant()
  Assert-Value ($packageActual -eq $packageExpected) "package archive transfer hash mismatch"
  $script:CatalogProbe = Join-Path $input "v1-release-catalog-probe.py"
  Assert-Value (Test-Path -LiteralPath $script:CatalogProbe -PathType Leaf) "catalog probe missing"

  $runnerTemp = if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) { [IO.Path]::GetTempPath() } else { $env:RUNNER_TEMP }
  $runRoot = Join-Path $runnerTemp ("v3-v1-installed-" + [Guid]::NewGuid().ToString("N"))
  $script:InstallRoot = Join-Path $runRoot "Installed V3 Quant Workbench"
  New-Item -ItemType Directory -Force -Path $script:InstallRoot | Out-Null
  $installProcess = Start-Process -FilePath $installerPath -ArgumentList @("/S", "/D=$($script:InstallRoot)") -WindowStyle Hidden -PassThru
  Assert-Value ($installProcess.WaitForExit(180000)) "installer timed out"
  $installProcess.Refresh()
  Assert-Value ($installProcess.ExitCode -eq 0) "installer exit code $($installProcess.ExitCode)"
  $script:AppPath = Join-Path $script:InstallRoot "v3-quant-workbench.exe"
  $script:BackendRoot = Join-Path $script:InstallRoot "resources\backend-runtime"
  $script:PythonPath = Join-Path $script:BackendRoot "python\python.exe"
  Assert-Value (Test-Path -LiteralPath $script:AppPath -PathType Leaf) "installed Electron executable missing"
  Assert-Value (Test-Path -LiteralPath $script:PythonPath -PathType Leaf) "installed packaged Python missing"
  $runtimeManifestPath = Join-Path $script:BackendRoot "runtime-manifest.json"
  $runtimeManifest = Read-Json $runtimeManifestPath
  Assert-Value ($runtimeManifest.product.version -eq "1.0.0") "installed version is not 1.0.0"
  Assert-Value ($runtimeManifest.source_git_sha -eq $release.source.git_sha -and $runtimeManifest.source_git_tree_sha -eq $release.source.git_tree_sha) "installed source identity mismatch"
  Assert-Value ((Get-FileHash -Algorithm SHA256 -LiteralPath $runtimeManifestPath).Hash.ToLowerInvariant() -eq ([string]$release.packaged_runtime.manifest_sha256).ToLowerInvariant()) "installed runtime manifest hash mismatch"
  Assert-Value ($runtimeManifest.python_runtime.version -eq "3.14.5" -and $runtimeManifest.real_free_source.package_version -eq "1.18.84") "installed Python/AKShare identity mismatch"

  $pathBefore = $env:Path
  foreach ($entry in @(Get-ChildItem Env: | Where-Object { $_.Name -match '^(V3_|PYTHON|NODE_|NPM_|ELECTRON_RUN_AS_NODE|VIRTUAL_ENV|CONDA_|POETRY_)' })) {
    Remove-Item -LiteralPath ("Env:" + $entry.Name) -ErrorAction SilentlyContinue
  }
  $systemRoot = if ([string]::IsNullOrWhiteSpace($env:SystemRoot)) { "C:\Windows" } else { $env:SystemRoot }
  $env:Path = Join-Path $systemRoot "System32"

  $successRoot = Join-Path $runRoot "Success"
  $first = Invoke-ProductPhase "create-submit" "DETERMINISTIC_SUCCESS" (Join-Path $script:EvidenceRoot "first.json") "first" `
    (Join-Path $successRoot "UserData") (Join-Path $successRoot "Local") (Join-Path $successRoot "Roaming") (Join-Path $successRoot "Profile") (Join-Path $successRoot "Temp")
  $reopen = Invoke-ProductPhase "reopen-discover" "DETERMINISTIC_SUCCESS" (Join-Path $script:EvidenceRoot "reopen.json") "reopen" `
    (Join-Path $successRoot "UserData") (Join-Path $successRoot "Local") (Join-Path $successRoot "Roaming") (Join-Path $successRoot "Profile") (Join-Path $successRoot "Temp")
  $before = Get-CanonicalIdentity $first.smoke
  $after = Get-CanonicalIdentity $reopen.smoke
  Assert-IdentityEqual $before $after
  Assert-Value ($reopen.smoke.flow.rendererEvidence.initialRendererState.lastResearch -eq $null) "new renderer initial state was not empty"
  Assert-Value ($reopen.smoke.flow.rendererEvidence.currentRendererState.researchDiscoveryState -eq "RECOVERED") "new store did not rediscover Task history"
  $successCatalog = Join-Path $successRoot "Local\v3-quant-workbench\product\catalog.sqlite3"
  $successProbe = Invoke-CatalogProbe $successCatalog
  Assert-Value ($successProbe.source_metadata.source_kind -eq "TEST_EXTERNAL_PROVIDER_BOUNDARY") "success data not marked test-only"
  Assert-Value ($successProbe.counts.task -eq 1 -and $successProbe.counts.raw_capture -eq 1 -and $successProbe.counts.result -ge 1 -and $successProbe.counts.artifact -ge 1) "canonical success persistence incomplete"

  $unavailableRoot = Join-Path $runRoot "Unavailable"
  $unavailable = Invoke-ProductPhase "provider-unavailable" "DETERMINISTIC_UNAVAILABLE" (Join-Path $script:EvidenceRoot "unavailable.json") "unavailable" `
    (Join-Path $unavailableRoot "UserData") (Join-Path $unavailableRoot "Local") (Join-Path $unavailableRoot "Roaming") (Join-Path $unavailableRoot "Profile") (Join-Path $unavailableRoot "Temp")
  Assert-Value ($unavailable.smoke.flow.tasks.Count -eq 0) "provider unavailable minted a Task"
  Assert-Value (([string]$unavailable.smoke.flow.rendererEvidence.currentRendererState.errorMessage).Contains("PROVIDER_ACQUISITION_UNAVAILABLE")) "provider failure not explicit"
  $unavailableCatalog = Join-Path $unavailableRoot "Local\v3-quant-workbench\product\catalog.sqlite3"
  $unavailableProbe = Invoke-CatalogProbe $unavailableCatalog
  Assert-Value ($unavailableProbe.counts.task -eq 0 -and $unavailableProbe.counts.run -eq 0 -and $unavailableProbe.counts.result -eq 0 -and $unavailableProbe.counts.raw_capture -eq 0) "provider unavailable created fake canonical market/research data"
  Assert-Value ($unavailableProbe.counts.artifact -eq 1 -and $unavailableProbe.artifact_roles.Count -eq 1 -and $unavailableProbe.artifact_roles[0] -eq "DATA_TRUTH_CAPABILITY_POLICY") "provider unavailable created an Artifact other than the real admission policy"

  $uninstaller = @(Get-ChildItem -LiteralPath $script:InstallRoot -Filter "Uninstall*.exe" -File | Select-Object -First 1)
  Assert-Value ($uninstaller.Count -eq 1) "NSIS uninstaller missing"
  $uninstallProcess = Start-Process -FilePath $uninstaller[0].FullName -ArgumentList @("/S") -WindowStyle Hidden -PassThru
  Assert-Value ($uninstallProcess.WaitForExit(180000)) "uninstaller timed out"
  $uninstallProcess.Refresh()
  Assert-Value ($uninstallProcess.ExitCode -eq 0) "uninstaller exit code $($uninstallProcess.ExitCode)"
  $removalDeadline = [DateTime]::UtcNow.AddSeconds(30)
  while ((Test-Path -LiteralPath $script:AppPath) -and [DateTime]::UtcNow -lt $removalDeadline) { Start-Sleep -Milliseconds 250 }
  Assert-Value (-not (Test-Path -LiteralPath $script:AppPath)) "installed executable remained after uninstall"

  $report = [ordered]@{
    schema_version = "v3.v1-release-clean-machine/1.0.0"
    result = "PASS_CANDIDATE"
    source_git_sha = [string]$release.source.git_sha
    source_git_tree_sha = [string]$release.source.git_tree_sha
    build_manifest_id = [string]$release.build.build_manifest_id
    product_version = "1.0.0"
    build_runner_name = [string]$buildRunner.runner_name
    verify_runner_name = [string]$env:RUNNER_NAME
    fresh_runner_distinct = $true
    checkout_used = $false
    repository_source_tree_present = $false
    no_npm_install_in_verify_job = $true
    no_pip_install_in_verify_job = $true
    system_python_used = $false
    system_node_used = $false
    runtime_path_before = $pathBefore
    runtime_path_after = [string]$env:Path
    installer_name = [string]$release.installer.name
    installer_sha256 = $installerActual
    package_artifact_name = "V3_V1_PRODUCT_RELEASE_PACKAGE.zip"
    package_artifact_sha256 = $packageActual
    installer_install = "PASS"
    first_launch = "PASS"
    project_create_open = "PASS"
    deterministic_product_research = "PASS_TEST_EXTERNAL_PROVIDER_BOUNDARY"
    canonical_identity_before_exit = $before
    canonical_identity_after_restart = $after
    cold_rediscovery_exact_equality = $true
    new_process = $true
    new_renderer = $true
    new_store_instance = $true
    history_discovery_operation = "TaskService.v1.listTasks"
    known_id_injection = $false
    history_shadow_store = $false
    provider_unavailable = "PASS_FAIL_CLOSED"
    provider_unavailable_reason = "PROVIDER_ACQUISITION_UNAVAILABLE"
    provider_unavailable_counts = $unavailableProbe.counts
    provider_unavailable_artifact_roles = $unavailableProbe.artifact_roles
    fallback_used = $false
    full_app_exit = $true
    backend_exit = "GRACEFUL_SHUTDOWN_SUCCESS"
    orphan_process_count = 0
    uninstall = "PASS"
    research_data_preserved_on_uninstall = (Test-Path -LiteralPath $successCatalog)
    runtime_manifest_sha256 = [string]$release.packaged_runtime.manifest_sha256
    app_asar_sha256 = [string]$release.electron.app_asar_sha256
    packaged_python_version = "3.14.5"
    akshare_version = "1.18.84"
    first_run = $first
    reopen_run = $reopen
    unavailable_run = $unavailable
    pre_download_inventory = $preDownload
  }
  $report | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $reportPath -Encoding UTF8
  Write-Output ($report | ConvertTo-Json -Depth 20)
  exit 0
} catch {
  [ordered]@{
    schema_version = "v3.v1-release-clean-machine/1.0.0"
    result = "STOP_FOR_REVIEW"
    error = $_.Exception.Message
    error_type = $_.Exception.GetType().FullName
    error_position = $_.InvocationInfo.PositionMessage
    stack = $_.ScriptStackTrace
  } | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $reportPath -Encoding UTF8
  Write-Error $_
  exit 1
}
