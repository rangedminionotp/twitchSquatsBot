import {recordResponse} from './state.js';
// Shared transport. Mutations are never automatically retried.
export async function json(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(url, {...options, signal: controller.signal});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || ('HTTP ' + response.status));
    if (!options.method || options.method === 'GET') recordResponse(url, body);
    return body;
  } catch (error) {
    if (!options.method || options.method === 'GET') recordResponse(url, null, error.message);
    if (error.name === 'AbortError') throw new Error('Request timed out. Check that Squat Capture is running.');
    throw error;
  } finally { clearTimeout(timeout); }
}
export function save(values = {}) {
  return json('/api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(values)});
}
