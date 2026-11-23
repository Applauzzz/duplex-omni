import base64
import io
import unittest
from unittest.mock import patch

from backbone import classifier_token_ids, create_backbone
from test_semantic_vad import FakeClient
from semantic_vad import _sse_data


class Tokenizer:
    def encode(self, code, add_special_tokens=False):
        return [{"有": 10, "无": 11, "已": 12, "未": 13}[code]]

    def decode(self, ids):
        return {10: "有", 11: "无", 12: "已", 13: "未"}[ids[0]]


class BackboneTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_sse_preserves_wire_bytes(self):
        lines = [b': keepalive\r\n', b'data: {"choices":[{"delta":{"role":"assistant","content":"Assistant:"}}]}\r\n',
                 b'\r\n', b'data: [DONE]\n', b'\n']
        async def source():
            for line in lines:
                yield line
        raw = io.BytesIO()
        parsed = [item async for item in _sse_data(source(), raw_log=raw)]
        self.assertEqual(raw.getvalue(), b"".join(lines))
        self.assertIn('"role":"assistant"', parsed[0])
        self.assertEqual(parsed[1], "[DONE]")

    async def test_raw_sse_records_malformed_event_before_error(self):
        async def source():
            yield b"data: incomplete\n"
        raw = io.BytesIO()
        with self.assertRaises(RuntimeError):
            _ = [item async for item in _sse_data(source(), raw_log=raw)]
        self.assertEqual(raw.getvalue(), b"data: incomplete\n")

    def test_tokenizer_validation(self):
        self.assertEqual(classifier_token_ids(Tokenizer())["有"], 10)
        with patch.object(Tokenizer, "encode", return_value=[1, 2]):
            with self.assertRaises(ValueError):
                classifier_token_ids(Tokenizer())

    async def test_qwen_classification_payload(self):
        client = FakeClient(["有", "已"])
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=Tokenizer()):
            semantic, chat = create_backbone(client, "http://qwen", backbone="qwen3-omni")
        chunks = [{"audio": base64.b64encode(b"\0\0" * 160).decode(),
                   "format": "pcm16", "sample_rate_hz": 16000}]
        self.assertTrue((await semantic.decide_sem(chunks, context={})).semantic)
        self.assertTrue((await semantic.decide_complete(chunks, context={})).complete)
        self.assertEqual(client.requests[0][1]["json"]["allowed_token_ids"], [10, 11])
        self.assertEqual(client.requests[1][1]["json"]["allowed_token_ids"], [12, 13])
        self.assertEqual(chat.model, "qwen3-omni-thinker")

    async def test_qwen_stream_is_incremental(self):
        released = False

        class Response:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                pass

            @property
            def content(self):
                async def stream():
                    yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n'
                    yield b'\n'
                    self.assert_released()
                    yield b'data: {"choices":[{"delta":{"content":"second"},"finish_reason":"stop"}]}\n'
                    yield b'\n'
                    yield b'data: [DONE]\n'
                    yield b'\n'
                return stream()

            def assert_released(self):
                assert released

        class Client:
            def post(self, url, **kwargs):
                self.payload = kwargs["json"]
                return Response()

        client = Client()
        with patch("transformers.AutoTokenizer.from_pretrained", return_value=Tokenizer()):
            _, chat = create_backbone(client, "http://qwen", backbone="qwen3-omni")
        chunks = [{"audio": base64.b64encode(b"\0\0" * 160).decode(),
                   "format": "pcm16", "sample_rate_hz": 16000}]
        stream = chat.stream_reply(chunks, history=[], prompt="test", context={})
        self.assertEqual(await anext(stream), "first")
        released = True
        self.assertEqual(await anext(stream), "second")
        with self.assertRaises(StopAsyncIteration):
            await anext(stream)
        self.assertTrue(client.payload["stream"])
        self.assertNotIn("chat_template_kwargs", client.payload)

    def test_mimo_default_preserved(self):
        semantic, chat = create_backbone(None, "http://mimo", backbone="mimo")
        self.assertEqual(semantic.code_token_ids["有"], 18830)
        self.assertEqual(chat.model, "mimo-v2.6-flash")
        self.assertIs(chat.enable_thinking, False)
