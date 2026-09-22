"""Regression coverage for the static control panel and asset boundary."""
import http.client
import json
import re
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from squat_capture.control_panel import ASSETS, CONTROL_HTML, POPUP_HTML, OVERLAY_HTML, STATIC_ROOT, static_asset
from squat_capture import twitch_eventsub_listener as server_module
from squat_capture.twitch_eventsub_listener import EventSubHandler


class ControlPanelTests(unittest.TestCase):
    def test_capture_overlay_assets_are_external(self):
        for html in (POPUP_HTML, OVERLAY_HTML, server_module.build_refresh_overlay_html()):
            self.assertNotIn('<style>', html)
            self.assertNotIn('<script>', html)
            self.assertNotRegex(html, r'%[A-Z_]+%')
            for asset in re.findall(r'(?:src|href)="(/static/[^"]+)"', html):
                self.assertIsNotNone(static_asset(asset), asset)

    def test_refresh_first_frame_and_escaping(self):
        with patch.object(server_module.OVERLAY_STATE, 'snapshot', return_value={
            'status': 'active', 'user_name': '<script>bad</script>', 'reward_title': 'Reps'
        }), patch.object(server_module.POPUP_STATE, 'progress_snapshot', return_value={
            'squat_count': 3, 'squat_target': 10
        }):
            html = server_module.build_refresh_overlay_html('#00ff00')
        self.assertIn('--page-background: #00ff00; --progress: 30%', html)
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;', html)
        self.assertIn('class="count">3</div>', html)
        self.assertNotRegex(html, r'%[A-Za-z_][A-Za-z_()]*%')

    def test_template_uses_modules(self):
        self.assertIn('type="module" src="/static/control/js/app.js"', CONTROL_HTML)
        self.assertNotIn('<style>', CONTROL_HTML)
        self.assertNotIn('<script>', CONTROL_HTML)
        ids = re.findall(r'\bid="([^"]+)"', CONTROL_HTML)
        self.assertEqual(len(ids), len(set(ids)))

    def test_assets_and_imports_are_shipped(self):
        for url, (relative, mime) in ASSETS.items():
            body, actual_mime = static_asset(url)
            self.assertTrue(body)
            self.assertEqual(mime, actual_mime)
            if relative.endswith('.js'):
                for module in re.findall(r"^import[^\n]+from ['\"]([^'\"]+)['\"]", body.decode(), re.MULTILINE):
                    target = STATIC_ROOT / module.removeprefix('/static/') if module.startswith('/static/') else (STATIC_ROOT / relative).parent / module
                    shipped = '/static/' + target.resolve().relative_to(STATIC_ROOT.resolve()).as_posix()
                    self.assertIn(shipped, ASSETS)

    def test_arbitrary_paths_are_not_assets(self):
        for path in ['/static/../app_config.py', '/static/%2e%2e/app_config.py',
                     '/static/js/../../config.json', '/static/package.json',
                     '/static/js/app.js/extra', '/static/missing.js']:
            self.assertIsNone(static_asset(path))

    def test_http_routes_and_mime(self):
        class QuietHandler(EventSubHandler):
            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path, status, mime in [('/control', 200, 'text/html'),
                                       ('/api/web-config', 200, 'application/json'),
                                       ('/control/', 200, 'text/html'),
                                       ('/capture/', 200, 'text/html'),
                                       ('/capture', 200, 'text/html'),
                                       ('/camera-overlay', 200, 'text/html'),
                                       ('/squat-popup', 200, 'text/html'),
                                       ('/overlay', 200, 'text/html'),
                                       ('/overlay/', 200, 'text/html'),
                                       ('/overlay-refresh', 200, 'text/html'),
                                       ('/overlay-key', 200, 'text/html'),
                                       ('/overlay-magenta-key', 200, 'text/html'),
                                       ('/static/control/js/app.js', 200, 'text/javascript'),
                                       ('/static/js/app.js?v=1', 200, 'text/javascript'),
                                       ('/static/css/tokens.css', 200, 'text/css'),
                                       ('/static/../app_config.py', 404, 'text/html')]:
                connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                try:
                    connection.request('GET', path)
                    response = connection.getresponse()
                    self.assertEqual(response.status, status)
                    self.assertTrue(response.getheader('Content-Type').startswith(mime))
                    body = response.read()
                    self.assertTrue(body)
                    if path == '/api/web-config':
                        config = json.loads(body)
                        self.assertEqual(set(config), {'popupEventsPath', 'squatProgressPath', 'squatCompletePath', 'defaultSquatTarget', 'popupVersion', 'overlayEventsPath', 'overlayStatePath'})
                        self.assertEqual(config['popupEventsPath'], server_module.POPUP_EVENTS_PATH)
                    if status == 200 and path.startswith('/static/'):
                        self.assertEqual(response.getheader('X-Content-Type-Options'), 'nosniff')
                finally:
                    connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
