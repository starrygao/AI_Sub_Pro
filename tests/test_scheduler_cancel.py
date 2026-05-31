def test_request_cancel_sets_flag():
    from app.engines.scheduler import request_cancel, is_cancelled, reset_cancel
    reset_cancel("pidc1")
    assert is_cancelled("pidc1") is False
    request_cancel("pidc1")
    assert is_cancelled("pidc1") is True


def test_is_cancelled_unknown_pid_is_false():
    from app.engines.scheduler import is_cancelled
    assert is_cancelled("never-existed-xxx") is False


def test_reset_cancel_clears_flag():
    from app.engines.scheduler import request_cancel, is_cancelled, reset_cancel
    request_cancel("pidc2")
    assert is_cancelled("pidc2") is True
    reset_cancel("pidc2")
    assert is_cancelled("pidc2") is False
