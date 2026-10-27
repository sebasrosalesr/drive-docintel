import json

from docintel.ask import agent


def test_tool_loop_with_citation_audit(session):
    script = iter([
        {"choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "run_sql", "arguments": json.dumps({"sql": "SELECT fund, value, document_id, observation_id FROM v_observations WHERE metric='return' AND period_month=1 ORDER BY value DESC", "purpose": "january"})}}]}}], "usage": {"cost": 0.001}},
        {"choices": [{"message": {"content": "Best January: **Test Fund LP** at +2.14% [obs:1] [doc:1]. Also [obs:999]."}}], "usage": {"cost": 0.002}},
    ])
    res = agent.ask("Which fund had the best January return?", session=session, transport=lambda body: next(script))
    assert res["checked_against_data"] and len(res["steps"]) == 1 and res["steps"][0]["sql"].endswith("LIMIT 200")
    assert res["calls"] == 2 and abs(res["cost_usd"] - 0.003) < 1e-9
    assert "obs:999" in res["dropped_citations"] and "[unverified]" in res["answer"]


def test_bad_sql_is_returned_to_the_model_as_error(session):
    script = iter([
        {"choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "run_sql", "arguments": json.dumps({"sql": "DROP TABLE funds", "purpose": "evil"})}}]}}], "usage": {}},
        {"choices": [{"message": {"content": "I could not run that."}}], "usage": {}},
    ])
    res = agent.ask("drop everything", transport=lambda body: next(script))
    assert res["steps"][0]["error"].startswith("SQLRejected")


def test_answer_without_tools_is_marked_unchecked():
    res = agent.ask("hello", transport=lambda body: {"choices": [{"message": {"content": "Hi, there are 42 funds."}}], "usage": {}})
    assert res["checked_against_data"] is False and res["uncited_numbers"] is True


def test_events_are_emitted_in_order(session):
    script = iter([
        {"choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "run_sql", "arguments": json.dumps({"sql": "SELECT count(*) AS n, 1 AS document_id FROM v_observations", "purpose": "count"})}}]}}], "usage": {}},
        {"choices": [{"message": {"content": "There are rows [doc:1]."}}], "usage": {}},
    ])
    events = []
    res = agent.ask("how many?", session=session, transport=lambda body: next(script), on_event=events.append)
    kinds = [e["type"] for e in events]
    assert kinds[:2] == ["round", "status"] and "step" in kinds and kinds[-1] == "token"
    assert "".join(e["text"] for e in events if e["type"] == "token") == "There are rows [doc:1]."
    assert res["steps"][0]["row_count"] == 1
