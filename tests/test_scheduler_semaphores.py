import threading
import time

import pytest


def test_sem_asr_respects_max_concurrent():
    from app.engines.scheduler import slot, _reset_sem_cache_for_testing
    _reset_sem_cache_for_testing()

    running = []
    peak = [0]
    lock = threading.Lock()

    def worker(i):
        with slot("asr", f"pid{i}"):
            with lock:
                running.append(i)
                peak[0] = max(peak[0], len(running))
            time.sleep(0.05)
            with lock:
                running.remove(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak[0] <= 2, f"ASR concurrency exceeded cap: peak={peak[0]}"


def test_sem_burn_is_strictly_sequential():
    from app.engines.scheduler import slot, _reset_sem_cache_for_testing
    _reset_sem_cache_for_testing()

    running = []
    peak = [0]
    lock = threading.Lock()

    def worker(i):
        with slot("burn", f"pid{i}"):
            with lock:
                running.append(i)
                peak[0] = max(peak[0], len(running))
            time.sleep(0.03)
            with lock:
                running.remove(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak[0] == 1, f"Burn must be sequential: peak={peak[0]}"


def test_user_configured_concurrency_takes_effect(monkeypatch):
    """Regression guard for the config-timing bug: user cap in config.json must win."""
    import app.config as cfg
    import app.engines.scheduler as sch

    # Pretend Config.load() has already run and user set asr=4
    cfg.Config._data = {"concurrency": {"asr": 4}}
    sch._reset_sem_cache_for_testing()

    sem = sch.get_semaphore("asr")
    # BoundedSemaphore stores initial value in _initial_value
    assert sem._initial_value == 4, f"Expected user cap=4, got {sem._initial_value}"

    # Cleanup: reset both to avoid polluting other tests
    cfg.Config._data = {}
    sch._reset_sem_cache_for_testing()


def test_invalid_user_concurrency_falls_back_to_default():
    import app.config as cfg
    import app.engines.scheduler as sch

    cfg.Config._data = {"concurrency": {"asr": "not-a-number", "burn": 0}}
    sch._reset_sem_cache_for_testing()

    asr = sch.get_semaphore("asr")
    burn = sch.get_semaphore("burn")

    assert asr._initial_value == 2
    assert burn._initial_value == 1

    cfg.Config._data = {}
    sch._reset_sem_cache_for_testing()


def test_malformed_concurrency_section_falls_back_to_default():
    import app.config as cfg
    import app.engines.scheduler as sch

    cfg.Config._data = {"concurrency": "bad"}
    sch._reset_sem_cache_for_testing()

    sem = sch.get_semaphore("asr")

    assert sem._initial_value == 2

    cfg.Config._data = {}
    sch._reset_sem_cache_for_testing()


def test_boolean_user_concurrency_falls_back_to_default():
    import app.config as cfg
    import app.engines.scheduler as sch

    cfg.Config._data = {"concurrency": {"asr": True}}
    sch._reset_sem_cache_for_testing()

    sem = sch.get_semaphore("asr")

    assert sem._initial_value == 2

    cfg.Config._data = {}
    sch._reset_sem_cache_for_testing()


def test_non_finite_user_concurrency_falls_back_to_default():
    import app.config as cfg
    import app.engines.scheduler as sch

    cfg.Config._data = {"concurrency": {"asr": float("inf")}}
    sch._reset_sem_cache_for_testing()

    sem = sch.get_semaphore("asr")

    assert sem._initial_value == 2

    cfg.Config._data = {}
    sch._reset_sem_cache_for_testing()


def test_user_concurrency_is_clamped_to_reasonable_upper_bound():
    import app.config as cfg
    import app.engines.scheduler as sch

    cfg.Config._data = {"concurrency": {"translate": 999}}
    sch._reset_sem_cache_for_testing()

    sem = sch.get_semaphore("translate")

    assert sem._initial_value == 16

    cfg.Config._data = {}
    sch._reset_sem_cache_for_testing()


def test_unknown_stage_raises():
    from app.engines.scheduler import get_semaphore
    with pytest.raises(ValueError, match="unknown stage"):
        get_semaphore("nonexistent")
