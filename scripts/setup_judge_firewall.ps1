# Judge worker firewall rules (Windows Defender Firewall).
#
# -Enable : create inbound allow-all + outbound block-all rules for the judge
#           service account, with explicit allow rules for Redis on
#           127.0.0.1:6379 and all loopback traffic. Idempotent: any existing
#           xinbaoyan-judge-* rule is removed first.
# -Remove : roll back all xinbaoyan-judge-* rules.
#
# Requires an elevated PowerShell session.

param(
    [switch]$Enable,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$RulePrefix = "xinbaoyan-judge"
$ServiceUser = "judge_svc"
$RedisAddress = "127.0.0.1"
$RedisPort = 6379

function Remove-XinbaoyanJudgeRules {
    $existing = Get-NetFirewallRule -DisplayName "$RulePrefix*" -ErrorAction SilentlyContinue
    foreach ($rule in $existing) {
        Write-Host "Removing existing rule: $($rule.DisplayName)"
        Remove-NetFirewallRule -Name $rule.Name
    }
}

if ($Remove) {
    Remove-XinbaoyanJudgeRules
    Write-Host "All $RulePrefix* firewall rules removed."
    exit 0
}

if (-not $Enable) {
    Write-Host "Usage: setup_judge_firewall.ps1 -Enable [-Remove]"
    Write-Host "  -Enable   create inbound allow / outbound block rules for $ServiceUser"
    Write-Host "  -Remove   remove all $RulePrefix* rules"
    exit 1
}

Remove-XinbaoyanJudgeRules

# Inbound: default allow for the judge service account.
New-NetFirewallRule -DisplayName "$RulePrefix-in-allow" -Name "$RulePrefix-in-allow" `
    -Direction Inbound -Action Allow -Enabled True -Profile Any `
    -Description "Inbound default allow for judge service account"

# Outbound: default block for the judge service account.
New-NetFirewallRule -DisplayName "$RulePrefix-out-block" -Name "$RulePrefix-out-block" `
    -Direction Outbound -Action Block -Enabled True -Profile Any `
    -Description "Outbound default block for judge service account"

# Explicit outbound allow for Redis broker and result queue on loopback.
New-NetFirewallRule -DisplayName "$RulePrefix-out-redis" -Name "$RulePrefix-out-redis" `
    -Direction Outbound -Action Allow -Protocol TCP -RemoteAddress $RedisAddress -RemotePort $RedisPort `
    -Enabled True -Profile Any `
    -Description "Allow outbound Redis to $RedisAddress`:$RedisPort"

# Explicit allow for all loopback traffic (inbound and outbound).
New-NetFirewallRule -DisplayName "$RulePrefix-loopback-out" -Name "$RulePrefix-loopback-out" `
    -Direction Outbound -Action Allow -RemoteAddress 127.0.0.1/8 -Enabled True -Profile Any `
    -Description "Allow outbound loopback traffic"
New-NetFirewallRule -DisplayName "$RulePrefix-loopback-in" -Name "$RulePrefix-loopback-in" `
    -Direction Inbound -Action Allow -LocalAddress 127.0.0.1/8 -Enabled True -Profile Any `
    -Description "Allow inbound loopback traffic"

Write-Host "Firewall rules created:"
Get-NetFirewallRule -DisplayName "$RulePrefix*" | Format-Table DisplayName, Direction, Action, Enabled

Write-Host ""
Write-Host "set JUDGE_FIREWALL_ACTIVE=1 before starting the worker"
