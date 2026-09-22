// Public route configuration only; no tokens or account settings.
async function loadConfig() {
  try {
    const response = await fetch('/api/web-config', {cache: 'no-store', signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return await response.json();
  } catch (error) {
    const message = document.createElement('p');
    message.setAttribute('role', 'alert');
    message.textContent = 'Could not load app configuration. Check that Squat Capture is running, then reload this page.';
    document.body.prepend(message);
    throw error;
  }
}
export const config = await loadConfig();
