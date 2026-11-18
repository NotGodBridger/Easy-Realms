import hashlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
MOJANGLES_SHA256 = 'b92024dd75dd54c203388fe7038d5b697681bb30d17de8a237348faffc347e65'


class FontPackagingTests(unittest.TestCase):
    def test_official_mojangles_asset_is_present_and_unchanged(self):
        font = ROOT / 'assets' / 'Minecraft-Seven_v2.ttf'
        self.assertTrue(font.is_file())
        self.assertEqual(hashlib.sha256(font.read_bytes()).hexdigest(), MOJANGLES_SHA256)

    def test_body_and_heading_fonts_are_separated(self):
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn('font-family:"Minecraft Seven v2"', app_source)
        self.assertIn('font-family:"Minecraft Ten"', app_source)
        self.assertIn("ASSETS/'Minecraft-Seven_v2.ttf'", app_source)

    def test_loading_screen_registers_mojangles(self):
        launcher_source = (ROOT / 'bootstrap.pyw').read_text(encoding='utf-8')
        self.assertIn("'Minecraft-Seven_v2.ttf'", launcher_source)
        self.assertIn("font=('Minecraft Seven v2',11)", launcher_source)


if __name__ == '__main__':
    unittest.main()
