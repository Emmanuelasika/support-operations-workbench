# Architecture

```text
case intake ──► redaction ──► risk + priority + SLA
                                  │
                                  ▼
                         case state machine
                          │             │
                          ▼             ▼
                      audit trail   safe Markdown export
                          │
                          ▼
                recurring-pattern insights
```

## Invariants

- Only redacted case content and notes are stored.
- State transitions must follow the explicit state machine.
- Assignment and transition changes append audit events.
- Customer messaging is not implemented; every case advertises the human
  approval requirement.

SQLite is appropriate for the local reference implementation. A production
deployment needs authenticated tenancy, row-level authorization, durable backup,
retention controls, and monitored migrations.
