"""Headless dashboard test using Streamlit's AppTest. Skipped automatically when streamlit isn't installed."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from streamlit.testing.v1 import AppTest
except Exception:  # streamlit not installed or too old
    AppTest = None


@unittest.skipIf(AppTest is None, "streamlit not installed")
class TestDashboard(unittest.TestCase):
    def test_dashboard_renders_with_demo_data(self):
        import seed_demo
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "hg.db")
            seed_demo.DB = db
            cwd = os.getcwd()
            os.chdir(ROOT)  # the app and seed script use paths relative to the project root
            try:
                seed_demo.main()
                os.environ["HOTELGUARD_DB"] = db
                at = AppTest.from_file(str(ROOT / "dashboard.py"), default_timeout=60).run()
                self.assertFalse(at.exception, [e.value for e in at.exception])
                self.assertGreaterEqual(len(at.metric), 5)
                self.assertEqual(at.metric[0].value, "8")  # hotels monitored
            finally:
                os.chdir(cwd)
                os.environ.pop("HOTELGUARD_DB", None)


if __name__ == "__main__":
    unittest.main()
