import os
import unittest
from unittest.mock import patch

from server.services.chat_service import ChatService


class _Request:
    def __init__(self, states):
        self._states = iter(states)

    async def is_disconnected(self):
        return next(self._states, True)


class ChatServiceStreamTest(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_without_llm_key_keeps_base_server_usable(self):
        service = ChatService()
        with patch.dict(os.environ, {"LLM_API_KEY": ""}, clear=False):
            with patch("model.config.read_json", return_value={}):
                await service.initialize()

        self.assertFalse(service.is_ready)
        self.assertIn("未配置 LLM API Key", service._initialization_error)

    async def test_sse_does_not_start_model_after_disconnect(self):
        service = ChatService()

        async def unexpected_stream(*_args, **_kwargs):
            self.fail("model stream should not start after the client disconnects")
            yield  # pragma: no cover - keeps this an async generator

        service.stream_chat_events = unexpected_stream
        chunks = [
            chunk
            async for chunk in service.sse_generator(
                "local_user",
                "hello",
                "topic",
                request=_Request([True]),
            )
        ]
        self.assertEqual(chunks, [])

    async def test_sse_stops_without_done_event_after_disconnect(self):
        service = ChatService()

        async def fake_stream(*_args, **_kwargs):
            yield ("thinking", "")
            yield ("token", "partial")

        service.stream_chat_events = fake_stream
        chunks = [
            chunk
            async for chunk in service.sse_generator(
                "local_user",
                "hello",
                "topic",
                request=_Request([False, False, True]),
            )
        ]
        self.assertEqual(len(chunks), 1)
        self.assertIn('"type": "thinking"', chunks[0])
        self.assertNotIn('"type": "done"', "".join(chunks))


if __name__ == "__main__":
    unittest.main()
