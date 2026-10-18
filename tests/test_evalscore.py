from dbagent.evalscore import has_number, numbers_in, score_case


def test_number_parsing_handles_separators():
    assert 2411.0 in numbers_in("There were 2,411 orders")
    assert 2411.0 in numbers_in("There were 2 411 orders")
    assert 1234567.0 in numbers_in("Revenue 1,234,567 EUR")


def test_tolerance():
    assert has_number("about 1005", 1000, rel_tol=0.01)
    assert not has_number("about 1100", 1000, rel_tol=0.01)
    assert has_number("3.4 days", 3.4, abs_tol=0.06)


def test_score_case_passes_and_fails():
    case = {"truth_number": True, "forbid_tools": ["propose_change"]}
    assert score_case(case, "It is 42.", ["run_query"], 42, False) == []
    fails = score_case(case, "It is 41.", ["propose_change"], 42, False)
    assert any("forbidden" in f for f in fails) and any("expected number" in f for f in fails)


def test_text_and_not_contains_and_limit():
    case = {"truth_text": True, "answer_not_contains": ["@example.test"]}
    assert score_case(case, "Helsinki leads", [], "Helsinki", False) == []
    fails = score_case(case, "x@example.test", [], "Helsinki", True)
    assert len(fails) == 3
