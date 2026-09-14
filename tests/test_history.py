"""The transcript bookkeeping that keeps a session replayable.

`climate.ask_claude` drives the tool-calling loop, so these two helpers are what
stand between a tool round that got cut short (recursion limit) and a 400 on the
next question.
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from climate_agent import climate


def _q(text: str) -> HumanMessage:
    return HumanMessage(text)


def _a(text: str) -> AIMessage:
    return AIMessage(text)


def _tool_use(sql: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "query_rankings", "args": {"sql": sql}, "id": "t1"}],
    )


def _tool_result() -> ToolMessage:
    return ToolMessage(content="rows", tool_call_id="t1")


def test_a_finished_turn_survives_intact():
    messages = [
        _q("where is best?"),
        _tool_use("SELECT 1"),
        _tool_result(),
        _a("Lima."),
    ]
    assert climate._committable(messages) == messages


def test_a_turn_cut_off_mid_tool_round_is_dropped():
    """The recursion limit can end the loop with a tool call nothing answered."""
    committable = climate._committable(
        [
            _q("where is best?"),
            _a("Lima."),
            _q("and in the shade?"),
            _tool_use("SELECT 2"),
            _tool_result(),
        ]
    )
    assert committable == [_q("where is best?"), _a("Lima.")]


def test_a_transcript_that_never_closes_commits_nothing():
    assert climate._committable([_q("hi"), _tool_use("SELECT 1")]) == []


def test_trimming_drops_whole_turns_not_halves_of_them():
    turns = []
    for i in range(30):
        turns += [_q(f"q{i}"), _tool_use("SELECT 1"), _tool_result()]
        turns += [_a(f"a{i}")]

    trimmed = climate._trim_session(turns)

    assert len(trimmed) <= climate.MAX_SESSION_MESSAGES
    # A tool result must never lead: it would reference a tool call that is gone.
    assert climate._is_question(trimmed[0])
    assert trimmed[-1] == turns[-1], "the newest turn is the one that is kept"


def test_a_short_session_is_left_alone():
    messages = [_q("q"), _a("a")]
    assert climate._trim_session(messages) == messages


def test_sql_of_last_turn_reads_only_the_current_turn():
    messages = [
        HumanMessage("first"),
        AIMessage(
            "",
            tool_calls=[
                {"name": "query_rankings", "args": {"sql": "SELECT 1"}, "id": "a"}
            ],
        ),
        ToolMessage("1", tool_call_id="a"),
        AIMessage("one"),
        HumanMessage("second"),
        AIMessage(
            "",
            tool_calls=[
                {"name": "query_rankings", "args": {"sql": "SELECT 2"}, "id": "b"},
                {"name": "read_methodology", "args": {"section": ""}, "id": "c"},
            ],
        ),
        ToolMessage("2", tool_call_id="b"),
        ToolMessage("doc", tool_call_id="c"),
        AIMessage("two"),
    ]
    assert climate.sql_of_last_turn(messages) == ["SELECT 2"]
    assert climate.sql_of_last_turn([]) == []
