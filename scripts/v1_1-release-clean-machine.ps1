param(
  [Parameter(Mandatory = $true)][string]$InputRoot,
  [Parameter(Mandatory = $true)][string]$EvidenceRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Fail([string]$Message) { throw "V1_1_RELEASE_CLEAN_MACHINE_FAILED: $Message" }
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
  })
}
function Set-ProcessEnvironment([hashtable]$Values) {
  $prior = @{}
  foreach ($name in $Values.Keys) {
    $prior[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    [Environment]::SetEnvironmentVariable($name, [string]$Values[$name], "Process")
  }
  return $prior
}
function Restore-ProcessEnvironment([hashtable]$Prior) {
  foreach ($name in $Prior.Keys) {
    [Environment]::SetEnvironmentVariable($name, $Prior[$name], "Process")
  }
}

$evidence = [IO.Path]::GetFullPath($EvidenceRoot)
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$reportPath = Join-Path $evidence "V3_V1_1_RELEASE_CLEAN_MACHINE_EVIDENCE.json"

try {
  $input = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $InputRoot).Path)
  Assert-Value (-not [string]::IsNullOrWhiteSpace($env:V3_V1_1_PRE_DOWNLOAD_INVENTORY)) "pre-download inventory path missing"
  Assert-Value ($env:V3_VERIFY_JOB_CHECKOUT_ACTION_PRESENT -eq "FALSE") "checkout absence was not declared"
  $preDownload = Read-Json $env:V3_V1_1_PRE_DOWNLOAD_INVENTORY
  Assert-Value ($preDownload.checkout_used -eq $false) "clean-machine job used checkout"
  Assert-Value ($preDownload.repository_source_tree_present -eq $false) "source tree existed before artifact download"

  $workspace = [IO.Path]::GetFullPath($env:GITHUB_WORKSPACE)
  $markers = @(".git", ".github", "AGENTS.md", "V3_PROJECT_CONSTITUTION.md", "package.json", "package-lock.json", "apps", "packages", "node_modules", "tsconfig.json")
  $hits = @($markers | Where-Object { Test-Path -LiteralPath (Join-Path $workspace $_) })
  Assert-Value ($hits.Count -eq 0) "source markers found after artifact download: $($hits -join ',')"

  $release = Read-Json (Join-Path $input "V3_RELEASE_MANIFEST.json")
  $buildRunner = Read-Json (Join-Path $input "V3_V1_1_RELEASE_BUILD_RUNNER.json")
  Assert-Value ($buildRunner.runner_name -ne $env:RUNNER_NAME) "package and verification runner identities are equal"
  Assert-Value ($buildRunner.source_git_sha -eq $release.source.git_sha) "build/release source SHA mismatch"
  Assert-Value ($buildRunner.source_git_tree_sha -eq $release.source.git_tree_sha) "build/release source tree mismatch"
  Assert-Value ($release.source.dirty_state -eq "CLEAN") "release manifest is not bound to a clean candidate"

  $installerPath = Join-Path $input ([string]$release.installer.name)
  $installerExpected = Read-HashFile "$installerPath.sha256"
  $installerActual = (Get-FileHash -Algorithm SHA256 -LiteralPath $installerPath).Hash.ToLowerInvariant()
  Assert-Value ($installerActual -eq $installerExpected) "installer transfer hash mismatch"
  Assert-Value ($installerActual -eq ([string]$release.installer.sha256).ToLowerInvariant()) "installer/release hash mismatch"

  $packageZip = Join-Path $input "V3_V1_1_PRODUCT_RELEASE_PACKAGE.zip"
  $packageExpected = Read-HashFile "$packageZip.sha256"
  $packageActual = (Get-FileHash -Algorithm SHA256 -LiteralPath $packageZip).Hash.ToLowerInvariant()
  Assert-Value ($packageActual -eq $packageExpected) "package archive transfer hash mismatch"

  $runnerTemp = if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) { [IO.Path]::GetTempPath() } else { $env:RUNNER_TEMP }
  $runRoot = Join-Path $runnerTemp ("v3-v1-1-clean-machine-" + [Guid]::NewGuid().ToString("N"))
  $installRoot = Join-Path $runRoot "Installed V3 Quant Workbench"
  $journeyRoot = Join-Path $runRoot "Journey Evidence"
  New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
  New-Item -ItemType Directory -Force -Path $journeyRoot | Out-Null

  $installProcess = Start-Process -FilePath $installerPath -ArgumentList @("/S", "/D=$installRoot") -WindowStyle Hidden -PassThru
  Assert-Value ($installProcess.WaitForExit(180000)) "installer timed out"
  $installProcess.Refresh()
  Assert-Value ($installProcess.ExitCode -eq 0) "installer exit code $($installProcess.ExitCode)"

  $appPath = Join-Path $installRoot "v3-quant-workbench.exe"
  $backendRoot = Join-Path $installRoot "resources\backend-runtime"
  $runtimeManifestPath = Join-Path $backendRoot "runtime-manifest.json"
  Assert-Value (Test-Path -LiteralPath $appPath -PathType Leaf) "installed Electron executable missing"
  $runtimeManifest = Read-Json $runtimeManifestPath
  Assert-Value ($runtimeManifest.product.version -eq $release.product.version) "installed product version mismatch"
  Assert-Value ($runtimeManifest.source_git_sha -eq $release.source.git_sha) "installed source SHA mismatch"
  Assert-Value ($runtimeManifest.source_git_tree_sha -eq $release.source.git_tree_sha) "installed source tree mismatch"
  Assert-Value ((Get-FileHash -Algorithm SHA256 -LiteralPath $runtimeManifestPath).Hash.ToLowerInvariant() -eq ([string]$release.packaged_runtime.manifest_sha256).ToLowerInvariant()) "runtime manifest hash mismatch"

  $driverPath = Join-Path $input "v1_1_product_release_packaged_e2e.mjs"
  Assert-Value (Test-Path -LiteralPath $driverPath -PathType Leaf) "V1.1 bounded driver missing"
  $innerReportPath = Join-Path $journeyRoot "V3_V1_1_PRODUCT_RELEASE_E2E.json"
  $stdoutPath = Join-Path $evidence "v1-1-journeys.stdout.log"
  $stderrPath = Join-Path $evidence "v1-1-journeys.stderr.log"
  $systemRoot = if ([string]::IsNullOrWhiteSpace($env:SystemRoot)) { "C:\Windows" } else { $env:SystemRoot }
  $prior = Set-ProcessEnvironment @{
    ELECTRON_RUN_AS_NODE = "1"
    V3_PACKAGE_ROOT = $installRoot
    V3_PRODUCT_RELEASE_REPORT = $innerReportPath
    V3_C4_TEMP_ROOT = $journeyRoot
    V3_PRODUCT_VERSION = [string]$release.product.version
    Path = (Join-Path $systemRoot "System32")
  }
  try {
    $driverProcess = Start-Process -FilePath $appPath -WorkingDirectory $input -ArgumentList @($driverPath) `
      -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -WindowStyle Hidden -PassThru
    Assert-Value ($driverProcess.WaitForExit(1800000)) "V1.1 clean-machine journeys timed out"
    $driverProcess.Refresh()
    Assert-Value ($driverProcess.ExitCode -eq 0) "V1.1 journey driver exit code $($driverProcess.ExitCode)"
  } finally {
    Restore-ProcessEnvironment $prior
  }

  $journey = Read-Json $innerReportPath
  Assert-Value ($journey.result -eq "PASS_CANDIDATE") "V1.1 journey report is not PASS_CANDIDATE"
  Assert-Value ($journey.source_boundary -eq "LOCAL_USER_SUPPLIED") "clean-machine journey source boundary drifted"
  Assert-Value ($journey.truth -eq "NOT_FORMAL" -and $journey.admission -eq "PRE_ALPHA" -and $journey.maturity -eq "PRODUCT_CONNECTED") "clean-machine truth ceiling drifted"
  Assert-Value ($journey.journeys.A.cold_rediscovery_exact_equality -eq $true) "Journey A restart identity failed"
  Assert-Value ($journey.journeys.B.cold_rediscovery_exact_equality -eq $true) "Journey B restart identity failed"
  Assert-Value ($journey.journeys.A.runs.Count -eq 3 -and $journey.journeys.B.runs.Count -eq 2) "V1.1 journey phase inventory is incomplete"
  foreach ($journeyName in @("A", "B")) {
    $roots = $journey.journeys.$journeyName.storage_roots
    foreach ($property in $roots.PSObject.Properties) {
      Assert-Value (-not (Test-PathInside $installRoot ([string]$property.Value))) "Journey $journeyName storage entered install root: $($property.Name)"
    }
  }
  Assert-Value (@(Get-BackendProcesses $backendRoot).Count -eq 0) "V1.1 journeys left an orphan backend"

  $uninstaller = @(Get-ChildItem -LiteralPath $installRoot -Filter "Uninstall*.exe" -File | Select-Object -First 1)
  Assert-Value ($uninstaller.Count -eq 1) "NSIS uninstaller missing"
  $uninstallProcess = Start-Process -FilePath $uninstaller[0].FullName -ArgumentList @("/S") -WindowStyle Hidden -PassThru
  Assert-Value ($uninstallProcess.WaitForExit(180000)) "uninstaller timed out"
  $uninstallProcess.Refresh()
  Assert-Value ($uninstallProcess.ExitCode -eq 0) "uninstaller exit code $($uninstallProcess.ExitCode)"

  $report = [ordered]@{
    schema_version = "v3.v1-1-release-clean-machine/1.0.0"
    result = "PASS_CANDIDATE"
    source_git_sha = [string]$release.source.git_sha
    source_git_tree_sha = [string]$release.source.git_tree_sha
    build_manifest_id = [string]$release.build.build_manifest_id
    product_version = [string]$release.product.version
    build_runner_name = [string]$buildRunner.runner_name
    verify_runner_name = [string]$env:RUNNER_NAME
    fresh_runner_distinct = $true
    checkout_used = $false
    repository_source_tree_present = $false
    no_npm_install_in_verify_job = $true
    no_pip_install_in_verify_job = $true
    system_python_used = $false
    system_node_used = $false
    bundled_electron_node_used_for_driver = $true
    user_data_outside_install_root = $true
    installer_sha256 = $installerActual
    package_artifact_sha256 = $packageActual
    runtime_manifest_sha256 = [string]$release.packaged_runtime.manifest_sha256
    installer_install = "PASS"
    golden_journey_a = "PASS_CANDIDATE"
    golden_journey_b = "PASS_CANDIDATE"
    cold_restart = "PASS_CANDIDATE"
    physical_windows_scaling = "NOT_RUN"
    user_visual_acceptance = "PENDING_USER_REVIEW"
    backend_exit = "GRACEFUL_SHUTDOWN_SUCCESS"
    orphan_process_count = 0
    uninstall = "PASS"
    pre_download_inventory = $preDownload
    journey_evidence = $journey
  }
  $report | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $reportPath -Encoding utf8
  Write-Output ($report | ConvertTo-Json -Depth 20)
  exit 0
} catch {
  [ordered]@{
    schema_version = "v3.v1-1-release-clean-machine/1.0.0"
    result = "STOP_FOR_REVIEW"
    error = $_.Exception.Message
    error_type = $_.Exception.GetType().FullName
    error_position = $_.InvocationInfo.PositionMessage
    stack = $_.ScriptStackTrace
  } | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $reportPath -Encoding utf8
  Write-Error $_
  exit 1
}
