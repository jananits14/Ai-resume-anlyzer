import os
import tempfile
import unittest

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app


class AppSmokeTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("RAPIDAPI_KEY", None)

    def test_ai_text_requires_key(self):
        self.assertIsNone(app.ai_text("hello"))

    def test_job_search_reports_missing_key(self):
        result = app.search_jobs_jsearch("python developer", "Chennai", False, "month")
        self.assertIn("RAPIDAPI_KEY", result["error"])

    def test_video_storage_dir_exists(self):
        app.ensure_video_storage()
        self.assertTrue(app.VIDEO_STORAGE_DIR.exists())


if __name__ == "__main__":
    unittest.main()
