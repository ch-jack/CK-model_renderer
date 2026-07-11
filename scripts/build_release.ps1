[CmdletBinding()]
param(
    [string]$OutputDirectory = "dist",
    [string]$SollumzSource = "Sollumz",
    [string]$Version = "",
    [string]$SollumzVersion = "v2.8.3"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$OutputPath = [System.IO.Path]::GetFullPath((Join-Path $RepositoryRoot $OutputDirectory))
$RepositoryPrefix = $RepositoryRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar

if (-not $OutputPath.StartsWith($RepositoryPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDirectory must resolve inside the repository: $OutputPath"
}

if (-not [System.IO.Path]::IsPathRooted($SollumzSource)) {
    $SollumzSource = Join-Path $RepositoryRoot $SollumzSource
}
$SollumzSource = [System.IO.Path]::GetFullPath($SollumzSource)

$RequiredFiles = @(
    "README.md",
    "blender_render_vehicle.py",
    "render_all_vehicles.py",
    "vehicle_assembly.py",
    "render_folder.cmd",
    "vehshare.ytd",
    "tools/7z.exe",
    "tools/7z.dll",
    "tools/CodeWalker.Core.dll",
    "tools/RpfTools.exe",
    "tools/RpfTools.exe.config",
    "tools/YtdTools.exe",
    "tools/YtdTools.exe.config",
    "tools/SharpDX.dll",
    "tools/SharpDX.Mathematics.dll",
    "tools/texconv.exe"
)

foreach ($RelativePath in $RequiredFiles) {
    $SourcePath = Join-Path $RepositoryRoot $RelativePath
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        throw "Required release file is missing: $RelativePath"
    }
}

$DocsSource = Join-Path $RepositoryRoot "docs"
if (-not (Test-Path -LiteralPath $DocsSource -PathType Container)) {
    throw "Required release directory is missing: docs"
}
if (-not (Test-Path -LiteralPath $SollumzSource -PathType Container)) {
    throw "Sollumz source directory is missing: $SollumzSource"
}
$SollumzManifest = Join-Path $SollumzSource "blender_manifest.toml"
if (-not (Test-Path -LiteralPath $SollumzManifest -PathType Leaf)) {
    throw "Sollumz source is invalid; blender_manifest.toml was not found: $SollumzSource"
}
$ExpectedSollumzVersion = $SollumzVersion.TrimStart([char]'v')
$SollumzVersionPattern = '(?m)^\s*version\s*=\s*"' + [regex]::Escape($ExpectedSollumzVersion) + '"\s*$'
if ([IO.File]::ReadAllText($SollumzManifest) -notmatch $SollumzVersionPattern) {
    throw "Sollumz source does not match required version $SollumzVersion."
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = (& git -C $RepositoryRoot rev-parse --short HEAD 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Version)) {
        $Version = "local"
    }
}
$SafeVersion = $Version -replace '[^A-Za-z0-9._-]', '-'
$PackageName = "CK-model_renderer-$SafeVersion-windows"
$StagingRoot = Join-Path $OutputPath "staging"
$PackageRoot = Join-Path $StagingRoot $PackageName
$ZipPath = Join-Path $OutputPath "$PackageName.zip"
$HashPath = "$ZipPath.sha256"

New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null
if (Test-Path -LiteralPath $StagingRoot) {
    Remove-Item -LiteralPath $StagingRoot -Recurse -Force
}
foreach ($OldOutput in @($ZipPath, $HashPath)) {
    if (Test-Path -LiteralPath $OldOutput) {
        Remove-Item -LiteralPath $OldOutput -Force
    }
}
New-Item -ItemType Directory -Path $PackageRoot -Force | Out-Null

foreach ($RelativePath in $RequiredFiles) {
    $SourcePath = Join-Path $RepositoryRoot $RelativePath
    $DestinationPath = Join-Path $PackageRoot $RelativePath
    $DestinationDirectory = Split-Path -Parent $DestinationPath
    New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null
    Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
}
Copy-Item -LiteralPath $DocsSource -Destination (Join-Path $PackageRoot "docs") -Recurse -Force

$SollumzDestination = Join-Path $PackageRoot "Sollumz"
& robocopy $SollumzSource $SollumzDestination /E /R:2 /W:1 /XD .git __pycache__ /XF *.pyc *.pyo /NFL /NDL /NJH /NJS /NP | Out-Host
if ($LASTEXITCODE -gt 7) {
    throw "Failed to copy Sollumz (robocopy exit code $LASTEXITCODE)."
}

$Commit = (& git -C $RepositoryRoot rev-parse HEAD 2>$null)
if ($LASTEXITCODE -ne 0) {
    $Commit = "unknown"
}
$BuildInfo = @(
    "Package: $PackageName",
    "Version: $Version",
    "Commit: $Commit",
    "Sollumz: $SollumzVersion",
    "BuiltAtUtc: $([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))",
    "Requirements: Windows, Python, Blender 4.2+ (5.1 recommended), .NET Framework 4.8"
)
$BuildInfo | Set-Content -LiteralPath (Join-Path $PackageRoot "BUILD_INFO.txt") -Encoding ASCII

$PythonFiles = @(
    (Join-Path $PackageRoot "blender_render_vehicle.py"),
    (Join-Path $PackageRoot "render_all_vehicles.py"),
    (Join-Path $PackageRoot "vehicle_assembly.py")
)
& python -m py_compile @PythonFiles
if ($LASTEXITCODE -ne 0) {
    throw "Python syntax validation failed."
}
Get-ChildItem -LiteralPath $PackageRoot -Directory -Filter "__pycache__" -Recurse | Remove-Item -Recurse -Force

Compress-Archive -LiteralPath $PackageRoot -DestinationPath $ZipPath -CompressionLevel Optimal
$Hash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
"$Hash  $([System.IO.Path]::GetFileName($ZipPath))" | Set-Content -LiteralPath $HashPath -Encoding ASCII
Remove-Item -LiteralPath $StagingRoot -Recurse -Force

Write-Host "Release package: $ZipPath"
Write-Host "SHA256: $HashPath"
