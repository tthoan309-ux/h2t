param(
    [string]$Data = "..\Data_B",
    [string]$Out = "outputs",
    [string]$Python = "python",
    [switch]$SkipQuick,
    [switch]$SkipScreening,
    [switch]$SkipFocused,
    [switch]$SkipValidation,
    [switch]$SkipFinal,
    [switch]$NoResume,
    [int]$QuickIterations = 100,
    [int]$QuickMaxConfigs = 5,
    [int]$ScreeningConfigs = 20,
    [int]$ScreeningIterations = 200,
    [string]$ScreeningSeeds = "1",
    [int]$FocusedConfigs = 10,
    [int]$FocusedIterations = 800,
    [string]$FocusedSeeds = "1,2,3",
    [int]$ValidationIterations = 3000,
    [string]$ValidationSeeds = "4,5,42",
    [int]$FinalIterations = 3000,
    [string]$FinalSeeds = "1,2,3,4,5"
)

$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [string]$Name,
        [string[]]$Args
    )

    Write-Host ""
    Write-Host "============================================================"
    Write-Host $Name
    Write-Host "============================================================"
    Write-Host "$Python $($Args -join ' ')"

    & $Python @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Name (exit code $LASTEXITCODE)"
    }
}

$resumeArgs = @()
if (-not $NoResume) {
    $resumeArgs += "--resume"
}

# Cac buoc duoc sap xep theo successive halving:
# 1) debug nho de kiem tra code/export,
# 2) screening rong nhung ngan,
# 3) focused sau hon tren vung tot,
# 4) validation/final comparison voi best_config.
if (-not $SkipQuick) {
    Invoke-Step "Stage 1 - Quick debug tuning" @(
        "main.py",
        "--data", $Data,
        "--out", $Out,
        "--tune",
        "--tune-mode", "quick",
        "--iterations", "$QuickIterations",
        "--tune-seeds", "1",
        "--max-configs", "$QuickMaxConfigs",
        "--debug"
    ) + $resumeArgs
}

if (-not $SkipScreening) {
    Invoke-Step "Stage 2 - Screening random search" @(
        "main.py",
        "--data", $Data,
        "--out", $Out,
        "--tune",
        "--tune-mode", "full",
        "--search-strategy", "random",
        "--n-configs", "$ScreeningConfigs",
        "--iterations", "$ScreeningIterations",
        "--tune-seeds", $ScreeningSeeds,
        "--tuning-stage", "screening",
        "--tune-light"
    ) + $resumeArgs
}

if (-not $SkipFocused) {
    Invoke-Step "Stage 3 - Focused tuning" @(
        "main.py",
        "--data", $Data,
        "--out", $Out,
        "--tune",
        "--tune-mode", "full",
        "--search-strategy", "random",
        "--n-configs", "$FocusedConfigs",
        "--iterations", "$FocusedIterations",
        "--tune-seeds", $FocusedSeeds,
        "--tuning-stage", "focused"
    ) + $resumeArgs
}

$bestConfig = Join-Path $Out "tuning\best_config.json"
if (-not (Test-Path $bestConfig)) {
    throw "Best config not found: $bestConfig. Run tuning stages first."
}

if (-not $SkipValidation) {
    Invoke-Step "Stage 4 - Validate tuned config on unseen seeds" @(
        "main.py",
        "--data", $Data,
        "--out", $Out,
        "--use-best-config", $bestConfig,
        "--iterations", "$ValidationIterations",
        "--seeds", $ValidationSeeds
    )
}

if (-not $SkipFinal) {
    Invoke-Step "Stage 5 - Final fair method comparison" @(
        "main.py",
        "--data", $Data,
        "--out", $Out,
        "--use-best-config", $bestConfig,
        "--iterations", "$FinalIterations",
        "--seeds", $FinalSeeds
    )
}

Write-Host ""
Write-Host "Pipeline completed."
Write-Host "Key files:"
Write-Host "  $Out\tuning\tuning_results_summary.csv"
Write-Host "  $Out\tuning\best_config.json"
Write-Host "  $Out\metrics\final_method_comparison.csv"
Write-Host "  $Out\metrics\final_method_comparison_summary.csv"
