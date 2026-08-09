param(
  [string]$BeforeDirectory = "D:\V3OpenSource\.rejected_baseline_fr1\screenshots\after",
  [string]$AfterDirectory = "D:\V3OpenSource\deliverables\visual-restoration-screenshots",
  [string]$OutputDirectory = "D:\V3OpenSource\deliverables\presentation-reconstruction-evidence"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

function New-ContactSheet {
  param([array]$Pairs, [string]$Title, [string]$OutputPath)
  $columnWidth = 720
  $imageWidth = 696
  $imageHeight = 392
  $headerHeight = 58
  $rowHeight = 432
  $canvas = New-Object System.Drawing.Bitmap ($columnWidth * 2), ($headerHeight + ($Pairs.Count * $rowHeight))
  $graphics = [System.Drawing.Graphics]::FromImage($canvas)
  $graphics.Clear([System.Drawing.Color]::FromArgb(11, 13, 20))
  $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $titleFont = New-Object System.Drawing.Font("Segoe UI", 18, [System.Drawing.FontStyle]::Bold)
  $labelFont = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Regular)
  $titleBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(228, 231, 240))
  $beforeBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(139, 144, 167))
  $afterBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(79, 195, 247))
  $borderPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(52, 58, 77), 1)
  try {
    $graphics.DrawString($Title, $titleFont, $titleBrush, 12, 12)
    for ($index = 0; $index -lt $Pairs.Count; $index += 1) {
      $pair = $Pairs[$index]
      $top = $headerHeight + ($index * $rowHeight)
      $beforePath = Join-Path $BeforeDirectory $pair.File
      $afterPath = Join-Path $AfterDirectory $pair.File
      if (-not (Test-Path -LiteralPath $beforePath)) { throw "Missing rejected-baseline screenshot: $beforePath" }
      if (-not (Test-Path -LiteralPath $afterPath)) { throw "Missing reconstruction screenshot: $afterPath" }
      $beforeImage = [System.Drawing.Image]::FromFile($beforePath)
      $afterImage = [System.Drawing.Image]::FromFile($afterPath)
      try {
        $graphics.DrawString("REJECTED  |  $($pair.Label)", $labelFont, $beforeBrush, 12, $top + 3)
        $graphics.DrawString("RECONSTRUCTED  |  $($pair.Label)", $labelFont, $afterBrush, $columnWidth + 12, $top + 3)
        $graphics.DrawImage($beforeImage, 12, $top + 27, $imageWidth, $imageHeight)
        $graphics.DrawImage($afterImage, $columnWidth + 12, $top + 27, $imageWidth, $imageHeight)
        $graphics.DrawRectangle($borderPen, 12, $top + 27, $imageWidth, $imageHeight)
        $graphics.DrawRectangle($borderPen, $columnWidth + 12, $top + 27, $imageWidth, $imageHeight)
      } finally { $beforeImage.Dispose(); $afterImage.Dispose() }
    }
    $canvas.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
  } finally {
    $borderPen.Dispose(); $afterBrush.Dispose(); $beforeBrush.Dispose(); $titleBrush.Dispose()
    $labelFont.Dispose(); $titleFont.Dispose(); $graphics.Dispose(); $canvas.Dispose()
  }
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$representativePairs = @(
  @{ File = "01-research-default-chart-first.png"; Label = "Research / chart-first" },
  @{ File = "02-research-selected-event-inspector.png"; Label = "Research / contextual Inspector" },
  @{ File = "03-research-universe-builder-focused.png"; Label = "Research / Universe workflow" },
  @{ File = "05-strategy-visual-mode.png"; Label = "Strategy / Visual workspace" },
  @{ File = "06-strategy-code-mode.png"; Label = "Strategy / Code workspace" },
  @{ File = "09-model-dataset-family-run-workflow.png"; Label = "Model / phased configuration" },
  @{ File = "10-model-study-trial-hpo-workflow.png"; Label = "Model / Study and Trial" },
  @{ File = "12-backtest-review.png"; Label = "Backtest / execution review" },
  @{ File = "13-result-review.png"; Label = "Result / performance identity" }
)
$fiveLabPairs = @(
  @{ File = "01-research-default-chart-first.png"; Label = "Research" },
  @{ File = "05-strategy-visual-mode.png"; Label = "Strategy" },
  @{ File = "09-model-dataset-family-run-workflow.png"; Label = "Model" },
  @{ File = "12-backtest-review.png"; Label = "Backtest" },
  @{ File = "13-result-review.png"; Label = "Result" }
)
New-ContactSheet -Pairs $representativePairs -Title "V3 Precision Research Workbench / Rejected Baseline to Full Reconstruction" -OutputPath (Join-Path $OutputDirectory "before_after_contact_sheet.png")
New-ContactSheet -Pairs $fiveLabPairs -Title "V3 Full Presentation-System Reconstruction / Five-Lab Comparison" -OutputPath (Join-Path $OutputDirectory "five_lab_before_after_contact_sheet.png")
Write-Output "Presentation reconstruction contact sheets generated in $OutputDirectory"
