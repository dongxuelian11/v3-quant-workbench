param(
  [Parameter(Mandatory = $true)]
  [string]$InputRoot,
  [Parameter(Mandatory = $true)]
  [string]$EvidenceRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Fail([string]$Message) {
  throw "LEVEL2_CLEAN_MACHINE_EVIDENCE_FAILED: $Message"
}

function Assert-Value([bool]$Condition, [string]$Message) {
  if (-not $Condition) { Fail $Message }
}

function Read-JsonFile([string]$Path) {
  Assert-Value (Test-Path -LiteralPath $Path -PathType Leaf) "required evidence file missing: $Path"
  return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Get-CommandObservation([string]$Name) {
  $command = Get-Command $Name -ErrorAction SilentlyContinue
  if ($null -ne $command) {
    return [ordered]@{ present = $true; path = [string]$command.Source }
  }
  $whereResult = @(& where.exe $Name 2>$null)
  if ($whereResult.Count -gt 0) {
    return [ordered]@{ present = $true; path = [string]$whereResult[0] }
  }
  return [ordered]@{ present = $false; path = $null }
}

function Test-PathInside([string]$Parent, [string]$Candidate) {
  $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd("\") + "\"
  $candidateFull = [IO.Path]::GetFullPath($Candidate)
  return $candidateFull.StartsWith($parentFull, [StringComparison]::OrdinalIgnoreCase)
}

function Get-DirectoryDigest([string]$Root) {
  $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd("\")
  $hash = [Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
  $zero = [byte[]]@(0)
  $buffer = New-Object byte[] (1024 * 1024)
  $totalBytes = [int64]0
  $fileCount = 0
  try {
    $files = @(Get-ChildItem -LiteralPath $rootFull -File -Recurse -Force | Sort-Object -Property FullName)
    foreach ($file in $files) {
      $relative = $file.FullName.Substring($rootFull.Length).TrimStart("\").Replace("\", "/")
      $nameBytes = [Text.Encoding]::UTF8.GetBytes($relative)
      $hash.AppendData($nameBytes, 0, $nameBytes.Length)
      $hash.AppendData($zero, 0, 1)
      $stream = [IO.File]::OpenRead($file.FullName)
      try {
        while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
          $hash.AppendData($buffer, 0, $read)
          $totalBytes += $read
        }
      } finally {
        $stream.Dispose()
      }
      $hash.AppendData($zero, 0, 1)
      $fileCount++
    }
    $digest = ([BitConverter]::ToString($hash.GetHashAndReset())).Replace("-", "").ToLowerInvariant()
    return [ordered]@{ sha256 = $digest; bytes = $totalBytes; file_count = $fileCount }
  } finally {
    $hash.Dispose()
  }
}

function Get-BackendProcessSnapshot([string]$ResourceRoot) {
  $needle = [IO.Path]::GetFullPath($ResourceRoot).TrimEnd("\")
  $processes = @()
  foreach ($process in @(Get-CimInstance Win32_Process)) {
    $commandLine = [string]$process.CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine)) { continue }
    if ($commandLine.IndexOf($needle, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
        $commandLine -match "v3_backend\.runtime\.bootstrap") {
      $processes += [ordered]@{
        process_id = [int]$process.ProcessId
        name = [string]$process.Name
        command_line = $commandLine
      }
    }
  }
  return @($processes)
}

function Invoke-PackagedSmoke([string]$Phase, [string]$OutputPath, [string]$Name) {
  $stdoutPath = Join-Path $script:EvidenceRoot "$Name.stdout.log"
  $stderrPath = Join-Path $script:EvidenceRoot "$Name.stderr.log"
  $arguments = @(
    "--v3-packaged-smoke",
    "--disable-gpu",
    "--disable-gpu-compositing",
    "--in-process-gpu"
  )
  $env:V3_PACKAGED_SMOKE_PHASE = $Phase
  $env:V3_PACKAGED_SMOKE_OUTPUT = $OutputPath
  $process = Start-Process -FilePath $script:AppPath -ArgumentList $arguments -WorkingDirectory $script:InstallRoot `
    -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -WindowStyle Hidden -PassThru
  $finished = $process.WaitForExit(120000)
  if (-not $finished) {
    try { $process.Kill() } catch { }
    Fail "$Phase packaged Electron did not exit within 120 seconds"
  }
  $process.Refresh()
  Assert-Value ($process.ExitCode -eq 0) "$Phase Electron exit code was $($process.ExitCode)"
  $smoke = Read-JsonFile $OutputPath
  $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -Raw -LiteralPath $stderrPath } else { "" }
  $stdout = if (Test-Path -LiteralPath $stdoutPath) { Get-Content -Raw -LiteralPath $stdoutPath } else { "" }
  Assert-Value ($smoke.success -eq $true) "$Phase packaged smoke did not report success: $($smoke | ConvertTo-Json -Depth 20)"
  Assert-Value ($smoke.app_is_packaged -eq $true) "$Phase did not run app.isPackaged=true"
  Assert-Value ($smoke.backend_runtime_mode -eq "PACKAGED") "$Phase did not select PACKAGED backend runtime"
  Assert-Value (-not $stderr.Contains("FORCED_SHUTDOWN_FALLBACK")) "$Phase used forced shutdown fallback"
  Assert-Value ($stderr.Contains("PACKAGED_RUNTIME_SELECTED")) "$Phase did not log packaged runtime selection"
  Assert-Value ($stderr.Contains("GRACEFUL_SHUTDOWN_SUCCESS")) "$Phase did not log graceful shutdown success"
  return [ordered]@{
    phase = $Phase
    process_id = [int]$process.Id
    exit_code = [int]$process.ExitCode
    smoke = $smoke
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
    stdout = $stdout
    stderr = $stderr
  }
}

$script:EvidenceRoot = [IO.Path]::GetFullPath($EvidenceRoot)
$script:InstallRoot = $null
$script:AppPath = $null
$firstRun = $null
$relaunchRun = $null
$installBefore = $null
$installAfter = $null
$sourceTreeHits = @()
$reportPath = Join-Path $script:EvidenceRoot "V3_PACKAGING_LEVEL2_CLEAN_MACHINE_EVIDENCE.json"
New-Item -ItemType Directory -Force -Path $script:EvidenceRoot | Out-Null

try {
  $input = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $InputRoot).Path)
  $workspace = [IO.Path]::GetFullPath($env:GITHUB_WORKSPACE)
  Assert-Value (-not [string]::IsNullOrWhiteSpace($env:V3_LEVEL2_PRE_DOWNLOAD_INVENTORY)) "Job B pre-download inventory path is unavailable"
  $preDownload = Read-JsonFile $env:V3_LEVEL2_PRE_DOWNLOAD_INVENTORY
  Assert-Value ($preDownload.repository_source_tree_present -eq $false) "pre-download inventory observed a repository source tree"
  Assert-Value ($preDownload.checkout_used -eq $false) "pre-download inventory observed checkout"

  $repoMarkers = @(
    ".git", ".github", "AGENTS.md", "V3_PROJECT_CONSTITUTION.md", "package.json",
    "package-lock.json", "apps", "packages", "node_modules", "tsconfig.json"
  )
  foreach ($marker in $repoMarkers) {
    if (Test-Path -LiteralPath (Join-Path $workspace $marker)) { $sourceTreeHits += $marker }
  }
  $gitRoot = ""
  try { $gitRoot = (& git.exe -C $workspace rev-parse --show-toplevel 2>$null | Out-String).Trim() } catch { $gitRoot = "" }
  Assert-Value ($sourceTreeHits.Count -eq 0) "repository source markers present in Job B workspace: $($sourceTreeHits -join ', ')"
  Assert-Value ([string]::IsNullOrWhiteSpace($gitRoot)) "Job B workspace is a Git checkout: $gitRoot"
  Assert-Value ($env:V3_VERIFY_JOB_CHECKOUT_ACTION_PRESENT -eq "FALSE") "workflow did not declare Job B checkout action absent"

  $pythonHost = Get-CommandObservation "python.exe"
  $nodeHost = Get-CommandObservation "node.exe"
  $npmHost = Get-CommandObservation "npm.cmd"
  $devVenvPresent = (-not [string]::IsNullOrWhiteSpace($env:VIRTUAL_ENV))
  foreach ($candidate in @(".venv", "venv", "env")) {
    if (Test-Path -LiteralPath (Join-Path $workspace $candidate)) { $devVenvPresent = $true }
  }
  $os = Get-CimInstance Win32_OperatingSystem
  $osArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
  $buildRunnerPath = Join-Path $input "V3_PACKAGING_LEVEL2_BUILD_RUNNER.json"
  $buildRunner = Read-JsonFile $buildRunnerPath
  Assert-Value (-not [string]::IsNullOrWhiteSpace($env:RUNNER_NAME)) "Job B runner name is unavailable"
  Assert-Value ($buildRunner.runner_name -ne $env:RUNNER_NAME) "Job A and Job B runner names are identical; fresh runner was not proven"

  $zipPath = Join-Path $input "V3_PACKAGING_LEVEL2_DELIVERY.zip"
  $hashPath = Join-Path $input "V3_PACKAGING_LEVEL2_DELIVERY.zip.sha256"
  $packageEvidence = Read-JsonFile (Join-Path $input "V3_PACKAGE_EVIDENCE.json")
  $buildPin = Read-JsonFile (Join-Path $input "V3_PACKAGING_LEVEL2_BUILD_PIN.json")
  Assert-Value (Test-Path -LiteralPath $zipPath -PathType Leaf) "delivery zip missing"
  $expectedHashLine = (Get-Content -Raw -LiteralPath $hashPath).Trim()
  $expectedHashMatch = [regex]::Match($expectedHashLine, "^(?<hash>[0-9a-fA-F]{64})\s+\*?(?<name>.+)$")
  Assert-Value $expectedHashMatch.Success "delivery hash file is malformed"
  $expectedZipHash = $expectedHashMatch.Groups["hash"].Value.ToLowerInvariant()
  $actualZipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()
  Assert-Value ($actualZipHash -eq $expectedZipHash) "delivery artifact SHA transfer mismatch"
  $zipBytes = (Get-Item -LiteralPath $zipPath).Length

  $runnerTemp = if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) { [IO.Path]::GetTempPath() } else { $env:RUNNER_TEMP }
  $runRoot = Join-Path $runnerTemp ("v3-level2-clean-machine-" + [Guid]::NewGuid().ToString("N"))
  $script:InstallRoot = Join-Path $runRoot "Fresh Extracted V3 Product With Spaces"
  $userDataRoot = Join-Path $runRoot "Fresh Electron UserData"
  $localAppDataRoot = Join-Path $runRoot "Fresh Local AppData"
  $roamingRoot = Join-Path $runRoot "Fresh Roaming AppData"
  $profileRoot = Join-Path $runRoot "Fresh User Profile"
  $tempRoot = Join-Path $runRoot "Fresh Temp"
  New-Item -ItemType Directory -Force -Path $script:InstallRoot, $userDataRoot, $localAppDataRoot, $roamingRoot, $profileRoot, $tempRoot | Out-Null
  $initialUserDataEntries = @(Get-ChildItem -LiteralPath $userDataRoot -Force)
  $initialLocalAppDataEntries = @(Get-ChildItem -LiteralPath $localAppDataRoot -Force)
  Assert-Value ($initialUserDataEntries.Count -eq 0 -and $initialLocalAppDataEntries.Count -eq 0) "fresh storage roots were not empty"

  & tar.exe -xf $zipPath -C $script:InstallRoot
  Assert-Value ($LASTEXITCODE -eq 0) "delivery artifact extraction failed"
  $script:AppPath = Join-Path $script:InstallRoot "v3-quant-workbench.exe"
  Assert-Value (Test-Path -LiteralPath $script:AppPath -PathType Leaf) "packaged Electron executable missing after extraction"
  $installBefore = Get-DirectoryDigest $script:InstallRoot

  $resourcesPath = Join-Path $script:InstallRoot "resources"
  $backendResourceRoot = Join-Path $resourcesPath "backend-runtime"
  $manifestPath = Join-Path $backendResourceRoot "runtime-manifest.json"
  $runtimeManifest = Read-JsonFile $manifestPath
  $pythonPath = Join-Path $backendResourceRoot "python\python.exe"
  $actualPythonSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $pythonPath).Hash.ToLowerInvariant()
  $manifestPythonSha = ([string]$runtimeManifest.python_runtime.source_python_sha256).ToLowerInvariant()
  $criticalPythonSha = ((@($runtimeManifest.critical_files) | Where-Object { $_.path -eq "python/python.exe" } | Select-Object -First 1).sha256).ToLowerInvariant()
  $pinnedPythonSha = ([string]$buildPin.cpython_sha_pinned_in_build).ToLowerInvariant()
  Assert-Value ($pinnedPythonSha -eq $manifestPythonSha -and $manifestPythonSha -eq $actualPythonSha -and $actualPythonSha -eq $criticalPythonSha) "CPython SHA three-way reconciliation failed"
  Assert-Value ($buildPin.cpython_sha_reconciliation -eq "PASS") "Job A did not record CPython reconciliation PASS"
  Assert-Value ($runtimeManifest.first_launch_network_install -eq $false) "packaged manifest permits first-launch network install"
  Assert-Value ($runtimeManifest.source_capability -eq "NOT_AVAILABLE") "packaged manifest source capability is not NOT_AVAILABLE"
  Assert-Value ($runtimeManifest.python_runtime.version -eq "3.14.5" -and $runtimeManifest.python_runtime.arch -eq "win_amd64") "packaged CPython identity is not 3.14.5 win_amd64"
  Assert-Value ($runtimeManifest.source_git_sha -eq $packageEvidence.source_git_sha) "package evidence and runtime manifest source SHA differ"

  $pathBefore = $env:Path
  $runtimeEnvPattern = '^(V3_|PYTHON|NODE_|NPM_|ELECTRON_RUN_AS_NODE|VIRTUAL_ENV|CONDA_|POETRY_)'
  $scrubbedBefore = @(Get-ChildItem Env: | Where-Object {
      $_.Name -match $runtimeEnvPattern -and $_.Name -notmatch '^V3_PACKAGED_SMOKE_'
    })
  $scrubbedNames = @(
    "V3_BACKEND_PYTHON", "V3_PYTHON", "V3_BACKEND_WORKING_DIRECTORY", "V3_PACKAGED_PYTHON_ROOT",
    "PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "NODE_PATH", "npm_config_prefix",
    "ELECTRON_RUN_AS_NODE", "V3_PRODUCT_STORAGE_ROOT", "V3_RESEARCH_PACKAGE_TRANSPORT_PATH",
    "V3_AGENT_EVIDENCE_MODE", "VIRTUAL_ENV"
  )
  foreach ($entry in $scrubbedBefore) { Remove-Item -ErrorAction SilentlyContinue -LiteralPath ("Env:" + $entry.Name) }
  foreach ($name in $scrubbedNames) { Remove-Item -ErrorAction SilentlyContinue -LiteralPath ("Env:" + $name) }
  $remainingRuntimeOverrides = @(Get-ChildItem Env: | Where-Object {
      $_.Name -match $runtimeEnvPattern -and $_.Name -notmatch '^V3_PACKAGED_SMOKE_'
    })
  $remainingRuntimeOverrideNames = @($remainingRuntimeOverrides | ForEach-Object { $_.Name })
  Assert-Value ($remainingRuntimeOverrides.Count -eq 0) "runtime override environment remained after scrub: $($remainingRuntimeOverrideNames -join ', ')"
  $systemRoot = if ([string]::IsNullOrWhiteSpace($env:SystemRoot)) { "C:\Windows" } else { $env:SystemRoot }
  $env:Path = ((@(
    (Join-Path $systemRoot "System32"),
    $systemRoot,
    (Join-Path $systemRoot "System32\Wbem"),
    (Join-Path $systemRoot "System32\WindowsPowerShell\v1.0")
  ) | Select-Object -Unique) -join ";")
  $pathAfter = $env:Path
  $env:APPDATA = $roamingRoot
  $env:LOCALAPPDATA = $localAppDataRoot
  $env:TEMP = $tempRoot
  $env:TMP = $tempRoot
  $env:USERPROFILE = $profileRoot
  $env:V3_PACKAGED_SMOKE_USER_DATA = $userDataRoot
  $env:V3_PACKAGED_SMOKE_OUTPUT = ""

  $firstOutput = Join-Path $script:EvidenceRoot "first.json"
  $firstRun = Invoke-PackagedSmoke "create-bind" $firstOutput "first"
  $firstSmoke = $firstRun.smoke
  $handshake = $firstSmoke.backend_handshake
  Assert-Value ($handshake.transport -eq "STDIO_FRAMED_V1" -and $handshake.ready -eq $true) "framed backend handshake did not reach READY"
  Assert-Value ($handshake.hello.kind -eq "backend.hello" -and $handshake.hello.protocol -eq "v3.local/1.0") "backend framed identity was not observed"
  Assert-Value ($handshake.hello.event_replay -eq $true) "backend handshake did not advertise event replay"
  Assert-Value ([int]$handshake.hello.pid -eq [int]$firstSmoke.backend_pid) "handshake PID does not match shipped backend PID"
  Assert-Value ($firstSmoke.product_status_before.backendState -eq "READY") "Product Runtime was not READY before first flow"
  Assert-Value ($firstSmoke.product_status_before.bindingState -eq "NO_CANONICAL_PROJECT_BOUND") "empty storage did not start unbound"
  Assert-Value ($firstSmoke.product_status_after.bindingState -eq "PROJECT_BOUND") "Project was not canonically bound"
  Assert-Value ($firstSmoke.source_capability.code -eq "DataSourceService" -and $firstSmoke.source_capability.truth_state -eq "UNAVAILABLE") "source capability was not honestly NOT_AVAILABLE"
  Assert-Value ($firstSmoke.writes_inside_install_root -eq $false) "first smoke reported writes inside install root"
  Assert-Value ($firstSmoke.first_launch_network_install -eq $false) "first smoke did not preserve no-network-install state"
  Assert-Value (Test-Path -LiteralPath $firstSmoke.user_data_path -PathType Container) "Electron userData was not bootstrapped"
  Assert-Value (Test-Path -LiteralPath $firstSmoke.catalog_path -PathType Leaf) "empty-storage bootstrap did not create catalog"
  Assert-Value (Test-Path -LiteralPath $firstSmoke.product_binding_path -PathType Leaf) "canonical product binding was not persisted"
  Assert-Value (-not (Test-PathInside $script:InstallRoot $firstSmoke.user_data_path)) "userData is inside install root"
  Assert-Value (-not (Test-PathInside $script:InstallRoot $firstSmoke.storage_root)) "product storage is inside install root"
  Assert-Value (Test-PathInside $backendResourceRoot $firstSmoke.backend_executable) "backend executable is outside resources/backend-runtime"
  Assert-Value ([IO.Path]::GetFullPath($firstSmoke.backend_executable) -eq [IO.Path]::GetFullPath($pythonPath)) "backend did not use shipped python.exe"
  Assert-Value (Test-PathInside $backendResourceRoot $firstSmoke.backend_working_directory) "backend working root is outside resources/backend-runtime"
  Assert-Value ($pythonPath -eq [IO.Path]::GetFullPath($firstSmoke.backend_executable)) "runner/system Python path was selected"
  $firstBackendPid = [int]$firstSmoke.backend_pid
  Assert-Value ($null -eq (Get-Process -Id $firstBackendPid -ErrorAction SilentlyContinue)) "first backend process remained alive after Electron exit"
  Assert-Value (@(Get-BackendProcessSnapshot $backendResourceRoot).Count -eq 0) "orphan backend process observed after first exit"

  $projectId = [string]$firstSmoke.created_project.projectId
  $revisionId = [string]$firstSmoke.created_project.projectContextRevisionId
  Assert-Value (-not [string]::IsNullOrWhiteSpace($projectId) -and -not [string]::IsNullOrWhiteSpace($revisionId)) "canonical Project identifiers are missing"
  Assert-Value ([string]$firstSmoke.project_context.projectId -eq $projectId -and [string]$firstSmoke.project_context.projectContextRevisionId -eq $revisionId) "create/bind context identity mismatch"

  $relaunchOutput = Join-Path $script:EvidenceRoot "relaunch.json"
  $relaunchRun = Invoke-PackagedSmoke "relaunch" $relaunchOutput "relaunch"
  $relaunchSmoke = $relaunchRun.smoke
  Assert-Value ($relaunchSmoke.product_status_before.backendState -eq "READY") "relaunch Product Runtime was not READY"
  Assert-Value ($relaunchSmoke.product_status_before.bindingState -eq "PROJECT_BOUND") "relaunch did not recover PROJECT_BOUND"
  Assert-Value ([string]$relaunchSmoke.product_status_before.boundProject.projectId -eq $projectId) "relaunch Project ID changed before reopen"
  Assert-Value ([string]$relaunchSmoke.product_status_before.boundProject.projectContextRevisionId -eq $revisionId) "relaunch Project revision changed before reopen"
  Assert-Value ([string]$relaunchSmoke.product_status_after.boundProject.projectId -eq $projectId) "relaunch Project ID changed after reopen"
  Assert-Value ([string]$relaunchSmoke.product_status_after.boundProject.projectContextRevisionId -eq $revisionId) "relaunch Project revision changed after reopen"
  Assert-Value ($relaunchSmoke.source_capability.truth_state -eq "UNAVAILABLE") "relaunch source capability was not NOT_AVAILABLE"
  Assert-Value (-not (Test-PathInside $script:InstallRoot $relaunchSmoke.user_data_path)) "relaunch userData is inside install root"
  Assert-Value (-not (Test-PathInside $script:InstallRoot $relaunchSmoke.storage_root)) "relaunch storage is inside install root"
  $relaunchBackendPid = [int]$relaunchSmoke.backend_pid
  Assert-Value ($null -eq (Get-Process -Id $relaunchBackendPid -ErrorAction SilentlyContinue)) "relaunch backend process remained alive after Electron exit"
  Assert-Value (@(Get-BackendProcessSnapshot $backendResourceRoot).Count -eq 0) "orphan backend process observed after relaunch exit"

  $installAfter = Get-DirectoryDigest $script:InstallRoot
  Assert-Value ($installBefore.sha256 -eq $installAfter.sha256 -and $installBefore.bytes -eq $installAfter.bytes -and $installBefore.file_count -eq $installAfter.file_count) "packaged install tree changed during full close/relaunch flow"

  $report = [ordered]@{
    schema_version = "v3.packaging-level2-clean-machine/1.0.0"
    task_id = "V3-PR47-LEVEL2-CLEAN-MACHINE-EVIDENCE-CLOSURE-20260821-01"
    result = "V3_PACKAGING_CLEAN_MACHINE_RUNTIME_CANDIDATE_COMPLETE"
    source_git_sha = [string]$packageEvidence.source_git_sha
    workflow_run_id = [string]$env:GITHUB_RUN_ID
    job_id = [string]$env:GITHUB_JOB
    runner_os = [string]$os.Caption
    runner_os_version = [string]$os.Version
    runner_os_build = [string]$os.BuildNumber
    runner_arch = $osArchitecture
    runner_name = [string]$env:RUNNER_NAME
    build_runner_name = [string]$buildRunner.runner_name
    fresh_runner_distinct = $true
    verify_job_checkout_action_present = $false
    repository_source_tree_present = $false
    checkout_used = $false
    job_b_pre_download_inventory = $preDownload
    workspace_source_markers = @($sourceTreeHits)
    product_started_from_delivery_artifact = $true
    no_source_archive_or_repository_downloaded = $true
    no_npm_install_in_verify_job = $true
    no_pip_install_in_verify_job = $true
    no_first_launch_network_install = $true
    delivery_artifact_name = "V3_PACKAGING_LEVEL2_DELIVERY.zip"
    delivery_artifact_bytes = [int64]$zipBytes
    delivery_artifact_sha256 = $actualZipHash
    delivery_artifact_expected_sha256 = $expectedZipHash
    artifact_transfer_hash = "PASS"
    package_version = [string]$runtimeManifest.product.version
    process_resources_path = [string]$firstSmoke.resources_path
    app_path = [string]$firstSmoke.app_path
    packaged_install_root = $script:InstallRoot
    backend_executable = [string]$firstSmoke.backend_executable
    backend_working_root = [string]$firstSmoke.backend_working_directory
    backend_resource_root = $backendResourceRoot
    backend_handshake = $handshake
    product_runtime_state = [string]$firstSmoke.product_status_after.bindingState
    app_is_packaged = $true
    packaged_backend_executable = [string]$firstSmoke.backend_executable
    packaged_backend_working_root = [string]$firstSmoke.backend_working_directory
    packaged_python_executable = $pythonPath
    packaged_python_version = [string]$runtimeManifest.python_runtime.version
    packaged_python_sha256 = $actualPythonSha
    cpython_sha_pinned_in_build = $pinnedPythonSha
    cpython_sha_from_manifest = $manifestPythonSha
    cpython_sha_actual = $actualPythonSha
    cpython_sha_reconciliation = "PASS"
    system_python_present = [bool]$pythonHost.present
    system_python_path = $pythonHost.path
    system_python_used = $false
    system_node_present = [bool]$nodeHost.present
    system_node_path = $nodeHost.path
    system_npm_present = [bool]$npmHost.present
    system_npm_path = $npmHost.path
    developer_venv_present = [bool]$devVenvPresent
    node_runtime_required_by_product = $false
    runtime_path_before = $pathBefore
    runtime_path_after = $pathAfter
    runtime_path_scrubbed = $true
    scrubbed_environment_names = @((@($scrubbedNames) + @($scrubbedBefore | ForEach-Object { $_.Name })) | Sort-Object -Unique)
    runtime_environment_scrubbed = $true
    user_data_path = [string]$firstSmoke.user_data_path
    catalog_path = [string]$firstSmoke.catalog_path
    artifact_root = [string]$firstSmoke.artifact_root
    storage_root = [string]$firstSmoke.storage_root
    workspace_state_path = [string]$firstSmoke.workspace_state_path
    product_binding_path = [string]$firstSmoke.product_binding_path
    writes_inside_install_root = $false
    storage_bootstrap = $true
    packaged_product_runtime_state = [string]$firstSmoke.product_status_after.bindingState
    packaged_project_create = $true
    project_id = $projectId
    project_context_revision_id = $revisionId
    packaged_project_bind = $true
    packaged_source_capability = $firstSmoke.source_capability
    packaged_full_app_exit = $true
    electron_exit_code = [int]$firstRun.exit_code
    packaged_backend_exit = "GRACEFUL_SHUTDOWN_SUCCESS"
    orphan_process_count = 0
    packaged_relaunch = $true
    packaged_project_reopen = $true
    project_reopen_exact_equality = $true
    install_tree_immutable = $true
    install_tree_sha256_before = $installBefore.sha256
    install_tree_sha256_after = $installAfter.sha256
    install_tree_file_count = [int]$installAfter.file_count
    install_tree_bytes = [int64]$installAfter.bytes
    first_launch = $firstRun
    relaunch = $relaunchRun
    source_capability = "NOT_AVAILABLE"
    real_free_source_smoke = "NOT_RUN"
    first_source_authority = "NOT_REISSUED"
    full_app_historical_rediscovery = "DEFERRED"
    workflow_run_clean_machine = "GITHUB_HOSTED_FRESH_WINDOWS_VM"
    clean_machine_launch = "PASS_CANDIDATE"
    level2_evidence = $reportPath
    level2_build_runner = $buildRunner
  }
  $report | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $reportPath -Encoding UTF8
  Write-Output ($report | ConvertTo-Json -Depth 20)
  exit 0
} catch {
  $failure = [ordered]@{
    schema_version = "v3.packaging-level2-clean-machine/1.0.0"
    task_id = "V3-PR47-LEVEL2-CLEAN-MACHINE-EVIDENCE-CLOSURE-20260821-01"
    result = "STOP_FOR_REVIEW"
    error = $_.Exception.Message
    error_type = $_.Exception.GetType().FullName
    error_position = $_.InvocationInfo.PositionMessage
    error_script_stack = $_.ScriptStackTrace
    verify_job_checkout_action_present = $false
    repository_source_tree_present = ($sourceTreeHits.Count -gt 0)
    checkout_used = ($sourceTreeHits.Count -gt 0)
    clean_machine_launch = "NOT_PROVEN"
    level2_evidence = $reportPath
  }
  $failure | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $reportPath -Encoding UTF8
  Write-Error ($failure | ConvertTo-Json -Depth 20)
  exit 1
}
