# Playbooks - Reusable Workflows

Pre-defined action sequences for common scenarios.

## Available Playbooks

- **explore_codebase** - Scout a new codebase
- **implement_feature** - Build a new feature with tests
- **fix_bug** - Diagnose and fix a bug
- **refactor** - Safely refactor code
- **review_pr** - Review a pull request
- **run_tests** - Execute test suite
- **deploy** - Deploy application
- **migrate** - Migrate from one system to another
- **goose_task_types** - Mission classes for Goose as a permanent scout

## Usage

```python
from fleet.core.playbooks import get_playbook

playbook = get_playbook("implement_feature")
result = await playbook.execute(context)
```

See [goose_task_types.md](/home/mikoleye/karma/fleet/core/playbooks/goose_task_types.md) for the scout-specific mission classes and close rules.
