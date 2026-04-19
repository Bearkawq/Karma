# Recovery Index

| Name | Use | Who Uses It | Status |
| --- | --- | --- | --- |
| Rollback Steps | back out from a bad direction cleanly | Builder, Helper | active |
| Low Confidence Recovery | recover from uncertain handoffs or guesses | Checker, Scout | active |
| Repeat Regression Response | respond when the same breakage returns | Checker, Helper | active |
| Unclear Root Cause Drill | force tighter diagnosis before more edits | Checker | active |

## Rollback Steps
- stop adding new changes
- identify the last known good point
- undo only the bad direction
- re-enter with a smaller patch

## Low Confidence Recovery
- write down what is known
- write down what is assumed
- verify one assumption before moving
- downgrade the handoff if uncertainty stays high

## Repeat Regression Response
- compare current failure to the previous one
- find the shared file, path, or missed check
- require a focused fix and a stronger check

## Unclear Root Cause Drill
- state the failure in one sentence
- list rejected explanations
- pick the next most testable check
- do not patch until the cause is narrower
