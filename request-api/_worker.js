// Bond credit monitor: static assets plus the event-request API.
// Deployed as the Pages advanced-mode worker for bond-credit-monitor.
// The request endpoint validates the form fields, then stores the
// request as a JSON object in the owner's R2 bucket (binding
// REQUESTS, prefix requests/). A scheduled check picks new objects
// up and reports them to the owner. The approve endpoint records an
// owner approval (prefix approvals/) for a stored request; the same
// scheduled check then registers the approved event. No third-party
// service is used.
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
  return json({ ok: true, key });
}

async function handleStatus(request, env) {
  if (request.method !== 'GET') return json({ ok: false, error: 'method' }, 405);
  const url = new URL(request.url);
  const key = url.searchParams.get('key') || '';
  if (!/^requests\/[A-Za-z0-9][A-Za-z0-9._-]*\.json$/.test(key)) {
    return json({ ok: false, error: 'bad_key' }, 400);
  }
  const base = key.slice('requests/'.length);
  const verdict = await env.REQUESTS.get('verdicts/' + base);
  if (!verdict) return json({ ok: true, status: 'pending' });
  let v;
  try {
    v = JSON.parse(await verdict.text());
  } catch (e) {
    return json({ ok: false, error: 'bad_verdict' }, 500);
  }
  return json({
    ok: true,
    status: v.status,
    reason: v.reason || '',
    reason_ko: v.reason_ko || '',
    reason_en: v.reason_en || '',
  });
}

function page(title, body, status) {
  const doc = '<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">'
    + '<title>' + title + '</title></head>'
    + '<body style="font-family:system-ui,sans-serif;max-width:560px;margin:48px auto;padding:0 16px;line-height:1.7">'
    + '<h1>' + title + '</h1>' + body + '</body></html>';
  return new Response(doc, {
    status: status || 200,
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
}

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function handleApprove(request, env) {
  if (request.method !== 'GET') {
    return page('잘못된 요청', '<p>이 링크는 브라우저로 여는 승인 링크입니다.</p>', 405);
  }
  const url = new URL(request.url);
  const key = url.searchParams.get('key') || '';
  if (!/^requests\/[A-Za-z0-9][A-Za-z0-9._-]*\.json$/.test(key)) {
    return page('잘못된 승인 링크', '<p>승인 링크 형식이 올바르지 않습니다.</p>', 400);
  }
  const base = key.slice('requests/'.length);
  const already = await env.REQUESTS.get('approvals/' + base);
  if (already) {
    return page('이미 승인된 요청', '<p>이 요청은 이미 승인되어 등록이 진행 중이거나 완료되었습니다.</p>');
  }
  const stored = await env.REQUESTS.get(key);
  if (!stored) {
    return page('찾을 수 없는 요청', '<p>해당 요청이 존재하지 않거나 이미 처리되었습니다.</p>', 404);
  }
  let record;
  try {
    record = JSON.parse(await stored.text());
  } catch (e) {
    return page('요청을 읽을 수 없음', '<p>저장된 요청 내용을 읽지 못했습니다.</p>', 500);
  }
  try {
    await env.REQUESTS.put('approvals/' + base, JSON.stringify({
      approved_at: new Date().toISOString(),
      request_key: key,
      article_url: record.article_url || '',
      requester_email: record.requester_email || '',
    }, null, 2), { httpMetadata: { contentType: 'application/json' } });
  } catch (e) {
    return page('승인 저장 실패', '<p>승인 기록 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.</p>', 502);
  }
  return page('승인되었습니다',
    '<p>이 사건의 등록이 진행됩니다.</p>'
    + '<p>기사 링크: <a href="' + esc(record.article_url || '') + '">'
    + esc(record.article_url || '') + '</a></p>'
    + '<p>등록이 끝나면 채팅으로 알려드립니다.</p>');
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/api/request-event') return handleRequest(request, env);
    if (url.pathname === '/api/approve-request') return handleApprove(request, env);
    if (url.pathname === '/api/request-status') return handleStatus(request, env);
    return env.ASSETS.fetch(request);
  },
};
