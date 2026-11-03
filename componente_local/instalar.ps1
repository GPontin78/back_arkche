param(
    [Parameter(Mandatory = $true)][string]$UrlBanco,
    [Parameter(Mandatory = $true)][string]$Pythonw
)
$ErrorActionPreference = 'Stop'
if (!(Test-Path -LiteralPath $Pythonw -PathType Leaf)) { throw 'Pythonw não encontrado.' }
$url = [uri]$UrlBanco
if ($url.Scheme -ne 'https' -or !$url.Host -or $url.UserInfo -or $url.Query -or $url.Fragment -or $url.AbsolutePath -ne '/') {
    throw 'Informe somente a URL HTTPS do banco, sem caminho ou parâmetros.'
}
$pasta = Join-Path $env:LOCALAPPDATA 'Arkhe'
New-Item -ItemType Directory -Path $pasta -Force | Out-Null
$arquivo = Join-Path $pasta 'abrir_banco.pyw'
if (Test-Path -LiteralPath $arquivo) {
    Copy-Item -LiteralPath $arquivo -Destination ($arquivo + '.antes-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'abrir_banco.pyw') -Destination $arquivo
$atalho = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Banco Arkhe - IP do PC.lnk'
if (Test-Path -LiteralPath $atalho) {
    Copy-Item -LiteralPath $atalho -Destination ($atalho + '.antes-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($atalho)
$link.TargetPath = (Resolve-Path -LiteralPath $Pythonw).Path
$link.Arguments = '"' + $arquivo + '" "' + $url.AbsoluteUri + '"'
$link.WorkingDirectory = $pasta
$link.Description = 'Abrir o Banco Arkhé e informar o IP interno deste PC nos logs.'
$link.Save()
Write-Output $atalho
