# Policies - Global Operating Policies

Fleet-wide policies that constrain all operations.

## Active Policies

- **safety** - Safety constraints for code changes
- **security** - Security requirements
- **quality** - Code quality standards
- **communication** - How agents communicate
- **resource_limits** - Resource constraints

## Policy Enforcement

Policies are checked at:
- Task assignment time
- During execution (where possible)
- At handoff boundaries

## Override

Project-local policies in .fleet/local_rules.md can add restrictions but not override fleet policies.