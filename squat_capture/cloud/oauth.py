"""Server-side code exchange. Credentials never enter browser JSON responses."""
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json


def json_request(url, data=None, headers=None):
    request = Request(url, data=urlencode(data).encode() if data is not None else None,
                      headers=headers or {})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


class TwitchOAuth:
    def __init__(self, client_id, client_secret, redirect_uri):
        self.client_id, self.client_secret, self.redirect_uri = client_id, client_secret, redirect_uri

    def authorize_url(self, state, events=False):
        return 'https://id.twitch.tv/oauth2/authorize?' + urlencode({
            'client_id': self.client_id, 'redirect_uri': self.redirect_uri,
            'response_type': 'code', 'scope': 'channel:read:redemptions channel:read:subscriptions bits:read' if events else '', 'state': state,
        })

    def exchange(self, code):
        tokens = json_request('https://id.twitch.tv/oauth2/token', data={
            'client_id': self.client_id, 'client_secret': self.client_secret,
            'code': code, 'grant_type': 'authorization_code', 'redirect_uri': self.redirect_uri,
        })
        identity = self.validate(tokens['access_token'])
        if identity.get('client_id') != self.client_id or not identity.get('user_id') or not identity.get('login'):
            raise ValueError('Token identity validation failed')
        return identity, {**{key: tokens[key] for key in ('access_token', 'refresh_token', 'expires_in')},
                          'scopes': identity.get('scopes', [])}

    def validate(self, access_token):
        return json_request('https://id.twitch.tv/oauth2/validate',
                            headers={'Authorization':'OAuth '+access_token})

    def refresh(self, refresh_token):
        return json_request('https://id.twitch.tv/oauth2/token', data={
            'client_id':self.client_id, 'client_secret':self.client_secret,
            'grant_type':'refresh_token', 'refresh_token':refresh_token,
        })
