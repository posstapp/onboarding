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
import requests
from datetime import datetime, timedelta
from flask import Flask, request, redirect, session, render_template_string
from cryptography.fernet import Fernet

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'change-this-in-production')

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

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

def api_get(path):
    try:
        r = requests.get(f'{API_BASE}{path}', timeout=10)
        return r.json()
    except Exception as e:
        log.error(f'API GET {path} error: {e}')
        return None

def api_post(path, data):
    try:
        r = requests.post(f'{API_BASE}{path}', json=data, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f'API POST {path} error: {e}')
        return None

def api_patch(path, data):
    try:
        r = requests.patch(f'{API_BASE}{path}', json=data, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f'API PATCH {path} error: {e}')
        return None

def get_client(client_id):
    result = api_get(f'/api/client/{client_id}')
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
      <strong>Step 1 — If Meta shows a "Reconnect" screen:</strong> click <strong>Edit settings</strong> to see your full page list and select the correct one.<br><br>
      <strong>Step 2 — Select pages:</strong> choose only the Facebook page for <strong>{{ business }}</strong> — uncheck any other pages.<br><br>
      <strong>Step 3 — Select Instagram:</strong> choose the Instagram account linked to <strong>{{ business }}</strong> — uncheck any others.<br><br>
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
    ⚠️ You manage multiple pages — make sure you select the correct one for <strong>{{ business }}</strong>.
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

    session['ll_token']  = ll_token
    session['ll_expiry'] = ll_expiry.strftime('%d/%m/%Y')
    session['client_id'] = client_id

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
    ll_token    = session.get('ll_token', '')
    ll_expiry   = session.get('ll_expiry', '')
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

    # Write to Supabase via posst-api
    api_patch(f'/api/client/{client_id}/token', {
        'fb_page_id':        fb_page_id,
        'fb_page_name':      page_name,
        'ig_business_id':    ig_biz_id,
        'ig_handle':         ig_username,
        'meta_token':        encrypt_token(page_token),
        'meta_token_expiry': expiry_str,
        'status':            'Token_Received',
        'pending_token':     '',
    })

    session['meta_done']    = True
    session['fb_page_name'] = page_name
    session['ig_username']  = ig_username

    return redirect(f'/connect?client_id={client_id}&_return=1')


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
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp
    try:
        d = request.get_json(silent=True) or {}
        drive_url = d.get('drive_url', '').strip()
        if not drive_url:
            resp = app.make_response(json.dumps({'valid': False, 'error': 'No URL provided'}))
            resp.content_type = 'application/json'
            resp.headers['Access-Control-Allow-Origin'] = '*'
            return resp

        # Extract folder ID from URL
        import re as _re
        match = _re.search(r'/folders/([a-zA-Z0-9_-]+)', drive_url)
        if not match:
            resp = app.make_response(json.dumps({'valid': False, 'error': 'Invalid Google Drive folder URL'}))
            resp.content_type = 'application/json'
            resp.headers['Access-Control-Allow-Origin'] = '*'
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
            resp.headers['Access-Control-Allow-Origin'] = '*'
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
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp

    except Exception as e:
        log.error(f'validate_drive error: {e}')
        resp = app.make_response(json.dumps({'valid': True, 'structure': [], 'error': str(e)}))
        resp.content_type = 'application/json'
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp

# ── CORS PROXY ────────────────────────────────────────────────
# Forwards browser calls to posst-api with proper CORS headers
# Allows complete retirement of Apps Script for data operations

def cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

AUTH_HEADERS = {'X-API-Key': POSST_API_SECRET}

@app.route('/proxy/<path:path>', methods=['GET', 'POST', 'PATCH', 'OPTIONS'])
def proxy(path):
    if request.method == 'OPTIONS':
        return cors_headers(app.make_response(''))

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
        response = app.make_response(json.dumps({'status': 'error', 'message': str(e)}))
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
