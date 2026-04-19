# Prompts - System Prompt Templates

Shared prompt templates used across fleet operations.

## Categories

- **system/** - Core system prompts for each role
- **tasks/** - Task-specific prompt templates
- **context/** - Context injection prompts
- **handoff/** - Handoff communication prompts

## Goose Scout Templates

- [goose_scout_prompt.md](/home/mikoleye/karma/fleet/core/prompts/goose_scout_prompt.md)
- [goose_handoff_packet.md](/home/mikoleye/karma/fleet/core/prompts/goose_handoff_packet.md)

These templates constrain Goose into bounded reconnaissance work with a fixed final report and a builder-ready handoff schema.

## Usage

```python
from fleet.core.prompts import get_prompt

system_msg = get_prompt("builder", project_context=context)
```
