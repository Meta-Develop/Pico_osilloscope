$raw = [Console]::In.ReadToEnd()

if ([string]::IsNullOrWhiteSpace($raw)) {
    exit 0
}

try {
    $payload = $raw | ConvertFrom-Json -Depth 20
} catch {
    exit 0
}

$allowedAgents = @("expert-coder", "expert-reviewer", "expert-explorer")

function Write-HookJson {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Body
    )

    $Body | ConvertTo-Json -Depth 20 -Compress | Write-Output
}

$eventName = [string]$payload.hookEventName

if ($eventName -eq "PreToolUse") {
    $toolName = [string]$payload.tool_name

    if ($toolName -match '(?i)agent|subagent') {
        $requestedAgent = $null
        $toolInput = $payload.tool_input

        foreach ($propertyName in @("agentName", "agent", "agent_type", "agentType", "subagent", "subagentName")) {
            if ($toolInput -and $toolInput.PSObject.Properties.Name -contains $propertyName) {
                $candidate = [string]$toolInput.$propertyName
                if (-not [string]::IsNullOrWhiteSpace($candidate)) {
                    $requestedAgent = $candidate
                    break
                }
            }
        }

        if ([string]::IsNullOrWhiteSpace($requestedAgent)) {
            Write-HookJson @{
                hookSpecificOutput = @{
                    hookEventName = "PreToolUse"
                    permissionDecision = "deny"
                    permissionDecisionReason = "Unnamed subagent invocation is blocked. Use strict-orchestrator with expert-coder, expert-reviewer, or expert-explorer."
                }
            }
            exit 0
        }

        if ($allowedAgents -notcontains $requestedAgent) {
            Write-HookJson @{
                hookSpecificOutput = @{
                    hookEventName = "PreToolUse"
                    permissionDecision = "deny"
                    permissionDecisionReason = "Subagent '$requestedAgent' is blocked. Allowed subagents: expert-coder, expert-reviewer, expert-explorer."
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
    exit 0
}

if ($eventName -eq "SubagentStart") {
    $agentType = [string]$payload.agent_type

    if (-not [string]::IsNullOrWhiteSpace($agentType) -and $allowedAgents -notcontains $agentType) {
        Write-HookJson @{
            continue = $false
            stopReason = "Blocked subagent '$agentType'. Allowed subagents: expert-coder, expert-reviewer, expert-explorer."
            systemMessage = "This workspace enforces strong-model-only subagents. Use strict-orchestrator or an approved custom agent."
        }
        exit 0
    }
}

Write-HookJson @{ continue = $true }
