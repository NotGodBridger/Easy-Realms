import unittest

from ui_guidance import creation_guidance


class UiGuidanceTests(unittest.TestCase):
    def guidance(self, **changes):
        values = dict(kind='Vanilla', version='1.21.10', has_spec=True, catalog_loading=False,
                      creating=False, accepted_eula=True, name='My Server', folder='servers')
        values.update(changes)
        return creation_guidance(**values)

    def test_ready_state_enables_both_actions(self):
        result = self.guidance()
        self.assertTrue(result.can_configure);self.assertTrue(result.can_create)
        self.assertEqual(result.state, 'ready')

    def test_loading_and_missing_version_explain_what_to_do(self):
        loading = self.guidance(has_spec=False, catalog_loading=True)
        self.assertFalse(loading.can_configure);self.assertIn('Loading', loading.message)
        missing = self.guidance(has_spec=False, version='')
        self.assertFalse(missing.can_create);self.assertIn('Choose a compatible', missing.message)

    def test_name_location_and_eula_are_explained_in_order(self):
        invalid = self.guidance(name='../bad', folder='', accepted_eula=False)
        self.assertFalse(invalid.can_create);self.assertIn('Server name:', invalid.message)
        location = self.guidance(folder='', accepted_eula=False)
        self.assertIn('where the new server folder', location.message)
        eula = self.guidance(accepted_eula=False)
        self.assertIn('Minecraft EULA', eula.message)

    def test_active_download_disables_creation(self):
        result = self.guidance(creating=True)
        self.assertFalse(result.can_configure);self.assertFalse(result.can_create)
        self.assertIn('Creating your server', result.message)


if __name__ == '__main__':
    unittest.main()
