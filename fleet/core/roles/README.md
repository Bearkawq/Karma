# Roles - Agent Role Definitions

Fleet defines standard roles that agents can assume. Each role has specific responsibilities and behavioral patterns.

## Available Roles

- **planner** - Breaks down complex tasks into steps, creates execution plans
- **builder** - Implements code, builds systems according to specs
- **checker** - Reviews work, validates correctness and quality
- **scout** - Explores codebases, finds relevant files and patterns
- **goose_scout** - Permanent scout discipline for Goose: reconnaissance, task extraction, risk spotting, and builder handoff packets
- **surgeon** - Makes precise surgical changes to code
- **stabilizer** - Fixes bugs, resolves issues, improves reliability
- **scope_guard** - Enforces boundaries, prevents over-engineering
- **validator** - Runs tests, verifies outputs, ensures requirements met
- **dreamer** - Brainstorms ideas, proposes creative solutions
- **forecaster** - Estimates effort, predicts outcomes, assesses risks
- **faultfinder** - Identifies problems, finds bugs, spots issues
- **helper** - Assists other agents, provides support

## Role Behavior

Each role is defined by:
- Primary responsibility
- Available tools/permissions
- Decision-making scope
- Communication patterns

## Usage

```yaml
role: builder
context:
  project: nexus
  rules:
    - "Write tests before code"
    - "No breaking changes"
```

See ROLES/ directory in karma root for detailed role specs.
See [goose_scout.md](/home/mikoleye/karma/fleet/core/roles/goose_scout.md) for the permanent Goose scout contract.
