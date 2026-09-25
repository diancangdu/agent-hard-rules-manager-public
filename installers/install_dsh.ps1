# install_dsh.ps1 - thin wrapper that configures the HardRules MCP server and the
# Claude-Code-style PreToolUse hooks for DSH.
#
# All logic lives in installers/install.py; this script only locates a Python
# interpreter and forwards the arguments. No state is changed unless -Apply.
#
# Usage:
#   .\install_dsh.ps1                                  # dry-run (default)
#   .\install_dsh.ps1 -Apply                           # write config
#   .\install_dsh.ps1 -Apply -AllowProfileWrite        # also write cordis.patch.yml
#   .\install_dsh.ps1 -Home D:\dsh-data
#   .\install_dsh.ps1 -Python D:\Python\python3.14.7\python.exe
#
# NOTE: keep this file pure ASCII. A UTF-8 BOM or non-ASCII characters here can
# make Windows PowerShell mis-parse the quotes in the command line.

[CmdletBinding()]
param(
    [string]$Home,
    [string]$Python,
    [switch]$Apply,
    [switch]$AllowProfileWrite,
    [switch]$AbsolutePython
)

$ErrorActionPreference = 'Stop'

function Resolve-Python {
    param([string]$Hint)

    $candidates = @()
    if ($Hint) { $candidates += $Hint }
    $candidates += @(
        'python',
        'python.exe',
        'py',
        'D:\Python\python3.14.7\python.exe',
        'F:\Anaconda3\python.exe'
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { return $cmd.Source }
    }
    throw 'Python interpreter not found. Pass -Python <path>.'
}

$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
$installer = Join-Path $here 'install.py'
if (-not (Test-Path -LiteralPath $installer)) {
    throw "install.py not found next to this script: $installer"
}

$cliArgs = @($installer, '--agent', 'dsh')
if ($Home)              { $cliArgs += @('--home', $Home) }
if ($Python)            { $cliArgs += @('--python', $Python) }
if ($AllowProfileWrite) { $cliArgs += '--allow-profile-write' }
if ($AbsolutePython)    { $cliArgs += '--absolute-python' }
if ($Apply)             { $cliArgs += '--apply' } else { $cliArgs += '--dry-run' }

$exe = Resolve-Python -Hint $Python
Write-Host "python: $exe"
& $exe @cliArgs
exit $LASTEXITCODE
