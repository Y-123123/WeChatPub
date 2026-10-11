import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streamlit.testing.v1 import AppTest


class AppTests(unittest.TestCase):
    def test_app_opens_without_network_or_keys(self):
        clean = {name: "" for name in ("LLM_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "WECHAT_APP_ID", "WECHAT_APP_SECRET", "LLM_MODEL", "LLM_BASE_URL")}
        clean["LLM_PROVIDER"] = "deepseek"
        with patch.dict(os.environ, clean), patch("requests.get") as get, patch("requests.post") as post:
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=20)
            self.assertFalse(app.exception)
            self.assertTrue(any(x.value == "publish" for x in app.selectbox))
            get.assert_not_called()
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
