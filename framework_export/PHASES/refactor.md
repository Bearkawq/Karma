# Refactor

- Phase purpose: improve structure without changing intent.
- Preferred active roles: `Builder`, `Scope Guard`.
- Preferred support roles: `Faultfinder`, `Scout`.
- Acceptable change size: moderate but staged.
- Common risks: drift, silent behavior change, validation gaps, diff sprawl.
- Escalation rules: escalate when file spread rises faster than validated benefit or regressions appear.
- Success shape: cleaner structure, same behavior, and controlled scope.
