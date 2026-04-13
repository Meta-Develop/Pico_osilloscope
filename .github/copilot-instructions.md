# Copilot Instructions — Pico Oscilloscope

## Project Overview

Pico Oscilloscope: Raspberry Pi Pico 2 (RP2350) を使った簡易オシロスコープ。
ハットモード（別 Pico 2 の全 GPIO ピンを監視）と通常オシロスコープモードの 2 モード。
AI Agent による自律的なハードウェアデバッグを実現するためのツール。

## Coding Delegation Rules (MANDATORY)

```
BLOOD RULE — COST-AWARE DELEGATION:
コーディングはデフォルトで GPT-5.4 に委譲すること。
Opus 4.6 はアーキテクト + レビュアーのみ。
自分でコードを書くのは最後の手段。
```

### Agent Role Assignment

| Agent | Role | Invocation |
|-------|------|------------|
| **Opus 4.6** (Chat) | Design, Review, Orchestration | VS Code Copilot Chat |
| **Copilot CLI** (Codex) | Implementation, Tests, Refactoring | `copilot --model gpt-5.4 -p "..."` |
| **Gemini CLI** | Design Discussion, Brainstorming | `gemini --model gemini-3.1 "..."` |

### Workflow

1. ユーザーからタスクを受領
2. Opus がコンテキストを読み計画
3. 設計判断 → Gemini CLI に相談
4. コーディング → Copilot CLI (GPT-5.4) に委譲
5. Opus が出力をレビュー (コンパイル, ロジック検証)
6. 問題があれば修正 or 再委譲
7. 完了時に簡潔に報告

## Absolute Rules

### Blood Rules
1. **検証済みの動作コードを再検証なしに変更しない**
2. **技術的な値を省略しない** (Hex, ピン番号, レジスタ等)
3. **ハードウェアを疑う前にすべてのソフトウェア原因を排除する**
4. **公開成果物に AI フットプリントを残さない**

### Technical Constraints
- **MCU**: Raspberry Pi Pico 2 (RP2350, Dual ARM Cortex-M33 @ 150MHz, 520KB SRAM)
- **SDK**: Pico SDK (C/C++)
- **ADC**: 12-bit, 4 チャンネル (GPIO26-29), 500ksps
- **PC App**: Python (シリアル通信 + GUI)
- **通信**: USB シリアル (CDC)

### Git
- **フィーチャーブランチ必須** — `main` への直接 push 禁止
- **Conventional Commits** 形式
- **`.agent/` と `AGENTS.md` は絶対に push しない**
- **コミットメッセージは自然な人間が書いたように**

## AI Footprint Concealment

公開リポジトリの成果物から AI 生成の痕跡をすべて排除:
- README.md: ユーザー向け情報のみ
- コミットメッセージ: 自然で具体的
- コードコメント: 自然な開発者スタイル
- `.agent/`, "AI", "agent", "LLM" への参照禁止

## Detailed Documentation

- Project Rules: `.agent/docs/PROJECT_RULES.md`
- Behavior Rules: `.agent/skills/agent-behavior-rules/SKILL.md`
- Hardware Reference: `.agent/docs/HARDWARE_REFERENCE.md`
- Pin Mapping: `.agent/docs/PIN_MAPPING.md`
