import pytest
from fastapi.testclient import TestClient

import app.main as main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE", tmp_path / "supportops.sqlite3")
    return TestClient(main.app)


def create_case(client, **overrides):
    payload = {"subject": "Webhook timeout", "description": "Timeout from the customer endpoint", "area": "technical"}
    payload.update(overrides)
    response = client.post("/api/cases", json=payload)
    assert response.status_code == 201
    return response.json()


def test_security_case_is_p1_and_redacted(client):
    brief = create_case(client, subject="Possible unauthorized access", description="Bearer sk_secret_is_here_123456 was exposed", area="security")
    assert brief["risk"] == "critical" and brief["priority"] == "P1"
    assert brief["requires_human_approval"] is True
    assert "sk_secret" not in str(brief)


def test_production_case_receives_p2_sla(client):
    brief = create_case(client, environment="production", customer_impact="low")
    assert brief["priority"] == "P2"
    assert brief["due_at"] > brief["created_at"]


def test_case_filter_and_detail_include_runbook(client):
    created = create_case(client, area="access", subject="Cannot login", description="403 after valid SSO sign-in")
    rows = client.get("/api/cases?area=access&status=new").json()["cases"]
    assert any(row["id"] == created["id"] for row in rows)
    assert client.get(f"/api/cases/{created['id']}").json()["runbook"]["steps"]


def test_transition_is_audited_and_redacted(client):
    created = create_case(client)
    moved = client.post(f"/api/cases/{created['id']}/transitions", json={"status": "investigating", "actor": "on-call", "note": "Checked Bearer sk_do_not_store_123456"})
    assert moved.status_code == 200
    detail = client.get(f"/api/cases/{created['id']}").json()
    assert detail["status"] == "investigating"
    assert "sk_do_not_store" not in str(detail["audit"])


def test_invalid_transition_is_rejected(client):
    created = create_case(client)
    response = client.post(f"/api/cases/{created['id']}/transitions", json={"status": "awaiting_approval", "actor": "agent", "note": "Skip state"})
    assert response.status_code == 409


def test_assignment_is_persisted_and_audited(client):
    created = create_case(client)
    assigned = client.post(f"/api/cases/{created['id']}/assignment", json={"assignee": "platform-support", "actor": "triage-lead"}).json()
    assert assigned["assignee"] == "platform-support"
    audit = client.get(f"/api/cases/{created['id']}").json()["audit"]
    assert audit[-1]["action"] == "assigned"


def test_markdown_export_contains_safe_case_and_audit(client):
    created = create_case(client, description="Failure with token=should-not-appear")
    export = client.get(f"/api/cases/{created['id']}/export")
    assert export.status_code == 200
    assert "# Support case" in export.text
    assert "should-not-appear" not in export.text


def test_insights_identify_recurring_fingerprint(client):
    create_case(client); create_case(client)
    insights = client.get("/api/insights").json()
    assert insights["recurring_patterns"][0]["count"] == 2


def test_unknown_case_returns_404(client):
    assert client.get("/api/cases/case_missing").status_code == 404
