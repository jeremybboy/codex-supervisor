import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import supervisor


class SupervisorTests(unittest.TestCase):
    def test_missing_control_socket_uses_stdio(self):
        with patch.dict(os.environ, {"SUPERVISOR_CODEX_TRANSPORT": "auto"}, clear=False), \
             patch.object(supervisor, "DEFAULT_CODEX_SOCKET", Path("/definitely/missing/socket")):
            self.assertEqual(supervisor.codex_command(), [supervisor.CODEX_BIN, "app-server", "--stdio"])

    def test_available_control_socket_uses_proxy(self):
        with patch.dict(os.environ, {"SUPERVISOR_CODEX_TRANSPORT": "auto"}, clear=False), \
             patch.object(Path, "exists", return_value=True):
            self.assertEqual(supervisor.codex_command(), [supervisor.CODEX_BIN, "app-server", "proxy"])

    def test_commentary_record_is_visible(self):
        record = {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "commentary", "content": [{"type": "output_text", "text": "Building the audio target."}]}}
        self.assertEqual(supervisor.rollout_event(record), ("commentary", "Building the audio target."))

    def test_final_request_is_visible(self):
        record = {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "final_answer", "content": [{"type": "output_text", "text": "Please connect power, then reply continue."}]}}
        self.assertEqual(supervisor.rollout_event(record), ("worker/final", "Please connect power, then reply continue."))

    def test_polling_is_compacted(self):
        kind, detail = supervisor.compact_event("tool/exec", "tools.write_stdin({session_id: 12})")
        self.assertEqual(kind, "build/poll")
        self.assertIn("Polled", detail)

    def test_json_pass_field_is_not_test_verdict(self):
        kind, _ = supervisor.compact_event("tool/result", json.dumps({"pass": False, "error": 0}))
        self.assertEqual(kind, "tool/result")


if __name__ == "__main__":
    unittest.main()
