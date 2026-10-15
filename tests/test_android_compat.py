from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AndroidCompatibilityTests(unittest.TestCase):
    def test_saved_history_timestamp_supports_declared_minimum_sdk(self):
        gradle = (ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8")
        activity = (ROOT / "android/app/src/main/java/com/leafwise/app/MainActivity.kt").read_text(encoding="utf-8")
        minimum = re.search(r"minSdk\s*=\s*(\d+)", gradle)
        if minimum is None:
            raise AssertionError("Android minimum SDK is not declared.")
        self.assertEqual(int(minimum.group(1)), 24)
        self.assertNotIn("java.time.Instant", activity)
        self.assertIn("SimpleDateFormat", activity)
        self.assertIn("TimeZone.getTimeZone(\"UTC\")", activity)


if __name__ == "__main__":
    unittest.main()
