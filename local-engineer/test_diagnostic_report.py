import unittest

from diagnostic_report import redact, summarize_log


class DiagnosticReportTests(unittest.TestCase):
    def test_redacts_common_secrets_and_url_credentials(self):
        line = "api_key=abc123 Authorization: BearerXYZ https://alice:pass@example.test/path"
        cleaned = redact(line)
        self.assertNotIn("abc123", cleaned)
        self.assertNotIn("alice:pass", cleaned)
        self.assertIn("[REDACTED]", cleaned)

    def test_summarizes_test_failure_without_dumping_whole_log(self):
        log = "\n".join([
            "setup details",
            "Traceback (most recent call last):",
            "AssertionError: api_key=secret-value did not match",
            "Ran 42 tests in 1.2s",
            "FAILED (failures=1)",
            "very long irrelevant detail",
        ])
        result = summarize_log(log, limit=5)
        joined = "\n".join(result)
        self.assertIn("Ran 42 tests in 1.2s", joined)
        self.assertIn("FAILED (failures=1)", joined)
        self.assertIn("AssertionError", joined)
        self.assertNotIn("secret-value", joined)
        self.assertLessEqual(len(result), 5)

    def test_empty_log_is_reported(self):
        self.assertEqual(summarize_log(" \n "), ["Log is empty."])

    def test_log_without_errors_returns_only_a_few_trailing_lines(self):
        result = summarize_log("one\ntwo\nthree\nfour\nfive\nsix\nseven", limit=3)
        self.assertEqual(result, ["five", "six", "seven"])


if __name__ == "__main__":
    unittest.main()
