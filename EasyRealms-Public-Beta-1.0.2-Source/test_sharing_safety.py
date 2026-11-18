import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import Window
from port_forwarding import MappingRequest


class _WindowState:
    def __init__(self, server):
        self.server = Path(server)
        self.direct_forwarding_approvals = set()
        self.navigation = []

    def navigate(self, page):
        self.navigation.append(page)


class _CancelBox:
    Warning = object()
    AcceptRole = object()
    DestructiveRole = object()
    Cancel = object()
    created = 0

    def __init__(self, parent=None):
        type(self).created += 1
        self._clicked = None

    def setIcon(self, value): pass
    def setWindowTitle(self, value): pass
    def setText(self, value): pass

    def addButton(self, label, role=None):
        button = object()
        if label is self.Cancel:
            self._clicked = button
        return button

    def setDefaultButton(self, button): pass
    def exec(self): pass
    def clickedButton(self): return self._clicked


class SharingSafetyTests(unittest.TestCase):
    def test_verified_accounts_are_rechecked_even_after_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            state = _WindowState(folder)
            key = (str(Path(folder).resolve()), (("TCP", 25565),))
            state.direct_forwarding_approvals.add(key)
            with patch("app.QMessageBox.critical") as critical:
                allowed = Window.confirm_direct_forwarding(
                    state,
                    {"kind": "Vanilla"},
                    {"online-mode": "false", "white-list": "true"},
                    [MappingRequest("TCP", 25565)],
                )
            self.assertFalse(allowed)
            critical.assert_called_once()

    def test_allow_list_is_required_for_direct_sharing(self):
        with tempfile.TemporaryDirectory() as folder:
            state = _WindowState(folder)
            with patch("app.QMessageBox.critical") as critical:
                allowed = Window.confirm_direct_forwarding(
                    state,
                    {"kind": "Paper"},
                    {"online-mode": "true", "white-list": "false"},
                    [MappingRequest("TCP", 25565)],
                )
            self.assertFalse(allowed)
            critical.assert_called_once()

    def test_approval_applies_only_to_the_exact_port_set(self):
        with tempfile.TemporaryDirectory() as folder:
            state = _WindowState(folder)
            key = (str(Path(folder).resolve()), (("TCP", 25565),))
            state.direct_forwarding_approvals.add(key)
            properties = {"online-mode": "true", "white-list": "true"}
            self.assertTrue(Window.confirm_direct_forwarding(
                state, {"kind": "Vanilla"}, properties, [MappingRequest("TCP", 25565)]
            ))

            _CancelBox.created = 0
            with patch("app.QMessageBox", _CancelBox):
                allowed = Window.confirm_direct_forwarding(
                    state, {"kind": "Vanilla"}, properties, [MappingRequest("TCP", 25566)]
                )
            self.assertFalse(allowed)
            self.assertEqual(_CancelBox.created, 1)


if __name__ == "__main__":
    unittest.main()
