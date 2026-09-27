# Clone and build the eight Augmented Nature MCP servers at the commits used
# for the paper (see servers.json). Requires git, Node.js >= 18 and npm.
#
#   pwsh servers/setup_servers.ps1 [-Target DIR]      # default: ~/mcp-servers
#
# Then:  python scripts/run_live.py --servers-root DIR
param(
    [string]$Target = $(if ($env:HPLAN_MCP_SERVERS_ROOT) { $env:HPLAN_MCP_SERVERS_ROOT } else { Join-Path $HOME "mcp-servers" })
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Target | Out-Null

# directory, repository, commit   (keep in sync with servers.json)
$Servers = @(
    @("OpenTargets-MCP-Server", "https://github.com/Augmented-Nature/OpenTargets-MCP-Server.git", "5a7b2ec932cb6c40fade79e56b8373e4aa38a22f"),
    @("UniProt-MCP-Server", "https://github.com/Augmented-Nature/UniProt-MCP-Server.git", "c3356f79d7559b7761cbf1e0712e20924934ae53"),
    @("Reactome-MCP-Server", "https://github.com/Augmented-Nature/Reactome-MCP-Server.git", "d89ba324d93a9b0f80e95645aa97d59faabaf7f4"),
    @("KEGG-MCP-Server", "https://github.com/Augmented-Nature/KEGG-MCP-Server.git", "7364d0e3af834c25c491d666f8a6ce1afcad159b"),
    @("PDB-MCP-Server", "https://github.com/Augmented-Nature/PDB-MCP-Server.git", "6bb2b9600e1846800d0ba222613241031c58a1ae"),
    @("AlphaFold-MCP-Server", "https://github.com/Augmented-Nature/AlphaFold-MCP-Server.git", "2c1b16b6c9590a5eeb1e8d565342975bfdd01496"),
    @("ChEMBL-MCP-Server", "https://github.com/Augmented-Nature/ChEMBL-MCP-Server.git", "43df11e5be0ec6322e05a9b7cd24dc4cc926cda0"),
    @("PubMed-MCP-Server", "https://github.com/Augmented-Nature/PubMed-MCP-Server.git", "01421daecad4e48d21b3f0db943ad20adc630624")
)

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

foreach ($s in $Servers) {
    $dir, $url, $commit = $s
    $dest = Join-Path $Target $dir
    if (-not (Test-Path (Join-Path $dest ".git"))) {
        Invoke-Checked git @("clone", "--quiet", $url, $dest)
    }
    Invoke-Checked git @("-C", $dest, "fetch", "--quiet", "origin")
    Invoke-Checked git @("-C", $dest, "-c", "advice.detachedHead=false", "checkout", "--quiet", $commit)
    Write-Host "== $dir @ $(git -C $dest rev-parse --short HEAD)"
    Push-Location $dest
    try {
        Invoke-Checked npm @("install", "--no-audit", "--no-fund")
        Invoke-Checked npm @("run", "build")
    } finally { Pop-Location }
    if (-not (Test-Path (Join-Path $dest "build/index.js"))) { throw "build failed: $dest/build/index.js missing" }
}

Write-Host ""
Write-Host "All eight servers built under $Target"
Write-Host "Next: python scripts/run_live.py --servers-root `"$Target`""
