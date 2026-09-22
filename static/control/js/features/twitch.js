import {json} from '../api.js';
import {$} from '../render.js';

export function initTwitch(ctx) {
  async function refresh() {
    try {
      const data = await json('/api/settings');
      ctx.settings = data.settings;
      ctx.applyLeagueSettings(data.settings);
      const connected = data.twitch.state === 'connected';
      $('twitchProfile').hidden = !data.settings.broadcaster_login;
      $('twitchName').textContent = data.settings.broadcaster_login || '';
      const avatar = data.settings.broadcaster_avatar || '';
      $('twitchAvatar').hidden = !avatar.startsWith('https://');
      if (!$('twitchAvatar').hidden) $('twitchAvatar').src = avatar;
      $('login').textContent = connected ? 'Reconnect Twitch' : 'Connect with Twitch';
      if (data.settings.twitch_access_token) await ctx.loadRewards();
    } catch (error) {
      $('loginHelp').textContent = error.message;
      $('loginHelp').className = 'status bad';
    }
  }

  $('login').onclick = async () => {
    try {
      $('login').disabled = true;
      const data = await json('/api/twitch/login', {method: 'POST'});
      $('loginHelp').replaceChildren();
      const link = document.createElement('a');
      link.href = data.verification_uri;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = 'Continue on Twitch ↗';
      link.style.color = 'var(--mint)';
      $('loginHelp').append(link, document.createTextNode(' · Code: ' + data.user_code));
      window.open(data.verification_uri, '_blank', 'noopener');
      poll(data.expires_in);
    } catch (error) {
      $('login').disabled = false;
      $('loginHelp').textContent = error.message;
      $('loginHelp').className = 'status bad';
    }
  };

  function poll(expires) {
    const deadline = Date.now() + (expires || 900) * 1000;
    let busy = false;
    const timer = setInterval(async () => {
      if (busy) return;
      if (Date.now() >= deadline) {
        clearInterval(timer);
        $('login').disabled = false;
        $('loginHelp').textContent = 'Login expired. Please try again.';
        return;
      }
      busy = true;
      try {
        const data = await json('/api/settings');
        if (['failed', 'success'].includes(data.twitch.auth_state)) {
          clearInterval(timer);
          $('login').disabled = false;
          const success = data.twitch.auth_state === 'success';
          $('loginHelp').textContent = success ? 'Twitch connected.' : data.twitch.message;
          $('loginHelp').className = 'status ' + (success ? 'good' : 'bad');
          await refresh();
        }
      } catch (error) {
        $('loginHelp').textContent = error.message + ' Retrying authorization status…';
      } finally { busy = false; }
    }, 2000);
  }
  refresh();
  setInterval(refresh, 10000);
}
