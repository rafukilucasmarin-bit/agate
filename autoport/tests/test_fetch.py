import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import fetch_geode  # noqa: E402

ASSETS = [{"name": n} for n in [
    "geode-v5.11.2-win.zip", "geode-v5.11.2-mac.zip", "geode-v5.11.2-android64.apk",
    "geode-installer-v5.11.2-win.exe", "geode-installer-v5.11.2-mac.pkg", "geode-v5.11.2-ios.zip"]]


class T(unittest.TestCase):
    def test_pick(self):
        self.assertEqual(fetch_geode.pick_asset(ASSETS, "win")["name"], "geode-v5.11.2-win.zip")
        self.assertEqual(fetch_geode.pick_asset(ASSETS, "mac")["name"], "geode-v5.11.2-mac.zip")

    def test_ambiguous_or_missing_fails_loudly(self):
        with self.assertRaises(SystemExit):
            fetch_geode.pick_asset(ASSETS[2:], "win")
        with self.assertRaises(SystemExit):
            fetch_geode.pick_asset(ASSETS + [{"name": "geode-v5.11.2-b-win.zip"}], "win")

    def test_layout_check_case_insensitive(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "GEODE.DLL").write_bytes(b""); (d / "xinput1_4.dll").write_bytes(b"")
        fetch_geode.check_layout("win", d)
        with self.assertRaises(SystemExit):
            fetch_geode.check_layout("mac", d)


if __name__ == "__main__":
    unittest.main()
