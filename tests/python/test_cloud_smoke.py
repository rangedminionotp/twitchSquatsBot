"""Deployment smoke checker stays read-only unless OAuth inspection is requested."""
import json
import unittest

from squat_capture.cloud.smoke import inspect_deployment


class CloudSmokeTests(unittest.TestCase):
    def requester(self,origin,path):
        headers = {'strict-transport-security':'max-age=31536000','x-content-type-options':'nosniff',
                   'x-frame-options':'DENY','cache-control':'no-store',
                   'content-security-policy':"default-src 'none'; script-src 'self'",
                   'permissions-policy':'camera=(self), microphone=()' if path == '/viewer' else 'camera=(), microphone=()'}
        values = {
            '/health':(200,json.dumps({'ok':True}).encode()),
            '/viewer':(200,b'Community Squats'),'/privacy':(200,b'Your camera stays with you'),
            '/rules':(200,b'No economic value'),'/api/me':(401,b'{}'),
            '/assets/%2e%2e/server.py':(404,b'{}')}
        status,body = values[path]
        return status,body,headers

    def test_expected_public_surface_passes(self):
        checks = inspect_deployment('https://squats.example.com',requester=self.requester)
        self.assertFalse([check for check in checks if check[0] == 'FAIL'],checks)

    def test_bad_origin_and_broken_boundary_fail(self):
        self.assertEqual(inspect_deployment('http://127.0.0.1:8090')[0][0],'FAIL')
        def broken(origin,path):
            status,body,headers = self.requester(origin,path)
            if path == '/api/me':status=200
            headers.pop('strict-transport-security',None)
            return status,body,headers
        checks = inspect_deployment('https://squats.example.com',requester=broken)
        failures = {label for level,label,_ in checks if level == 'FAIL'}
        self.assertIn('anonymous API boundary',failures)
        self.assertIn('security headers /viewer',failures)

    def test_oauth_check_is_explicit_and_checks_cookie(self):
        calls=[]
        def oauth(origin,path):
            calls.append(path)
            if path == '/viewer/login':
                return 303,b'',{'location':'https://id.twitch.tv/oauth2/authorize?state=x',
                                'set-cookie':'__Host-sc_oauth=x; Secure; HttpOnly; SameSite=Lax'}
            return self.requester(origin,path)
        self.assertNotIn('/viewer/login',calls)
        checks=inspect_deployment('https://squats.example.com',include_oauth=True,requester=oauth)
        self.assertIn('/viewer/login',calls)
        self.assertFalse([check for check in checks if check[0] == 'FAIL'],checks)


if __name__ == '__main__':
    unittest.main()
