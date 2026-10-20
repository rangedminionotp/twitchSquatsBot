import unittest
from unittest.mock import patch
from squat_capture.camera_overlay import CameraControl


class CameraTests(unittest.TestCase):
    def test_modes(self):
        camera = CameraControl()
        self.assertEqual(camera.snapshot()['mode'], 'webcam')
        self.assertEqual(camera.update({'mode': 'capture'})['mode'], 'capture')
        with self.assertRaises(ValueError):
            camera.update({'mode': 'invalid'})
        self.assertEqual(camera.snapshot()['mode'], 'capture')

    def test_heartbeat_expiry(self):
        camera = CameraControl()
        with patch('squat_capture.camera_overlay.time.monotonic', return_value=100):
            self.assertFalse(camera.snapshot()['page_connected'])
            self.assertTrue(camera.update({'heartbeat': True})['page_connected'])
        with patch('squat_capture.camera_overlay.time.monotonic', return_value=109):
            self.assertFalse(camera.snapshot()['page_connected'])

    def test_exclusive_owner_and_expiry(self):
        camera = CameraControl()
        with patch('squat_capture.camera_overlay.time.monotonic', return_value=100):
            self.assertTrue(camera.update({'heartbeat': True, 'page_id':'a', 'telemetry':{'camera_live':True}})['owns_camera'])
            self.assertFalse(camera.update({'heartbeat': True, 'page_id':'b'})['owns_camera'])
            self.assertTrue(camera.owns('a'))
            self.assertFalse(camera.owns('b'))
        with patch('squat_capture.camera_overlay.time.monotonic', return_value=109):
            self.assertEqual(camera.snapshot()['telemetry'], {})
            self.assertTrue(camera.update({'heartbeat': True, 'page_id':'b'})['owns_camera'])
            self.assertFalse(camera.owns('a'))

    def test_telemetry_allowlist(self):
        camera = CameraControl()
        status=camera.update({'heartbeat':True,'page_id':'a','telemetry':{'camera_live':True,'token':'secret','pending':2}})
        self.assertNotIn('token',str(status))
        self.assertEqual(status['telemetry']['pending'],2)

    def test_camera_error_codes_are_bounded(self):
        camera = CameraControl()
        for code in ('permission_denied', 'camera_unavailable', 'model_failed', 'private detail'):
            status = camera.update({'heartbeat': True, 'page_id': 'a', 'telemetry': {'error_code': code}})
            self.assertEqual(status['telemetry']['error_code'], '' if code == 'private detail' else code)

    def test_calibration_stage_is_bounded(self):
        camera = CameraControl()
        for stage in ('required','standing','lowering','returning','ready','private detail'):
            status=camera.update({'heartbeat':True,'page_id':'a','telemetry':{'calibration':stage}})
            self.assertEqual(status['telemetry']['calibration'],'unknown' if stage=='private detail' else stage)


if __name__ == '__main__':
    unittest.main()
