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
