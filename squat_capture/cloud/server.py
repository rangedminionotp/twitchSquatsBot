"""Loopback-only cloud prototype. Deploy behind HTTPS only after release review."""
import hmac
import json
import os
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from squat_capture.cloud.oauth import TwitchOAuth
from squat_capture.cloud.store import Store, SESSION_SECONDS
from squat_capture.cloud.events import handle_event
from squat_capture.cloud.tokens import TokenService
from squat_capture.cloud.subscriptions import EventSubAPI, SubscriptionService
from squat_capture.cloud.challenges import Challenges, ChallengeConflict
from squat_capture.cloud.twitch_data import TwitchData
from squat_capture.cloud.donations import Donations, DonationWorkers
from squat_capture.cloud.http_safety import BoundedHTTPServer, RateLimiter
from squat_capture.cloud.community import Community, CommunityConflict

STATIC = Path(__file__).resolve().parents[2] / 'static' / 'cloud'


@dataclass(frozen=True)
class Settings:
    origin: str
    client_id: str
    client_secret: str
    encryption_key: str
    database: str
    port: int = 8090
    development: bool = False
    eventsub_secret: str = ''
    enable_events: bool = False
    allowed_users: str = ''
    community_owner_id: str = ''
    community_timezone: str = 'America/Los_Angeles'

    def __post_init__(self):
        url = urlsplit(self.origin)
        if not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
            raise ValueError('CLOUD_ORIGIN must be an origin without a trailing slash or path')
        if self.development:
            if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost'):
                raise ValueError('Development mode requires an HTTP loopback origin')
        elif url.scheme != 'https':
            raise ValueError('HTTPS is required outside development mode')
        if not self.client_id or not self.client_secret or not self.encryption_key:
            raise ValueError('Cloud Twitch client ID, client secret and encryption key are required')
        if self.eventsub_secret and (not self.eventsub_secret.isascii() or not 32 <= len(self.eventsub_secret) <= 100):
            raise ValueError('EventSub secret must be 32-100 ASCII characters')
        if self.community_owner_id and not self.community_owner_id.isdecimal():
            raise ValueError('CLOUD_COMMUNITY_OWNER_ID must be a numeric Twitch user ID')
        if self.enable_events and (self.development or url.scheme != 'https' or url.port not in (None, 443) or not self.eventsub_secret):
            raise ValueError('Live EventSub requires HTTPS on port 443 and CLOUD_EVENTSUB_SECRET')

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get('CLOUD_ORIGIN', ''), os.environ.get('CLOUD_TWITCH_CLIENT_ID', ''),
                   os.environ.get('CLOUD_TWITCH_CLIENT_SECRET', ''), os.environ.get('CLOUD_ENCRYPTION_KEY', ''),
                   os.environ.get('CLOUD_DATABASE', '.cloud-data/cloud.sqlite3'),
                   int(os.environ.get('CLOUD_PORT', '8090')), os.environ.get('CLOUD_DEV') == '1',
                   os.environ.get('CLOUD_EVENTSUB_SECRET', ''), os.environ.get('CLOUD_ENABLE_EVENTS') == '1',
                   os.environ.get('CLOUD_ALLOWED_USERS',''), os.environ.get('CLOUD_COMMUNITY_OWNER_ID',''),
                   os.environ.get('CLOUD_COMMUNITY_TIMEZONE','America/Los_Angeles'))


def make_handler(settings, store, oauth, token_service=None, twitch_data=None, donation_workers=None,
                 community=None):
    challenges = Challenges(store)
    donations = donation_workers.repository if donation_workers else Donations(store)
    community = community or Community(store, settings.community_owner_id, settings.community_timezone)
    limiter = RateLimiter()
    session_cookie = 'sc_session' if settings.development else '__Host-sc_session'
    state_cookie = 'sc_oauth' if settings.development else '__Host-sc_oauth'

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_args):
            # Default logs leak OAuth codes and OBS bearer URLs. No request URLs.
            pass

        def cookie(self, name):
            jar = SimpleCookie()
            try:
                jar.load(self.headers.get('Cookie', ''))
                return jar[name].value if name in jar else ''
            except Exception:
                return ''

        def cookie_header(self, name, value, seconds):
            return ('Set-Cookie', f'{name}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={seconds}'
                    + ('' if settings.development else '; Secure'))

        def reply(self, status, body=b'', mime='application/json', headers=()):
            if isinstance(body, dict):
                body = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            camera_page = urlsplit(self.path).path in ('/camera', '/viewer')
            model_host = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.22-rc.20250304/'
            policy = (f"script-src 'self' 'wasm-unsafe-eval' {model_host}; connect-src 'self' {model_host} https://storage.googleapis.com/mediapipe-models/; media-src 'self' blob:; worker-src 'self' blob:; "
                      if camera_page else "script-src 'self'; connect-src 'self'; ")
            self.send_header('Content-Security-Policy', "default-src 'none'; " + policy + "style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.send_header('Permissions-Policy', 'camera=(self), microphone=()' if camera_page else 'camera=(), microphone=()')
            if not settings.development:
                self.send_header('Strict-Transport-Security', 'max-age=31536000')
            for key, value in headers:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def redirect(self, target, headers=()):
            self.reply(303, headers=[('Location', target), *headers])

        def valid_host(self):
            if self.headers.get('Host') != urlsplit(settings.origin).netloc:
                self.reply(400, {'error': 'Unexpected host'})
                return False
            path=urlsplit(self.path).path
            if (path.startswith('/auth/') or path == '/viewer/login') and not limiter.allow('auth',30):
                self.reply(429,{'error':'Too many login attempts. Wait a minute.'})
                return False
            return True

        def do_GET(self):
            if not self.valid_host():
                return
            parsed = urlsplit(self.path)
            path = parsed.path
            if path == '/health':
                try:
                    with store.connection() as db:db.execute('SELECT 1')
                    self.reply(200,{'ok':True})
                except Exception:self.reply(503,{'ok':False})
            elif path == '/auth/twitch':
                state, binding = store.start_oauth('admin')
                events = settings.enable_events and parse_qs(parsed.query).get('events') == ['1']
                target = oauth.authorize_url(state, events=True) if events else oauth.authorize_url(state)
                self.redirect(target, [self.cookie_header(state_cookie, binding, 600)])
            elif path == '/viewer/login':
                state, binding = store.start_oauth('viewer')
                self.redirect(oauth.authorize_url(state), [self.cookie_header(state_cookie, binding, 600)])
            elif path == '/auth/callback':
                query = parse_qs(parsed.query)
                state = query.get('state', [''])[0]
                clear = self.cookie_header(state_cookie, '', 0)
                purpose = store.consume_oauth(state, self.cookie(state_cookie))
                if not purpose:
                    self.reply(400, {'error': 'Invalid or expired login. Start again.'}, headers=[clear])
                    return
                if 'error' in query or not query.get('code'):
                    self.reply(400, {'error': 'Authorization was not completed. Start again.'}, headers=[clear])
                    return
                try:
                    identity, tokens = oauth.exchange(query['code'][0])
                    allowed = {value.strip() for value in settings.allowed_users.split(',') if value.strip()}
                    if purpose == 'admin' and not settings.development and identity['user_id'] not in allowed:
                        self.reply(403,{'error':'This beta is invite-only. Ask the operator to allow your Twitch user ID.'},headers=[clear])
                        return
                    token = store.login(identity, tokens, role=purpose)
                    if token_service:
                        token_service.invalidate(identity['user_id'])
                except Exception:
                    # Do not expose OAuth response bodies, tokens or DB errors.
                    self.reply(502, {'error': 'Twitch login failed. Please retry.'}, headers=[clear])
                    return
                store.logout(self.cookie(session_cookie))
                self.redirect('/viewer' if purpose == 'viewer' else '/',
                              [clear, self.cookie_header(session_cookie, token, SESSION_SECONDS)])
            elif path == '/api/me':
                session = store.session(self.cookie(session_cookie))
                if not session:
                    self.reply(401, {'error': 'Login required'})
                    return
                if session['role'] != 'admin':
                    self.reply(403, {'error': 'Broadcaster access required'})
                    return
                self.reply(200, {'user': store.profile(session['user_id']), 'csrf': session['csrf'],
                                 'authorization': store.auth_health(session['user_id']),
                                 'rules': store.rules(session['user_id']), 'queue': store.queue(session['user_id']),
                                 'stage': 'event-subscription-lifecycle', 'event_listener': store.listener(session['user_id']),
                                 'events_available': settings.enable_events,
                                 'challenge': challenges.state(session['user_id']),
                                 'stream': store.stream_summary(session['user_id']),
                                 'donations': donations.public(session['user_id']),
                                 'donation_status': donation_workers.status(session['user_id']) if donation_workers else {},
                                 'capture': 'browser_preview'})
            elif path == '/api/community':
                try:
                    self.reply(200, community.public())
                except CommunityConflict as error:
                    self.reply(503, {'error':str(error)})
            elif path == '/api/community/admin':
                session = store.session(self.cookie(session_cookie))
                if not session:
                    self.reply(401, {'error':'Login required'})
                elif session['role'] != 'admin':
                    self.reply(403, {'error':'Broadcaster access required'})
                else:
                    try:self.reply(200, community.admin(session['user_id']))
                    except CommunityConflict as error:self.reply(403, {'error':str(error)})
            elif path == '/api/viewer':
                session = store.session(self.cookie(session_cookie))
                if not session:
                    self.reply(401, {'error':'Login required'})
                    return
                try:
                    profile = store.profile(session['user_id'])
                    self.reply(200, {'user':{'login':profile['login']}, 'csrf':session['csrf'],
                                     'community':community.viewer(session['user_id'])})
                except CommunityConflict as error:
                    self.reply(503, {'error':str(error)})
            elif path == '/api/rewards':
                session = store.session(self.cookie(session_cookie))
                if not session:
                    self.reply(401, {'error':'Login required'})
                elif session['role'] != 'admin':
                    self.reply(403, {'error':'Broadcaster access required'})
                elif not twitch_data:
                    self.reply(503, {'error':'Twitch data service unavailable'})
                else:
                    try:
                        self.reply(200, {'rewards':twitch_data.rewards(session['user_id'])})
                    except Exception:
                        self.reply(502, {'error':'Could not load rewards. Check event permissions, Twitch connection and Channel Points eligibility.'})
            elif path == '/api/capture/run':
                session = store.session(self.cookie(session_cookie))
                if not session:
                    self.reply(401, {'error': 'Login required'})
                    return
                if session['role'] != 'admin':
                    self.reply(403, {'error': 'Broadcaster access required'})
                    return
                run_id = parse_qs(parsed.query).get('id', [''])[0]
                with store.connection() as db:
                    run = challenges.snapshot(db, session['user_id'], run_id) if run_id else None
                self.reply(200 if run else 404, {'run':run} if run else {'error':'Challenge not found'})
            elif path == '/camera':
                session = store.session(self.cookie(session_cookie))
                if not session or session['role'] != 'admin':
                    self.redirect('/')
                    return
                self.reply(200, (STATIC / 'camera.html').read_bytes(), 'text/html; charset=utf-8')
            elif path == '/viewer':
                self.reply(200, (STATIC / 'viewer.html').read_bytes(), 'text/html; charset=utf-8')
            elif path in ('/privacy','/rules'):
                self.reply(200, (STATIC / (path.removeprefix('/') + '.html')).read_bytes(), 'text/html; charset=utf-8')
            elif path in ('/assets/camera.js', '/assets/capture-core.mjs', '/assets/pose.mjs', '/assets/camera.css',
                          '/assets/donations.js', '/assets/viewer.js', '/assets/viewer-core.mjs', '/assets/viewer.css',
                          '/assets/legal.css'):
                name = path.removeprefix('/assets/')
                mime = 'text/css' if name.endswith('.css') else 'text/javascript'
                self.reply(200, (STATIC / name).read_bytes(), mime + '; charset=utf-8')
            elif path.startswith('/api/overlay/'):
                public = store.overlay(path.removeprefix('/api/overlay/'), include_stream=True)
                self.reply(200 if public else 404, public or {'error': 'Overlay link invalid or reset'})
            elif path.startswith('/overlay/'):
                if not store.overlay(path.removeprefix('/overlay/')):
                    self.reply(404, {'error': 'Overlay link invalid or reset'})
                    return
                self.reply(200, (STATIC / 'overlay.html').read_bytes(), 'text/html; charset=utf-8')
            elif path in ('/', '/assets/cloud.js', '/assets/cloud.css'):
                name, mime = {'/': ('index.html', 'text/html'), '/assets/cloud.js': ('cloud.js', 'text/javascript'),
                              '/assets/cloud.css': ('cloud.css', 'text/css')}[path]
                self.reply(200, (STATIC / name).read_bytes(), mime + '; charset=utf-8')
            else:
                self.reply(404, {'error': 'Not found'})

        def do_POST(self):
            if not self.valid_host():
                return
            if urlsplit(self.path).path == '/eventsub':
                if not settings.enable_events:
                    self.reply(503, b'EventSub not enabled', 'text/plain')
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 65536 or self.headers.get('Transfer-Encoding'):
                        raise ValueError('Invalid body size')
                    status, body = handle_event(store, settings.eventsub_secret, self.headers, self.rfile.read(length))
                    self.reply(status, body, 'text/plain; charset=utf-8')
                except ValueError:
                    self.reply(400, {'error': 'Invalid body size'})
                return
            session_token = self.cookie(session_cookie)
            session = store.session(session_token)
            if not session:
                self.reply(401, {'error': 'Login required'})
                return
            path = urlsplit(self.path).path
            viewer_paths = {'/api/viewer/start','/api/viewer/calibrate','/api/viewer/progress',
                            '/api/viewer/delete','/api/logout'}
            if session['role'] != 'admin' and path not in viewer_paths:
                self.reply(403, {'error': 'Broadcaster access required'})
                return
            if not limiter.allow('write:'+session['user_id'],300):
                self.reply(429,{'error':'Too many changes. Wait a minute.'})
                return
            if (self.headers.get('Origin') != settings.origin or
                    not hmac.compare_digest(self.headers.get('X-CSRF-Token', '').encode(), session['csrf'].encode())):
                self.reply(403, {'error': 'Request verification failed'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096 or self.headers.get('Content-Type') != 'application/json' or self.headers.get('Transfer-Encoding'):
                    raise ValueError('Expected a small JSON request')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Expected a JSON object')
                if path == '/api/owed' and set(payload) == {'owed'}:
                    self.reply(200, {'user': store.set_owed(session['user_id'], payload['owed'])})
                elif path == '/api/rules':
                    self.reply(200, {'rules': store.save_rules(session['user_id'], payload)})
                elif path == '/api/challenge/start' and set(payload) == {'request_id'}:
                    self.reply(200, {'challenge': challenges.start(session['user_id'],payload['request_id'])})
                elif path == '/api/capture/free' and set(payload) == {'request_id','target'}:
                    self.reply(200, {'challenge': challenges.start(session['user_id'],payload['request_id'],payload['target'])})
                elif path == '/api/capture/end' and set(payload) == {'run_id'}:
                    self.reply(200, {'challenge': challenges.end_free(session['user_id'],payload['run_id'])})
                elif path == '/api/donations' and set(payload) == {'source','settings'} and isinstance(payload['settings'],dict):
                    self.reply(200, {'donations': donations.save(session['user_id'],payload['source'],payload['settings'])})
                elif path == '/api/challenge/pause' and set(payload) == {'run_id'}:
                    self.reply(200, {'challenge': challenges.pause(session['user_id'],payload['run_id'])})
                elif path == '/api/capture/claim' and set(payload) == {'run_id','page_id'}:
                    self.reply(200, challenges.claim(session['user_id'],payload['run_id'],payload['page_id']))
                elif path == '/api/capture/progress' and set(payload) == {'run_id','lease','count'}:
                    self.reply(200, challenges.progress(session['user_id'],payload['run_id'],payload['lease'],payload['count']))
                elif path == '/api/listener' and set(payload) == {'enabled'}:
                    if payload['enabled'] is True and not settings.enable_events:
                        self.reply(409, {'error': 'Live events are not enabled on this server'})
                        return
                    store.enable_listener(session['user_id'], payload['enabled'])
                    self.reply(200, {'listener': store.listener(session['user_id'])})
                elif path == '/api/overlay/rotate' and not payload:
                    token = store.rotate_overlay(session['user_id'])
                    self.reply(200, {'url': settings.origin + '/overlay/' + token})
                elif path == '/api/logout' and not payload:
                    store.logout(session_token)
                    self.reply(200, {'ok': True}, headers=[self.cookie_header(session_cookie, '', 0)])
                elif path == '/api/account/delete' and payload == {'confirm':'DELETE'}:
                    try:store.delete_account(session['user_id'])
                    except ValueError as error:
                        self.reply(409,{'error':str(error)})
                        return
                    self.reply(200,{'ok':True},headers=[self.cookie_header(session_cookie,'',0)])
                elif path == '/api/community/revoke' and set(payload) == {'contribution_id'}:
                    self.reply(200,community.revoke(session['user_id'],payload['contribution_id']))
                elif path == '/api/viewer/start' and not payload:
                    self.reply(200, {'run':community.start(session['user_id']),
                                     'community':community.viewer(session['user_id'])})
                elif path == '/api/viewer/calibrate' and set(payload) == {'run_id','standing_angle','squat_angle','duration_ms'}:
                    run = community.calibrate(session['user_id'],payload['run_id'],payload['standing_angle'],
                                              payload['squat_angle'],payload['duration_ms'])
                    self.reply(200, {'run':run, 'community':community.viewer(session['user_id'])})
                elif path == '/api/viewer/progress' and set(payload) == {'run_id','sequence','count','elapsed_ms'}:
                    run = community.progress(session['user_id'],payload['run_id'],payload['sequence'],
                                             payload['count'],payload['elapsed_ms'])
                    self.reply(200, {'run':run, 'community':community.viewer(session['user_id'])})
                elif path == '/api/viewer/delete' and payload == {'confirm':'DELETE'}:
                    if session['role'] != 'viewer':
                        self.reply(403,{'error':'Viewer session required'})
                        return
                    store.delete_viewer_data(session['user_id'],settings.community_owner_id)
                    self.reply(200,{'ok':True},headers=[self.cookie_header(session_cookie,'',0)])
                else:
                    self.reply(400, {'error': 'Unknown action or unexpected fields'})
            except ChallengeConflict as error:
                self.reply(409, {'error':str(error)})
            except CommunityConflict as error:
                self.reply(409, {'error':str(error)})
            except (ValueError, UnicodeDecodeError):
                self.reply(400, {'error': 'Invalid request or counter value'})

    return Handler


def main():
    settings = Settings.from_environment()
    store = Store(settings.database, settings.encryption_key)
    oauth = TwitchOAuth(settings.client_id, settings.client_secret, settings.origin + '/auth/callback')
    tokens = TokenService(store, oauth)
    twitch_data = TwitchData(store,tokens,settings.client_id)
    donation_workers = DonationWorkers(Donations(store))
    server = BoundedHTTPServer(('127.0.0.1', settings.port), make_handler(settings, store, oauth, tokens, twitch_data, donation_workers))
    subscriptions = SubscriptionService(store, tokens, EventSubAPI(settings.client_id, settings.client_secret),
                                       settings.origin + '/eventsub', settings.eventsub_secret) if settings.enable_events else None
    tokens.start()
    twitch_data.start()
    donation_workers.start()
    if subscriptions:
        subscriptions.start()
    print('Cloud prototype: identity, rules, event receiver and persistent queue. Not a public release.')
    print(f'Listening on loopback port {settings.port}. Live events configured: {settings.enable_events}. Camera preview: /camera.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        donation_workers.stop()
        twitch_data.stop()
        if subscriptions:
            subscriptions.stop()
        tokens.stop()
        server.server_close()
