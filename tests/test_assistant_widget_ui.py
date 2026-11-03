"""Floating chat keeps private conversations separate from the current workspace page."""
from html.parser import HTMLParser
import re

import pytest

from tests.test_web import clients, login, post
from backend.routers import assistant


class Elements(HTMLParser):
    """Record rendered element ancestry without depending on template formatting."""

    def __init__(self, markup):
        super().__init__()
        self.elements = []
        self.stack = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.elements.append((tag, attrs, tuple(self.stack)))
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def find(self, tag=None, **attributes):
        return [(name, attrs, parents) for name, attrs, parents in self.elements
                if (tag is None or name == tag)
                and all(attrs.get(key.replace("_", "-")) == value for key, value in attributes.items())]


@pytest.mark.parametrize("index,role", [(0, "citizen"), (1, "admin"), (2, "response_team")])
def test_authenticated_header_keeps_notifications_and_floating_launcher_available(clients, index, role):
    client = clients[index]
    login(client, role)
    page = client.get("/dashboard")
    assert page.status_code == 200
    elements = Elements(page.text)
    notifications = elements.find("a", data_nav="updates")
    assert len(notifications) == 1
    _, notification, parents = notifications[0]
    assert notification["href"] == "/updates"
    assert notification["aria-label"] == "Notifications"
    assert any(tag == "header" for tag, _ in parents)
    assert not any(tag == "details" for tag, _ in parents)
    badge = elements.find(id="updates-count")
    assert len(badge) == 1
    assert any(tag == "a" and attrs.get("data-nav") == "updates" for tag, attrs in badge[0][2])
    assert not elements.find("a", data_nav="permissions")
    assert not elements.find("a", data_nav="assistant")
    launcher = elements.find("button", id="assistant-widget-launcher")
    assert len(launcher) == 1
    assert launcher[0][1]["aria-controls"] == "assistant-widget-panel"
    assert launcher[0][1]["aria-expanded"] == "false"
    assert len(elements.find(id="assistant-widget-content")) == 1


def test_widget_load_is_a_fragment_with_its_own_target(clients):
    citizen, _, _ = clients
    login(citizen, "citizen")
    page = citizen.get("/assistant?widget=1", headers={"HX-Request": "true"})
    assert page.status_code == 200
    assert "<html" not in page.text.lower()
    assert 'id="main-content"' not in page.text
    elements = Elements(page.text)
    form = elements.find("form", action="/ui/assistant/chat")[0][1]
    assert form["hx-target"] == "#assistant-widget-content"
    assert form["hx-push-url"] == "false"
    assert elements.find("input", name="widget", value="1")
    assert page.headers["HX-Push-Url"] == "false"
    assert page.headers["HX-Retarget"] == "#assistant-widget-content"
    assert page.headers["HX-Reswap"] == "innerHTML"
    assert "How can I help you today?" in page.text


def test_widget_chat_retains_history_without_changing_workspace_url_and_is_private(clients, monkeypatch):
    async def answer(db, question, user=None, history=None):
        return {"answer": "Widget answer: " + question, "mode": "local_fallback",
                "sources": [], "tool_events": [], "warning": None}

    monkeypatch.setattr(assistant, "answer_question", answer)
    citizen, admin, _ = clients
    login(citizen, "citizen")
    login(admin, "admin")
    first = post(citizen, "/ui/assistant/chat", widget="1", question="Where can I find shelter?")
    assert first.status_code == 200
    assert first.headers["HX-Push-Url"] == "false"
    assert first.headers["HX-Retarget"] == "#assistant-widget-content"
    session_id = re.search(r'name="session_id" value="(\d+)"', first.text).group(1)
    assert "Widget answer: Where can I find shelter?" in first.text
    second = post(citizen, "/ui/assistant/chat", widget="1", session_id=session_id,
                  question="More details please")
    assert second.status_code == 200
    assert second.headers["HX-Push-Url"] == "false"
    assert "Widget answer: Where can I find shelter?" in second.text
    assert "Widget answer: More details please" in second.text
    history_url = f"/assistant?widget=1&session_id={session_id}"
    restored = citizen.get(history_url, headers={"HX-Request": "true"})
    assert restored.status_code == 200
    assert "Widget answer: More details please" in restored.text
    denied = admin.get(history_url, headers={"HX-Request": "true"})
    assert denied.status_code == 404
    assert denied.headers["HX-Retarget"] == "#assistant-widget-content"
    assert "Widget answer:" not in denied.text
    own = admin.get("/assistant?widget=1", headers={"HX-Request": "true"})
    assert "Where can I find shelter?" not in own.text


def test_widget_validation_keeps_draft_and_stays_in_widget(clients):
    citizen, _, _ = clients
    login(citizen, "citizen")
    invalid = post(citizen, "/ui/assistant/chat", widget="1", question="x")
    assert invalid.status_code == 422
    assert "Enter a question between 2 and 2000 characters." in invalid.text
    assert invalid.headers["HX-Push-Url"] == "false"
    assert invalid.headers["HX-Retarget"] == "#assistant-widget-content"
    assert re.search(r'<textarea\b[^>]*\bname="question"[^>]*>x</textarea>', invalid.text)
    invalid_session = post(citizen, "/ui/assistant/chat", widget="1", session_id="invalid",
                           question="Keep this draft")
    assert invalid_session.status_code == 422
    assert "Choose a valid conversation." in invalid_session.text
    assert "Keep this draft" in invalid_session.text
    assert invalid_session.headers["HX-Retarget"] == "#assistant-widget-content"


def test_widget_obeys_sign_in_and_csrf_boundaries(clients):
    citizen, _, anonymous = clients
    anonymous.get("/login")
    denied = anonymous.get("/assistant?widget=1", headers={"HX-Request": "true"})
    assert denied.headers.get("HX-Redirect") == "/login"
    assert "data-chat-composer" not in denied.text
    not_signed_in = post(anonymous, "/ui/assistant/chat", widget="1", question="Shelter information")
    assert not_signed_in.headers.get("HX-Redirect") == "/login"
    login(citizen, "citizen")
    expired = citizen.post("/ui/assistant/chat", headers={"HX-Request": "true"},
                           data={"widget": "1", "question": "Shelter information", "_csrf": "invalid"})
    assert expired.status_code == 403
    assert "form expired" in expired.text


@pytest.mark.parametrize("query,headers", [
    ("session_id=42", {}),
    ("widget=1&session_id=42", {}),
    ("widget=1&session_id=42", {"HX-Request": "true", "X-ResQ-Bootstrap": "true"}),
    ("widget=1&session_id=42", {"HX-Request": "true", "HX-History-Restore-Request": "true"}),
])
def test_full_assistant_link_opens_dashboard_widget_instead_of_full_page(clients, query, headers):
    citizen, _, _ = clients
    login(citizen, "citizen")
    page = citizen.get("/assistant?" + query, headers=headers, follow_redirects=False)
    assert page.status_code == (200 if headers.get("HX-Request") == "true" else 303)
    destination = page.headers.get("HX-Redirect") or page.headers.get("Location")
    assert destination == "/dashboard?chat=1&session_id=42"
    assert "data-chat-composer" not in page.text
