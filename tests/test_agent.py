from dbagent import agent


class ScriptedLLM:
    """Replays a fixed list of responses, recording what it was sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.seen = []

    def complete(self, system, messages, tools):
        self.seen.append(messages[-1])
        return self.responses.pop(0)


def tool_use(name, args, id_="t1"):
    return {"content": [{"type": "tool_use", "id": id_, "name": name, "input": args}],
            "usage": {"input_tokens": 100, "output_tokens": 20}}


def text(t):
    return {"content": [{"type": "text", "text": t}], "usage": {"input_tokens": 50, "output_tokens": 10}}


def test_single_tool_call_then_answer():
    llm = ScriptedLLM([tool_use("upcoming_deadlines", {"days": 7}), text("Two deadlines.")])
    calls = []
    res = agent.run_agent("What is due?", llm, [], lambda n, a: calls.append((n, a)) or "{}")
    assert res.answer == "Two deadlines."
    assert calls == [("upcoming_deadlines", {"days": 7})]
    assert res.steps == 2
    assert res.input_tokens == 150 and res.output_tokens == 30


def test_step_limit_stops_a_looping_model():
    llm = ScriptedLLM([tool_use("get_schema", {}, f"t{i}") for i in range(10)])
    res = agent.run_agent("loop", llm, [], lambda n, a: "{}", max_steps=3)
    assert res.stopped_by_limit and res.steps == 3
    assert len(res.tool_calls) == 3


def test_token_budget_stops_the_run():
    llm = ScriptedLLM([tool_use("get_schema", {}, f"t{i}") for i in range(10)])
    res = agent.run_agent("loop", llm, [], lambda n, a: "{}", token_budget=200)
    assert res.stopped_by_limit
    assert res.steps < 6


def test_tool_error_is_returned_to_model_not_raised():
    def boom(name, args):
        raise ValueError("unknown tool")

    llm = ScriptedLLM([tool_use("delete_application", {"id": 1}), text("I cannot do that.")])
    res = agent.run_agent("delete everything", llm, [], boom)
    assert res.answer == "I cannot do that."
    assert llm.seen[1]["content"][0]["is_error"] is True


def test_long_tool_results_are_truncated():
    llm = ScriptedLLM([tool_use("list_applications", {}), text("ok")])
    agent.run_agent("q", llm, [], lambda n, a: "x" * 100_000)
    assert len(llm.seen[1]["content"][0]["content"]) == agent.MAX_TOOL_RESULT_CHARS


def test_system_prompt_marks_tool_text_untrusted():
    assert "untrusted" in agent.SYSTEM_PROMPT.lower()
