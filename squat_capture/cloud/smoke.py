"""Read-only public deployment checks for the HTTPS edge and Viewer surface."""
import argparse
import json
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def fetch(origin, path):
    request = Request(origin + path,headers={'User-Agent':'SquatCapture-Deployment-Check/1'})
    opener = build_opener(_NoRedirect)
    try:
        response = opener.open(request,timeout=8)
    except HTTPError as error:
        response = error
    with response:
        body = response.read(1024 * 1024)
        return response.status,body,{key.lower():value for key,value in response.headers.items()}


def inspect_deployment(origin, include_oauth=False, requester=fetch):
    checks = []

    def add(ok,label,detail):
        checks.append(('PASS' if ok else 'FAIL',label,detail))

    parsed = urlsplit(origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or
            parsed.path or parsed.query or parsed.fragment or parsed.port not in (None,443)):
        return [('FAIL','origin','Expected an HTTPS origin on port 443 without a path or trailing slash')]

    responses = {}
    for path in ('/health','/viewer','/privacy','/rules','/api/me','/assets/%2e%2e/server.py'):
        try:
            responses[path] = requester(origin,path)
        except Exception:
            responses[path] = (0,b'',{})

    status,body,headers = responses['/health']
    try:
        healthy = status == 200 and json.loads(body) == {'ok':True}
    except Exception:
        healthy = False
    add(healthy,'health endpoint','HTTPS edge can reach the application database')

    for path,needle,label in (('/viewer',b'Community Squats','viewer page'),
                              ('/privacy',b'Your camera stays with you','privacy page'),
                              ('/rules',b'No economic value','rules page')):
        status,body,_ = responses[path]
        add(status == 200 and needle in body,label,'Expected public content is available')
    add(responses['/api/me'][0] == 401,'anonymous API boundary','Broadcaster data requires login')
    add(responses['/assets/%2e%2e/server.py'][0] == 404,'static traversal boundary','Non-allowlisted asset is rejected')

    for path in ('/health','/viewer','/privacy','/rules','/api/me'):
        _status,_body,headers = responses[path]
        secure = ('max-age=' in headers.get('strict-transport-security','') and
                  headers.get('x-content-type-options') == 'nosniff' and
                  headers.get('x-frame-options') == 'DENY' and
                  'no-store' in headers.get('cache-control','') and
                  "default-src 'none'" in headers.get('content-security-policy',''))
        add(secure,f'security headers {path}','HSTS, no-store, nosniff, frame denial and CSP are present')
    add('camera=(self)' in responses['/viewer'][2].get('permissions-policy',''),
        'viewer camera policy','Camera permission is scoped to the Viewer page')
    add('camera=()' in responses['/privacy'][2].get('permissions-policy',''),
        'legal camera policy','Legal pages cannot request camera access')

    if include_oauth:
        try:
            status,_body,headers = requester(origin,'/viewer/login')
        except Exception:
            status,headers = 0,{}
        location = headers.get('location','')
        cookie = headers.get('set-cookie','')
        add(status == 303 and location.startswith('https://id.twitch.tv/oauth2/authorize?'),
            'Viewer OAuth redirect','Login starts at Twitch over HTTPS')
        add('__Host-sc_oauth=' in cookie and 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie,
            'OAuth state cookie','Host-only secure browser binding is present')
    return checks


def main():
    parser = argparse.ArgumentParser(description='Check a deployed Squat Capture public beta without signing in.')
    parser.add_argument('origin',help='Exact public origin, for example https://squats.example.com')
    parser.add_argument('--oauth',action='store_true',help='Also create one transient OAuth state and inspect its redirect/cookie')
    args = parser.parse_args()
    checks = inspect_deployment(args.origin,args.oauth)
    for level,label,detail in checks:
        print(f'{level:4}  {label}: {detail}')
    failures = sum(level == 'FAIL' for level,_,_ in checks)
    if failures:
        print(f'NOT READY: {failures} deployment check(s) failed.')
        raise SystemExit(1)
    print('READY: public edge passed automated smoke checks. Real account and camera checks are still required.')


if __name__ == '__main__':
    main()
