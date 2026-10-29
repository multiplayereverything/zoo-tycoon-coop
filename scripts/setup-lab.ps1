# Creates two lab copies of Zoo Tycoon (private\lab-host, private\lab-client) as hardlinks of the
# install, each with its own zoo.ini (windowed, no intro movies), openzt.toml (own console port, no
# TUI) and the freshly built res-openzt.dll. The real install is never modified.
param(
    [string]$GameDir = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$Dll = "$PSScriptRoot\..\vendor\openzt\target\i686-pc-windows-msvc\release\openzt.dll"
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..").Path
if (-not (Test-Path "$GameDir\zoo.exe")) { throw "zoo.exe not found in $GameDir" }
if (-not (Test-Path $Dll)) { throw "DLL not built: $Dll (run scripts\build.cmd)" }

$copies = @{ 'lab-host' = 8181; 'lab-client' = 8182 }
foreach ($name in $copies.Keys) {
    $dest = Join-Path $root "private\$name"
    if (-not (Test-Path "$dest\zoo.exe")) {
        Write-Host "linking $name ..."
        Get-ChildItem -LiteralPath $GameDir -Recurse -File | Where-Object {
            $_.FullName -notlike "$root*" -and $_.Name -notin @('zoo.ini', 'openzt.toml', 'openzt.log') -and $_.Name -notlike 'res-openzt*.dll'
        } | ForEach-Object {
            $rel = $_.FullName.Substring($GameDir.Length).TrimStart('\')
            $target = Join-Path $dest $rel
            New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
            New-Item -ItemType HardLink -Path $target -Target $_.FullName | Out-Null
        }
        New-Item -ItemType Directory -Force "$dest\Saved Games" | Out-Null
    }

    $ini = Get-Content "$GameDir\zoo.ini"
    $set = @{ fullscreen = '0'; screenwidth = '800'; screenheight = '600'; playMovie = '0'; playSecondMovie = '0'; noMenuMusic = '1' }
    $ini = $ini | ForEach-Object {
        $line = $_
        foreach ($k in $set.Keys) { if ($line -match "^\s*$k\s*=") { $line = "$k=$($set[$k])" } }
        $line
    }
    Set-Content -Encoding ascii "$dest\zoo.ini" $ini

    $port = $copies[$name]
    Set-Content -Encoding ascii "$dest\openzt.toml" @"
[dev]
console_listen = "127.0.0.1:$port"

[tui]
enabled = false
"@
    Copy-Item -Force $Dll "$dest\res-openzt.dll"
    Write-Host "$name ready (console $port)"
}
