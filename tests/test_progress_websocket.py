import pytest
from fastapi import WebSocketDisconnect


@pytest.mark.asyncio
async def test_progress_websocket_observes_client_disconnect():
    from app.main import ws_progress

    class FakeWebSocket:
        def __init__(self):
            self.accepted = False
            self.sent = []
            self.receive_calls = 0

        async def accept(self):
            self.accepted = True

        async def send_json(self, payload):
            self.sent.append(payload)

        async def receive_text(self):
            self.receive_calls += 1
            raise WebSocketDisconnect()

    websocket = FakeWebSocket()

    await ws_progress(websocket, "missing-project")

    assert websocket.accepted is True
    assert websocket.sent == [{}]
    assert websocket.receive_calls == 1


@pytest.mark.asyncio
async def test_progress_websocket_reports_terminal_completion_with_stage_cleared(
    tmp_project_dir,
):
    from app.engines.scheduler import complete_progress, update_progress
    from app.main import ws_progress

    pid = "ws-terminal"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    update_progress(pid, "translate", 100, "translation stage done")
    complete_progress(pid, "translation workflow complete")

    class FakeWebSocket:
        def __init__(self):
            self.sent = []

        async def accept(self):
            return None

        async def send_json(self, payload):
            self.sent.append(payload)

        async def receive_text(self):
            raise WebSocketDisconnect()

    websocket = FakeWebSocket()

    await ws_progress(websocket, pid)

    assert websocket.sent
    assert websocket.sent[0]["progress"] == 100
    assert websocket.sent[0]["stage"] == ""
    assert websocket.sent[0]["message"] == "translation workflow complete"
