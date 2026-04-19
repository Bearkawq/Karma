# Fleet Core

The fleet core contains reusable orchestration logic and role behavior that all projects share.

## Directory Structure

- **bridge/** - Inter-process communication and event bridging
- **roles/** - Agent role definitions and behavior specs
- **dispatcher/** - Task distribution and worker allocation
- **routing/** - Request routing and target resolution
- **prompts/** - Shared prompt templates and system messages
- **playbooks/** - Reusable action sequences and workflows
- **policies/** - Global operating policies and constraints
- **shared_tools/** - Common tools available to all agents
- **shared_config/** - Configuration shared across projects

## Usage

All agents operating on any project use these core systems. The core is project-agnostic - it provides the infrastructure for coordination, while projects provide the specific context and rules.