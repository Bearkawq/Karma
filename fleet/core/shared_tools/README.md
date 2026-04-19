# Shared Tools

Tools available to all agents regardless of project context.

## Categories

- **file_ops/** - File read, write, search operations
- **code_analysis/** - Static analysis, AST parsing
- **git_ops/** - Git operations
- **shell/** - Shell command execution
- **search/** - Code and content search
- **transform/** - Code transformation utilities

## Usage

```python
from fleet.core.shared_tools import file_ops, search

results = search.grep(pattern="TODO", path=project_root)
```