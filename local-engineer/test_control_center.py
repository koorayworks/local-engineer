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
        self.control_dir_patch.start()
        self.tasks_path_patch.start()

    def tearDown(self):
        self.control_dir_patch.stop()
        self.tasks_path_patch.stop()
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
        response = {
            "choices": [{"message": {"content": "まずタイマーとDMAの対応表を確認します。"}}]
        }

        class FakeResponse:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, _limit):
                return json.dumps(response).encode()

        with patch.object(cc.urllib.request, "urlopen", return_value=FakeResponse()) as urlopen:
            answer = cc.bonsai_chat("WS2812の設計で確認することは？")
        self.assertIn("タイマー", answer)
        req = urlopen.call_args.args[0]
        payload = json.loads(req.data.decode())
        self.assertEqual(req.full_url, cc.API_BASE.rstrip("/") + "/chat/completions")
        self.assertIn("cannot inspect or edit files", payload["messages"][0]["content"])
        self.assertEqual(payload["messages"][1]["content"], "WS2812の設計で確認することは？")

    def test_chat_rejects_empty_and_oversized_messages(self):
        with self.assertRaises(ValueError):
            cc.bonsai_chat(" ")
        with self.assertRaises(ValueError):
            cc.bonsai_chat("x" * 4001)


if __name__ == "__main__":
    unittest.main()
