# Fetches openzt (MIT, https://github.com/openzt1/openzt) into vendor\openzt at the commit our patch
# is based on, and applies patches\openzt-zoo-together.patch on a zoo-together branch.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..").Path
$dest = Join-Path $root 'vendor\openzt'
$base = 'df01b96'
if (-not (Test-Path "$dest\.git")) {
    git clone https://github.com/openzt1/openzt $dest
}
Push-Location $dest
try {
    if ((git branch --list zoo-together)) {
        Write-Host 'vendor\openzt already has the zoo-together branch'
    } else {
        git checkout -b zoo-together $base
        git am "$root\patches\openzt-zoo-together.patch"
    }
} finally { Pop-Location }
