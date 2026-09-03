import json
import unittest

import supervisor


class SupervisorTests(unittest.TestCase):
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
