#!/usr/bin/env python3
"""posst.app — OAuth Token Exchange Endpoint v4.0
Changes from v3.3:
  - All data reads/writes go to Supabase via posst-api (port 5680)
  - Removed gspread dependency
  - Fernet encryption retained for tokens
"""

import os
import json
import logging
import threading
import requests
from datetime import datetime, timedelta
from flask import Flask, request, redirect, session, render_template_string, jsonify
from cryptography.fernet import Fernet

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', '')
if not app.secret_key:
    raise RuntimeError('[SECURITY] FLASK_SECRET env var is not set. Refusing to start.')

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# D1-6 Security: Server-side token store for OAuth flow.
# Meta long-lived tokens were previously stored in Flask's signed cookie (client-side).
# Anyone with the cookie value and FLASK_SECRET could read the Meta token.
# Now tokens are stored server-side, keyed by session ID. The cookie only holds
# a reference key. Tokens auto-expire after 30 minutes (OAuth flow is <5 min).
import time as _time
_token_store = {}  # key → {'ll_token': str, 'll_expiry': str, 'created': float}
_TOKEN_TTL = 1800  # 30 minutes

def _store_token(key, ll_token, ll_expiry):
    """Store a Meta token server-side, keyed by session reference."""
    _token_store[key] = {'ll_token': ll_token, 'll_expiry': ll_expiry, 'created': _time.time()}
    # Cleanup expired entries (same pattern as rate limiting)
    now = _time.time()
    expired = [k for k, v in _token_store.items() if now - v['created'] > _TOKEN_TTL]
    for k in expired:
        del _token_store[k]

def _get_token(key):
    """Retrieve a stored token. Returns (ll_token, ll_expiry) or ('', '')."""
    entry = _token_store.get(key)
    if entry and _time.time() - entry['created'] < _TOKEN_TTL:
        return entry['ll_token'], entry['ll_expiry']
    return '', ''

def _clear_token(key):
    """Remove a token after use."""
    _token_store.pop(key, None)

META_APP_ID          = os.environ.get('META_APP_ID', '')
META_APP_SECRET      = os.environ.get('META_APP_SECRET', '')
META_REDIRECT_URI    = os.environ.get('META_REDIRECT_URI', 'https://posst.app/connect/meta/callback')
GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
GOOGLE_REDIRECT_URI  = os.environ.get('GOOGLE_REDIRECT_URI', 'https://posst.app/connect/google/callback')
GOOGLE_SCOPES        = ['https://www.googleapis.com/auth/business.manage']
ENCRYPT_KEY          = os.environ.get('TOKEN_ENCRYPT_KEY', '')
cipher               = Fernet(ENCRYPT_KEY.encode()) if ENCRYPT_KEY else None

API_BASE        = 'http://127.0.0.1:5680'
POSST_API_SECRET = os.environ.get('POSST_API_SECRET', 'posst-api-secret-2026')

# ── AUDIT LOGGING (A2 Security, Jul 11 2026) ─────────────────
# Writes to Supabase audit_log table via direct connection (same creds as posst-api).
_AUDIT_SB_URL = os.environ.get('SUPABASE_URL', 'https://itlndeorkphlorvcohaw.supabase.co')
_AUDIT_SB_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')

def _audit_log(action, detail=None, actor=None, status_code=200):
    try:
        ip = request.headers.get('X-Real-IP') or request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr
        endpoint = request.path
        method = request.method
    except RuntimeError:
        ip, endpoint, method = 'system', 'background', 'SYSTEM'
    row = {
        'action': action, 'actor': actor or ip, 'ip': ip,
        'endpoint': endpoint, 'method': method, 'status_code': status_code,
        'detail': detail or {}, 'server': 'posst-oauth',
    }
    def _insert():
        try:
            requests.post(
                f'{_AUDIT_SB_URL}/rest/v1/audit_log',
                json=row,
                headers={
                    'apikey': _AUDIT_SB_KEY,
                    'Authorization': f'Bearer {_AUDIT_SB_KEY}',
                    'Content-Type': 'application/json',
                    'Prefer': 'return=minimal',
                },
                timeout=5,
            )
        except Exception as e:
            print(f'[AUDIT-WARN] Failed to write audit_log: {e}', flush=True)
    threading.Thread(target=_insert, daemon=True).start()

# D1-5: Internal API calls now pass X-API-Key header so they can request
# full client data (including tokens) via ?full=1. Without this, the
# _safe_client filter in posst_api.py would strip meta_token and
# meta_user_token from token refresh/recover operations.
_INTERNAL_HEADERS = {'X-API-Key': POSST_API_SECRET}

def api_get(path):
    try:
        r = requests.get(f'{API_BASE}{path}', headers=_INTERNAL_HEADERS, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f'API GET {path} error: {e}')
        return None

def api_post(path, data):
    try:
        r = requests.post(f'{API_BASE}{path}', json=data, headers=_INTERNAL_HEADERS, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f'API POST {path} error: {e}')
        return None

def api_patch(path, data):
    try:
        r = requests.patch(f'{API_BASE}{path}', json=data, headers=_INTERNAL_HEADERS, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f'API PATCH {path} error: {e}')
        return None

def get_client(client_id):
    # ?full=1 requests unfiltered data — needed for token operations
    result = api_get(f'/api/client/{client_id}?full=1')
    if result and result.get('status') == 'success':
        return result.get('data')
    return None

def encrypt_token(token: str) -> str:
    if cipher:
        return cipher.encrypt(token.encode()).decode()
    return token

# ── TEMPLATES ─────────────────────────────────────────────────

CONNECT_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Connect your accounts — posst.app</title>
<link rel="icon" href="https://posst.app/favicon.ico">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'DM Sans',sans-serif;background:#FFFAF4;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
  .card{background:#fff;border-radius:16px;padding:40px;max-width:480px;width:100%;border:1px solid #E4DFD6;text-align:center}
  .logo{height:32px;margin-bottom:28px}
  h1{font-size:22px;font-weight:600;color:#0F0E17;margin-bottom:8px}
  p.sub{font-size:14px;color:#4A4860;line-height:1.6;margin-bottom:28px}
  .step-row{display:flex;align-items:center;gap:16px;padding:16px;border-radius:12px;border:1.5px solid #E4DFD6;margin-bottom:12px;text-align:left;background:#fff}
  .step-row.done{border-color:#16a34a;background:#f0fdf4}
  .step-row.active{border-color:#1648FF;background:#f5f7ff}
  .step-row.inactive{opacity:.45}
  .step-icon{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;background:#f7f4ef}
  .step-icon.done{background:#dcfce7}
  .step-body{flex:1}
  .step-title{font-size:14px;font-weight:600;color:#0F0E17;margin-bottom:2px}
  .step-desc{font-size:12px;color:#4A4860;line-height:1.5}
  .step-confirmed{font-size:12px;color:#16a34a;font-weight:500;margin-top:4px}
  .step-action{flex-shrink:0}
  .btn{display:inline-block;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;font-family:'DM Sans',sans-serif;cursor:pointer;border:none;text-decoration:none;transition:opacity .15s}
  .btn-meta{background:#1877F2;color:#fff}
  .btn-google{background:#fff;color:#3c4043;border:1.5px solid #E4DFD6}
  .btn-done{background:#dcfce7;color:#16a34a;cursor:default}
  .btn-disabled{background:#f7f4ef;color:#9e9e9e;cursor:not-allowed;border:1.5px solid #E4DFD6}
  .btn:hover:not(.btn-done):not(.btn-disabled){opacity:.85}
  .badge{display:inline-block;background:#f0fdf4;color:#15803d;font-size:11px;font-weight:600;padding:3px 10px;border-radius:100px;margin-bottom:20px}
  .privacy{font-size:11px;color:#9e9e9e;margin-top:20px}
  .privacy a{color:#1648FF}
  @keyframes spin{to{transform:rotate(360deg)}}
  #loading-overlay{display:none;position:fixed;inset:0;background:rgba(255,250,244,.92);z-index:999;flex-direction:column;align-items:center;justify-content:center;gap:14px}
  #loading-overlay.active{display:flex}
  .spinner{width:36px;height:36px;border:3px solid #E4DFD6;border-top-color:#1648FF;border-radius:50%;animation:spin .75s linear infinite}
  .loading-text{font-size:14px;font-weight:600;color:#0F0E17}
  .loading-sub{font-size:12px;color:#4A4860}
</style>
</head>
<body>
<div id="loading-overlay">
  <div class="spinner"></div>
  <div class="loading-text">Connecting...</div>
  <div class="loading-sub">You will be redirected back in a moment.</div>
</div>
<div class="card">
  <img class="logo" src="https://posst.app/posst_logo_dark.png" alt="posst.app">
  <div class="badge">Almost there</div>
  <h1>Connect your accounts</h1>
  <p class="sub">Authorise posst.app to post on your behalf. You only do this once.</p>
  {% if business %}
  <div style="background:#FFF7ED;border:1.5px solid #FED7AA;border-radius:12px;padding:14px 16px;margin-bottom:20px;text-align:left">
    <div style="font-size:12px;font-weight:700;color:#C2410C;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.05em">⚠️ Important — read before connecting</div>
    <div style="font-size:13px;color:#7C2D12;line-height:1.6">
      You are connecting accounts for <strong>{{ business }}</strong>.<br><br>
      <strong>Step 1 — Grant access to ALL pages:</strong> When Facebook asks which pages to share, select <strong>all</strong> your Facebook pages — even if you manage more than one. This keeps your connection working correctly.<br><br>
      <strong>Step 2 — Select Instagram:</strong> Select <strong>all</strong> Instagram accounts linked to your pages.<br><br>
      <strong>Step 3 — Choose your page:</strong> After returning to posst.app, you'll pick the specific page for <strong>{{ business }}</strong> on the next screen.<br><br>
      Complete all steps — both Facebook and Instagram must be selected to finish.
    </div>
  </div>
  {% endif %}
  <div class="step-row {% if meta_done %}done{% else %}active{% endif %}">
    <div class="step-icon {% if meta_done %}done{% endif %}">{% if meta_done %}✅{% else %}📘{% endif %}</div>
    <div class="step-body">
      <div class="step-title">{% if "instagram" in platforms %}Facebook + Instagram{% else %}Facebook{% endif %}</div>
      {% if meta_done %}
        <div class="step-confirmed">✅ Facebook: {{ fb_page_name }}</div>
        {% if "instagram" in platforms %}
          {% if ig_username %}<div class="step-confirmed">✅ Instagram: @{{ ig_username }}</div>
          {% else %}<div class="step-confirmed" style="color:#b45309">⚠️ No Instagram found — go back and reconnect, making sure to select your Instagram account</div>{% endif %}
        {% endif %}
      {% else %}
        <div class="step-desc">
          {% if "instagram" in platforms %}Connect your Facebook page and Instagram account — you will go through 3 Meta screens{% else %}Connect your Facebook page{% endif %}
        </div>
      {% endif %}
    </div>
    <div class="step-action">
      {% if meta_done %}<span class="btn btn-done">Connected</span>
      {% else %}<a class="btn btn-meta" href="{{ meta_url }}" onclick="showLoading(this)">Connect</a>{% endif %}
    </div>
  </div>
  {% if 'gbp' in platforms %}
  <div class="step-row {% if gbp_done %}done{% elif meta_done %}active{% else %}inactive{% endif %}">
    <div class="step-icon {% if gbp_done %}done{% endif %}">{% if gbp_done %}✅{% else %}🗺️{% endif %}</div>
    <div class="step-body">
      <div class="step-title">Google Business Profile</div>
      {% if gbp_done %}<div class="step-confirmed">✅ Google Business connected</div>
      {% else %}<div class="step-desc">Connect your Google Business Profile{% if not meta_done %} — complete Step 1 first{% endif %}</div>{% endif %}
    </div>
    <div class="step-action">
      {% if gbp_done %}<span class="btn btn-done">Connected</span>
      {% elif meta_done %}<a class="btn btn-google" href="{{ google_url }}">Connect</a>
      {% else %}<span class="btn btn-disabled">Connect</span>{% endif %}
    </div>
  </div>
  {% endif %}
  <p class="privacy">🔒 We only post on your behalf. We never share your data. <a href="mailto:chief@posst.app">Questions?</a></p>
</div>
<script>
  function showLoading(el) { setTimeout(function(){ document.getElementById('loading-overlay').classList.add('active'); }, 50); }
  (function() {
    var params = new URLSearchParams(window.location.search);
    if (params.get('_return')) {
      var overlay = document.getElementById('loading-overlay');
      overlay.querySelector('.loading-text').textContent = 'Finishing connection...';
      overlay.querySelector('.loading-sub').textContent = 'Almost done.';
      overlay.classList.add('active');
      setTimeout(function() { overlay.classList.remove('active'); }, 1000);
    }
  })();
</script>
</body>
</html>
"""

PAGE_SELECT_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Select your page — posst.app</title>
<link rel="icon" href="https://posst.app/favicon.ico">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'DM Sans',sans-serif;background:#FFFAF4;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
  .card{background:#fff;border-radius:16px;padding:40px;max-width:480px;width:100%;border:1px solid #E4DFD6;text-align:center}
  .logo{height:32px;margin-bottom:28px}
  h1{font-size:22px;font-weight:600;color:#0F0E17;margin-bottom:8px}
  p{font-size:14px;color:#4A4860;line-height:1.6;margin-bottom:24px}
  .page-btn{display:flex;align-items:center;gap:14px;width:100%;padding:14px 16px;border-radius:12px;font-family:'DM Sans',sans-serif;cursor:pointer;border:1.5px solid #E4DFD6;background:#fff;margin-bottom:10px;text-align:left;transition:border-color .15s,background .15s}
  .page-btn:hover{border-color:#1648FF;background:#f5f7ff}
  .page-icon{width:40px;height:40px;border-radius:10px;background:#eff3ff;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0}
  .page-name{font-weight:600;color:#0F0E17;font-size:14px}
  .page-meta{font-size:11px;color:#4A4860;margin-top:3px}
  .ig-yes{color:#16a34a;font-weight:500}
  .ig-no{color:#b45309}
</style>
</head>
<body>
<div class="card">
  <img class="logo" src="https://posst.app/posst_logo_dark.png" alt="posst.app">
  <h1>Select your business page</h1>
  <p>We found {{ pages|length }} Facebook page{{ 's' if pages|length > 1 else '' }}. Select the page for <strong>{{ business }}</strong>.</p>
  {% if pages|length > 1 %}
  <div style="background:#FFF7ED;border:1.5px solid #FED7AA;border-radius:10px;padding:12px 14px;margin-bottom:16px;text-align:left;font-size:13px;color:#92400E">
    ⚠️ You manage multiple pages — choose the one that posst.app will post to for <strong>{{ business }}</strong>.
  </div>
  {% endif %}
  {% for page in pages %}
  <form method="POST" action="/connect/meta/select">
    <input type="hidden" name="page_id" value="{{ page.id }}">
    <input type="hidden" name="page_name" value="{{ page.name }}">
    <input type="hidden" name="ig_biz_id" value="{{ page.ig_biz_id }}">
    <input type="hidden" name="ig_username" value="{{ page.ig_username }}">
    <button type="submit" class="page-btn">
      <div class="page-icon">📘</div>
      <div>
        <div class="page-name">{{ page.name }}</div>
        <div class="page-meta">
          {% if page.ig_biz_id %}<span class="ig-yes">✅ Instagram: @{{ page.ig_username if page.ig_username else page.ig_biz_id }}</span>
          {% else %}<span class="ig-no">⚠️ No Instagram linked to this page</span>{% endif %}
        </div>
      </div>
    </button>
  </form>
  {% endfor %}
</div>
</body>
</html>
"""

SUCCESS_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>All connected! — posst.app</title>
<link rel="icon" href="https://posst.app/favicon.ico">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'DM Sans',sans-serif;background:#FFFAF4;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
  .card{background:#fff;border-radius:16px;padding:40px;max-width:480px;width:100%;border:1px solid #E4DFD6;text-align:center}
  .logo{height:32px;margin-bottom:28px}
  .icon{width:64px;height:64px;background:#f0fdf4;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:28px;margin:0 auto 20px}
  h1{font-size:22px;font-weight:600;color:#0F0E17;margin-bottom:8px}
  p{font-size:14px;color:#4A4860;line-height:1.6;margin-bottom:20px}
  .step{display:flex;gap:12px;padding:12px 0;border-bottom:1px solid #E4DFD6}
  .step:last-child{border-bottom:none}
  .step-num{width:24px;height:24px;border-radius:50%;background:#eff3ff;color:#1648FF;font-size:11px;font-weight:600;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:1px}
  .step-text{font-size:13px;color:#0F0E17;line-height:1.5;text-align:left}
</style>
</head>
<body>
<div class="card">
  <img class="logo" src="https://posst.app/posst_logo_dark.png" alt="posst.app">
  <div class="icon">✅</div>
  <h1>You are all set!</h1>
  <p>Your accounts are connected. We are setting everything up now.</p>
  {% if fb_page_name or ig_handle or gbp_name %}
  <div style="background:#f0fdf4;border:1px solid #BBF7D0;border-radius:12px;padding:16px;margin-bottom:20px;text-align:left">
    <div style="font-size:12px;font-weight:600;color:#166534;margin-bottom:10px;text-transform:uppercase;letter-spacing:0.05em">Connected accounts</div>
    {% if fb_page_name %}<div style="display:flex;align-items:center;gap:8px;font-size:13px;color:#0F0E17;margin-bottom:6px">
      <span style="font-size:16px">📘</span><span><strong>Facebook:</strong> {{ fb_page_name }}</span></div>{% endif %}
    {% if ig_handle %}<div style="display:flex;align-items:center;gap:8px;font-size:13px;color:#0F0E17;margin-bottom:6px">
      <span style="font-size:16px">📸</span><span><strong>Instagram:</strong> @{{ ig_handle }}</span></div>{% endif %}
    {% if gbp_name %}<div style="display:flex;align-items:center;gap:8px;font-size:13px;color:#0F0E17;margin-bottom:6px">
      <span style="font-size:16px">📍</span><span><strong>Google:</strong> {{ gbp_name }}</span></div>{% endif %}
  </div>
  {% endif %}
  <div class="step"><div class="step-num">1</div><div class="step-text"><strong>Check your email</strong> — confirmation sent to {{ email }}</div></div>
  <div class="step"><div class="step-num">2</div><div class="step-text"><strong>We set everything up</strong> — your automation goes live within 24 hours</div></div>
  <div class="step"><div class="step-num">3</div><div class="step-text"><strong>First post goes out</strong> — you will get an email notification when you are live</div></div>
  {% if show_drive %}
  <div id="drive-box" style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:12px;padding:18px;margin:20px 0;text-align:left">
    <p style="font-size:13px;color:#92400e;margin-bottom:12px;line-height:1.5">&#x1F4F7; <strong>One more thing</strong> — you are on Pro. Connect your Google Drive photo library so we use your real photos in every post.</p>
    <a href="{{ drive_url }}" style="display:inline-block;background:#1648FF;color:#fff;font-size:14px;font-weight:600;text-decoration:none;padding:11px 28px;border-radius:8px">Set up photo library &#x2192;</a>
    <button onclick="document.getElementById('drive-box').style.display='none'" style="display:block;margin-top:10px;font-size:12px;color:#9896A8;cursor:pointer;background:none;border:none;font-family:inherit;text-decoration:underline;width:100%;text-align:center">Skip for now</button>
  </div>
  {% endif %}
  <p style="margin-top:24px;font-size:13px;color:#9896A8">You can now close this window. Thank you for trusting posst.app.</p>
</div>
</body>
</html>
"""

TOKEN_ERROR_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Link expired — posst.app</title>
<link rel="icon" href="https://posst.app/favicon.ico">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'DM Sans',sans-serif;background:#FFFAF4;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
  .card{background:#fff;border-radius:16px;padding:40px;max-width:440px;width:100%;border:1px solid #E4DFD6;text-align:center}
  .logo{height:32px;margin-bottom:28px}
  .icon{font-size:40px;margin-bottom:16px}
  h1{font-size:20px;font-weight:600;color:#0F0E17;margin-bottom:10px}
  p{font-size:14px;color:#4A4860;line-height:1.6;margin-bottom:20px}
  a{color:#1648FF;font-weight:600}
</style>
</head>
<body>
<div class="card">
  <img class="logo" src="https://posst.app/posst_logo_dark.png" alt="posst.app">
  <div class="icon">🔗</div>
  <h1>This link has expired</h1>
  <p>This connection link can only be used once and may have already been used or expired.<br><br>Please <a href="mailto:chief@posst.app">contact us</a> and we will send you a fresh link.</p>
</div>
</body>
</html>
"""

# ── ROUTES ────────────────────────────────────────────────────

def render_success(client_id, email):
    mobile_return = session.get('mobile_return', '')
    if mobile_return:
        import urllib.parse
        sep = '&' if '?' in mobile_return else '?'
        return redirect(f'{mobile_return}{sep}client_id={urllib.parse.quote(client_id)}&status=connected')
    show_drive = False
    drive_url  = ''
    try:
        client = get_client(client_id)
        if client:
            plan = (client.get('plan') or '').lower()
            drive_intent = (client.get('google_drive_intent') or '').lower()
            drive_url_val = (client.get('google_drive_url') or '').strip()
            if plan == 'pro' and drive_intent != 'now' and not drive_url_val:
                show_drive = True
                try:
                    import urllib.parse
                    r = requests.post('http://127.0.0.1:5679/generate_token', json={'client_id': client_id, 'purpose': 'drive_setup'}, timeout=5)
                    tok = r.json().get('token', '')
                    if tok:
                        biz = urllib.parse.quote(client.get('business_name') or '')
                        drive_url = f'https://onboarding.posst.app/drive-setup.html?token={tok}&business={biz}'
                except:
                    pass
    except:
        pass
    # Get connected account names for display
    fb_page_name = ''
    ig_handle    = ''
    gbp_name     = ''
    try:
        if client:
            fb_page_name = client.get('fb_page_name') or ''
            ig_handle    = client.get('ig_handle') or ''
            gbp_name     = client.get('gbp_name') or '' if client.get('gbp_location_id') else ''
    except:
        pass
    return render_template_string(SUCCESS_PAGE, email=email, show_drive=show_drive, drive_url=drive_url,
                                  fb_page_name=fb_page_name, ig_handle=ig_handle, gbp_name=gbp_name)


@app.route('/connect')
def connect_page():
    client_id  = request.args.get('client_id', session.get('client_id', ''))
    platforms  = request.args.get('platforms', session.get('platforms_str', 'facebook,instagram')).split(',')
    business   = request.args.get('business', session.get('business', 'your business'))
    email      = request.args.get('email', session.get('email', ''))

    # Fresh start on new token
    incoming_client_id = request.args.get('client_id', '')
    incoming_token     = request.args.get('token', '')
    is_return          = request.args.get('_return', '')
    if incoming_token and not is_return:
        session.clear()
    elif incoming_client_id and incoming_client_id != session.get('client_id', ''):
        session.clear()

    mobile_return = request.args.get('mobile_return', session.get('mobile_return', ''))
    session['client_id']     = client_id
    session['platforms']     = platforms
    session['platforms_str'] = ','.join(platforms)
    session['business']      = business
    session['email']         = email
    session['mobile_return'] = mobile_return  # persists across OAuth round trips

    # Validate pending token
    if not session.get('meta_done', False):
        incoming_token = request.args.get('token', '')
        if not incoming_token:
            return render_template_string(TOKEN_ERROR_PAGE, reason='missing'), 403
        try:
            result = api_get(f'/api/client/{client_id}/pending_token')
            if not result or result.get('status') != 'success':
                return render_template_string(TOKEN_ERROR_PAGE, reason='not_found'), 403
            sheet_token = result.get('token', '')
            if not sheet_token or sheet_token.strip() != incoming_token.strip():
                return render_template_string(TOKEN_ERROR_PAGE, reason='invalid'), 403
        except Exception as e:
            log.error(f'Token validation error for {client_id}: {e}')
            return render_template_string(TOKEN_ERROR_PAGE, reason='error'), 500
        session['validated_token'] = incoming_token

    meta_done    = session.get('meta_done', False)
    gbp_done     = session.get('gbp_done', False)
    fb_page_name = session.get('fb_page_name', '')
    ig_username  = session.get('ig_username', '')

    # GBP-only flow
    gbp_only = set(platforms) <= {'gbp', 'google'}
    if gbp_only and not gbp_done:
        google_url = (f'https://accounts.google.com/o/oauth2/v2/auth?client_id={GOOGLE_CLIENT_ID}'
                      f'&redirect_uri={GOOGLE_REDIRECT_URI}&scope={"%20".join(GOOGLE_SCOPES)}'
                      f'&response_type=code&access_type=offline&prompt=consent&state={client_id}')
        return redirect(google_url)
    if gbp_only and gbp_done:
        return render_success(client_id, session.get('email', ''))

    needs_gbp = 'gbp' in platforms
    all_done  = meta_done and (gbp_done if needs_gbp else True)
    if all_done:
        return render_success(client_id, session.get('email', ''))

    meta_perms = 'pages_show_list,pages_read_engagement,pages_manage_posts,instagram_basic,instagram_content_publish,business_management'
    meta_url   = (f'https://www.facebook.com/v19.0/dialog/oauth?client_id={META_APP_ID}'
                  f'&redirect_uri={META_REDIRECT_URI}&scope={meta_perms}&state={client_id}&response_type=code')
    google_url = (f'https://accounts.google.com/o/oauth2/v2/auth?client_id={GOOGLE_CLIENT_ID}'
                  f'&redirect_uri={GOOGLE_REDIRECT_URI}&scope={"%20".join(GOOGLE_SCOPES)}'
                  f'&response_type=code&access_type=offline&prompt=consent&state={client_id}')

    return render_template_string(CONNECT_PAGE,
        meta_url=meta_url, google_url=google_url,
        platforms=platforms, business=business,
        meta_done=meta_done, gbp_done=gbp_done,
        fb_page_name=fb_page_name, ig_username=ig_username)


@app.route('/connect/meta/callback')
def meta_callback():
    code      = request.args.get('code', '')
    client_id = request.args.get('state', session.get('client_id', ''))
    error     = request.args.get('error', '')
    if error:
        return f'<p>Error: {error}. Please <a href="mailto:chief@posst.app">contact support</a>.</p>', 400

    r = requests.get('https://graph.facebook.com/v19.0/oauth/access_token', params={
        'client_id': META_APP_ID, 'client_secret': META_APP_SECRET,
        'redirect_uri': META_REDIRECT_URI, 'code': code
    })
    short_token = r.json().get('access_token', '')
    if not short_token:
        return '<p>Failed to get access token. Please try again.</p>', 500

    ll_r = requests.get('https://graph.facebook.com/v19.0/oauth/access_token', params={
        'grant_type': 'fb_exchange_token', 'client_id': META_APP_ID,
        'client_secret': META_APP_SECRET, 'fb_exchange_token': short_token
    })
    ll_data   = ll_r.json()
    ll_token  = ll_data.get('access_token', '')
    ll_expiry = datetime.now() + timedelta(seconds=ll_data.get('expires_in', 5184000))

    pages_r = requests.get('https://graph.facebook.com/v19.0/me/accounts', params={
        'access_token': ll_token,
        'fields': 'id,name,instagram_business_account{id,username}'
    })
    pages_data = pages_r.json().get('data', [])
    if not pages_data:
        return '<p>No Facebook pages found. Make sure you have a business page and try again.</p>', 400

    # D1-6: Store token server-side, NOT in cookie. Cookie only holds a reference key.
    import secrets as _secrets
    token_ref = _secrets.token_hex(16)
    _store_token(token_ref, ll_token, ll_expiry.strftime('%d/%m/%Y'))
    session['_token_ref'] = token_ref
    session['client_id']  = client_id

    page_list = []
    for p in pages_data:
        ig = p.get('instagram_business_account', {}) or {}
        page_list.append({'id': p.get('id',''), 'name': p.get('name',''), 'ig_biz_id': ig.get('id',''), 'ig_username': ig.get('username','')})

    log.info(f'Meta OAuth success for {client_id} — {len(page_list)} pages found')

    # Always show page picker — never auto-select
    # Customers with multiple businesses must choose the correct page
    business_name = get_client(client_id)
    business_name = (business_name.get('business_name') or '') if business_name else ''
    return render_template_string(PAGE_SELECT_PAGE, pages=page_list, business=business_name)


@app.route('/connect/meta/select', methods=['POST'])
def meta_page_select():
    page_id     = request.form.get('page_id', '')
    page_name   = request.form.get('page_name', '')
    ig_biz_id   = request.form.get('ig_biz_id', '')
    ig_username = request.form.get('ig_username', '')
    client_id   = session.get('client_id', '')
    # D1-6: Read token from server-side store, not cookie
    token_ref   = session.get('_token_ref', '')
    ll_token, ll_expiry = _get_token(token_ref) if token_ref else ('', '')
    if not ll_token:
        return '<p>Session expired. Please <a href="/connect?client_id=' + client_id + '">start again</a>.</p>', 400
    _clear_token(token_ref)  # One-time use — clean up after page selection
    return save_meta_page(client_id, page_id, page_name, ig_biz_id, ig_username, ll_token, ll_expiry)


def save_meta_page(client_id, fb_page_id, page_name, ig_biz_id, ig_username, ll_token, expiry_str):
    page_token_r = requests.get(f'https://graph.facebook.com/v19.0/{fb_page_id}', params={
        'fields': 'access_token', 'access_token': ll_token
    })
    page_token = page_token_r.json().get('access_token', ll_token)

    # Only save IG if client selected instagram
    platforms = session.get('platforms', [])
    if 'instagram' not in platforms:
        ig_biz_id   = ''
        ig_username = ''

    log.info(f'Saving page {fb_page_id} ({page_name}) for {client_id}, IG: {ig_biz_id}')

    # Read client status BEFORE patching the token so the reconnect email decision
    # is based on a reliable pre-patch read — not a post-patch get_client() call
    # that could fail and silently skip the email.
    pre_patch_client = get_client(client_id)
    pre_status       = (pre_patch_client or {}).get('status', '')
    log.info(f'meta_callback: client {client_id} pre-patch status = {pre_status!r}')

    # Write to Supabase via posst-api
    api_patch(f'/api/client/{client_id}/token', {
        'fb_page_id':        fb_page_id,
        'fb_page_name':      page_name,
        'ig_business_id':    ig_biz_id,
        'ig_handle':         ig_username,
        'meta_token':        encrypt_token(page_token),
        'meta_token_expiry': expiry_str,
        'meta_user_token':   encrypt_token(ll_token),
        'status':            'Token_Received',
        'pending_token':     '',
    })

    _audit_log('oauth_completed', actor=client_id, detail={'platform': 'meta', 'page': page_name})

    session['meta_done']    = True
    session['fb_page_name'] = page_name
    session['ig_username']  = ig_username

    # Send reconnect confirmation email for existing Active clients only.
    # (new signups have status Token_Received/Pending here — they get go-live email instead)
    # Uses pre_status captured before the patch to avoid a second API call that could fail.
    if pre_status == 'Active':
        try:
            platforms_connected = []
            if fb_page_id: platforms_connected.append('Facebook')
            if ig_biz_id:  platforms_connected.append('Instagram')
            log.info(f'meta_callback: sending reconnect confirmation email for {client_id} '
                     f'platforms={platforms_connected}')
            result = api_post('/api/email/reconnect_confirmation', {
                'client_id':    client_id,
                'posting_time': pre_patch_client.get('posting_time', ''),
                'timezone':     pre_patch_client.get('timezone', 'Australia/Melbourne'),
                'platforms':    platforms_connected,
            })
            log.info(f'meta_callback: reconnect email result for {client_id}: {result}')
        except Exception as e:
            log.error(f'meta_callback: reconnect confirmation email FAILED for {client_id}: {e}')
    else:
        log.info(f'meta_callback: skipping reconnect email for {client_id} (status={pre_status!r}, not Active)')

    return redirect(f'/connect?client_id={client_id}&_return=1')


@app.route('/tokens/refresh', methods=['POST'])
def tokens_refresh():
    """
    Auto-refresh Meta tokens for all Active clients whose token expires within 45 days.
    Called daily by n8n at 22:00 UTC (08:00 AEST).

    Tiered behaviour:
      > 45 days left  : skip (too early)
      15-45 days left : refresh silently
      7-14 days left  : refresh + warn client via connection_error email
      < 7 days left   : refresh + urgent email to client
      refresh fails   : send connection_error email immediately (don't wait for post to fail)
    """
    from datetime import date, timezone as _tz
    import dateutil.parser

    results = {'refreshed': [], 'failed': [], 'skipped': [], 'errors': []}

    # Fetch all active clients
    clients_res = api_get('/api/clients/active')
    clients = (clients_res or {}).get('data', [])

    for c in clients:
        cid        = c.get('client_id', '')
        biz        = c.get('business_name', cid)
        user_token_enc = c.get('meta_user_token', '')
        expiry_str = c.get('meta_token_expiry', '')  # DD/MM/YYYY

        if not cid:
            continue

        # Skip if no user token stored (client hasn't reconnected since this feature launched)
        if not user_token_enc:
            results['skipped'].append(f'{cid}: no meta_user_token yet')
            continue

        # Parse expiry date
        days_left = None
        if expiry_str:
            try:
                exp_date = datetime.strptime(expiry_str, '%d/%m/%Y').date()
                days_left = (exp_date - date.today()).days
            except Exception:
                pass

        # Skip if token is fresh (> 45 days left)
        if days_left is not None and days_left > 45:
            results['skipped'].append(f'{cid}: {days_left} days left, not due')
            continue

        # Attempt refresh
        try:
            # Decrypt the stored user token
            dec_res = requests.post('http://127.0.0.1:5679/decrypt',
                                    json={'token': user_token_enc}, timeout=10)
            user_token = dec_res.json().get('token', '')
            if not user_token:
                raise ValueError('Decrypt returned empty token')

            # Call Meta to extend the user token
            refresh_res = requests.get('https://graph.facebook.com/v19.0/oauth/access_token',
                params={
                    'grant_type':       'fb_exchange_token',
                    'client_id':        META_APP_ID,
                    'client_secret':    META_APP_SECRET,
                    'fb_exchange_token': user_token,
                }, timeout=15)
            refresh_data = refresh_res.json()

            if 'error' in refresh_data:
                raise ValueError(f"Meta error: {refresh_data['error'].get('message', str(refresh_data))}")

            new_user_token = refresh_data.get('access_token', '')
            expires_in     = refresh_data.get('expires_in', 5184000)
            new_expiry     = (datetime.now() + timedelta(seconds=expires_in)).strftime('%d/%m/%Y')

            if not new_user_token:
                raise ValueError('Meta returned empty access_token')

            # Get fresh page token
            fb_page_id = c.get('fb_page_id', '')
            page_token = new_user_token  # fallback
            if fb_page_id:
                pt_res = requests.get(f'https://graph.facebook.com/v19.0/{fb_page_id}',
                    params={'fields': 'access_token', 'access_token': new_user_token},
                    timeout=10)
                page_token = pt_res.json().get('access_token', new_user_token)

            # Save back to Supabase via posst-api
            api_patch(f'/api/client/{cid}/token', {
                'meta_token':        encrypt_token(page_token),
                'meta_token_expiry': new_expiry,
                'meta_user_token':   encrypt_token(new_user_token),
            })

            log.info(f'tokens_refresh: refreshed {cid} ({biz}) — new expiry {new_expiry}')
            _audit_log('token_refresh', actor=cid, detail={'new_expiry': new_expiry})
            results['refreshed'].append(f'{cid}: new expiry {new_expiry}')

            # Warn client if in danger zone (7-14 days) even though refresh succeeded
            # (next refresh might fail if Meta revokes between now and then)
            if days_left is not None and days_left <= 14:
                api_post('/api/notify_error', {
                    'client_id': cid,
                    'fb_failed': False,
                    'ig_failed': False,
                    'gbp_failed': False,
                    'fb_error_msg': '',
                    'ig_error_msg': f'Your Meta connection is being automatically maintained. No action needed.',
                    'gbp_error_msg': '',
                })

        except Exception as e:
            log.error(f'tokens_refresh: FAILED for {cid} ({biz}): {e}')
            results['failed'].append(f'{cid}: {str(e)[:100]}')
            results['errors'].append(cid)

            # Token refresh failed — alert client NOW before their post fails tonight
            try:
                failed_platforms = []
                if c.get('fb_page_id'):  failed_platforms.append({'name': 'Facebook',  'icon': '📘'})
                if c.get('ig_biz_id') or c.get('ig_business_id'):
                    failed_platforms.append({'name': 'Instagram', 'icon': '📸'})
                if failed_platforms:
                    api_post('/api/notify_error', {
                        'client_id':   cid,
                        'fb_failed':   bool(c.get('fb_page_id')),
                        'ig_failed':   bool(c.get('ig_biz_id') or c.get('ig_business_id')),
                        'gbp_failed':  False,
                        'fb_error_msg':  f'Token refresh failed: {str(e)[:80]}',
                        'ig_error_msg':  f'Token refresh failed: {str(e)[:80]}',
                        'gbp_error_msg': '',
                    })
            except Exception as email_err:
                log.error(f'tokens_refresh: failed to send alert for {cid}: {email_err}')

    log.info(f'tokens_refresh complete: {len(results["refreshed"])} refreshed, '
             f'{len(results["failed"])} failed, {len(results["skipped"])} skipped')
    from flask import jsonify
    return jsonify({'status': 'success', 'results': results})


@app.route('/tokens/recover', methods=['POST'])
def tokens_recover():
    """
    Recover a broken Meta page token for a single client.
    Called by n8n sub-workflow when a post fails with OAuthException / permissions error.
    Uses the stored meta_user_token to re-derive a fresh page_access_token.

    Body: { "client_id": "POSST_20260620_002" }
    Returns: { "recovered": true } or { "recovered": false, "reason": "..." }
    """
    data      = request.get_json(force=True) or {}
    client_id = data.get('client_id', '').strip()

    if not client_id:
        return jsonify({'recovered': False, 'reason': 'missing client_id'}), 400

    try:
        # 1. Fetch client from Supabase
        client_res = api_get(f'/api/client/{client_id}')
        c = (client_res or {}).get('data')
        if not c:
            raise ValueError(f'Client {client_id} not found')

        user_token_enc = c.get('meta_user_token', '')
        fb_page_id     = c.get('fb_page_id', '')

        if not user_token_enc:
            raise ValueError('No meta_user_token stored — client must reconnect manually')

        # 2. Decrypt the stored user token via posst-r2
        dec_res    = requests.post('http://127.0.0.1:5679/decrypt',
                                   json={'token': user_token_enc}, timeout=10)
        user_token = dec_res.json().get('token', '')
        if not user_token:
            raise ValueError('Decrypt returned empty token — client must reconnect manually')

        # 3. Re-derive page access token via /me/accounts (same as tokens_refresh)
        page_token = user_token  # fallback if page lookup fails
        if fb_page_id:
            accounts_res = requests.get(
                'https://graph.facebook.com/v19.0/me/accounts',
                params={'access_token': user_token, 'fields': 'id,access_token'},
                timeout=10)
            accounts_data = accounts_res.json()
            if 'error' in accounts_data:
                raise ValueError(f"Meta accounts error: {accounts_data['error'].get('message', str(accounts_data))}")
            pages = accounts_data.get('data', [])
            page_ids_found = [str(p.get('id')) for p in pages]
            log.info(f'tokens_recover: {client_id} /me/accounts returned page ids: {page_ids_found}')
            matched = next((p for p in pages if str(p.get('id')) == str(fb_page_id)), None)
            if matched:
                page_token = matched.get('access_token', user_token)
            else:
                raise ValueError(f'Page {fb_page_id} not found in /me/accounts — found: {page_ids_found} — client must reconnect')

        # 4. Save fresh page token back to Supabase (keep same expiry — token cycle unchanged)
        api_patch(f'/api/client/{client_id}/token', {
            'meta_token': encrypt_token(page_token),
        })

        log.info(f'tokens_recover: recovered {client_id} — fresh page token saved')
        return jsonify({'recovered': True, 'client_id': client_id})

    except Exception as e:
        log.error(f'tokens_recover: FAILED for {client_id}: {e}')
        return jsonify({'recovered': False, 'reason': str(e)}), 200


@app.route('/connect/google/callback')
def google_callback():
    code      = request.args.get('code', '')
    client_id = request.args.get('state', session.get('client_id', ''))
    error     = request.args.get('error', '')
    if error:
        return f'<p>Error: {error}. Please contact chief@posst.app</p>', 400

    token_r = requests.post('https://oauth2.googleapis.com/token', data={
        'code': code, 'client_id': GOOGLE_CLIENT_ID, 'client_secret': GOOGLE_CLIENT_SECRET,
        'redirect_uri': GOOGLE_REDIRECT_URI, 'grant_type': 'authorization_code'
    })
    token_data    = token_r.json()
    access_token  = token_data.get('access_token', '')
    refresh_token = token_data.get('refresh_token', '')
    if not refresh_token:
        return '<p>Failed to get Google token. Please try again.</p>', 500

    gbp_location_id = ''
    try:
        accounts_r = requests.get('https://mybusinessaccountmanagement.googleapis.com/v1/accounts',
                                   headers={'Authorization': f'Bearer {access_token}'})
        accounts_data = accounts_r.json()
        log.info(f'GBP accounts response for {client_id}: {accounts_data}')
        accounts = accounts_data.get('accounts', [])
        if accounts:
            account_name = accounts[0]['name']
            locations_r = requests.get(
                f'https://mybusinessbusinessinformation.googleapis.com/v1/{account_name}/locations?readMask=name,title',
                headers={'Authorization': f'Bearer {access_token}'})
            locations_data = locations_r.json()
            log.info(f'GBP locations response for {client_id}: {locations_data}')
            locations = locations_data.get('locations', [])
            if locations:
                gbp_location_id = locations[0]['name'].split('/')[-1]
        else:
            log.warning(f'GBP no accounts found for {client_id}')
    except Exception as e:
        log.error(f'GBP location fetch error for {client_id}: {e}')

    # Write GBP token to Supabase
    client = get_client(client_id)
    current_status = (client.get('status') or '') if client else ''

    api_patch(f'/api/client/{client_id}/token', {
        'gbp_location_id':   gbp_location_id,
        'gbp_refresh_token': encrypt_token(refresh_token),
        'status':            'Token_Received' if current_status not in ('Token_Received','Provisioning','Active') else current_status,
    })

    # Add to GBP_Clients if Active
    if current_status == 'Active' and client:
        api_post('/api/gbp_clients', {
            'client_id':        client_id,
            'client_name':      client.get('business_name', ''),
            'gbp_location_id':  gbp_location_id,
            'gbp_credential':   encrypt_token(refresh_token),
            'business_type':    client.get('business_type', ''),
            'business_location':client.get('business_city', ''),
            'reply_sign_off':   (client.get('business_name') or '') + ' Team',
        })

    session['gbp_done'] = True
    return render_success(client_id, session.get('email', ''))


@app.route('/connect/health')
def health():
    return {'status': 'ok', 'service': 'posst-oauth', 'version': '4.0'}, 200




# ── VALIDATE DRIVE ────────────────────────────────────────────
# Checks if a Google Drive folder URL is accessible and returns subfolder structure
@app.route('/validate_drive', methods=['POST', 'OPTIONS'])
def validate_drive():
    if request.method == 'OPTIONS':
        resp = app.make_response('')
        resp.headers['Access-Control-Allow-Origin'] = _allowed_origin() or 'https://posst.app'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp
    try:
        d = request.get_json(silent=True) or {}
        drive_url = d.get('drive_url', '').strip()
        if not drive_url:
            resp = app.make_response(json.dumps({'valid': False, 'error': 'No URL provided'}))
            resp.content_type = 'application/json'
            resp.headers['Access-Control-Allow-Origin'] = _allowed_origin() or 'https://posst.app'
            return resp

        # Extract folder ID from URL
        import re as _re
        match = _re.search(r'/folders/([a-zA-Z0-9_-]+)', drive_url)
        if not match:
            resp = app.make_response(json.dumps({'valid': False, 'error': 'Invalid Google Drive folder URL'}))
            resp.content_type = 'application/json'
            resp.headers['Access-Control-Allow-Origin'] = _allowed_origin() or 'https://posst.app'
            return resp

        folder_id = match.group(1)

        # Try to list folder contents using Drive API
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        import os as _os

        sa_file = _os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', '/opt/posst/oauth/service_account.json')
        if not _os.path.exists(sa_file):
            # No service account — return valid=True with empty structure (best effort)
            resp = app.make_response(json.dumps({'valid': True, 'structure': [], 'note': 'no_service_account'}))
            resp.content_type = 'application/json'
            resp.headers['Access-Control-Allow-Origin'] = _allowed_origin() or 'https://posst.app'
            return resp

        creds = service_account.Credentials.from_service_account_file(
            sa_file, scopes=['https://www.googleapis.com/auth/drive.readonly'])
        service = build('drive', 'v3', credentials=creds)
        results = service.files().list(
            q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields='files(id,name)', pageSize=20).execute()
        folders = [f['name'] for f in results.get('files', [])]

        resp = app.make_response(json.dumps({'valid': True, 'structure': folders}))
        resp.content_type = 'application/json'
        resp.headers['Access-Control-Allow-Origin'] = _allowed_origin() or 'https://posst.app'
        return resp

    except Exception as e:
        log.error(f'validate_drive error: {e}')
        resp = app.make_response(json.dumps({'valid': True, 'structure': [], 'error': str(e)}))
        resp.content_type = 'application/json'
        resp.headers['Access-Control-Allow-Origin'] = _allowed_origin() or 'https://posst.app'
        return resp

# ── CORS PROXY ────────────────────────────────────────────────
# Forwards browser calls to posst-api with proper CORS headers
# Allows complete retirement of Apps Script for data operations

_CORS_ALLOWED = ['https://posst.app', 'https://www.posst.app', 'https://onboarding.posst.app', 'https://connect.posst.app']

def _allowed_origin():
    origin = request.headers.get('Origin', '')
    if origin.startswith('http://localhost:') or origin.startswith('http://127.0.0.1:'):
        return origin
    return origin if origin in _CORS_ALLOWED else ''

def cors_headers(response):
    origin = _allowed_origin()
    response.headers['Access-Control-Allow-Origin'] = origin if origin else 'https://posst.app'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# D2-11 Security: Add CSP and security headers to all responses from the OAuth server.
# Prevents XSS on the /connect pages (which render user-supplied business names).
@app.after_request
def add_security_headers(response):
    if 'text/html' in response.content_type:
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self' https://posst.app data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

AUTH_HEADERS = {'X-API-Key': POSST_API_SECRET}

# D1-2 Security: Only proxy the specific paths the frontend (onboarding + portal)
# actually calls. Previously the proxy forwarded ANY path — including /clients/active
# (all client data), /client/<id> (full row with encrypted tokens), and every admin
# endpoint. An attacker could simply call /proxy/clients/active from their browser
# and enumerate every client's data.
import re as _proxy_re

# Exact-match paths (no dynamic segments)
_PROXY_EXACT = {
    'portal_lookup', 'prospect', 'prospect/progress', 'prospect/convert',
    'search_volume', 'otp/send', 'otp/verify', 'client', 'chat',
    'stripe/checkout', 'stripe/coupon', 'stripe/portal',
    'email/reengagement', 'email/upgrade',
}

# Pattern-match paths (client_id dynamic segment)
# Each pattern is (compiled_regex, allowed_methods)
_PROXY_PATTERNS = [
    (_proxy_re.compile(r'^client/POSST_\d{8}_\d{3}/schedule$'),       {'PATCH'}),
    (_proxy_re.compile(r'^client/POSST_\d{8}_\d{3}/themes$'),         {'PATCH'}),
    (_proxy_re.compile(r'^client/POSST_\d{8}_\d{3}/drive$'),          {'PATCH'}),
    (_proxy_re.compile(r'^client/POSST_\d{8}_\d{3}/plan$'),           {'PATCH'}),
    (_proxy_re.compile(r'^client/POSST_\d{8}_\d{3}/pending_token$'),  {'GET', 'POST'}),
    (_proxy_re.compile(r'^client/POSST_\d{8}_\d{3}/cancel$'),         {'POST'}),
    (_proxy_re.compile(r'^client/POSST_\d{8}_\d{3}/pause$'),              {'POST'}),
    (_proxy_re.compile(r'^client/POSST_\d{8}_\d{3}/resume$'),             {'POST'}),
    # Phase 4: Style gallery + logo upload + portal onboarding (v43, Jul 15 2026)
    (_proxy_re.compile(r'^client/POSST_\d{8}_\d{3}/style-gallery$'),      {'GET'}),
    (_proxy_re.compile(r'^client/POSST_\d{8}_\d{3}/artistic-styles$'),    {'GET', 'POST'}),
    (_proxy_re.compile(r'^client/POSST_\d{8}_\d{3}/logo$'),               {'POST'}),
    (_proxy_re.compile(r'^client/POSST_\d{8}_\d{3}/portal-onboarded$'),   {'PATCH'}),
]

def _proxy_allowed(path, method):
    """Return True if this path+method is in the frontend allowlist."""
    if path in _PROXY_EXACT:
        return True
    for pattern, methods in _PROXY_PATTERNS:
        if pattern.match(path) and method in methods:
            return True
    return False

@app.route('/proxy/<path:path>', methods=['GET', 'POST', 'PATCH', 'OPTIONS'])
def proxy(path):
    if request.method == 'OPTIONS':
        return cors_headers(app.make_response(''))

    if not _proxy_allowed(path, request.method):
        log.warning(f'[PROXY BLOCKED] {request.method} /proxy/{path} from {request.headers.get("Origin", "unknown")}')
        _audit_log('proxy_blocked', detail={'path': path, 'method': request.method}, status_code=403)
        response = app.make_response(json.dumps({'status': 'error', 'message': 'Not allowed'}))
        response.status_code = 403
        response.content_type = 'application/json'
        return cors_headers(response)

    try:
        method = request.method
        url    = f'http://127.0.0.1:5680/api/{path}'
        data   = request.get_json(silent=True)
        params = request.args

        if method == 'GET':
            resp = requests.get(url, params=params, headers=AUTH_HEADERS, timeout=15)
        elif method == 'POST':
            resp = requests.post(url, json=data, headers=AUTH_HEADERS, timeout=15)
        elif method == 'PATCH':
            resp = requests.patch(url, json=data, headers=AUTH_HEADERS, timeout=15)
        else:
            return cors_headers(app.make_response(('Method not allowed', 405)))

        response = app.make_response(resp.text)
        response.status_code = resp.status_code
        response.content_type = 'application/json'
        return cors_headers(response)

    except Exception as e:
        log.error(f'Proxy error for {path}: {e}')
        response = app.make_response(json.dumps({'status': 'error', 'message': 'Internal error'}))
        response.status_code = 500
        response.content_type = 'application/json'
        return cors_headers(response)

# ── STRIPE WEBHOOK PASSTHROUGH ────────────────────────────────
# Stripe POSTs directly here — must forward raw bytes to posst-api
# so the HMAC signature check against the raw payload works correctly.
@app.route('/stripe/webhook', methods=['POST'])
def stripe_webhook_proxy():
    raw_body = request.get_data()
    sig      = request.headers.get('Stripe-Signature', '')
    try:
        resp = requests.post(
            'http://127.0.0.1:5680/api/stripe/webhook',
            data=raw_body,
            headers={'Content-Type': 'application/json', 'Stripe-Signature': sig},
            timeout=15
        )
        return resp.text, resp.status_code, {'Content-Type': 'application/json'}
    except Exception as e:
        log.error(f'Stripe webhook proxy error: {e}')
        return json.dumps({'status': 'error', 'message': str(e)}), 500, {'Content-Type': 'application/json'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

