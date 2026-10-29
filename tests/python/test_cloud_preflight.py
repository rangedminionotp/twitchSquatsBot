"""Production preflight must fail closed without exposing secret values."""
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from squat_capture.cloud.preflight import inspect_environment


class CloudPreflightTests(unittest.TestCase):
    def environment(self, root):
        backup = root/'backups';backup.mkdir(mode=0o700)
        return {
            'CLOUD_DEV':'0','CLOUD_ORIGIN':'https://squats.example.com','CLOUD_PORT':'8090',
            'CLOUD_TWITCH_CLIENT_ID':'real-client-id','CLOUD_TWITCH_CLIENT_SECRET':'real-client-secret',
            'CLOUD_ENCRYPTION_KEY':Fernet.generate_key().decode(),
            'CLOUD_DATABASE':str(root/'cloud.sqlite3'),'CLOUD_ENABLE_EVENTS':'0',
            'CLOUD_BACKUP_DIRECTORY':str(backup),'CLOUD_BACKUP_RETENTION_DAYS':'7',
            'CLOUD_ALLOWED_USERS':'11,22','CLOUD_COMMUNITY_OWNER_ID':'11',
            'CLOUD_COMMUNITY_TIMEZONE':'America/Los_Angeles'}

    def test_valid_beta_configuration_passes_and_hides_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);root.chmod(0o700)
            env = self.environment(root)
            checks = inspect_environment(env,platform='posix')
            self.assertFalse([check for check in checks if check[0] == 'FAIL'],checks)
            rendered = repr(checks)
            self.assertNotIn(env['CLOUD_TWITCH_CLIENT_SECRET'],rendered)
            self.assertNotIn(env['CLOUD_ENCRYPTION_KEY'],rendered)
            self.assertIn('database bootstrap',rendered)

    def test_local_placeholder_and_bad_admission_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);root.chmod(0o755)
            env = self.environment(root)
            env.update(CLOUD_DEV='1',CLOUD_ORIGIN='http://127.0.0.1:8090',
                       CLOUD_TWITCH_CLIENT_SECRET='change-me',CLOUD_ALLOWED_USERS='22')
            checks = inspect_environment(env,platform='posix')
            failures = {label for level,label,_ in checks if level == 'FAIL'}
            self.assertTrue({'runtime mode','public origin','public hostname','Twitch client secret',
                             'owner admission','database directory permissions'} <= failures)

    def test_invalid_base_settings_are_reported_as_one_safe_failure(self):
        checks = inspect_environment({},platform='posix')
        self.assertEqual(checks[0][0:2],('FAIL','configuration'))


if __name__ == '__main__':
    unittest.main()
