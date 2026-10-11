import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline
import providers
import settings
import sources
from locking import cycle_lock


class ProviderTests(unittest.TestCase):
    def test_compatible_providers(self):
        for name in ("openai", "gemini", "deepseek", "custom"):
            with self.subTest(name=name), patch.dict(os.environ, {"LLM_PROVIDER": name, "LLM_API_KEY": "dummy-key", "LLM_MODEL": "test-model", "LLM_BASE_URL": "https://example.org/v1"}, clear=True):
                response = Mock(status_code=200)
                response.json.return_value = {"choices": [{"message": {"content": "result"}, "finish_reason": "stop"}]}
                with patch("providers.requests.post", return_value=response) as post:
                    self.assertEqual(providers.complete("system", "input"), "result")
                    self.assertTrue(post.call_args.args[0].endswith("/chat/completions"))
                    self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer dummy-key")
                    self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_claude_native_messages(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "claude", "ANTHROPIC_API_KEY": "dummy-key", "CLAUDE_MODEL": "test-model"}, clear=True):
            response = Mock(status_code=200)
            response.json.return_value = {"content": [{"type": "text", "text": "one"}, {"type": "text", "text": "two"}]}
            with patch("providers.requests.post", return_value=response) as post:
                self.assertEqual(providers.complete("system", "input"), "onetwo")
                self.assertTrue(post.call_args.args[0].endswith("/messages"))
                self.assertEqual(post.call_args.kwargs["json"]["system"], "system")
                self.assertEqual(post.call_args.kwargs["headers"]["x-api-key"], "dummy-key")

    def test_secrets_not_in_error(self):
        with patch.dict(os.environ, {"LLM_API_KEY": "dummy-secret"}, clear=True):
            response = Mock(status_code=401, text="dummy-secret")
            with patch("providers.requests.post", return_value=response), self.assertRaises(RuntimeError) as error:
                providers.complete("system", "input")
            self.assertNotIn("dummy-secret", str(error.exception))

    def test_bad_base_does_not_send_key(self):
        for base in ("http://example.org", "https://key@example.org", "https://example.org?key=secret"):
            with patch.dict(os.environ, {"LLM_API_KEY": "dummy", "LLM_BASE_URL": base}, clear=True), patch("providers.requests.post") as post:
                with self.assertRaises(ValueError):
                    providers.complete("s", "u")
                post.assert_not_called()

    def test_arxiv_parsing_deduplicates_versions(self):
        feed = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2601.12345v2</id><title>Brain AI</title><summary>Real source abstract.</summary><published>2026-01-01T00:00:00Z</published><author><name>A</name></author></entry></feed>'''
        source = sources.parse_arxiv(feed, days=0)[0]
        self.assertEqual(source["pmid"], "arxiv-2601.12345")
        self.assertEqual(source["url"], "https://arxiv.org/abs/2601.12345")
        self.assertEqual(source["publication_types"], ["Preprint"])

    def test_preview_does_not_publish(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, "DATA", Path(directory)), patch("sources.search", return_value={"articles": []}), patch.object(pipeline, "send") as send:
            self.assertEqual(pipeline.run({"mode": "preview"}), [])
            send.assert_not_called()

    def test_missing_credentials_stop_before_search(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, "DATA", Path(directory)), patch.dict(os.environ, {}, clear=True), patch("sources.search") as search:
            with self.assertRaises(ValueError):
                pipeline.run({"mode": "publish"})
            search.assert_not_called()

    def test_automatic_published_skip(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(pipeline, "DATA", Path(directory)), patch.dict(os.environ, {"LLM_API_KEY": "dummy", "WECHAT_APP_ID": "account", "WECHAT_APP_SECRET": "dummy"}, clear=True):
            with pipeline.db() as db:
                db.execute("INSERT INTO jobs(account,pmid,bundle,fingerprint,stage) VALUES(?,?,?,?,?)", ("account", "123", "/already-published", "hash", "published"))
            with patch("sources.search", return_value={"articles": [{"pmid": "123"}]}), patch.object(pipeline, "build") as build, patch.object(pipeline, "send") as send:
                result = pipeline.run({"mode": "publish"})
                self.assertTrue(result[0]["skipped"])
                build.assert_not_called()
                send.assert_not_called()

    def test_lock_prevents_simultaneous_cycles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runner.lock"
            with cycle_lock(path), self.assertRaises(RuntimeError):
                with cycle_lock(path):
                    pass
            with cycle_lock(path):
                pass

    def test_default_config_is_publish_without_credentials(self):
        config = settings.load_config(settings.ROOT / "config.example.json")
        self.assertEqual(config["mode"], "publish")
        self.assertEqual(config["sources"], ["pubmed", "arxiv"])
        self.assertIn("artificial intelligence", config["query"])


if __name__ == "__main__":
    unittest.main()
