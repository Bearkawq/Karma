# Goose Handoff Packet

Use this exact schema when Goose prepares work for a builder or operator.

```md
## TASK TITLE
<short concrete task>

## OBJECTIVE
<what should be done next>

## LIKELY FILES INVOLVED
- path

## WHY THIS MATTERS
<impact in one or two sentences>

## CONFIDENCE
<high|medium|low>

## BLOCKERS / RISKS
- blocker or risk

## SUGGESTED VALIDATION
- command
- check

## RECOMMENDED NEXT WORKER
<builder|checker|operator|planner>
```

## Rules
- Keep one packet per task candidate
- Prefer direct file paths over vague area names
- Do not mix multiple unrelated tasks into one packet
- If the evidence is weak, say so in `CONFIDENCE` and `BLOCKERS / RISKS`
- If no builder action is justified yet, do not emit a packet
