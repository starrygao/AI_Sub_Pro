"""HTTP request binding for the shared translation-task service."""
from fastapi import APIRouter, Path as PathParam
from app.services import translation_tasks as tasks
from app.utils.project_store import PID_PATTERN
from app.services.translation_tasks import ASRRequest, TranslateRequest, FullPipelineRequest, RetryRequest

router = APIRouter(prefix="/api/projects", tags=["pipeline"])

@router.post("/{pid}/start-asr")
def start_asr(pid: str = PathParam(pattern=PID_PATTERN), req: ASRRequest = ASRRequest()):
    return tasks.start_asr(pid, req)


@router.post("/{pid}/start-translate")
def start_translate(pid: str = PathParam(pattern=PID_PATTERN), req: TranslateRequest = TranslateRequest()):
    return tasks.start_translate(pid, req)


@router.post("/{pid}/start-full")
def start_full(pid: str = PathParam(pattern=PID_PATTERN), req: FullPipelineRequest = FullPipelineRequest()):
    return tasks.start_full(pid, req)


@router.post("/{pid}/start-transcribe-translate")
def start_transcribe_translate(pid: str = PathParam(pattern=PID_PATTERN), req: FullPipelineRequest = FullPipelineRequest()):
    return tasks.start_transcribe_translate(pid, req)


@router.post("/{pid}/retry")
def retry_project(pid: str = PathParam(pattern=PID_PATTERN), req: RetryRequest = RetryRequest()):
    return tasks.retry_project(pid, req)


@router.post("/{pid}/resume")
def resume_project(pid: str = PathParam(pattern=PID_PATTERN)):
    return tasks.resume_project(pid)


@router.post("/{pid}/cancel")
def cancel_task(pid: str = PathParam(pattern=PID_PATTERN)):
    return tasks.cancel_task(pid)


@router.post("/{pid}/burn")
def start_burn(pid: str = PathParam(pattern=PID_PATTERN)):
    return tasks.start_burn(pid)


@router.get("/{pid}/progress")
def get_progress(pid: str = PathParam(pattern=PID_PATTERN)):
    return tasks.get_progress(pid)
