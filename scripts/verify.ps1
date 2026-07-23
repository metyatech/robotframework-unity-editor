Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-VerifyCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Command
    )

    $exe = $Command[0]
    $args = @()
    if ($Command.Length -gt 1) {
        $args = $Command[1..($Command.Length - 1)]
    }

    & $exe @args
    if ($LASTEXITCODE -ne 0) {
        throw "Verification command failed (exit=$LASTEXITCODE): $($Command -join ' ')"
    }
}

Invoke-VerifyCommand @("python", "-m", "ruff", "format", "--check", ".")
Invoke-VerifyCommand @("python", "-m", "ruff", "check", ".")
Invoke-VerifyCommand @("python", "-m", "pyright")
Invoke-VerifyCommand @("python", "-m", "pytest")
