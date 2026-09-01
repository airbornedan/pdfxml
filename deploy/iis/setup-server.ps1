<#
.SYNOPSIS
  One-time setup of PDFXML on a Windows Server 2022 IIS host (fatwxsweb1).
  Run as Administrator ON the server (or via Enter-PSSession).

  Installs prerequisites (Python 3.12, Git, HttpPlatformHandler), builds the
  venv, creates the IIS app pool + site on port 5055 with Windows
  Authentication (anonymous off), opens the firewall, and optionally installs
  a GitHub Actions self-hosted runner (as NETWORK SERVICE, non-admin) so
  pushes to main auto-deploy without server admin rights.

.PARAMETER RunnerToken
  Registration token from GitHub: repo Settings > Actions > Runners >
  New self-hosted runner (valid ~1 hour). Omit to skip runner install.

.EXAMPLE
  .\setup-server.ps1 -RunnerToken ABCDEF123...
#>
[CmdletBinding()]
param(
    [string]$AppRoot    = 'E:\PDFXML',
    [string]$SiteName   = 'PDFXML',
    [int]   $Port       = 5055,
    [string]$RepoUrl    = 'https://github.com/airbornedan/pdfxml',
    [string]$RunnerRoot = 'E:\actions-runner-pdfxml',
    [string]$RunnerToken
)

$ErrorActionPreference = 'Stop'
$tmp = Join-Path $env:TEMP 'pdfxml-setup'
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '== 1/8 IIS features =='
Install-WindowsFeature Web-Server, Web-Windows-Auth | Out-Null
Import-Module WebAdministration

Write-Host '== 2/8 HttpPlatformHandler =='
if (-not (Test-Path "$env:SystemRoot\System32\inetsrv\httpPlatformHandler.dll")) {
    $msi = Join-Path $tmp 'httpPlatformHandler_amd64.msi'
    Invoke-WebRequest 'https://go.microsoft.com/fwlink/?LinkId=690721' -OutFile $msi -UseBasicParsing
    Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart" -Wait
}

Write-Host '== 3/8 Python 3.12 (machine-wide) =='
$py = 'C:\Program Files\Python312\python.exe'
if (-not (Test-Path $py)) {
    $pyExe = Join-Path $tmp 'python-3.12.10-amd64.exe'
    Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $pyExe -UseBasicParsing
    Start-Process $pyExe -ArgumentList '/quiet InstallAllUsers=1 PrependPath=0 Include_test=0 Include_launcher=0' -Wait
    if (-not (Test-Path $py)) { throw 'Python 3.12 install failed' }
}

Write-Host '== 4/8 Git (needed by the Actions runner checkout) =='
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    $gitExe = Join-Path $tmp 'git-installer.exe'
    Invoke-WebRequest 'https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe' -OutFile $gitExe -UseBasicParsing
    Start-Process $gitExe -ArgumentList '/VERYSILENT /NORESTART /NOCANCEL /SP-' -Wait
}

Write-Host "== 5/8 Virtual environment + dependencies in $AppRoot =="
if (-not (Test-Path (Join-Path $AppRoot 'requirements.txt'))) {
    throw "$AppRoot does not contain the app source. Copy the repo there first."
}
New-Item -ItemType Directory -Path (Join-Path $AppRoot 'logs') -Force | Out-Null
$venvPy = Join-Path $AppRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) { & $py -m venv (Join-Path $AppRoot '.venv') }
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r (Join-Path $AppRoot 'deploy\iis\requirements-iis.txt') --quiet

Write-Host "== 6/8 IIS app pool + site '$SiteName' on port $Port =="
if (-not (Test-Path "IIS:\AppPools\$SiteName")) { New-WebAppPool -Name $SiteName | Out-Null }
Set-ItemProperty "IIS:\AppPools\$SiteName" managedRuntimeVersion ''
Set-ItemProperty "IIS:\AppPools\$SiteName" processModel.loadUserProfile $true
Set-ItemProperty "IIS:\AppPools\$SiteName" processModel.idleTimeout ([TimeSpan]::Zero)
Set-ItemProperty "IIS:\AppPools\$SiteName" startMode 'AlwaysRunning'
if (-not (Get-Website -Name $SiteName -ErrorAction SilentlyContinue)) {
    New-Website -Name $SiteName -Port $Port -PhysicalPath $AppRoot -ApplicationPool $SiteName | Out-Null
}

# Windows Authentication with 401 challenge; anonymous off. Set at the server
# (APPHOST) level with a location tag -- these sections are locked for web.config.
Set-WebConfigurationProperty -PSPath 'MACHINE/WEBROOT/APPHOST' -Location $SiteName `
    -Filter 'system.webServer/security/authentication/anonymousAuthentication' -Name enabled -Value $false
Set-WebConfigurationProperty -PSPath 'MACHINE/WEBROOT/APPHOST' -Location $SiteName `
    -Filter 'system.webServer/security/authentication/windowsAuthentication' -Name enabled -Value $true

# App pool identity needs to write uploads/, logs/, and .secret_key.
$acl = Get-Acl $AppRoot
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "IIS AppPool\$SiteName", 'Modify', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
$acl.AddAccessRule($rule)
Set-Acl $AppRoot $acl

Write-Host '== 7/8 Firewall =='
if (-not (Get-NetFirewallRule -DisplayName "PDFXML HTTP $Port" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "PDFXML HTTP $Port" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
}

Write-Host '== 8/8 GitHub Actions self-hosted runner =='
if ($RunnerToken) {
    if (-not (Test-Path (Join-Path $RunnerRoot 'config.cmd'))) {
        $rel = Invoke-RestMethod 'https://api.github.com/repos/actions/runner/releases/latest' -UseBasicParsing
        $asset = $rel.assets | Where-Object name -like 'actions-runner-win-x64-*.zip' | Select-Object -First 1
        $zip = Join-Path $tmp $asset.name
        Invoke-WebRequest $asset.browser_download_url -OutFile $zip -UseBasicParsing
        New-Item -ItemType Directory -Path $RunnerRoot -Force | Out-Null
        Expand-Archive $zip -DestinationPath $RunnerRoot -Force
    }
    # NETWORK SERVICE (non-admin) deploys via file operations only; grant it the app folder.
    $acl = Get-Acl $AppRoot
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        'NT AUTHORITY\NETWORK SERVICE', 'Modify', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
    Set-Acl $AppRoot $acl
    $acl = Get-Acl $RunnerRoot
    $acl.AddAccessRule($rule)
    Set-Acl $RunnerRoot $acl

    Push-Location $RunnerRoot
    & .\config.cmd --url $RepoUrl --token $RunnerToken --unattended `
        --name "$env:COMPUTERNAME-pdfxml" --labels pdfxml --runasservice `
        --windowslogonaccount 'NT AUTHORITY\NETWORK SERVICE'
    Pop-Location
} else {
    Write-Warning 'No -RunnerToken given; skipped runner install. Re-run step 8 later with a token.'
}

Start-Website -Name $SiteName
Write-Host "Done. Browse http://$($env:COMPUTERNAME):$Port (Windows Authentication required)."
