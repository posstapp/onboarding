#!/usr/bin/env python3
"""
posst.app — Main API v1.0
Replaces Google Apps Script as the backend for all posst.app operations.
Connects to Supabase for data storage.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from supabase import create_client, Client
from functools import wraps

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────
SUPABASE_URL     = os.environ.get('SUPABASE_URL', 'https://itlndeorkphlorvcohaw.supabase.co')
SUPABASE_KEY     = os.environ.get('SUPABASE_SERVICE_KEY', '')
API_SECRET       = os.environ.get('POSST_API_SECRET', 'posst-api-secret-2026')

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── AUTH MIDDLEWARE ───────────────────────────────────────────
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('X-API-Key') or request.json.get('api_key', '') if request.json else ''
        if auth != API_SECRET:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

# ── HELPERS ───────────────────────────────────────────────────
def generate_client_id():
    """Generate next client ID for today."""
    today = datetime.now().strftime('%Y%m%d')
    prefix = f'POSST_{today}_'
    result = sb.table('clients').select('client_id').like('client_id', f'{prefix}%').execute()
    existing = [r['client_id'] for r in result.data]
    max_seq = 0
    for cid in existing:
        try:
            seq = int(cid.replace(prefix, ''))
            if seq > max_seq:
                max_seq = seq
        except:
            pass
    return f'{prefix}{str(max_seq + 1).zfill(3)}'

def generate_token():
    import secrets
    return secrets.token_hex(16)

def ok(data=None, **kwargs):
    r = {'status': 'success'}
    if data: r['data'] = data
    r.update(kwargs)
    return jsonify(r)

def err(message, code=400):
    return jsonify({'status': 'error', 'message': message}), code

# ── HEALTH ────────────────────────────────────────────────────
@app.route('/health')
def health():
    return ok(version='1.0', service='posst-api')

# ── CLIENT CRUD ───────────────────────────────────────────────
@app.route('/api/client', methods=['POST'])
def create_client_record():
    """Create new client — called from onboarding form submit."""
    d = request.json or {}
    client_id = generate_client_id()
    pending_token = generate_token()

    # Compute UTC posting time
    posting_time = d.get('posting_time', '11:00')
    timezone = d.get('timezone', 'Australia/Melbourne')

    posting_days = d.get('posting_days', 'Mon,Tue,Wed,Thu,Fri,Sat,Sun')
    if isinstance(posting_days, dict):
        days = [k[:3].capitalize() for k,v in posting_days.items() if v.get('active')]
        posting_days = ','.join(days)

    platforms = d.get('platforms', [])
    if isinstance(platforms, list):
        platforms = ','.join(platforms)

    drive_categories = d.get('drive_categories', [])
    if isinstance(drive_categories, str):
        try: drive_categories = json.loads(drive_categories)
        except: drive_categories = []

    notes = {}
    if d.get('caption_cta_phone'):
        notes['caption_phone'] = d['caption_cta_phone']

    row = {
        'client_id':           client_id,
        'status':              'Pending_Token',
        'phone':               d.get('business_phone', ''),
        'business_name':       d.get('business_name', ''),
        'business_city':       d.get('business_city', ''),
        'business_suburb':     d.get('business_suburb', ''),
        'business_country':    d.get('business_country', 'Australia'),
        'contact_email':       d.get('contact_email', ''),
        'business_type':       d.get('business_type', ''),
        'business_desc':       d.get('business_description', ''),
        'brand_keywords':      d.get('brand_keywords', ''),
        'plan':                d.get('tier', 'Standard'),
        'platforms':           platforms,
        'fb_page_name':        d.get('fb_page_name', ''),
        'fb_page_url':         d.get('facebook_page_url', ''),
        'ig_handle':           d.get('ig_handle', ''),
        'gbp_name':            d.get('gbp_name', ''),
        'posting_days':        posting_days,
        'posting_time':        posting_time,
        'timezone':            timezone,
        'monthly_report_day':  datetime.now().day,
        'notes':               notes,
        'google_drive_url':    d.get('google_drive_url', ''),
        'drive_categories':    drive_categories,
        'google_drive_intent': d.get('google_drive_intent', ''),
        'pending_token':       pending_token,
        'caption_email':       d.get('caption_cta_email', ''),
        'caption_phone':       d.get('caption_cta_phone', ''),
    }

    result = sb.table('clients').insert(row).execute()
    if not result.data:
        return err('Failed to create client')

    log.info(f'Client created: {client_id} — {d.get("business_name")}')
    return ok(client_id=client_id, pending_token=pending_token)

@app.route('/api/client/<client_id>', methods=['GET'])
def get_client(client_id):
    result = sb.table('clients').select('*').eq('client_id', client_id).single().execute()
    if not result.data:
        return err('Client not found', 404)
    return ok(result.data)

@app.route('/api/client/<client_id>/status', methods=['PATCH'])
def update_client_status(client_id):
    d = request.json or {}
    update = {'status': d.get('status')}
    if d.get('provisioned_at'):
        update['provisioned_at'] = d['provisioned_at']
    sb.table('clients').update(update).eq('client_id', client_id).execute()
    return ok()

@app.route('/api/client/<client_id>/schedule', methods=['PATCH'])
def update_schedule(client_id):
    d = request.json or {}
    update = {}
    if d.get('posting_days'): update['posting_days'] = d['posting_days']
    if d.get('posting_time'): update['posting_time'] = d['posting_time']
    if d.get('timezone'):     update['timezone'] = d['timezone']
    sb.table('clients').update(update).eq('client_id', client_id).execute()
    log.info(f'Schedule updated: {client_id}')
    return ok()

@app.route('/api/client/<client_id>/plan', methods=['PATCH'])
def update_plan(client_id):
    d = request.json or {}
    sb.table('clients').update({'plan': d.get('plan', 'Pro')}).eq('client_id', client_id).execute()
    log.info(f'Plan updated: {client_id} → {d.get("plan")}')
    return ok()

@app.route('/api/client/<client_id>/drive', methods=['PATCH'])
def update_drive(client_id):
    d = request.json or {}
    update = {
        'google_drive_url':    d.get('google_drive_url', ''),
        'drive_categories':    d.get('drive_categories', []),
        'google_drive_intent': d.get('google_drive_intent', 'now'),
        'pending_token':       ''
    }
    sb.table('clients').update(update).eq('client_id', client_id).execute()
    return ok()

@app.route('/api/client/<client_id>/token', methods=['PATCH'])
def update_token(client_id):
    d = request.json or {}
    update = {}
    if d.get('meta_token'):        update['meta_token'] = d['meta_token']
    if d.get('meta_token_expiry'): update['meta_token_expiry'] = d['meta_token_expiry']
    if d.get('fb_page_id'):        update['fb_page_id'] = d['fb_page_id']
    if d.get('fb_page_name'):      update['fb_page_name'] = d['fb_page_name']
    if d.get('ig_business_id'):    update['ig_business_id'] = d['ig_business_id']
    if d.get('ig_handle'):         update['ig_handle'] = d['ig_handle']
    if d.get('gbp_refresh_token'): update['gbp_refresh_token'] = d['gbp_refresh_token']
    if d.get('gbp_location_id'):   update['gbp_location_id'] = d['gbp_location_id']
    if d.get('status'):            update['status'] = d['status']
    if d.get('pending_token') is not None: update['pending_token'] = d['pending_token']
    sb.table('clients').update(update).eq('client_id', client_id).execute()
    return ok()

@app.route('/api/client/<client_id>/themes', methods=['PATCH'])
def update_themes(client_id):
    d = request.json or {}
    result = sb.table('clients').select('notes').eq('client_id', client_id).single().execute()
    notes = result.data.get('notes', {}) if result.data else {}
    if isinstance(notes, str):
        try: notes = json.loads(notes)
        except: notes = {}
    notes['day_themes'] = d.get('day_themes', {})
    sb.table('clients').update({'notes': notes}).eq('client_id', client_id).execute()
    return ok()

@app.route('/api/client/<client_id>/cancel', methods=['POST'])
def cancel_client(client_id):
    sb.table('clients').update({'status': 'Cancelled'}).eq('client_id', client_id).execute()
    log.info(f'Client cancelled: {client_id}')
    return ok()

@app.route('/api/client/<client_id>/pause', methods=['POST'])
def pause_client(client_id):
    sb.table('clients').update({'status': 'Paused'}).eq('client_id', client_id).execute()
    log.info(f'Client paused: {client_id}')
    return ok()

# ── PORTAL LOOKUP ─────────────────────────────────────────────
@app.route('/api/portal_lookup', methods=['POST'])
def portal_lookup():
    d = request.json or {}
    phone = d.get('phone', '').strip().replace(' ', '')
    if not phone:
        return err('Phone required')
    # Try with + prefix and without
    result = sb.table('clients').select('*').eq('phone', phone).execute()
    if not result.data:
        # Try stripping leading apostrophe (legacy sheet format)
        result = sb.table('clients').select('*').eq('phone', "'" + phone).execute()
    if not result.data:
        return jsonify({'status': 'not_found'})
    client = result.data[0]
    return ok({
        'client_id':        client['client_id'],
        'business_name':    client['business_name'],
        'email':            client['contact_email'],
        'plan':             client['plan'],
        'platforms':        client['platforms'],
        'drive_intent':     client['google_drive_intent'],
        'google_drive_url': client['google_drive_url'],
        'status':           client['status'],
        'fb_connected':     bool(client.get('fb_page_id')),
        'ig_connected':     bool(client.get('ig_business_id')),
        'gbp_connected':    bool(client.get('gbp_location_id')),
        'posting_days':     client['posting_days'],
        'posting_time':     client['posting_time'],
        'timezone':         client['timezone'],
        'notes':            client.get('notes', {}),
        'fb_page_name':     client.get('fb_page_name', ''),
        'ig_handle':        client.get('ig_handle', ''),
    })

# ── PENDING TOKEN ─────────────────────────────────────────────
@app.route('/api/client/<client_id>/pending_token', methods=['GET'])
def get_pending_token(client_id):
    result = sb.table('clients').select('pending_token').eq('client_id', client_id).single().execute()
    if not result.data:
        return err('Client not found', 404)
    return ok(token=result.data.get('pending_token', ''))

@app.route('/api/client/<client_id>/pending_token', methods=['POST'])
def generate_pending_token(client_id):
    token = generate_token()
    sb.table('clients').update({'pending_token': token}).eq('client_id', client_id).execute()
    return ok(token=token)

# ── ACTIVE CLIENTS FOR POSTING ────────────────────────────────
@app.route('/api/clients/active', methods=['GET'])
def get_active_clients():
    result = sb.table('clients').select('*').eq('status', 'Active').execute()
    return ok(result.data, count=len(result.data))

@app.route('/api/clients/token_received', methods=['GET'])
def get_token_received_clients():
    result = sb.table('clients').select('*').eq('status', 'Token_Received').execute()
    return ok(result.data, count=len(result.data))

# ── PROSPECTS ─────────────────────────────────────────────────
@app.route('/api/prospect', methods=['POST'])
def create_prospect():
    d = request.json or {}
    phone = d.get('phone', '')
    if not phone:
        return err('Phone required')
    # Check if exists
    existing = sb.table('prospects').select('id').eq('phone', phone).execute()
    if existing.data:
        return ok(action='exists')
    row = {
        'session_id':    d.get('session_id', ''),
        'phone':         phone,
        'business_name': d.get('business_name', ''),
        'business_city': d.get('business_city', ''),
        'business_type': d.get('business_type', ''),
        'google_score':  d.get('google_score'),
        'search_volume': d.get('search_volume'),
        'review_count':  d.get('review_count'),
        'competitor_avg':d.get('competitor_avg'),
        'status':        'prospect',
        'last_step_reached': 'landing',
    }
    sb.table('prospects').insert(row).execute()
    return ok(action='created')

@app.route('/api/prospect/progress', methods=['POST'])
def save_progress():
    d = request.json or {}
    phone = d.get('phone', '')
    if not phone:
        return err('Phone required')
    state = json.dumps({'step': d.get('step', 0), 'form': d.get('form', {}), 'saved_at': datetime.now().isoformat()})
    existing = sb.table('prospects').select('id').eq('phone', phone).execute()
    if existing.data:
        sb.table('prospects').update({'form_state': state, 'last_step_reached': str(d.get('step', 0))}).eq('phone', phone).execute()
    return ok(action='saved')

@app.route('/api/prospect/progress', methods=['GET'])
def load_progress():
    phone = request.args.get('phone', '').strip()
    if not phone:
        return err('Phone required')
    result = sb.table('prospects').select('*').eq('phone', phone).execute()
    if not result.data:
        return jsonify({'success': False, 'error': 'no saved progress'})
    row = result.data[0]
    if row.get('status') == 'converted':
        return jsonify({'success': False, 'error': 'already converted'})
    form_state = row.get('form_state', {})
    if isinstance(form_state, str):
        try: form_state = json.loads(form_state)
        except: form_state = {}
    if not form_state:
        return jsonify({'success': False, 'error': 'no saved progress'})
    return jsonify({'success': True, 'step': form_state.get('step', 0), 'form': form_state.get('form', {}), 'saved_at': form_state.get('saved_at', ''), 'business_name': row.get('business_name', '')})

@app.route('/api/prospect/convert', methods=['POST'])
def convert_prospect():
    d = request.json or {}
    phone = d.get('phone', '')
    if not phone:
        return err('Phone required')
    sb.table('prospects').update({'status': 'converted', 'converted_at': datetime.now().isoformat(), 'form_state': {}}).eq('phone', phone).execute()
    return ok(action='converted')

# ── POSTS LOG ─────────────────────────────────────────────────
@app.route('/api/posts_log', methods=['POST'])
def log_post():
    d = request.json or {}
    row = {
        'client_id':    d.get('client_id'),
        'business_name':d.get('business_name', ''),
        'pillar':       d.get('pillar', ''),
        'fb_status':    d.get('fb_status', ''),
        'ig_status':    d.get('ig_status', ''),
        'gbp_status':   d.get('gbp_status', 'N/A'),
        'image_url':    d.get('image_url', ''),
        'fb_post_id':   d.get('fb_post_id', ''),
        'ig_post_id':   d.get('ig_post_id', ''),
        'gbp_post_id':  d.get('gbp_post_id', ''),
        'fb_caption':   d.get('fb_caption', ''),
        'ig_caption':   d.get('ig_caption', ''),
        'gbp_caption':  d.get('gbp_caption', ''),
        'image_prompt': d.get('image_prompt', ''),
        'image_source': d.get('image_source', 'ai'),
    }
    sb.table('posts_log').insert(row).execute()
    return ok()

# ── PROVISIONING LOG ──────────────────────────────────────────
@app.route('/api/provisioning_log', methods=['POST'])
def log_provisioning():
    d = request.json or {}
    row = {
        'client_id':    d.get('client_id'),
        'business_name':d.get('business_name', ''),
        'plan':         d.get('plan', ''),
        'platforms':    d.get('platforms', ''),
        'workflow_id':  d.get('workflow_id', ''),
        'status':       d.get('status', ''),
        'error':        d.get('error', ''),
    }
    sb.table('provisioning_log').insert(row).execute()
    return ok()

# ── GBP CLIENTS ───────────────────────────────────────────────
@app.route('/api/gbp_clients', methods=['GET'])
def get_gbp_clients():
    result = sb.table('gbp_clients').select('*').eq('active', True).eq('gbp_enabled', True).execute()
    return ok(result.data, count=len(result.data))

@app.route('/api/gbp_clients', methods=['POST'])
def add_gbp_client():
    d = request.json or {}
    # Check if already exists
    existing = sb.table('gbp_clients').select('id').eq('client_id', d.get('client_id')).execute()
    if existing.data:
        sb.table('gbp_clients').update({
            'gbp_location_id': d.get('gbp_location_id', ''),
            'gbp_credential':  d.get('gbp_credential', ''),
            'active':          True,
            'gbp_enabled':     True,
        }).eq('client_id', d.get('client_id')).execute()
        return ok(action='updated')
    row = {
        'client_id':        d.get('client_id'),
        'client_name':      d.get('client_name', ''),
        'active':           True,
        'gbp_enabled':      True,
        'gbp_location_id':  d.get('gbp_location_id', ''),
        'gbp_credential':   d.get('gbp_credential', ''),
        'business_type':    d.get('business_type', ''),
        'business_location':d.get('business_location', ''),
        'reply_sign_off':   d.get('reply_sign_off', ''),
    }
    sb.table('gbp_clients').insert(row).execute()
    return ok(action='created')

# ── REVIEW LOG ────────────────────────────────────────────────
@app.route('/api/review_log', methods=['POST'])
def log_review():
    d = request.json or {}
    row = {
        'client_id':    d.get('client_id'),
        'business_name':d.get('business_name', ''),
        'reviewer_name':d.get('reviewer_name', ''),
        'rating':       d.get('rating'),
        'review_text':  d.get('review_text', ''),
        'reply_text':   d.get('reply_text', ''),
        'reply_status': d.get('reply_status', ''),
        'review_id':    d.get('review_id', ''),
    }
    try:
        sb.table('review_log').insert(row).execute()
    except Exception as e:
        if 'unique' in str(e).lower():
            return ok(action='already_logged')
        raise
    return ok()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5680, debug=False)
