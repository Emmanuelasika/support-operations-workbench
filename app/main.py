"""SupportOps Copilot: an internal investigation workflow, never an auto-reply bot.

The application stores only redacted case evidence. Every state transition is
audited and no endpoint sends customer-facing communication.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

app = FastAPI(title="SupportOps Copilot", version="1.0.0")
DATABASE = Path(__file__).parent.parent / "supportops.sqlite3"
SECRET = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]+|(?:api[_-]?key|password|token)\s*[:=]\s*\S+)\b", re.I)
Area = Literal["access", "billing", "technical", "security"]
Status = Literal["new", "investigating", "awaiting_approval", "resolved"]


class CaseInput(BaseModel):
    subject: str = Field(min_length=4, max_length=160)
    description: str = Field(min_length=8, max_length=4_000)
    area: Area
    customer_impact: Literal["low", "medium", "high"] = "medium"
    request_id: str | None = Field(default=None, max_length=120)
    environment: Literal["development", "staging", "production", "unknown"] = "unknown"


class TransitionInput(BaseModel):
    status: Status
    actor: str = Field(min_length=2, max_length=80)
    note: str = Field(min_length=2, max_length=1_000)


class AssignmentInput(BaseModel):
    assignee: str = Field(min_length=2, max_length=80)
    actor: str = Field(min_length=2, max_length=80)


ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"investigating", "resolved"}),
    "investigating": frozenset({"awaiting_approval", "resolved"}),
    "awaiting_approval": frozenset({"investigating", "resolved"}),
    "resolved": frozenset(),
}
RUNBOOKS = {
    "access": {"title": "Access and entitlement", "steps": ["Verify identity without requesting credentials.", "Confirm project membership and role.", "Capture the correlation ID and UTC timestamp."]},
    "billing": {"title": "Billing state investigation", "steps": ["Identify the account and invoice reference.", "Compare payment and entitlement state.", "Escalate corrections through an approved billing workflow."]},
    "technical": {"title": "Technical reproduction", "steps": ["Create a minimal sanitized reproduction.", "Capture status, request ID, and timing.", "Compare a successful and failed request."]},
    "security": {"title": "Security escalation", "steps": ["Stop routine troubleshooting.", "Preserve minimum necessary evidence.", "Route to the security response owner."]},
}


def now() -> str:
    return datetime.now(UTC).isoformat()


def redact(text: str) -> str:
    return SECRET.sub("[REDACTED]", text)


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(DATABASE)
    database.row_factory = sqlite3.Row
    try:
        yield database
        database.commit()
    finally:
        database.close()


def initialize() -> None:
    with connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, area TEXT NOT NULL,
                risk TEXT NOT NULL, status TEXT NOT NULL, subject TEXT NOT NULL,
                description TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS case_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,
                actor TEXT NOT NULL, action TEXT NOT NULL, note TEXT NOT NULL,
                created_at TEXT NOT NULL, FOREIGN KEY(case_id) REFERENCES cases(id)
            );
            CREATE INDEX IF NOT EXISTS idx_cases_area ON cases(area);
            CREATE INDEX IF NOT EXISTS idx_audit_case ON case_audit(case_id, id);
        """)
        # Migration for the earlier portfolio prototype. SQLite cannot add a
        # NOT NULL column without a default, so legacy rows retain NULLs while
        # all new writes use the complete contract below.
        existing = {row[1] for row in db.execute("PRAGMA table_info(cases)")}
        for column, definition in {
            "fingerprint": "TEXT", "status": "TEXT DEFAULT 'new'",
            "subject": "TEXT", "description": "TEXT", "updated_at": "TEXT",
            "priority": "TEXT DEFAULT 'P3'", "assignee": "TEXT",
            "due_at": "TEXT", "request_id": "TEXT", "environment": "TEXT DEFAULT 'unknown'",
        }.items():
            if column not in existing:
                db.execute(f"ALTER TABLE cases ADD COLUMN {column} {definition}")


def risk_for(case: CaseInput) -> str:
    content = f"{case.subject} {case.description}".lower()
    is_security_incident = case.area == "security" or any(word in content for word in ("breach", "compromised", "unauthorized", "leak"))
    return "critical" if is_security_incident or case.customer_impact == "high" else "standard"


def priority_for(case: CaseInput, risk: str) -> str:
    if risk == "critical": return "P1"
    if case.environment == "production" or case.customer_impact == "medium": return "P2"
    return "P3"


def due_at_for(priority: str, created_at: datetime) -> str:
    hours = {"P1": 1, "P2": 8, "P3": 24}[priority]
    return (created_at + timedelta(hours=hours)).isoformat()


def investigation_for(area: Area) -> str:
    return {
        "access": "Verify identity and entitlement state; capture a correlation ID, never credentials.",
        "billing": "Identify the invoice or payment reference and verify account state before proposing a correction.",
        "technical": "Collect a minimal reproduction, UTC timestamp, request ID, and sanitized error response.",
        "security": "Stop routine troubleshooting and route minimum necessary evidence to the security response process.",
    }[area]


def row_to_case(row: sqlite3.Row) -> dict[str, object]:
    return {"id": row["id"], "fingerprint": row["fingerprint"], "area": row["area"], "risk": row["risk"], "priority": row["priority"], "status": row["status"], "assignee": row["assignee"], "due_at": row["due_at"],
            "safe_case": {"subject": row["subject"], "description": row["description"]}, "created_at": row["created_at"], "updated_at": row["updated_at"],
            "request_id": row["request_id"], "environment": row["environment"], "investigation": investigation_for(row["area"]), "runbook": RUNBOOKS[row["area"]], "requires_human_approval": True,
            "customer_message": "Not generated: communication is owned by an approved human workflow."}


@app.get("/health")
def health() -> dict[str, str]:
    initialize()
    return {"status": "ok", "customer_messaging": "human_approval_required", "data_policy": "redacted_evidence_only"}


@app.post("/api/cases", status_code=201)
def create_case(case: CaseInput) -> dict[str, object]:
    initialize()
    safe_subject, safe_description = redact(case.subject), redact(case.description)
    fingerprint = hashlib.sha256(f"{case.area}|{safe_subject}|{safe_description}".encode()).hexdigest()[:12]
    case_id, created_at, risk = f"case_{uuid4().hex[:12]}", now(), risk_for(case)
    priority = priority_for(case, risk)
    due_at = due_at_for(priority, datetime.fromisoformat(created_at))
    with connection() as db:
        db.execute(
            """INSERT INTO cases
            (id, fingerprint, area, risk, priority, status, subject, description, created_at, updated_at, due_at, request_id, environment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (case_id, fingerprint, case.area, risk, priority, "new", safe_subject, safe_description, created_at, created_at, due_at, redact(case.request_id) if case.request_id else None, case.environment),
        )
        db.execute("INSERT INTO case_audit (case_id, actor, action, note, created_at) VALUES (?, ?, ?, ?, ?)", (case_id, "system", "created", "Case created from sanitized intake.", created_at))
        row = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    return row_to_case(row)


@app.get("/api/cases")
def list_cases(status: Status | None = None, area: Area | None = None, limit: int = Query(default=50, ge=1, le=100)) -> dict[str, object]:
    initialize()
    clauses, values = [], []
    if status: clauses.append("status = ?"); values.append(status)
    if area: clauses.append("area = ?"); values.append(area)
    query = "SELECT * FROM cases" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY updated_at DESC LIMIT ?"
    with connection() as db:
        rows = db.execute(query, (*values, limit)).fetchall()
    return {"cases": [row_to_case(row) for row in rows]}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict[str, object]:
    initialize()
    with connection() as db:
        row = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        audits = db.execute("SELECT actor, action, note, created_at FROM case_audit WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
    if not row: raise HTTPException(404, "Case not found")
    return {**row_to_case(row), "audit": [dict(audit) for audit in audits]}


@app.post("/api/cases/{case_id}/transitions")
def transition_case(case_id: str, transition: TransitionInput) -> dict[str, object]:
    initialize()
    safe_note = redact(transition.note)
    with connection() as db:
        row = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if not row: raise HTTPException(404, "Case not found")
        if transition.status not in ALLOWED_TRANSITIONS[row["status"]]:
            raise HTTPException(409, f"Invalid transition: {row['status']} -> {transition.status}")
        db.execute("UPDATE cases SET status = ?, updated_at = ? WHERE id = ?", (transition.status, now(), case_id))
        db.execute("INSERT INTO case_audit (case_id, actor, action, note, created_at) VALUES (?, ?, ?, ?, ?)", (case_id, transition.actor, f"status:{transition.status}", safe_note, now()))
        updated = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    return row_to_case(updated)


@app.post("/api/cases/{case_id}/assignment")
def assign_case(case_id: str, assignment: AssignmentInput) -> dict[str, object]:
    initialize()
    with connection() as db:
        row = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if not row: raise HTTPException(404, "Case not found")
        updated_at = now()
        db.execute("UPDATE cases SET assignee = ?, updated_at = ? WHERE id = ?", (assignment.assignee, updated_at, case_id))
        db.execute("INSERT INTO case_audit (case_id, actor, action, note, created_at) VALUES (?, ?, ?, ?, ?)", (case_id, assignment.actor, "assigned", f"Assigned to {assignment.assignee}.", updated_at))
        updated = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    return row_to_case(updated)


@app.get("/api/cases/{case_id}/export", response_class=PlainTextResponse)
def export_case(case_id: str) -> str:
    detail = get_case(case_id)
    safe = detail["safe_case"]
    audit = "\n".join(f"- {item['created_at']} — {item['actor']}: {item['action']} — {item['note']}" for item in detail["audit"])
    return f"""# Support case `{detail['id']}`

| Field | Value |
| --- | --- |
| Status | {detail['status']} |
| Priority | {detail['priority']} |
| Risk | {detail['risk']} |
| Area | {detail['area']} |
| Assignee | {detail['assignee'] or 'Unassigned'} |
| Due | {detail['due_at']} |

## Safe case

**{safe['subject']}**

{safe['description']}

## Investigation

{detail['investigation']}

## Audit trail

{audit}
"""


@app.get("/api/runbooks")
def runbooks() -> dict[str, object]:
    return {"runbooks": RUNBOOKS}


@app.get("/api/insights")
def insights() -> dict[str, object]:
    initialize()
    with connection() as db:
        rows = db.execute("SELECT area, status, count(*) AS count FROM cases GROUP BY area, status ORDER BY count DESC, area").fetchall()
        recurring = db.execute("SELECT fingerprint, area, count(*) AS count FROM cases GROUP BY fingerprint, area HAVING count(*) > 1 ORDER BY count DESC LIMIT 20").fetchall()
        overdue = db.execute("SELECT count(*) FROM cases WHERE status != 'resolved' AND due_at < ?", (now(),)).fetchone()[0]
    return {"case_volume": [dict(row) for row in rows], "recurring_patterns": [dict(row) for row in recurring], "overdue_open_cases": overdue,
            "interpretation": "Use confirmed recurring patterns to create product issues; do not treat raw ticket volume as root-cause evidence."}


@app.get("/")
def home() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")
