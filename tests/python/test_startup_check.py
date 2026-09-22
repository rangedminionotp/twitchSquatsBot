import tempfile
import unittest
from unittest.mock import patch, Mock
from pathlib import Path

from squat_capture import startup_check


class StartupTests(unittest.TestCase):
    def test_missing_dependencies(self):
        with patch('squat_capture.startup_check.importlib.import_module', side_effect=ImportError):
            self.assertEqual(startup_check.dependency_errors(), ['requests', 'websocket-client'])

    def test_compatible_dependencies(self):
        with patch.object(startup_check.importlib.metadata, 'version', side_effect=['2.31.0', '1.8.0']), patch.object(startup_check.importlib, 'import_module', return_value=Mock(create_connection=Mock())):
            self.assertEqual(startup_check.dependency_errors(), [])

    def test_old_versions(self):
        with patch.object(startup_check.importlib.metadata, 'version', side_effect=['2.20.0', '1.7.0']), patch.object(startup_check.importlib, 'import_module'):
            self.assertEqual(len(startup_check.dependency_errors()), 2)

    def test_storage_probe_leaves_no_files(self):
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'SQUAT_CAPTURE_DATA_DIR': root}):
            self.assertTrue(startup_check.check_storage())
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_storage_error(self):
        with patch('squat_capture.startup_check.tempfile.TemporaryFile', side_effect=OSError), patch('squat_capture.startup_check.Path.mkdir'):
            self.assertFalse(startup_check.check_storage())

    def test_refuses_global_install(self):
        with patch.object(startup_check, 'dependency_errors', return_value=['requests']), patch.object(startup_check.sys, 'argv', ['squat_capture.startup_check.py', '--repair']), patch.object(startup_check.sys, 'prefix', startup_check.sys.base_prefix), patch('squat_capture.startup_check.subprocess.call') as install:
            self.assertEqual(startup_check.main(), 1)
            install.assert_not_called()

    def test_no_install_when_healthy(self):
        with patch.object(startup_check, 'dependency_errors', return_value=[]), patch.object(startup_check, 'check_storage', return_value=True), patch('squat_capture.startup_check.subprocess.call') as install:
            self.assertEqual(startup_check.main(), 0)
            install.assert_not_called()


if __name__ == '__main__':
    unittest.main()
