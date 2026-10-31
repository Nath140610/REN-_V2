$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Read-PrivateVariable {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Prompt,
        [bool]$Required = $false
    )

    $current = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if (-not [string]::IsNullOrWhiteSpace($current)) { return }

    $secure = Read-Host -Prompt $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }

    if ($Required -and [string]::IsNullOrWhiteSpace($value)) {
        throw "$Name est obligatoire."
    }
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        [Environment]::SetEnvironmentVariable($Name, $value, 'Process')
    }
}

Write-Host 'René va démarrer sur ce PC. Copie les valeurs depuis Render > Environment.'
Write-Host 'Les valeurs saisies restent privées et ne sont pas enregistrées dans le dépôt.'
Read-PrivateVariable -Name 'DISCORD_TOKEN' -Prompt 'DISCORD_TOKEN (bot René original)' -Required $true
Read-PrivateVariable -Name 'STATE_SECRET' -Prompt 'STATE_SECRET (Entrée si absent sur Render)'
Read-PrivateVariable -Name 'STATE_SECRET_PREVIOUS' -Prompt 'STATE_SECRET_PREVIOUS (Entrée si absent sur Render)'

python -c 'import discord, flask, waitress, cryptography'
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installation des dépendances Python...'
    python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Installation Python impossible.' }
}

Write-Host 'Connexion à Discord. Laisse cette fenêtre ouverte ; Ctrl+C arrête René.'
python -u local_bot.py
