import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import control_center as cc


class ControlCenterQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.control_dir_patch = patch.object(cc, "CONTROL_DIR", self.root / "control-center")
        self.tasks_path_patch = patch.object(cc, "TASKS_PATH", self.root / "control-center" / "tasks.json")
        self.token_path_patch = patch.object(cc, "TOKEN_PATH", self.root / "control-center" / "auth.token")
        self.control_dir_patch.start()
        self.tasks_path_patch.start()
        self.token_path_patch.start()

    def tearDown(self):
        self.control_dir_patch.stop()
        self.tasks_path_patch.stop()
        self.token_path_patch.stop()
        self.temp.cleanup()

    def test_task_persists_and_can_be_deleted(self):
        task = cc.add_task("  inspect   WS2812 DMA  ", "high")
        self.assertEqual(task["title"], "inspect WS2812 DMA")
        self.assertEqual(task["status"], "queued")
        self.assertEqual(cc.load_tasks(), [task])
        self.assertTrue(cc.delete_task(task["id"]))
        self.assertEqual(cc.load_tasks(), [])
        self.assertFalse(cc.delete_task(task["id"]))

    def test_invalid_task_is_rejected(self):
        for title, priority in (("", "normal"), ("x", "urgent"), ("x" * 1001, "normal")):
            with self.subTest(title_length=len(title), priority=priority):
                with self.assertRaises(ValueError):
                    cc.add_task(title, priority)
        self.assertEqual(cc.load_tasks(), [])

    def test_token_is_saved_with_restrictive_permissions_where_supported(self):
        token = cc.ensure_token()
        self.assertTrue(token)
        self.assertEqual(cc.ensure_token(), token)
        self.assertEqual((self.root / "control-center" / "auth.token").read_text().strip(), token)

    def test_chat_sends_planning_only_prompt_to_configured_api(self):
        responses = [
            {"data": [{"id": "local-bonsai-27b"}]},
            {"choices": [{"message": {"content": "まずタイマーとDMAの対応表を確認します。"}}]},
        ]

        class FakeResponse:
            status = 200
            def __init__(self, value):
                self.value = value
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, _limit):
                return json.dumps(self.value).encode()

        with patch.object(cc.urllib.request, "urlopen", side_effect=[FakeResponse(x) for x in responses]) as urlopen:
            answer = cc.bonsai_chat("WS2812の設計で確認することは？")
        self.assertIn("タイマー", answer)
        req = urlopen.call_args_list[1].args[0]
        payload = json.loads(req.data.decode())
        self.assertEqual(req.full_url, cc.API_BASE.rstrip("/") + "/chat/completions")
        self.assertEqual(payload["model"], "local-bonsai-27b")
        self.assertIn("cannot inspect or edit files", payload["messages"][0]["content"])
        self.assertEqual(payload["messages"][1]["content"], "WS2812の設計で確認することは？")

    def test_chat_stream_emits_content_deltas_and_uses_streaming_api(self):
        class FakeResponse:
            status = 200
            def __init__(self, lines):
                self.lines = iter(lines)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def readline(self):
                return next(self.lines, b"")

        events = [
            'data: {"choices":[{"delta":{"content":"こんにちは"}}]}'.encode("utf-8") + bytes([10]),
            'data: {"choices":[{"delta":{"content":"！"}}]}'.encode("utf-8") + bytes([10]),
            b'data: [DONE]\n',
        ]
        with patch.dict("os.environ", {"BONSAI_MODEL": "local-bonsai-27b"}):
            with patch.object(cc.urllib.request, "urlopen", return_value=FakeResponse(events)) as urlopen:
                result = list(cc.bonsai_stream("テスト"))
        self.assertEqual(result, [{"delta": "こんにちは"}, {"delta": "！"}])
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode())
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["model"], "local-bonsai-27b")

    def test_chat_stream_reports_empty_content_without_exposing_reasoning(self):
        class FakeResponse:
            def __init__(self):
                self.lines = iter([
                    'data: {"choices":[{"delta":{"reasoning_content":"private reasoning"},"finish_reason":"stop"}]}'.encode("utf-8") + bytes([10]),
                    'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":4,"total_tokens":16}}'.encode("utf-8") + bytes([10]),
                ])
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def readline(self):
                return next(self.lines, b"")

        with patch.dict("os.environ", {"BONSAI_MODEL": "local-bonsai-27b"}):
            with patch.object(cc.urllib.request, "urlopen", return_value=FakeResponse()):
                result = list(cc.bonsai_stream("テスト"))
        self.assertEqual(len(result), 1)
        self.assertIn("error", result[0])
        self.assertIn("finish_reason=stop", result[0]["error"])
        self.assertIn("prompt_tokens=12", result[0]["error"])
        self.assertNotIn("private reasoning", json.dumps(result, ensure_ascii=False))

    def test_bonsai_plan_returns_bounded_steps_without_executing_them(self):
        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, _limit):
                return json.dumps({"choices": [{"message": {"content":
                    '{"summary":"確認してから進める","steps":['
                    '{"title":"作業ツリーを確認","priority":"high"},'
                    '{"title":"必要なテストを調べる","priority":"invalid"}]}'}}]}).encode()

        with patch.dict("os.environ", {"BONSAI_MODEL": "local-bonsai-27b"}):
            with patch.object(cc.urllib.request, "urlopen", return_value=FakeResponse()) as urlopen:
                plan = cc.bonsai_plan("現在の状態を調べる")
        self.assertEqual(plan["summary"], "確認してから進める")
        self.assertEqual(len(plan["steps"]), 2)
        self.assertEqual(plan["steps"][0]["priority"], "high")
        self.assertEqual(plan["steps"][1]["priority"], "normal")
        payload = json.loads(urlopen.call_args.args[0].data.decode())
        self.assertFalse(payload["stream"])
        self.assertIn("Return ONLY a JSON object", payload["messages"][0]["content"])

    def test_add_tasks_validates_then_persists_batch(self):
        tasks = cc.add_tasks([
            {"title": "状態を確認", "priority": "high"},
            {"title": "結果を報告", "priority": "normal"},
        ])
        self.assertEqual(len(tasks), 2)
        self.assertEqual(cc.load_tasks(), tasks)
        with self.assertRaises(ValueError):
            cc.add_tasks([{"title": "valid"}, {"title": ""}])
        self.assertEqual(cc.load_tasks(), tasks)

    def test_chat_stream_stops_when_consultation_was_cancelled(self):
        import threading

        class FakeResponse:
            def __init__(self):
                self.closed = False
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def close(self):
                self.closed = True
            def readline(self):
                raise AssertionError("cancelled stream must not read upstream")

        response = FakeResponse()
        event = threading.Event()
        event.set()
        with cc.STREAM_LOCK:
            cc.ACTIVE_STREAMS["cancel-test"] = {"cancelled": event, "response": None}
        try:
            with patch.dict("os.environ", {"BONSAI_MODEL": "local-bonsai-27b"}):
                with patch.object(cc.urllib.request, "urlopen", return_value=response):
                    result = list(cc.bonsai_stream("テスト", request_id="cancel-test"))
            self.assertEqual(result, [{"cancelled": True}])
            self.assertTrue(response.closed)
        finally:
            with cc.STREAM_LOCK:
                cc.ACTIVE_STREAMS.pop("cancel-test", None)

    def test_chat_rejects_empty_and_oversized_messages(self):
        with self.assertRaises(ValueError):
            cc.bonsai_chat(" ")
        with self.assertRaises(ValueError):
            cc.bonsai_chat("x" * 4001)


if __name__ == "__main__":
    unittest.main()
