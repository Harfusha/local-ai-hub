from local_ai_hub.command_policy import _classification_result


def test_classification_result_preserves_common_fields_and_omits_replay_policy():
    assert _classification_result(
        "read", cacheable=False, allowed=True, reason="powershell read command"
    ) == {
        "class": "read",
        "cacheable": False,
        "allowed": True,
        "reason": "powershell read command",
    }


def test_classification_result_preserves_explicit_replay_policy_values():
    assert _classification_result(
        "validation",
        cacheable=False,
        allowed=True,
        reason="powershell validation command",
        replay_safe=True,
    ) == {
        "class": "validation",
        "cacheable": False,
        "allowed": True,
        "replay_safe": True,
        "reason": "powershell validation command",
    }
    assert _classification_result(
        "validation",
        cacheable=False,
        allowed=True,
        reason="user-whitelisted powershell tool",
        replay_safe=False,
    )["replay_safe"] is False
