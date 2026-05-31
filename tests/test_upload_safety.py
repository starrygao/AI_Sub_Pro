"""Phase 4 — input validation for /api/projects/upload:
defense-in-depth path confinement + max upload size."""
import io
from pathlib import Path

import pytest
from fastapi import HTTPException


class _StubUploadFile:
    """Minimal stand-in for fastapi.UploadFile in unit tests.

    Streams from a configurable byte sequence so we can simulate both a
    tiny file (happy path) and a giant one (DoS attempt) without writing
    1+ GB to disk."""

    def __init__(self, filename: str, chunks):
        self.filename = filename
        self._chunks = list(chunks)

    async def read(self, size: int):
        if not self._chunks:
            return b""
        # ignore size — just yield the next prepared chunk
        return self._chunks.pop(0)


@pytest.fixture
def patched_projects_dir(tmp_project_dir, monkeypatch):
    """Make sure projects.py sees the temp PROJECTS_DIR."""
    from app.api import projects as projects_api
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    return tmp_project_dir


# ---- P4-1: dest must always resolve under uploads_dir ----------------------

@pytest.mark.asyncio
async def test_upload_rejects_dotdot_only_filename(patched_projects_dir):
    """filename == '..' would resolve to uploads_dir's parent; reject."""
    from app.api.projects import upload_video

    f = _StubUploadFile(filename="..", chunks=[b"x" * 16])
    with pytest.raises(HTTPException) as ei:
        await upload_video(file=f)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_empty_filename(patched_projects_dir):
    """filename == '' would build dest = uploads_dir itself (a directory);
    open() would later raise IsADirectoryError. Reject up front."""
    from app.api.projects import upload_video

    f = _StubUploadFile(filename="", chunks=[b"x" * 16])
    with pytest.raises(HTTPException) as ei:
        await upload_video(file=f)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_control_character_filename(patched_projects_dir):
    from app.api.projects import upload_video

    f = _StubUploadFile(filename="bad\x00name.mp4", chunks=[b"x" * 16])
    with pytest.raises(HTTPException) as ei:
        await upload_video(file=f)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_overlong_filename(patched_projects_dir):
    from app.api.projects import upload_video

    f = _StubUploadFile(filename=("a" * 300) + ".mp4", chunks=[b"x" * 16])
    with pytest.raises(HTTPException) as ei:
        await upload_video(file=f)
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_non_video_extension(patched_projects_dir):
    from app.api.projects import upload_video

    f = _StubUploadFile(filename="notes.txt", chunks=[b"x" * 16])
    with pytest.raises(HTTPException) as ei:
        await upload_video(file=f)

    assert ei.value.status_code == 400
    assert "video" in ei.value.detail.lower()
    uploads = patched_projects_dir / "_uploads"
    leftovers = list(uploads.rglob("notes*")) if uploads.exists() else []
    assert leftovers == []


@pytest.mark.asyncio
async def test_upload_rejects_symlinked_upload_directory(patched_projects_dir, tmp_path):
    from app.api.projects import upload_video

    outside = tmp_path / "outside_uploads"
    outside.mkdir()
    (patched_projects_dir / "_uploads").symlink_to(outside, target_is_directory=True)

    f = _StubUploadFile(filename="movie.mp4", chunks=[b"x" * 16])
    with pytest.raises(HTTPException) as ei:
        await upload_video(file=f)

    assert ei.value.status_code == 400
    assert "Upload directory is invalid" in ei.value.detail
    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_upload_rejects_upload_directory_replaced_by_file(patched_projects_dir):
    from app.api.projects import upload_video

    (patched_projects_dir / "_uploads").write_text("not a directory", encoding="utf-8")

    f = _StubUploadFile(filename="movie.mp4", chunks=[b"x" * 16])
    with pytest.raises(HTTPException) as ei:
        await upload_video(file=f)

    assert ei.value.status_code == 400
    assert "Upload directory is invalid" in ei.value.detail


# ---- P4-2: upload size cap -------------------------------------------------

@pytest.mark.asyncio
async def test_upload_rejects_oversize_file(patched_projects_dir, monkeypatch):
    """If the uploaded payload exceeds the configured cap, abort with 413
    before writing the entire stream to disk. Without this, an attacker
    can fill the disk with one POST."""
    from app.api import projects as projects_api
    from app.api.projects import upload_video

    monkeypatch.setattr(projects_api, "MAX_UPLOAD_BYTES", 4 * 1024 * 1024)  # 4 MiB

    big_chunk = b"x" * (1024 * 1024)  # 1 MiB
    # 6 MiB worth of chunks: over the 4 MiB cap.
    f = _StubUploadFile(filename="big.mp4", chunks=[big_chunk] * 6)

    with pytest.raises(HTTPException) as ei:
        await upload_video(file=f)
    assert ei.value.status_code == 413, \
        "must abort with 413 Payload Too Large before exhausting disk"

    # The partial file must NOT survive on disk.
    uploads = patched_projects_dir / "_uploads"
    leftovers = list(uploads.rglob("big*.mp4")) if uploads.exists() else []
    assert leftovers == [], f"oversize upload left partial file behind: {leftovers}"


@pytest.mark.asyncio
async def test_upload_accepts_undersize_file(patched_projects_dir, monkeypatch):
    """Sanity: a normal small upload still succeeds with the cap in place."""
    from app.api import projects as projects_api
    from app.api.projects import upload_video

    monkeypatch.setattr(projects_api, "MAX_UPLOAD_BYTES", 4 * 1024 * 1024)

    f = _StubUploadFile(filename="small.mp4", chunks=[b"x" * (32 * 1024)])
    result = await upload_video(file=f)
    assert result and Path(result["path"]).exists()


@pytest.mark.asyncio
async def test_upload_collision_truncates_overlong_generated_name(patched_projects_dir):
    from app.api.projects import upload_video

    uploads = patched_projects_dir / "_uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    filename = ("a" * 251) + ".mp4"
    (uploads / filename).write_bytes(b"existing")

    f = _StubUploadFile(filename=filename, chunks=[b"x" * 16])
    result = await upload_video(file=f)

    saved = Path(result["path"])
    assert saved.exists()
    assert saved.name.endswith("_1.mp4")
    assert len(saved.name.encode("utf-8")) <= 255


@pytest.mark.asyncio
async def test_upload_never_follows_preexisting_broken_symlink(patched_projects_dir, tmp_path):
    from app.api.projects import upload_video

    uploads = patched_projects_dir / "_uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.mp4"
    symlink = uploads / "movie.mp4"
    symlink.symlink_to(outside)

    f = _StubUploadFile(filename="movie.mp4", chunks=[b"x" * 16])
    result = await upload_video(file=f)

    saved = Path(result["path"])
    assert saved == uploads / "movie_1.mp4"
    assert saved.exists()
    assert symlink.is_symlink()
    assert not outside.exists()


@pytest.mark.asyncio
async def test_upload_rejects_empty_file(patched_projects_dir):
    from app.api.projects import upload_video

    f = _StubUploadFile(filename="empty.mp4", chunks=[])

    with pytest.raises(HTTPException) as ei:
        await upload_video(file=f)

    assert ei.value.status_code == 400
    uploads = patched_projects_dir / "_uploads"
    leftovers = list(uploads.rglob("empty*.mp4")) if uploads.exists() else []
    assert leftovers == []
