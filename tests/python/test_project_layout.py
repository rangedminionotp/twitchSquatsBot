"""Guard paths and the package entry point after repository reorganization."""
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from squat_capture import control_panel, startup_check


class ProjectLayoutTests(unittest.TestCase):
    def test_resource_roots(self):
        root = Path(startup_check.__file__).resolve().parent.parent
        self.assertTrue((root / 'requirements.txt').is_file())
        self.assertEqual(control_panel.STATIC_ROOT, root / 'static')
        self.assertTrue((root / 'scripts/start_windows.ps1').is_file())
        self.assertTrue((root / 'scripts/start_wsl.sh').is_file())

    def test_module_entry_calls_server(self):
        with patch('squat_capture.twitch_eventsub_listener.main', return_value=0) as main:
            with self.assertRaises(SystemExit) as result:
                runpy.run_module('squat_capture', run_name='__main__')
        self.assertEqual(result.exception.code, 0)
        main.assert_called_once_with()

    def test_launchers_use_package_and_root_environment(self):
        root = Path(startup_check.__file__).resolve().parent.parent
        for name in ('start_windows.ps1', 'start_wsl.sh'):
            text = (root / 'scripts' / name).read_text(encoding='utf-8')
            self.assertIn('-m squat_capture.startup_check --repair', text)
            self.assertIn('-m squat_capture', text)
            self.assertIn('.venv', text)


if __name__ == '__main__':
    unittest.main()
