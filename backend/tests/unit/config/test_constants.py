from agentdrops.config.constants import CHAT_TITLE_MAX_LENGTH, truncate_title


def test_truncate_title_leaves_short_messages_untouched():
    assert truncate_title("Research the EV charging market") == "Research the EV charging market"


def test_truncate_title_leaves_exact_length_messages_untouched():
    message = "x" * CHAT_TITLE_MAX_LENGTH
    assert truncate_title(message) == message


def test_truncate_title_appends_ellipsis_when_cut_short():
    message = "x" * (CHAT_TITLE_MAX_LENGTH + 20)
    result = truncate_title(message)
    assert len(result) == CHAT_TITLE_MAX_LENGTH
    assert result.endswith("…")
    assert result[:-1] == message[: CHAT_TITLE_MAX_LENGTH - 1]
