# Copilot Instructions — Pico Oscilloscope

## Project Overview

Pico Oscilloscope: Simple oscilloscope built on Raspberry Pi Pico 2 (RP2350).
Hat mode monitors all target Pico 2 GPIO pins as digital logic.
Oscilloscope mode provides 4ch analog (ADC0-ADC3) + remaining digital channels.
Designed for autonomous hardware debugging by AI agents.

## Coding Delegation Rules (MANDATORY)

```
BLOOD RULE — COST-AWARE DELEGATION:
Coding MUST be delegated to GPT-5.4 by default.
Opus 4.6 acts as architect + reviewer only.
Writing code yourself is a LAST RESORT.
```

### Agent Role Assignment

| Agent | Role | Invocation |
|-------|------|------------|
| **Opus 4.6** (Chat) | Design, Review, Orchestration | VS Code Copilot Chat |
| **Copilot CLI** (Codex) | Implementation, Tests, Refactoring | `copilot --model gpt-5.4 -p "..."` |
| **Gemini CLI** | Design Discussion, Brainstorming | `gemini --model gemini-3.1 "..."` |

### Workflow

1. Receive task from user
2. Opus reads context and plans
3. Design decision needed → Consult Gemini CLI
4. Coding needed → Delegate to Copilot CLI (GPT-5.4)
5. Opus reviews output (compile check, logic verification)
6. Fix issues or re-delegate
7. Report to user briefly upon completion

## Absolute Rules

### Blood Rules
1. **Never modify verified working code without re-verification**
2. **Never omit technical values** (Hex, Pin numbers, Registers, etc.)
3. **Exhaust all software causes before suspecting hardware**
4. **No AI footprint in public-facing artifacts**

### Language Policy (BLOOD RULE)

```
BLOOD RULE — ENGLISH ONLY:
All project files must be written in English.
This includes: code, comments, docstrings, commit messages,
documentation (.md), YAML, configuration files, and variable names.

Japanese (or any non-English language) is FORBIDDEN in:
- Source code and comments
- Documentation files
- Commit messages
- Configuration and YAML files
- Log messages and user-facing strings

NO EXCEPTIONS. Even commented-out non-English text is prohibited.
```

### Technical Constraints
- **MCU**: Raspberry Pi Pico 2 (RP2350, Dual ARM Cortex-M33 @ 150MHz)
- **ADC**: 12-bit, 4 channels (ADC0-ADC3, GPIO26-29), 500ksps
- **PC App**: Python (serial + CLI/CSV)
- **Communication**: USB CDC Serial

### Git
- **Feature branches required** — No direct push to `main`
- **Conventional Commits** format
- **`.agent/` and `AGENTS.md` must NEVER be pushed**
- **Commit messages must read like natural human writing**

## AI Footprint Concealment

Remove all traces of AI generation from public repository artifacts:
- README.md: User-facing information only
- Commit messages: Natural and specific
- Code comments: Natural developer style
- No references to `.agent/`, "AI", "agent", "LLM"

## Detailed Documentation

- Project Rules: `.agent/docs/PROJECT_RULES.md`
- Behavior Rules: `.agent/skills/agent-behavior-rules/SKILL.md`
- Hardware Reference: `.agent/docs/HARDWARE_REFERENCE.md`
- Pin Mapping: `.agent/docs/PIN_MAPPING.md`
