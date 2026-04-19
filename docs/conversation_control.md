# Conversation Control Spec

Behavioral contract for Karma's turn routing and follow-up handling.

## Turn Classes (precedence order)

| Priority | Class | Route | Example |
|----------|-------|-------|---------|
| 1 | **introspection** | respond_only | "what is the current topic", "show active artifacts" |
| 2 | **follow-up/reference** | resolve then act | "the second one", "that file", "those results" |
| 3 | **continuation** | retrieve_and_respond | "go on", "continue", "more" |
| 4 | **summary_request** | retrieve_and_respond | "summarize that", "sum it up" |
| 5 | **explicit command** | act_and_report | "list files in core", "search files *.py" |
| 6 | **question** | respond_only or act | "can you list files" (question-shaped command) |
| 7 | **clarification_answer** | respond_only | "yes", "nope" (after agent asked) |
| 8 | **correction** | ask_clarification | "no, the other one", "i meant X" |
| 9 | **statement** | respond_only | general statements |
| 10 | **empty** | respond_only | no input |

## Current-Subject Model

The agent tracks:
- `current_topic` — last inferred topic from user input or entities
- `previous_topic` — topic before the current one
- `last_subject` — last concrete entity (filename, path, name)
- `active_thread` — thread being actively discussed
- `artifact_ledger` — ordered list of observed artifacts (files, results)
- `answer_fragments` — recent structured answer segments

## Follow-Up Resolution Order

When the user says "the second one", "that file", etc.:

1. Check `active_options` (from compare/choice contexts)
2. Check `artifact_ledger` (filtered for junk: __pycache__, .git, .venv, etc.)
3. Check `active_thread` topic
4. Check `current_topic`
5. If nothing resolves: ask specific clarification ("Which folder do you mean?")

## Clarification Policy

- Never fall back to generic help text for unresolved references
- Ask a specific question naming the referent type: "Which folder/file/result?"
- Include recent items if available: "Recent items: planner.py, retrieval.py"
- Track clarification failures as scars for future routing bias

## Introspection Commands

These bypass intent parsing entirely:

| Input pattern | Returns |
|---------------|---------|
| "current topic" / "active topic" | current + previous topic |
| "active artifacts" / "show artifacts" | artifact ledger (last 8) |
| "active thread" / "show thread" | thread topic, state, recent episodes |
| "unresolved references" | list of unresolved refs |
| "conversation state" | full state summary |

## Fallback Policy

1. Dialogue handler (introspection, clarification, continuation, summary)
2. Question-shaped command rescue (score >= 0.32, lowered by scars)
3. Responder: learned patterns > knowledge recall > base templates
4. Never silent — always produce a response

## Scar-Biased Routing

Scars from past failures adjust routing:
- `question_command_swallow`: lowers command-signal threshold for questions
- `unresolved_reference`: increases clarification priority

## Pronoun Resolution

- Only applied for intent-parsed paths (commands, questions)
- Skipped for dialogue-handled acts (corrections, continuations, summaries)
- This prevents mangling of references before the dialogue handler resolves them
