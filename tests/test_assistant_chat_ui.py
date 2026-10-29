"""Conversation layout, composer and safe rendering of message content."""
from tests.test_web import clients, login, post
from backend.routers import assistant


def test_chat_empty_state_has_working_prompt_hooks_and_composer(clients):
    citizen, _, _ = clients
    login(citizen, 'citizen')
    page = citizen.get('/assistant', headers={'HX-Request': 'true'})
    assert page.status_code == 200
    assert 'class="chat-workspace"' in page.text
    assert 'aria-label="Conversation history"' in page.text
    assert 'How can I help you today?' in page.text
    assert 'data-chat-prompt="What is the status of my report?"' in page.text
    assert 'data-chat-composer' in page.text
    assert 'aria-label="Send message"' in page.text
    assert 'hx-post="/ui/assistant/chat"' in page.text
    assert 'hx-disabled-elt="find button[type=\'submit\']"' in page.text
    assert 'Thinking…' in page.text


def test_chat_bubbles_escape_content_and_keep_saved_conversation(clients, monkeypatch):
    async def answer(db, question, user=None, history=None):
        return {'answer': '<script>unsafe()</script>\nSecond line', 'mode': 'local_help',
                'warning': None, 'sources': [], 'tool_events': []}
    monkeypatch.setattr(assistant, 'answer_question', answer)
    citizen, _, _ = clients
    login(citizen, 'citizen')
    result = post(citizen, '/ui/assistant/chat', question='How do I submit a report?')
    assert result.status_code == 200
    assert 'chat-message-user' in result.text and 'chat-message-assistant' in result.text
    assert '&lt;script&gt;unsafe()&lt;/script&gt;' in result.text
    assert '<script>unsafe()</script>' not in result.text
    assert 'How can I help you today?' not in result.text
    assert 'aria-current="page"' in result.text
    assert 'name="session_id" value="' in result.text
    assert 'href="/assistant?session_id=' in result.text
