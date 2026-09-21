import pytest

from tap.messages import ToolResultMessage


@pytest.fixture
def assert_no_orphaned_tool_calls():
    """Ensure every tool call has exactly one matching ToolResultMessage.

    An orphaned call (present in a request but missing its result) causes the next
    provider request to be rejected.
    """

    def _check(messages) -> None:
        resolved = {
            m.tool_call_id for m in messages
            if isinstance(m, ToolResultMessage)
        }
        for msg in messages:
            for call in getattr(msg, "tool_calls", None) or ():
                assert call.id in resolved, f"orphaned tool_call: {call.id!r}"
    return _check
