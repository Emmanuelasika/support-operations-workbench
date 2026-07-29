from html.parser import HTMLParser
from pathlib import Path


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.add(attributes["id"])
        if tag in {"a", "link"}:
            self.links.append(attributes.get("href", ""))


def test_pages_site_has_complete_navigation_and_assets():
    root = Path(__file__).parents[1]
    parser = PageParser()
    parser.feed((root / "docs/index.html").read_text(encoding="utf-8"))
    assert {"top", "case-file", "sanitization", "ownership", "handoff",
            "run-it", "install-command"} <= parser.ids
    assert "site.css" in parser.links
    assert (root / "docs/site.css").stat().st_size > 18_000
    for asset in (
        "operations-command-desk.webp",
        "operations-paper-grid.webp",
        "safe-engineering-handoff.webp",
    ):
        assert (root / "docs/assets" / asset).stat().st_size > 40_000


def test_pages_site_contains_a_real_case_and_safety_boundary():
    root = Path(__file__).parents[1]
    page = (root / "docs/index.html").read_text(encoding="utf-8")
    assert "case_92fd8c10b614" in page
    assert "[REDACTED]" in page
    assert "409 Conflict" in page
    assert "No customer reply is generated or sent." in page
    assert "Emmanuel Asika" in page
    assert "Support Operations Workbench" in page
    assert "SupportOps Copilot" not in page
    assert "Open queue" in page
    assert "Activity ledger" in page
    assert "ENGINEERING BRIEF" in page
    assert "SLA 00:42:16" in page
    assert "Technical reproduction" in page
    assert "assets/operations-command-desk.webp" in page
    assert "assets/safe-engineering-handoff.webp" in page
    assert 'property="og:image"' in page
    assert 'class="line removed"' in page
    assert 'class="line added"' in page
    assert 'class="terminal"' in page
    assert "What this proves—and what it does not." in page
