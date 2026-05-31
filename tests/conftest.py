import pytest
from pathlib import Path


@pytest.fixture
def tmp_project_dir(tmp_path, monkeypatch):
    """Isolated data/projects dir. Patches app.config paths + scheduler PROJECTS_DIR."""
    import app.config as cfg
    data_dir = tmp_path / "data"
    projects_dir = data_dir / "projects"
    projects_dir.mkdir(parents=True)
    monkeypatch.setattr(cfg, "DATA_DIR", data_dir)
    monkeypatch.setattr(cfg, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(cfg, "CONFIG_FILE", data_dir / "config.json")
    try:
        import app.engines.scheduler as sch
        monkeypatch.setattr(sch, "PROJECTS_DIR", projects_dir, raising=False)
    except ImportError:
        pass  # scheduler doesn't exist yet until Task 7
    try:
        import app.utils.project_store as _ps
        monkeypatch.setattr(_ps, "PROJECTS_DIR", projects_dir, raising=False)
    except ImportError:
        pass
    # API + trailer pipeline modules also re-bind PROJECTS_DIR at import time;
    # patch the ones already in sys.modules so a test that runs after them
    # sees the tmp dir (without this, the first ASR test in alphabetical order
    # binds the real path and contaminates the rest of the session).
    for _modname in ("app.api.translate", "app.api.projects",
                     "app.engines.trailer_pipeline"):
        import sys as _sys
        _mod = _sys.modules.get(_modname)
        if _mod is not None and hasattr(_mod, "PROJECTS_DIR"):
            monkeypatch.setattr(_mod, "PROJECTS_DIR", projects_dir, raising=False)
    return projects_dir


@pytest.fixture(autouse=True)
def _reset_scheduler_progress_store():
    """Prevent inter-test contamination of module-global progress_store."""
    try:
        from app.engines.scheduler import progress_store
        progress_store.clear()
        yield
        progress_store.clear()
    except ImportError:
        yield
