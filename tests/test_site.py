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
    assert {"top", "intake", "triage", "investigation", "handoff", "architecture"} <= parser.ids
    assert "site.css" in parser.links
    assert (root / "docs/site.css").stat().st_size > 10_000


def test_pages_site_contains_a_real_case_and_safety_boundary():
    root = Path(__file__).parents[1]
    page = (root / "docs/index.html").read_text(encoding="utf-8")
    assert "CASE_92FD8C" in page
    assert "[REDACTED]" in page
    assert "409 CONFLICT" in page
    assert "Not generated" in page
    assert "Emmanuel Asika" in page
    assert "Support Operations Workbench" in page
    assert "SupportOps Copilot" not in page
