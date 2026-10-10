param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): $Program $($Arguments -join ' ')"
    }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    $venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Invoke-Checked -Program $Python -Arguments @("-m", "venv", ".venv")
    }
    Invoke-Checked -Program $venvPython -Arguments @(
        "-m", "pip", "install", "--no-cache-dir", "-r", "requirements-dev.txt", "pyinstaller>=6,<7"
    )
    Invoke-Checked -Program $venvPython -Arguments @("-m", "pytest", "-q")
    Invoke-Checked -Program $venvPython -Arguments @(
        "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", "dist", "--workpath", "build", "prank_news.spec"
    )
    $exePath = Join-Path $PSScriptRoot "dist\PrankNews.exe"
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw "Build completed without producing $exePath"
    }
    Write-Host "Built: $exePath"
}
finally {
    Pop-Location
}
