$raw = [Console]::In.ReadToEnd()

if ([string]::IsNullOrWhiteSpace($raw)) {
    exit 0
}

try {
    $payload = $raw | ConvertFrom-Json -Depth 20
} catch {
    exit 0
}

function Write-HookJson {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Body
    )

    $Body | ConvertTo-Json -Depth 20 -Compress | Write-Output
}

function Get-CurrentBranch {
    try {
        $branch = (git rev-parse --abbrev-ref HEAD 2>$null).Trim()
        if ([string]::IsNullOrWhiteSpace($branch)) {
            return $null
        }
        return $branch
    } catch {
        return $null
    }
}

$branch = Get-CurrentBranch
$protectedBranches = @("main", "master")
$onProtectedBranch = $branch -eq "HEAD" -or $protectedBranches -contains $branch
$eventName = [string]$payload.hookEventName

if ($eventName -eq "SessionStart") {
    $message = if ($onProtectedBranch) {
        "Current branch is '$branch'. Protected branches are read-only for tracked-file edits. Create a feature branch before the first edit, commit every logical unit, push regularly, and merge with --no-ff."
    } else {
        "Current branch is '$branch'. Keep commits atomic, push branch progress regularly, and merge to main with --no-ff."
    }

    Write-HookJson @{
        hookSpecificOutput = @{
            hookEventName = "SessionStart"
            additionalContext = $message
        }
    }
    exit 0
}

if ($eventName -ne "PreToolUse") {
    Write-HookJson @{ continue = $true }
    exit 0
}

$toolName = [string]$payload.tool_name
$toolInput = $payload.tool_input
$isEditLikeTool = $toolName -match '(?i)apply_patch|edit|write|create|delete|rename|move|replace|insert'
$isCommandTool = $toolName -match '(?i)terminal|shell|execute|command|run'
$commandText = if ($toolInput -and $toolInput.PSObject.Properties.Name -contains 'command') { [string]$toolInput.command } else { '' }
$normalizedCommand = $commandText.ToLowerInvariant()

if ($onProtectedBranch -and $isEditLikeTool) {
    Write-HookJson @{
        hookSpecificOutput = @{
            hookEventName = "PreToolUse"
            permissionDecision = "deny"
            permissionDecisionReason = "Tracked-file edits on '$branch' are blocked. Create a feature branch first with git switch -c <type>/<short-desc>."
        }
    }
    exit 0
}

if ($isCommandTool -and -not [string]::IsNullOrWhiteSpace($normalizedCommand)) {
    if ($onProtectedBranch -and $normalizedCommand -match 'git\s+commit\b') {
        Write-HookJson @{
            hookSpecificOutput = @{
                hookEventName = "PreToolUse"
                permissionDecision = "deny"
                permissionDecisionReason = "Direct commits on '$branch' are blocked. Create a feature branch first."
            }
        }
        exit 0
    }

    if ($onProtectedBranch -and $normalizedCommand -match 'git\s+push\b') {
        Write-HookJson @{
            hookSpecificOutput = @{
                hookEventName = "PreToolUse"
                permissionDecision = "deny"
                permissionDecisionReason = "Direct pushes from '$branch' are blocked. Push a feature branch instead."
            }
        }
        exit 0
    }

    if ($normalizedCommand -match 'git\s+merge\b' -and $normalizedCommand -notmatch '--no-ff') {
        Write-HookJson @{
            hookSpecificOutput = @{
                hookEventName = "PreToolUse"
                permissionDecision = "deny"
                permissionDecisionReason = "Merges must use git merge --no-ff to preserve branch history."
            }
        }
        exit 0
    }
}

Write-HookJson @{
    hookSpecificOutput = @{
        hookEventName = "PreToolUse"
        permissionDecision = "allow"
    }
}
