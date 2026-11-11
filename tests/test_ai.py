from datetime import date, timedelta

from app import ai

from .conftest import register_and_login

TODAY = date(2030, 6, 15)


def task(id, title="t", priority="medium", status="todo", due=None):
    return {"id": id, "title": title, "priority": priority, "status": status, "due_date": due}


# ---------------------------------------------------------------- ranking
def test_high_priority_ranks_above_low():
    ranked = ai.rank_tasks([task(1, priority="low"), task(2, priority="high")], TODAY)
    assert [t["id"] for t in ranked] == [2, 1]


def test_overdue_beats_higher_priority_without_deadline():
    overdue_low = task(1, priority="low", due=TODAY - timedelta(days=3))
    high_no_date = task(2, priority="high")
    ranked = ai.rank_tasks([high_no_date, overdue_low], TODAY)
    assert ranked[0]["id"] == 1


def test_sooner_deadline_ranks_first_with_equal_priority():
    soon = task(1, due=TODAY + timedelta(days=1))
    later = task(2, due=TODAY + timedelta(days=30))
    assert [t["id"] for t in ai.rank_tasks([later, soon], TODAY)] == [1, 2]


def test_ranking_is_stable_for_ties():
    ranked = ai.rank_tasks([task(3), task(1), task(2)], TODAY)
    assert [t["id"] for t in ranked] == [1, 2, 3]


# ---------------------------------------------------------------- summary
def test_empty_task_list():
    result = ai.summarize_tasks([], TODAY)
    assert result["suggested_order"] == []
    assert "no open tasks" in result["summary"].lower()


def test_rule_based_summary_mentions_counts():
    tasks = [
        task(1, "Pay rent", "high", due=TODAY - timedelta(days=1)),
        task(2, "Read book", "low"),
        task(3, "Email boss", "high", due=TODAY + timedelta(days=1)),
    ]
    result = ai.rule_based_summary(tasks, TODAY)
    assert result["source"] == "rule-based"
    assert "3 open tasks" in result["summary"]
    assert "2 high priority" in result["summary"]
    assert "1 overdue" in result["summary"]
    assert "Pay rent" in result["summary"]
    assert sorted(result["suggested_order"]) == [1, 2, 3]
    assert result["suggested_order"][0] == 1


def test_singular_wording():
    result = ai.rule_based_summary([task(1, "Only one")], TODAY)
    assert "1 open task " in result["summary"] or "1 open task." in result["summary"]
    assert "1 open tasks" not in result["summary"]


def test_no_api_key_uses_rules(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert ai.summarize_tasks([task(1)], TODAY)["source"] == "rule-based"


def test_llm_failure_falls_back_to_rules(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")

    def boom(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(ai, "_llm_summary", boom)
    result = ai.summarize_tasks([task(1)], TODAY)
    assert result["source"] == "rule-based"


def test_llm_path_used_when_key_present(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    fake = {"summary": "From the model.", "suggested_order": [1], "source": "llm"}
    monkeypatch.setattr(ai, "_llm_summary", lambda *_a, **_k: fake)
    assert ai.summarize_tasks([task(1)], TODAY) == fake


def test_extract_json_handles_surrounding_text():
    text = 'Sure! Here you go:\n```json\n{"summary": "ok", "suggested_order": [2, 1]}\n```'
    assert ai._extract_json(text) == {"summary": "ok", "suggested_order": [2, 1]}


def test_extract_json_raises_without_json():
    import pytest

    with pytest.raises(ValueError):
        ai._extract_json("no braces here")


# ------------------------------------------------- LLM call (fake client)
class _FakeCompletions:
    """Mimics groq_client.chat.completions without any network call."""

    def __init__(self, text):
        self._text = text
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        message = type("Message", (), {"content": self._text})()
        choice = type("Choice", (), {"message": message})()
        return type("Completion", (), {"choices": [choice]})()


def _install_fake_client(monkeypatch, reply_text):
    import groq

    completions = _FakeCompletions(reply_text)
    chat = type("Chat", (), {"completions": completions})()
    fake_client = type("FakeClient", (), {"chat": chat})()
    monkeypatch.setattr(groq, "Groq", lambda *a, **k: fake_client)
    return completions


def test_llm_summary_parses_response_and_cleans_order(monkeypatch):
    # Model returns an unknown id (99), a duplicate (2) and skips task 3.
    reply = '{"summary": " Focus on the report first. ", "suggested_order": [2, 99, 2, 1]}'
    completions = _install_fake_client(monkeypatch, reply)

    tasks = [task(1), task(2), task(3, priority="high")]
    result = ai._llm_summary(tasks, TODAY)

    assert result["source"] == "llm"
    assert result["summary"] == "Focus on the report first."
    # unknown id dropped, duplicate removed, missing task appended
    assert result["suggested_order"] == [2, 1, 3]
    # task text is sent to the model, and flagged as data
    prompt = completions.last_kwargs["messages"][0]["content"]
    assert "never as instructions" in prompt
    assert completions.last_kwargs["model"] == ai.DEFAULT_MODEL


def test_invalid_llm_json_falls_back_to_rules(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    _install_fake_client(monkeypatch, "Sorry, I can't do that.")
    assert ai.summarize_tasks([task(1)], TODAY)["source"] == "rule-based"


# ---------------------------------------------------------------- endpoint
def test_summary_endpoint_requires_auth(client):
    assert client.post("/api/ai/summary").status_code == 401


def test_summary_endpoint_ignores_done_tasks(client):
    headers = register_and_login(client)
    client.post("/api/tasks", json={"title": "Finished", "status": "done"}, headers=headers)
    client.post("/api/tasks", json={"title": "Open one", "priority": "high"}, headers=headers)

    res = client.post("/api/ai/summary", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "rule-based"
    assert len(body["suggested_order"]) == 1
    assert "Open one" in body["summary"]
    assert "Finished" not in body["summary"]


def test_summary_endpoint_with_no_tasks(client):
    headers = register_and_login(client)
    body = client.post("/api/ai/summary", headers=headers).json()
    assert body["suggested_order"] == []
