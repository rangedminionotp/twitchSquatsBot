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
                self.telemetry['pending'] = max(0, min(100000, int(data.get('pending', 0))))
                return {**self.snapshot(), 'owns_camera': True}
            return self.snapshot()


CAMERA_CONTROL = CameraControl()

CAMERA_STYLE = '''<style>
html,body{margin:0!important;padding:0!important;background:#000!important;overflow:hidden!important}
.shell{display:block!important;width:100vw!important;max-width:none!important;height:100vh!important;margin:0!important;padding:0!important}
.stage{width:100vw!important;height:100vh!important;min-height:0!important;border:0!important;border-radius:0!important;box-shadow:none!important}
#video,#overlayCanvas{width:100%!important;height:100%!important;object-fit:contain!important}
.panel{display:none!important}.stage>.overlay{display:none!important}
body[data-camera-mode="capture"] .stage>.overlay{display:flex!important}
body[data-camera-mode="webcam"] #overlayCanvas{display:none!important}
#cameraTools{position:fixed;top:12px;left:12px;right:12px;z-index:20;padding:12px;background:#101827eb;border-radius:12px;color:white;font:14px system-ui;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
#cameraTools select{max-width:260px}#cameraTools p{margin:0;width:100%}
body.clean #cameraTools{display:none}#cameraWarning{position:fixed;bottom:10px;left:12px;z-index:21;color:#ffb4b4;background:#17121bef;max-width:80%;white-space:pre-wrap;font:13px system-ui}
</style>'''
