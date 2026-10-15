$ErrorActionPreference = 'Stop'
$root = git rev-parse --show-toplevel
if (-not $root) { throw 'Run this from inside the SITARA Git repository.' }
Set-Location $root
git config core.hooksPath .githooks
Write-Host 'Git hooks installed: .githooks'
Write-Host 'The hook runs in Git Bash or another shell that supports .githooks/pre-commit.'
