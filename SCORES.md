# SCORES.md — Performance Memory

*Compact role fitness tracking. Update after each significant work chunk.*

---

## Agent: OpenCode

| Role | Fitness | Notes |
|------|---------|-------|
| Builder | 0.85 | Strong implementation, good diff control |
| Surgeon | 0.80 | Precise changes when needed |
| Dreamer | 0.65 | Good ideas but needs Validator |
| Stabilizer | 0.60 | Can recover but prefers building |

**Recent Failures**: None recent
**Rework Rate**: Low (10%)
**Confidence Trend**: Stable
**Domain Fit**: Code implementation, Python strong

---

## Agent: Codex

| Role | Fitness | Notes |
|------|---------|-------|
| Faultfinder | 0.90 | Strong error detection, thorough |
| Validator | 0.85 | Good idea screening |
| Scope Guard | 0.70 | Noticing drift, prefer进攻 |
| Builder | 0.50 | Prefers finding bugs to writing code |

**Recent Failures**: None
**Rework Rate**: Very low (5%)
**Confidence Trend**: Rising
**Domain Fit**: Debugging, testing, validation

---

## Agent: Goose/Qwen

| Role | Fitness | Notes |
|------|---------|-------|
| Scout | 0.90 | Excellent terrain mapping |
| Forecaster | 0.80 | Good phase prediction |
| Stabilizer | 0.65 | Can recover but slower |
| Builder | 0.55 | Prefers exploration |

**Recent Failures**: None
**Rework Rate**: Low
**Confidence Trend**: Stable
**Domain Fit**: Discovery, context gathering

---

## Scoring Notes

- Fitness: 0.0-1.0 scale
- Recent failures: list last 3
- Rework rate: % of code that needed revision
- Confidence trend: rising/stable/falling
- Domain fit: what the agent is naturally good at
- Decay: Favor recent performance over old

---

## Recency Decay
Scores favor last 10 work chunks. Older performance has diminishing weight.

---
*Manually editable. Update after phase completion or significant handoff.*