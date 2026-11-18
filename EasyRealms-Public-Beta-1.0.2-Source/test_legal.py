import unittest

import legal


class FakeSettings:
    def __init__(self):
        self.values = {}
        self.synced = False

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        self.synced = True


class LegalTests(unittest.TestCase):
    def test_public_beta_version(self):
        self.assertEqual(legal.APP_VERSION, "Public Beta 1.0.2")

    def test_new_install_requires_acceptance(self):
        self.assertFalse(legal.agreement_is_current(FakeSettings()))

    def test_current_acceptance_is_recorded(self):
        settings = FakeSettings()
        legal.record_acceptance(settings, "2026-11-17T00:00:00+00:00")
        self.assertTrue(legal.agreement_is_current(settings))
        self.assertEqual(settings.values["legal/accepted_at_utc"], "2026-11-17T00:00:00+00:00")
        self.assertTrue(settings.synced)

    def test_disclaimer_names_mojang_and_microsoft(self):
        self.assertIn("NOT AN OFFICIAL MINECRAFT PRODUCT", legal.DISCLAIMER)
        self.assertIn("MOJANG OR MICROSOFT", legal.DISCLAIMER)


if __name__ == "__main__":
    unittest.main()
