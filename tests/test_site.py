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
    assert {"top", "what-it-does", "users", "workflow", "example", "case-study",
            "architecture", "quick-start", "safety", "limitations"} <= parser.ids
    assert "site.css" in parser.links
    assert "product.css" in parser.links
    assert "syntax.css" in parser.links
    assert (root / "docs/site.css").stat().st_size > 4_000


def test_pages_site_contains_a_real_case_and_safety_boundary():
    root = Path(__file__).parents[1]
    page = (root / "docs/index.html").read_text(encoding="utf-8")
    assert "case_92fd8c10b614" in page
    assert "[REDACTED]" in page
    assert "409 Conflict" in page
    assert "Not generated" in page
    assert "Emmanuel Asika" in page
    assert "Support Operations Workbench" in page
    assert "SupportOps Copilot" not in page
    assert "WHO IT IS FOR" in page
    assert "BEFORE PRODUCTION" in page
    assert "Case queue" in page
    assert "Lifecycle and audit" in page
    assert "Safe engineering handoff ready" in page
    assert 'class="badge p1"' in page
    for token_class in (
        "tok-prompt",
        "tok-command",
        "tok-flag",
        "tok-url",
        "tok-key",
        "tok-string",
        "tok-boolean",
        "tok-secret",
        "tok-redacted",
    ):
        assert token_class in page
    assert "code-unsafe" in page
    assert "code-safe" in page
    assert "code-terminal" in page
