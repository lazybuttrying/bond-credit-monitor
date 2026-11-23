// Bond credit monitor: static assets plus the event-request API.
// Deployed as the Pages advanced-mode worker for bond-credit-monitor.
// The request endpoint validates the form fields, then stores the
// request as a JSON object in the owner's R2 bucket (binding
// REQUESTS, prefix requests/). A scheduled check picks new objects
// up and reports them to the owner. No third-party service is used.
function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function handleRequest(request, env) {
  if (request.method !== 'POST') return json({ ok: false, error: 'method' }, 405);
  let body;
  try {
    body = await request.json();
  } catch (e) {
    return json({ ok: false, error: 'bad_json' }, 400);
  }
  const link = String(body.url || '').trim();
  const email = String(body.email || '').trim();
  const note = String(body.note || '').trim().slice(0, 1000);
  if (!/^https?:\/\/\S+$/i.test(link) || link.length > 2000) {
    return json({ ok: false, error: 'bad_url' }, 400);
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 200) {
    return json({ ok: false, error: 'bad_email' }, 400);
  }
  const now = new Date();
  const stamp = now.toISOString().replace(/[:.]/g, '-');
  const rand = Math.random().toString(36).slice(2, 8);
  const key = 'requests/' + stamp + '-' + rand + '.json';
  const record = {
    received_at: now.toISOString(),
    article_url: link,
    requester_email: email,
    note: note,
  };
  try {
    await env.REQUESTS.put(key, JSON.stringify(record, null, 2), {
      httpMetadata: { contentType: 'application/json' },
    });
  } catch (e) {
    return json({ ok: false, error: 'store_failed' }, 502);
  }
  return json({ ok: true });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/api/request-event') return handleRequest(request, env);
    return env.ASSETS.fetch(request);
  },
};
