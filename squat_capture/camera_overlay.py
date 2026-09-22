import threading
import time


class CameraControl:
    def __init__(self):
        self.lock = threading.RLock()
        self.mode = "webcam"
        self.last_seen = None
        self.owner = None
        self.telemetry = {}

    def snapshot(self):
        with self.lock:
            live = self.last_seen is not None and time.monotonic() - self.last_seen < 8
            return {"mode": self.mode, "page_connected": live, "telemetry": dict(self.telemetry) if live else {}}

    def owns(self, page_id):
        with self.lock:
            return bool(page_id and page_id == self.owner and self.snapshot()['page_connected'])

    def update(self, payload):
        with self.lock:
            if "mode" in payload:
                if payload["mode"] not in ("webcam", "capture"):
                    raise ValueError("Mode must be webcam or capture")
                self.mode = payload["mode"]
            if payload.get("heartbeat") is True:
                page_id = payload.get('page_id', 'legacy')
                if not isinstance(page_id, str) or not 1 <= len(page_id) <= 100:
                    raise ValueError('Invalid camera page')
                if self.snapshot()['page_connected'] and self.owner != page_id:
                    return {**self.snapshot(), 'owns_camera': False}
                self.owner = page_id
                self.last_seen = time.monotonic()
                data = payload.get('telemetry', {})
                self.telemetry = {key: data.get(key) is True for key in ('camera_live', 'model_ready', 'body_detected', 'storage_ok')}
                self.telemetry['actual_mode'] = 'capture' if data.get('actual_mode') == 'capture' else 'webcam'
                code = data.get('error_code')
                self.telemetry['error_code'] = code if code in ('permission_denied', 'camera_unavailable', 'model_failed') else ''
                self.telemetry['pending'] = max(0, min(100000, int(data.get('pending', 0))))
                return {**self.snapshot(), 'owns_camera': True}
            return self.snapshot()


CAMERA_CONTROL = CameraControl()
