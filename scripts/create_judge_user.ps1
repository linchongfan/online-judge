<#
.SYNOPSIS
    Create and harden the judge_svc low-privilege account for the OJ judge worker.

.DESCRIPTION
    Run as Administrator. Creates judge_svc with a random password, denies
    interactive/network/remote logons, and prints the minimal ACL checklist.
    The password is written to %ProgramData%\xinbaoyan\judge_svc.cred for the
    watchdog/service installer to read; protect that file accordingly.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\create_judge_user.ps1
#>

#Requires -RunAsAdministrator

$ErrorActionPreference = 'Stop'

$AccountName = 'judge_svc'
$CredDir = Join-Path $env:ProgramData 'xinbaoyan'
$CredFile = Join-Path $CredDir 'judge_svc.cred'

# 1. Generate a strong password (16 chars, printable ASCII subset).
Add-Type -AssemblyName 'System.Web'
$Password = [System.Web.Security.Membership]::GeneratePassword(20, 4)
# net user rejects some specials; keep alnum + a few safe symbols.
$Password = ($Password -replace '[^a-zA-Z0-9]', 'x')
if ($Password.Length -gt 14) { $Password = $Password.Substring(0, 14) }

# 2. Create the account (idempotent).
$existing = Get-LocalUser -Name $AccountName -ErrorAction SilentlyContinue
if (-not $existing) {
    New-LocalUser -Name $AccountName -Password (ConvertTo-SecureString $Password -AsPlainText -Force) `
        -Description 'Xinbaoyan OJ judge worker service account' `
        -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
    Write-Host "Created account $AccountName"
} else {
    Set-LocalUser -Name $AccountName -Password (ConvertTo-SecureString $Password -AsPlainText -Force)
    Write-Host "Reset password for existing account $AccountName"
}

# 3. Deny interactive, network and remote interactive logon.
$denyRights = @(
    'SeDenyInteractiveLogonRight',
    'SeDenyNetworkLogonRight',
    'SeDenyRemoteInteractiveLogonRight'
)
foreach ($right in $denyRights) {
    # Use secedit to add the deny right; append to existing list.
    $tmp = Join-Path $env:TEMP "secedit_$right.inf"
    $db = Join-Path $env:TEMP "secedit_$right.sdb"
    "[Unicode]`r`nUnicode=yes`r`n[Privilege Rights]`r`n$right = $AccountName`r`n" | Out-File -FilePath $tmp -Encoding unicode
    & secedit.exe /configure /db $db /cfg $tmp /quiet | Out-Null
    Remove-Item $tmp, $db -Force -ErrorAction SilentlyContinue
    Write-Host "Applied $right = $AccountName"
}

# 4. Store the credential for the service installer.
New-Item -ItemType Directory -Force -Path $CredDir | Out-Null
$Password | Out-File -FilePath $CredFile -Encoding ascii -Force
$acl = Get-Acl $CredFile
$acl.SetAccessRuleProtection($true, $false)
$adminRule = New-Object System.Security.AccessControl.FileSystemAccessRule('Administrators', 'FullControl', 'Allow')
$acl.SetAccessRule($adminRule)
Set-Acl -Path $CredFile -AclObject $acl
Write-Host "Credential written to $CredFile (Administrators only)"

Write-Host ''
Write-Host '=== Minimal ACL checklist ===' -ForegroundColor Cyan
Write-Host '1. Toolchain dirs (READ ONLY for judge_svc):'
Write-Host '   - C:\Program Files (x86)\Dev-Cpp\MinGW64\bin'
Write-Host '   - C:\Program Files\Amazon Corretto\jdk1.8.0_512\bin'
Write-Host '   - C:\Python386'
Write-Host '2. Work root (READ/WRITE): the directory set as JUDGE_WORK_ROOT, e.g. D:\judge-work'
Write-Host '3. DENY access to: project source dir, data\, .env, and any business secrets.'
Write-Host '4. Run scripts\setup_judge_firewall.ps1 to block outbound network for judge_svc.'
Write-Host '5. Install the watchdog: powershell -File scripts\install_judge_watchdog.ps1'
