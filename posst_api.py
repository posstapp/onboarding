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
from urllib.parse import quote
from flask import Flask, request, jsonify
from supabase import create_client, Client
import sys
sys.path.insert(0, '/opt/posst')
try:
    from posst_email import (
        send_go_live_email, send_cancellation_email, send_pause_email,
        send_day1_email, send_day7_standard_email, send_day7_pro_email,
        send_trial_ending_email, send_monthly_email, send_missing_platform_email,
        send_reengagement_email, send_internal_alert, send_upgrade_email,
        send_connection_error_email, send_reconnect_confirmation_email
    )
    EMAIL_AVAILABLE = True
except Exception as e:
    EMAIL_AVAILABLE = False
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
    return ok(version='1.3', service='posst-api')

# ── CLIENT CRUD ───────────────────────────────────────────────
@app.route('/api/client', methods=['POST'])
def create_client_record():
    """Create new client — called from onboarding form submit."""
    d = request.json or {}
    client_id = generate_client_id()
    pending_token = generate_token()

    # Compute UTC posting time — the calculation was previously missing
    # entirely despite this comment claiming otherwise. Every client created
    # via onboarding had posting_time_utc left unset, so the n8n posting
    # workflow (which schedules off the UTC field) fell back to whatever
    # default it assumed instead of the business's actual chosen time.
    posting_time = d.get('posting_time', '11:00')
    timezone = d.get('timezone', 'Australia/Melbourne')
    posting_time_utc = None
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime as dt
        local_h, local_m = map(int, posting_time.split(':'))
        tz = ZoneInfo(timezone)
        local_dt = dt.now(tz).replace(hour=local_h, minute=local_m, second=0, microsecond=0)
        utc_dt = local_dt.astimezone(ZoneInfo('UTC'))
        posting_time_utc = utc_dt.strftime('%H:%M')
    except Exception as e:
        log.warning(f'Could not calculate posting_time_utc at creation: {e}')

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
        'posting_time_utc':    posting_time_utc,
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
    new_status = d.get('status')
    update = {'status': new_status}
    if d.get('provisioned_at'):
        update['provisioned_at'] = d['provisioned_at']
    # Set trial_start when client first goes Active
    if new_status == 'Active':
        existing = sb.table('clients').select('trial_start').eq('client_id', client_id).single().execute()
        if not (existing.data or {}).get('trial_start'):
            update['trial_start'] = datetime.now().strftime('%Y-%m-%d')
    sb.table('clients').update(update).eq('client_id', client_id).execute()
    return ok()

@app.route('/api/client/<client_id>/schedule', methods=['PATCH'])
def update_schedule(client_id):
    d = request.json or {}
    update = {}
    if d.get('posting_days'): update['posting_days'] = d['posting_days']
    if d.get('posting_time'): update['posting_time'] = d['posting_time']
    if d.get('timezone'):     update['timezone'] = d['timezone']
    # Calculate posting_time_utc from local time + timezone
    if d.get('posting_time') and d.get('timezone'):
        try:
            from zoneinfo import ZoneInfo
            from datetime import datetime as dt
            local_h, local_m = map(int, d['posting_time'].split(':'))
            tz = ZoneInfo(d['timezone'])
            local_dt = dt.now(tz).replace(hour=local_h, minute=local_m, second=0, microsecond=0)
            utc_dt = local_dt.astimezone(ZoneInfo('UTC'))
            update['posting_time_utc'] = utc_dt.strftime('%H:%M')
        except Exception as e:
            log.warning(f'Could not calculate posting_time_utc: {e}')
    sb.table('clients').update(update).eq('client_id', client_id).execute()
    log.info(f'Schedule updated: {client_id}')
    return ok()

@app.route('/api/client/<client_id>/plan', methods=['PATCH'])
def update_plan(client_id):
    d = request.json or {}
    new_plan = d.get('plan', 'Pro')

    # Look up subscription so we can swap the Stripe price to match (prevents
    # plan/price drift — see Lesson: Upgrade to Pro previously only touched
    # Supabase, never the actual Stripe subscription price).
    client_res = sb.table('clients').select('stripe_subscription_id').eq('client_id', client_id).single().execute()
    stripe_subscription_id = (client_res.data or {}).get('stripe_subscription_id', '')

    if stripe_subscription_id and new_plan in STRIPE_PRICES and STRIPE_PRICES[new_plan]:
        # Fetch current subscription to get the line item ID to swap
        sub, sub_err = stripe_request('GET', f'/subscriptions/{stripe_subscription_id}')
        if sub_err:
            log.error(f'Plan update — could not fetch subscription for {client_id}: {sub_err}')
            return err(f'Could not verify Stripe subscription: {sub_err}')
        items = (sub or {}).get('items', {}).get('data', [])
        if items:
            item_id = items[0]['id']
            swap_payload = {
                'items[0][id]':    item_id,
                'items[0][price]': STRIPE_PRICES[new_plan],
                'proration_behavior': 'none',  # trial/manual upgrades — no surprise mid-cycle charge
            }
            result, result_err = stripe_request('POST', f'/subscriptions/{stripe_subscription_id}', swap_payload)
            if result_err:
                log.error(f'Plan update — Stripe price swap failed for {client_id}: {result_err}')
                return err(f'Stripe price update failed: {result_err}')
            log.info(f'Stripe subscription price swapped: {client_id} → {new_plan}')
        else:
            log.warning(f'Plan update — no subscription items found for {client_id}, Supabase-only update')
    else:
        log.warning(f'Plan update — no stripe_subscription_id for {client_id}, Supabase-only update (pre-payment client)')

    sb.table('clients').update({'plan': new_plan}).eq('client_id', client_id).execute()
    log.info(f'Plan updated: {client_id} → {new_plan}')
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
    if d.get('status'):
        # The OAuth flow (oauth_connect_v4.py) sends status='Token_Received' on
        # EVERY completed connection, including when an already-Active/Paused/
        # Cancelled client reconnects or adds a platform later (e.g. adding
        # Instagram to an FB-only client from the portal). Previously this
        # blindly overwrote status, which downgraded an established client
        # back to Token_Received — and a separate (n8n) job polling for
        # Token_Received clients then re-ran full go-live provisioning,
        # re-sending the "you're live" go-live email and logging a duplicate
        # provisioning_log entry for a client that was already live.
        # Confirmed happening live on 2026-06-20 15:20 UTC against Clippers.
        # Token_Received should only ever apply to a client's first-ever
        # connection — never downgrade a client already past that point.
        existing = sb.table('clients').select('status').eq('client_id', client_id).single().execute()
        current_status = (existing.data or {}).get('status', '')
        if d['status'] == 'Token_Received' and current_status in ('Active', 'Paused', 'Cancelled'):
            log.info(f'update_token: skipping status downgrade to Token_Received for {client_id} (currently {current_status})')
        else:
            update['status'] = d['status']
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
    # Cancel the actual Stripe subscription, not just the Supabase status —
    # same root-cause pattern as the plan/price drift bug (see /plan endpoint).
    # A "cancelled" client whose Stripe sub keeps running is the same class of bug.
    client_res = sb.table('clients').select('stripe_subscription_id').eq('client_id', client_id).single().execute()
    stripe_subscription_id = (client_res.data or {}).get('stripe_subscription_id', '')

    if stripe_subscription_id:
        result, result_err = stripe_request('DELETE', f'/subscriptions/{stripe_subscription_id}')
        if result_err:
            # If Stripe says it's already cancelled/missing, don't block the Supabase update —
            # but any other error should surface so it isn't silently swallowed.
            if 'already' not in result_err.lower() and 'no such subscription' not in result_err.lower():
                log.error(f'Cancel — Stripe cancellation failed for {client_id}: {result_err}')
                return err(f'Stripe cancellation failed: {result_err}')
            log.warning(f'Cancel — Stripe sub already gone for {client_id}, proceeding: {result_err}')
        else:
            log.info(f'Stripe subscription cancelled: {client_id} ({stripe_subscription_id})')
    else:
        log.warning(f'Cancel — no stripe_subscription_id for {client_id}, Supabase-only update (pre-payment client)')

    sb.table('clients').update({'status': 'Cancelled'}).eq('client_id', client_id).execute()
    log.info(f'Client cancelled: {client_id}')
    return ok()

@app.route('/api/client/<client_id>/pause', methods=['POST'])
def pause_client(client_id):
    # Pause billing via Stripe's native pause_collection (keeps the subscription
    # intact and resumable — distinct from cancel, which deletes it outright).
    client_res = sb.table('clients').select('stripe_subscription_id').eq('client_id', client_id).single().execute()
    stripe_subscription_id = (client_res.data or {}).get('stripe_subscription_id', '')

    if stripe_subscription_id:
        pause_payload = {'pause_collection[behavior]': 'void'}
        result, result_err = stripe_request('POST', f'/subscriptions/{stripe_subscription_id}', pause_payload)
        if result_err:
            log.error(f'Pause — Stripe pause_collection failed for {client_id}: {result_err}')
            return err(f'Stripe pause failed: {result_err}')
        log.info(f'Stripe subscription billing paused: {client_id} ({stripe_subscription_id})')
    else:
        log.warning(f'Pause — no stripe_subscription_id for {client_id}, Supabase-only update (pre-payment client)')

    sb.table('clients').update({'status': 'Paused'}).eq('client_id', client_id).execute()
    log.info(f'Client paused: {client_id}')
    return ok()

@app.route('/api/client/<client_id>/resume', methods=['POST'])
def resume_client(client_id):
    # Resumes billing for a paused client — clears pause_collection on Stripe
    # and restores Active status. No UI button yet (manual/portal use for now).
    client_res = sb.table('clients').select('stripe_subscription_id').eq('client_id', client_id).single().execute()
    stripe_subscription_id = (client_res.data or {}).get('stripe_subscription_id', '')

    if stripe_subscription_id:
        resume_payload = {'pause_collection': ''}
        result, result_err = stripe_request('POST', f'/subscriptions/{stripe_subscription_id}', resume_payload)
        if result_err:
            log.error(f'Resume — Stripe resume failed for {client_id}: {result_err}')
            return err(f'Stripe resume failed: {result_err}')
        log.info(f'Stripe subscription billing resumed: {client_id} ({stripe_subscription_id})')
    else:
        log.warning(f'Resume — no stripe_subscription_id for {client_id}, Supabase-only update')

    sb.table('clients').update({'status': 'Active'}).eq('client_id', client_id).execute()
    log.info(f'Client resumed: {client_id}')
    return ok()

# ── PORTAL LOOKUP ─────────────────────────────────────────────
@app.route('/api/portal_lookup', methods=['POST'])
def portal_lookup():
    d = request.json or {}
    phone_raw = d.get('phone', '').strip()
    if not phone_raw:
        return err('Phone required')
    # Normalize — remove all spaces for comparison
    phone = phone_raw.replace(' ', '')
    # Fetch all clients and compare normalized phones — collect ALL matches
    result = sb.table('clients').select('*').order('created_at', desc=False).execute()
    clients = []
    for row in result.data:
        stored = (row.get('phone') or '').replace(' ', '').lstrip("'")
        if stored == phone:
            clients.append(row)
    if not clients:
        return jsonify({'status': 'not_found'})
    # If client_id specified (business switcher), use that client as primary
    requested_id = d.get('client_id', '')
    if requested_id:
        primary = next((c for c in clients if c['client_id'] == requested_id), clients[0])
    else:
        # Default to first Active client, else first client
        primary = next((c for c in clients if c.get('status') == 'Active'), clients[0])
    def get_latest_post_status(client_id, client_updated_at=None):
        """Query posts_log for the most recent row — derive error flags from it.

        If a FAILED row exists but the client row was updated (token refreshed)
        AFTER that failure, the error is stale — clear it so the portal stops
        showing Reconnect after a successful OAuth flow.
        """
        try:
            res = sb.table('posts_log') \
                    .select('fb_status,ig_status,gbp_status,posted_at') \
                    .eq('client_id', client_id) \
                    .order('posted_at', desc=True) \
                    .limit(1) \
                    .execute()
            if res.data:
                row = res.data[0]
                fb_failed  = row['fb_status']  == 'FAILED'
                ig_failed  = row['ig_status']  == 'FAILED'
                gbp_failed = row['gbp_status'] == 'FAILED'

                # If any platform failed, check whether the token was refreshed
                # after that failure. If so, the error is stale — suppress it.
                # Guard: only apply if both timestamps are present and parseable.
                if (fb_failed or ig_failed or gbp_failed) and client_updated_at and row.get('posted_at'):
                    try:
                        from datetime import timezone as _tz
                        def _parse(ts):
                            # Handle both offset-aware and naive timestamps from Supabase
                            import dateutil.parser
                            return dateutil.parser.parse(ts)
                        t_updated = _parse(str(client_updated_at))
                        t_posted  = _parse(str(row['posted_at']))
                        if t_updated > t_posted:
                            # Token was refreshed after this failure — stale error, clear it
                            log.info(f'get_latest_post_status: clearing stale error for {client_id} '
                                     f'(token refreshed {t_updated} after failure {t_posted})')
                            fb_failed  = False
                            ig_failed  = False
                            gbp_failed = False
                    except Exception as te:
                        # If timestamp parsing fails, fall back to showing the error (safe default)
                        log.warning(f'get_latest_post_status: timestamp compare failed for {client_id}: {te}')

                return {
                    'fb_error':      fb_failed,
                    'ig_error':      ig_failed,
                    'gbp_error':     gbp_failed,
                    'last_post_at':  row['posted_at'],
                }
        except Exception:
            pass
        return {'fb_error': False, 'ig_error': False, 'gbp_error': False, 'last_post_at': None}

    def fmt(client):
        post_status = get_latest_post_status(client['client_id'], client.get('updated_at'))
        return {
            'client_id':        client['client_id'],
            'business_name':    client['business_name'],
            'business_city':    client.get('business_city', ''),
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
            'trial_start':      client.get('trial_start', ''),
            'drive_categories': client.get('drive_categories', []),
            'pending_token':    client.get('pending_token', ''),
            'contact_email':    client.get('contact_email', ''),
            # Operational status — derived from posts_log, never stored on clients
            'fb_error':         post_status['fb_error'],
            'ig_error':         post_status['ig_error'],
            'gbp_error':        post_status['gbp_error'],
            'last_post_at':     post_status['last_post_at'],
        }
    # Return primary client + full list for switcher
    # Check for an incomplete prospect (a separate, never-converted signup attempt)
    # for this same phone — without this, a returning user with a real client AND
    # an abandoned new-business attempt would never see the abandoned one again,
    # since prospects and clients are different tables and this endpoint only
    # ever looked at clients. Surfaced as 'draft_prospect' so the switcher can
    # show it as a resumable entry rather than it silently disappearing.
    draft_prospect = None
    prospect_res = sb.table('prospects').select('*').execute()
    for prow in (prospect_res.data or []):
        stored_phone = (prow.get('phone') or '').replace(' ', '').lstrip("'")
        if stored_phone == phone and prow.get('status') != 'converted' and prow.get('business_name'):
            draft_prospect = {
                'business_name':      prow.get('business_name', ''),
                'last_step_reached':  prow.get('last_step_reached', ''),
                'status':             'Draft',
            }
            break

    return ok({
        **fmt(primary),
        'all_clients': [{'client_id': c['client_id'], 'business_name': c['business_name'], 'status': c['status']} for c in clients],
        'draft_prospect': draft_prospect,
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
    log.info(f'create_prospect: incoming payload for phone={phone}: {d}')
    existing = sb.table('prospects').select('*').eq('phone', phone).execute()
    # Only ever update a row that is still an active, incomplete draft.
    # A 'converted' row is a permanent historical record of a real past
    # signup and must NEVER be overwritten by a later, unrelated attempt
    # under the same phone (e.g. testing a different business) — an
    # earlier version of this fix did exactly that and destroyed a real
    # historical row on 2026-06-20. Converted rows are now untouchable.
    active_row = next((r for r in (existing.data or []) if r.get('status') != 'converted'), None)
    if active_row:
        # Guard against regression: createProspect() is called fresh at the
        # very start of EVERY OTP verification (status='otp_verified',
        # last_step_reached='otp'), regardless of whether this is a brand
        # new attempt or a second/stray OTP verify under the same phone
        # while a real, further-along draft already exists (e.g. a second
        # browser tab, or re-verifying for an unrelated reason). Without
        # this guard, that early-stage write blindly overwrites
        # business_name/city/type with whatever sessionStorage happened to
        # hold at that moment — even placeholder/blank data — destroying a
        # real in-progress draft that was already several steps further
        # along. Confirmed live: an Angelicurio draft (last_step_reached: 4,
        # real business data) got overwritten by a later OTP-verify call
        # (last_step_reached: 'otp') carrying "Melbourne"/"local business"
        # placeholder data, on 2026-06-21. If the active row already shows
        # real progress (a numeric/step_ last_step_reached, i.e. anything
        # past the bare OTP stage) and this write is itself just the bare
        # OTP-verify stage, don't let it clobber the further-along data.
        existing_step = str(active_row.get('last_step_reached', ''))
        incoming_step = str(d.get('last_step_reached', ''))
        existing_has_progress = existing_step not in ('', 'otp', 'landing')
        is_otp_stage_write = incoming_step == 'otp'
        if is_otp_stage_write and existing_has_progress:
            log.info(f'create_prospect: skipping OTP-stage overwrite for phone={phone} — active row already at last_step_reached={existing_step}')
            if d.get('session_id'):
                sb.table('prospects').update({'session_id': d.get('session_id')}).eq('id', active_row['id']).execute()
            return ok(action='skipped_regression_guard')
        update = {}
        if d.get('business_name'): update['business_name'] = d.get('business_name')
        if d.get('business_city'): update['business_city'] = d.get('business_city')
        if d.get('business_type'): update['business_type'] = d.get('business_type')
        if d.get('email'):         update['email'] = d.get('email')
        if d.get('status'):        update['status'] = d.get('status')
        if d.get('last_step_reached'): update['last_step_reached'] = d.get('last_step_reached')
        if d.get('session_id'):    update['session_id'] = d.get('session_id')
        if update:
            sb.table('prospects').update(update).eq('id', active_row['id']).execute()
        return ok(action='updated')
    # No active draft for this phone — either a first-ever attempt, or every
    # prior row for this phone is already converted. Insert a fresh row;
    # a phone genuinely can convert more than once over time (different
    # businesses), so multiple historical rows per phone is correct.
    row = {
        'session_id':    d.get('session_id', ''),
        'phone':         phone,
        'business_name': d.get('business_name', ''),
        'business_city': d.get('business_city', ''),
        'business_type': d.get('business_type', ''),
        'email':         d.get('email', ''),
        'google_score':  d.get('google_score'),
        'search_volume': d.get('search_volume'),
        'review_count':  d.get('review_count'),
        'competitor_avg':d.get('competitor_avg'),
        'status':        'prospect',
        'last_step_reached': 'landing',
    }
    # Do NOT swallow insert failures — a prior version of this endpoint
    # returned ok(action='created') unconditionally even if the insert
    # never wrote a row. If the same phone already has a 'converted'
    # row and a UNIQUE constraint exists on prospects.phone, this insert
    # will throw — that must surface as a real error, not a silent 500
    # that the frontend's try/catch then hides from the user entirely.
    try:
        result = sb.table('prospects').insert(row).execute()
        if not result.data:
            log.error(f'create_prospect: insert returned no data for phone={phone}, row={row}')
            return err('Failed to create prospect row (no data returned)', 500)
    except Exception as e:
        log.error(f'create_prospect: insert failed for phone={phone}: {e}')
        return err(f'Failed to create prospect row: {e}', 500)
    return ok(action='created')

@app.route('/api/prospect/progress', methods=['POST'])
def save_progress():
    d = request.json or {}
    phone = d.get('phone', '')
    if not phone:
        return err('Phone required')
    log.info(f'save_progress: incoming for phone={phone}, step={d.get("step")}, form.business_name={(d.get("form") or {}).get("business_name")}, form.business_city={(d.get("form") or {}).get("business_city")}')
    state = json.dumps({'step': d.get('step', 0), 'form': d.get('form', {}), 'saved_at': datetime.now().isoformat()})
    existing = sb.table('prospects').select('*').eq('phone', phone).execute()
    # Same protection as create_prospect: only ever write form_state to an
    # active, non-converted draft row. This endpoint previously matched by
    # phone alone and would silently overwrite a converted row's form_state
    # with whatever the current in-progress draft was — exactly what
    # corrupted the Clippers historical record on 2026-06-20.
    active_row = next((r for r in (existing.data or []) if r.get('status') != 'converted'), None)
    if not active_row:
        # Previously fell through to `return ok(action='saved')` here even
        # though nothing was written — a silent false-positive that would
        # mask exactly the failure mode where create_prospect()'s insert
        # never landed a row in the first place. Surface it instead.
        log.error(f'save_progress: no active (non-converted) prospect row found for phone={phone}; nothing saved')
        return err('No active prospect row to save progress against', 404)
    update = {'form_state': state, 'last_step_reached': str(d.get('step', 0))}
    form = d.get('form', {})
    if form.get('tier'):
        update['plan_selected'] = form.get('tier')
    if form.get('platforms'):
        plat = form.get('platforms')
        update['platforms_selected'] = ','.join(plat) if isinstance(plat, list) else str(plat)
    # Also sync the top-level descriptive columns (business_name/city/type)
    # from the form payload whenever present. Previously these columns were
    # ONLY ever set once, at OTP-verify time in create_prospect() — fine for
    # the landing-page flow (business already picked via Google Places
    # before OTP, so the data exists immediately), but for the "Add another
    # business" flow OTP happens BEFORE business selection, so the initial
    # insert always had these blank and nothing ever went back to fill them
    # in once a business was actually chosen. Combined with convert_prospect()
    # wiping form_state to {} on conversion, this meant a converted row from
    # that flow ended up permanently blank with no recoverable business data.
    # Confirmed live: posst.app prospect row (id 22) on 2026-06-20.
    if form.get('business_name'): update['business_name'] = form.get('business_name')
    if form.get('business_city'): update['business_city'] = form.get('business_city')
    if form.get('business_type'): update['business_type'] = form.get('business_type')
    # Same gap as business_name above, but for email: contact_email was
    # captured into the in-memory form and used exactly once, live, to fire
    # the reengagement email — then discarded. It was never written to a
    # queryable column, meaning the prospects table couldn't be used as a
    # contact/outreach list at all despite being the obvious place for it.
    if form.get('contact_email'): update['email'] = form.get('contact_email')
    try:
        result = sb.table('prospects').update(update).eq('id', active_row['id']).execute()
        if not result.data:
            log.error(f'save_progress: update returned no data for phone={phone}, id={active_row["id"]}')
            return err('Failed to save progress (no data returned)', 500)
    except Exception as e:
        log.error(f'save_progress: update failed for phone={phone}, id={active_row["id"]}: {e}')
        return err(f'Failed to save progress: {e}', 500)
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
    fb_status  = d.get('fb_status', '')
    ig_status  = d.get('ig_status', '')
    gbp_status = d.get('gbp_status', 'N/A')
    row = {
        'client_id':    d.get('client_id'),
        'business_name':d.get('business_name', ''),
        'pillar':       d.get('pillar', ''),
        'fb_status':    fb_status,
        'ig_status':    ig_status,
        'gbp_status':   gbp_status,
        'image_url':    d.get('image_url', ''),
        'fb_post_id':   d.get('fb_post_id', ''),
        'ig_post_id':   d.get('ig_post_id', ''),
        'gbp_post_id':  d.get('gbp_post_id', ''),
        'fb_caption':   d.get('fb_caption', ''),
        'ig_caption':   d.get('ig_caption', ''),
        'gbp_caption':  d.get('gbp_caption', ''),
        'image_prompt': d.get('image_prompt', ''),
        'image_source': d.get('image_source', 'ai'),
        # Error fields — populated on FAILED status
        'fb_error':     fb_status  == 'FAILED',
        'fb_error_msg': d.get('fb_error_msg', '') if fb_status  == 'FAILED' else '',
        'ig_error':     ig_status  == 'FAILED',
        'ig_error_msg': d.get('ig_error_msg', '') if ig_status  == 'FAILED' else '',
        'gbp_error':    gbp_status == 'FAILED',
        'gbp_error_msg':d.get('gbp_error_msg', '') if gbp_status == 'FAILED' else '',
    }
    sb.table('posts_log').insert(row).execute()
    return ok()


# Returns the most recent posts_log row per active client — used by health check
@app.route('/api/posts_log/recent', methods=['GET'])
def get_recent_posts():
    # Get all active client IDs
    clients_res = sb.table('clients').select('client_id').eq('status', 'Active').execute()
    client_ids  = [c['client_id'] for c in (clients_res.data or [])]
    if not client_ids:
        return ok([], count=0)
    # Fetch last 5 rows per client (enough for health check)
    rows = []
    for cid in client_ids:
        res = sb.table('posts_log') \
                .select('client_id,business_name,fb_status,ig_status,gbp_status,fb_error,ig_error,gbp_error,fb_error_msg,ig_error_msg,posted_at') \
                .eq('client_id', cid) \
                .order('posted_at', desc=True) \
                .limit(5) \
                .execute()
        rows.extend(res.data or [])
    return ok(rows, count=len(rows))


# ── NOTIFY ERROR ───────────────────────────────────────────────
# Called by n8n immediately when a posting attempt fails.
# Sends platform-aware customer email. Deduplicates via email_campaign_log.
@app.route('/api/notify_error', methods=['POST'])
def notify_error():
    d = request.json or {}
    client_id = d.get('client_id', '')
    if not client_id:
        return err('client_id required')

    # Load full client row for email
    res = sb.table('clients').select('*').eq('client_id', client_id).single().execute()
    if not res.data:
        return err(f'Client not found: {client_id}')
    c = res.data

    # Only email Active clients — not new signups or paused
    if c.get('status') != 'Active':
        return ok(action='skipped', reason='client not active')

    # Build failed platforms list from payload
    failed_platforms = []
    if d.get('fb_failed'):  failed_platforms.append({'name': 'Facebook',        'icon': '📘'})
    if d.get('ig_failed'):  failed_platforms.append({'name': 'Instagram',       'icon': '📸'})
    if d.get('gbp_failed'): failed_platforms.append({'name': 'Google Business', 'icon': '🗺️'})

    if not failed_platforms:
        return ok(action='skipped', reason='no failed platforms')

    # Deduplicate — one email per client per day per error type
    from datetime import date
    camp_key = f"connection_error_{date.today().isoformat()}"
    already_sent = bool(
        sb.table('email_campaign_log').select('id')
          .eq('client_id', client_id).eq('campaign', camp_key).execute().data
    )
    if already_sent:
        return ok(action='skipped', reason='already sent today')

    if not EMAIL_AVAILABLE:
        return err('Email service unavailable')

    send_connection_error_email(c, failed_platforms)
    sb.table('email_campaign_log').insert({
        'client_id': client_id,
        'campaign':  camp_key,
        'email':     c.get('contact_email', '')
    }).execute()

    return ok(action='sent', platforms=[p['name'] for p in failed_platforms])

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



@app.route('/api/email/upgrade', methods=['POST'])
def email_upgrade():
    d = request.json or {}
    client_id = d.get('client_id', '')
    if not client_id:
        return err('client_id required')
    client = sb.table('clients').select('*').eq('client_id', client_id).single().execute()
    if not client.data:
        return err('Client not found')
    c = client.data
    has_drive = bool(c.get('google_drive_url'))
    notes = c.get('notes') or {}
    if isinstance(notes, str):
        try: notes = json.loads(notes)
        except: notes = {}
    has_themes = bool(notes.get('day_themes'))
    send_upgrade_email(c.get('contact_email', ''), c.get('business_name', 'there'), has_drive, has_themes)
    return ok()

@app.route('/api/email/go_live', methods=['POST'])
def email_go_live():
    d = request.json or {}
    cid = d.get('client_id')
    if not cid: return err('client_id required')
    r = sb.table('clients').select('*').eq('client_id', cid).single().execute()
    if not r.data: return err('Client not found', 404)
    if EMAIL_AVAILABLE:
        send_go_live_email(r.data)
        sb.table('clients').update({'go_live_email_sent': True}).eq('client_id', cid).execute()
    return ok()

@app.route('/api/email/cancel', methods=['POST'])
def email_cancel():
    d = request.json or {}
    cid = d.get('client_id')
    r = sb.table('clients').select('*').eq('client_id', cid).single().execute()
    if r.data and EMAIL_AVAILABLE: send_cancellation_email(r.data)
    return ok()

@app.route('/api/email/pause', methods=['POST'])
def email_pause():
    d = request.json or {}
    cid = d.get('client_id')
    r = sb.table('clients').select('*').eq('client_id', cid).single().execute()
    if r.data and EMAIL_AVAILABLE: send_pause_email(r.data)
    return ok()

@app.route('/api/prospects/eligible', methods=['GET'])
def prospects_eligible():
    """Return prospects eligible for re-engagement.
    Rules:
    - status != converted (stop if converted)
    - created > 2 hours ago
    - re_engagement_sent_at IS NULL (never sent) OR last sent > 7 days ago
    """
    try:
        now = datetime.now(timezone.utc)
        two_hours_ago  = (now - timedelta(hours=2)).isoformat()
        seven_days_ago = (now - timedelta(days=7)).isoformat()

        # Fetch all non-converted prospects created > 2 hours ago
        res = sb.table('prospects') \
            .select('id,phone,email,business_name,status,created_at,re_engagement_sent_at') \
            .neq('status', 'converted') \
            .lt('created_at', two_hours_ago) \
            .execute()

        eligible = []
        for row in (res.data or []):
            sent_at = row.get('re_engagement_sent_at')
            if not sent_at:
                # Never sent — eligible
                eligible.append(row)
            elif sent_at < seven_days_ago:
                # Last sent > 7 days ago — eligible again
                eligible.append(row)
            # else: sent within last 7 days — skip

        return jsonify(eligible)
    except Exception as e:
        log.error(f'prospects_eligible error: {e}')
        return err(str(e), 500)


@app.route('/api/prospects/mark_reengaged', methods=['POST'])
def mark_reengaged():
    """Set re_engagement_sent_at = now on a prospect row."""
    try:
        d = request.json or {}
        prospect_id = d.get('prospect_id')
        if not prospect_id:
            return err('prospect_id required')
        sb.table('prospects').update({
            're_engagement_sent': True,
            're_engagement_sent_at': datetime.now(timezone.utc).isoformat()
        }).eq('id', prospect_id).execute()
        return ok(action='marked')
    except Exception as e:
        log.error(f'mark_reengaged error: {e}')
        return err(str(e), 500)


@app.route('/api/email/reengagement', methods=['POST'])
def email_reengagement():
    d = request.json or {}
    if EMAIL_AVAILABLE:
        # Previously this always sent the bare https://onboarding.posst.app
        # URL with no phone or mode param at all — meaning the "Complete
        # my setup" link forced the user to retype their phone number with
        # zero context, and never triggered the login framing or resume
        # path. Now includes mode=login (clean login framing, no "Step 1
        # of 7" onboarding badge) + resume=1&phone=... (reuses the
        # existing, already-tested pre-fill path used by the portal's
        # "Resume signup" switcher entry).
        phone = d.get('phone', '')
        if phone:
            resume_url = f'https://onboarding.posst.app?mode=login&resume=1&phone={quote(phone)}'
        else:
            resume_url = 'https://onboarding.posst.app?mode=login'
        send_reengagement_email(d.get('email',''), d.get('business_name','there'), resume_url)
    return ok()

@app.route('/api/email/alert', methods=['POST'])
def email_alert():
    d = request.json or {}
    if EMAIL_AVAILABLE:
        send_internal_alert(d.get('title','Alert'), d.get('message',''), d.get('level','alert'))
    return ok()

@app.route('/api/email/campaigns', methods=['POST'])
def run_campaigns():
    from datetime import datetime
    today = datetime.utcnow().replace(hour=0,minute=0,second=0,microsecond=0)
    results = {'day1':0,'day2':0,'day7_std':0,'day7_pro':0,'day27':0,'day28':0,'day29':0,'monthly':0,'billing_alerts':0,'errors':[]}
    clients = sb.table('clients').select('*').eq('status','Active').execute()
    for c in (clients.data or []):
        cid = c.get('client_id','')
        try:
            # ── Safety net: catch any failures not caught by notify_error ──
            # Primary error emails are sent immediately by /api/notify_error
            # called from n8n at post time. This is a daily safety net only —
            # email_campaign_log deduplication ensures no double-send.
            from datetime import timezone, date
            recent = sb.table('posts_log') \
                       .select('fb_status,ig_status,gbp_status,posted_at') \
                       .eq('client_id', cid) \
                       .order('posted_at', desc=True) \
                       .limit(1) \
                       .execute()
            recent_rows = recent.data or []
            if recent_rows:
                last = recent_rows[0]
                failed_platforms = []
                if last.get('fb_status')  == 'FAILED': failed_platforms.append({'name': 'Facebook',        'icon': '📘'})
                if last.get('ig_status')  == 'FAILED': failed_platforms.append({'name': 'Instagram',       'icon': '📸'})
                if last.get('gbp_status') == 'FAILED': failed_platforms.append({'name': 'Google Business', 'icon': '🗺️'})
                if failed_platforms:
                    camp_key = f"connection_error_{date.today().isoformat()}"
                    already_sent = bool(sb.table('email_campaign_log').select('id')
                                         .eq('client_id', cid).eq('campaign', camp_key).execute().data)
                    if not already_sent and EMAIL_AVAILABLE:
                        send_connection_error_email(c, failed_platforms)
                        sb.table('email_campaign_log').insert({'client_id': cid, 'campaign': camp_key, 'email': c.get('contact_email','')}).execute()
                        results.setdefault('connection_errors', 0)
                        results['connection_errors'] += 1
            # ── End safety net ─────────────────────────────────────────────

            # Use trial_start if available, otherwise fall back to provisioned_at
            trial_start = c.get('trial_start') or c.get('provisioned_at')
            if not trial_start: continue
            # trial_start is DATE (YYYY-MM-DD), provisioned_at is ISO datetime
            if 'T' in str(trial_start) or 'Z' in str(trial_start):
                prov_date = datetime.fromisoformat(trial_start.replace('Z','+00:00')).replace(tzinfo=None).replace(hour=0,minute=0,second=0,microsecond=0)
            else:
                prov_date = datetime.strptime(str(trial_start)[:10], '%Y-%m-%d')
            days = (today - prov_date).days
            is_pro = (c.get('plan') or '').lower() == 'pro'
            def sent(camp): return bool(sb.table('email_campaign_log').select('id').eq('client_id',cid).eq('campaign',camp).execute().data)
            def log_sent(camp): sb.table('email_campaign_log').insert({'client_id':cid,'campaign':camp,'email':c.get('contact_email','')}).execute()
            if days==1 and not sent('day1'):
                if EMAIL_AVAILABLE: send_day1_email(c)
                log_sent('day1'); results['day1']+=1
            if days==7 and not is_pro and not sent('day7_standard'):
                if EMAIL_AVAILABLE: send_day7_standard_email(c)
                log_sent('day7_standard'); results['day7_std']+=1
            if days==7 and is_pro and not sent('day7_pro'):
                if EMAIL_AVAILABLE: send_day7_pro_email(c)
                log_sent('day7_pro'); results['day7_pro']+=1
            for td in [27,28,29]:
                camp = f'trial_day{td}'
                if days==td and not sent(camp):
                    if EMAIL_AVAILABLE: send_trial_ending_email(c, 30-td)
                    log_sent(camp); results[f'day{td}']+=1
            mday = int(c.get('monthly_report_day') or 1)
            mcamp = f"monthly_{datetime.utcnow().strftime('%Y_%m')}"
            if datetime.utcnow().day==mday and days>=30 and not sent(mcamp):
                if EMAIL_AVAILABLE: send_monthly_email(c)
                log_sent(mcamp); results['monthly']+=1
            # Safety check — trial ended but no subscription ID recorded
            if days >= 31 and not c.get('stripe_subscription_id') and not sent('billing_alert'):
                msg = f"Client {cid} ({c.get('business_name','?')}) — trial ended {days-30} day(s) ago but no stripe_subscription_id on record. Manual check required."
                if EMAIL_AVAILABLE: send_internal_alert('Billing Alert — Missing Subscription', msg, 'alert')
                log_sent('billing_alert'); results.setdefault('billing_alerts', 0); results['billing_alerts'] += 1
        except Exception as e:
            results['errors'].append(f'{cid}:{str(e)}')
    if EMAIL_AVAILABLE:
        send_internal_alert('Daily Campaigns Complete', str(results), 'info')
    return ok(results=results)


# ── POST STATUS (called by n8n after each posting run) ────────
# ── RECONNECT CONFIRMATION EMAIL ──────────────────────────────
@app.route('/api/email/reconnect_confirmation', methods=['POST'])
def send_reconnect_email():
    d          = request.json or {}
    client_id  = d.get('client_id')
    if not client_id:
        return err('Missing client_id', 400)
    client_row = sb.table('clients').select('*').eq('client_id', client_id).single().execute()
    if not client_row.data:
        return err('Client not found', 404)
    if EMAIL_AVAILABLE:
        send_reconnect_confirmation_email(
            client_row.data,
            d.get('posting_time', client_row.data.get('posting_time', '')),
            d.get('timezone',     client_row.data.get('timezone', 'Australia/Melbourne')),
            d.get('platforms',    ['Facebook', 'Instagram']),
        )
    return ok(sent=EMAIL_AVAILABLE)

# ── OTP SYSTEM ────────────────────────────────────────────────
import re as _re
import time as _time

TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN  = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_VERIFY_SID  = os.environ.get('TWILIO_VERIFY_SID', '')

MAX_OTP_PER_PHONE = 20
MAX_OTP_PER_IP    = 20
MAX_VERIFY_TRIES  = 10
LOCKOUT_MINS      = 60

ALLOWED_CODES = ['+61','+91','+1','+44','+971','+65','+64','+27','+49','+33',
                 '+39','+34','+31','+353','+46','+47','+45','+41','+48','+966',
                 '+974','+973','+968','+965','+20','+234','+254','+55','+52',
                 '+60','+63','+66','+84','+81','+82','+852','+92','+880','+94']

_otp_rate = {}
_otp_attempts = {}

def _check_rate(key, max_per_hour):
    now = _time.time()
    rec = _otp_rate.get(key, {})
    if now > rec.get('window_end', 0):
        _otp_rate[key] = {'count': 1, 'window_end': now + 3600}
        return True
    if rec['count'] >= max_per_hour:
        return False
    _otp_rate[key]['count'] += 1
    return True

def _is_locked(phone):
    rec = _otp_attempts.get(phone, {})
    if rec.get('locked_until', 0) > _time.time():
        return True, rec.get('locked_until', 0)
    return False, 0

def _inc_attempts(phone):
    rec = _otp_attempts.get(phone, {'count': 0, 'locked_until': 0})
    rec['count'] = rec.get('count', 0) + 1
    if rec['count'] >= MAX_VERIFY_TRIES:
        rec['locked_until'] = _time.time() + LOCKOUT_MINS * 60
        rec['count'] = 0
    _otp_attempts[phone] = rec
    return rec

def _clear_attempts(phone):
    _otp_attempts.pop(phone, None)

def _twilio_send(phone):
    import urllib.request, urllib.parse, base64 as _b64
    url = 'https://verify.twilio.com/v2/Services/' + TWILIO_VERIFY_SID + '/Verifications'
    data = urllib.parse.urlencode({'To': phone, 'Channel': 'sms'}).encode()
    creds = _b64.b64encode((TWILIO_ACCOUNT_SID + ':' + TWILIO_AUTH_TOKEN).encode()).decode()
    req = urllib.request.Request(url, data=data, headers={'Authorization': 'Basic ' + creds})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get('status') == 'pending'
    except Exception as e:
        log.error(f'Twilio send error: {e}')
        return False

def _twilio_verify(phone, code):
    import urllib.request, urllib.parse, base64 as _b64
    url = 'https://verify.twilio.com/v2/Services/' + TWILIO_VERIFY_SID + '/VerificationCheck'
    data = urllib.parse.urlencode({'To': phone, 'Code': code}).encode()
    creds = _b64.b64encode((TWILIO_ACCOUNT_SID + ':' + TWILIO_AUTH_TOKEN).encode()).decode()
    req = urllib.request.Request(url, data=data, headers={'Authorization': 'Basic ' + creds})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get('status') == 'approved'
    except Exception as e:
        log.error(f'Twilio verify error: {e}')
        return False

@app.route('/api/otp/send', methods=['POST'])
def otp_send():
    d = request.json or {}
    phone = (d.get('phone') or '').strip()
    client_ip = request.headers.get('X-Real-IP', request.remote_addr or 'unknown')
    if not phone or len(phone) < 8 or len(phone) > 16:
        return jsonify({'status': 'error', 'code': 'INVALID_PHONE', 'message': 'Invalid phone number'}), 400
    is_allowed = any(phone.startswith(c) for c in ALLOWED_CODES)
    if not is_allowed:
        return jsonify({'status': 'success', 'message': 'OTP sent'})
    locked, until = _is_locked(phone)
    if locked:
        mins = int((until - _time.time()) / 60) + 1
        return jsonify({'status': 'error', 'code': 'LOCKED', 'message': f'Too many attempts. Try again in {mins} minutes.'}), 429
    if not _check_rate('ip_' + str(client_ip), MAX_OTP_PER_IP):
        return jsonify({'status': 'error', 'code': 'RATE_LIMITED', 'message': 'Too many requests. Please try again later.'}), 429
    if not _check_rate('phone_' + phone, MAX_OTP_PER_PHONE):
        return jsonify({'status': 'error', 'code': 'RATE_LIMITED', 'message': 'Too many requests for this number. Try again in an hour.'}), 429
    # Twilio Verify requires strict E.164 (no spaces) — Supabase/app format includes a space (e.g. "+61 414208895")
    phone_e164 = phone.replace(' ', '')
    if not _twilio_send(phone_e164):
        return jsonify({'status': 'error', 'code': 'SEND_FAILED', 'message': 'Failed to send code. Please check your number and try again.'}), 500
    return jsonify({'status': 'success', 'message': 'Verification code sent'})

@app.route('/api/otp/verify', methods=['POST'])
def otp_verify():
    d = request.json or {}
    phone = (d.get('phone') or '').strip()
    code  = (d.get('otp') or d.get('code') or '').strip()
    if not phone or not code:
        return jsonify({'status': 'error', 'code': 'INVALID', 'message': 'Phone and code required'}), 400
    if not _re.match(r'^[0-9]{4,6}$', code):
        return jsonify({'status': 'error', 'code': 'INVALID_CODE', 'message': 'Invalid code format'}), 400
    locked, until = _is_locked(phone)
    if locked:
        mins = int((until - _time.time()) / 60) + 1
        return jsonify({'status': 'error', 'code': 'LOCKED', 'message': f'Too many wrong attempts. Try again in {mins} minutes.'}), 429
    if _twilio_verify(phone.replace(' ', ''), code):
        _clear_attempts(phone)
        return jsonify({'status': 'success', 'verified': True})
    rec = _inc_attempts(phone)
    if rec.get('locked_until', 0) > _time.time():
        return jsonify({'status': 'error', 'code': 'LOCKED', 'message': f'Too many wrong attempts. Locked for {LOCKOUT_MINS} minutes.'}), 429
    remaining = MAX_VERIFY_TRIES - rec.get('count', 0)
    return jsonify({'status': 'error', 'code': 'WRONG_CODE', 'message': f'Incorrect code. {remaining} attempt{"s" if remaining != 1 else ""} remaining.'}), 400


# ── SUPPORT CHAT (mobile widget) ─────────────────────────────
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
MAX_CHAT_PER_IP = 30

@app.route('/api/chat', methods=['POST'])
def chat():
    d = request.json or {}
    system = (d.get('system') or '')[:4000]
    messages = d.get('messages') or []
    if not isinstance(messages, list) or not messages:
        return jsonify({'status': 'error', 'message': 'messages required'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'status': 'error', 'message': 'Chat is not configured yet.'}), 503
    client_ip = request.headers.get('X-Real-IP', request.remote_addr or 'unknown')
    if not _check_rate('chat_ip_' + str(client_ip), MAX_CHAT_PER_IP):
        return jsonify({'status': 'error', 'message': 'Too many messages. Please try again later.'}), 429
    # Cap history to last 20 messages to control cost/payload size
    messages = messages[-20:]
    import urllib.request as _ur
    payload = json.dumps({
        'model': 'claude-sonnet-4-6',
        'max_tokens': 500,
        'system': system,
        'messages': messages,
    }).encode()
    req = _ur.Request('https://api.anthropic.com/v1/messages', data=payload, headers={
        'Content-Type': 'application/json',
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
    })
    try:
        with _ur.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        reply = next((b.get('text','') for b in result.get('content', []) if b.get('type') == 'text'), '')
        if not reply:
            reply = 'Sorry, I could not get a response. Please try again.'
        return jsonify({'status': 'success', 'reply': reply})
    except Exception as e:
        log.error(f'Chat error: {e}')
        return jsonify({'status': 'error', 'message': 'Connection error. Please try again.'}), 500


# ── SEARCH VOLUME (DataForSEO) ───────────────────────────────
DATAFORSEO_LOGIN    = os.environ.get('DATAFORSEO_LOGIN', '')
DATAFORSEO_PASSWORD = os.environ.get('DATAFORSEO_PASSWORD', '')

SEARCH_PROXY = {
    'dog grooming':  {'metro': 3200,  'regional': 800},
    'pet grooming':  {'metro': 3200,  'regional': 800},
    'hair salon':    {'metro': 12400, 'regional': 2800},
    'hairdresser':   {'metro': 12400, 'regional': 2800},
    'restaurant':    {'metro': 28000, 'regional': 5400},
    'cafe':          {'metro': 18000, 'regional': 3200},
    'coffee':        {'metro': 18000, 'regional': 3200},
    'plumber':       {'metro': 8900,  'regional': 1800},
    'electrician':   {'metro': 7200,  'regional': 1400},
    'dentist':       {'metro': 9800,  'regional': 2100},
    'gym':           {'metro': 14000, 'regional': 2800},
    'fitness':       {'metro': 14000, 'regional': 2800},
    'mechanic':      {'metro': 6800,  'regional': 1600},
    'physiotherapy': {'metro': 5400,  'regional': 1200},
    'real estate':   {'metro': 22000, 'regional': 4800},
    'default':       {'metro': 5000,  'regional': 1200},
}

AU_LOCATION_CODES = {
    'melbourne': 21167, 'sydney': 21173, 'brisbane': 21171,
    'perth': 21174, 'adelaide': 21170, 'canberra': 21168,
    'hobart': 21175, 'darwin': 21169, 'gold coast': 21171,
    'newcastle': 21173, 'geelong': 21167, 'townsville': 21171,
}

def get_proxy_volume(keyword, is_metro):
    k = keyword.lower()
    match = SEARCH_PROXY['default']
    for key in SEARCH_PROXY:
        if key != 'default' and key in k:
            match = SEARCH_PROXY[key]
    return match['metro'] if is_metro else match['regional']

def get_location_code(city):
    city_lower = (city or '').lower()
    for k, code in AU_LOCATION_CODES.items():
        if k in city_lower:
            return code
    return 2036  # Australia default

@app.route('/api/search_volume', methods=['POST'])
def search_volume():
    d = request.json or {}
    keyword  = d.get('keyword', '')
    city     = d.get('city', '')
    is_metro = d.get('is_metro', True)
    if not keyword:
        return err('keyword required')

    # Try DataForSEO if credentials available
    if DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD:
        try:
            import base64 as _b64, urllib.request, urllib.parse
            credentials = _b64.b64encode(f'{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}'.encode()).decode()
            location_code = get_location_code(city)
            payload_data = json.dumps([{'keywords': [keyword], 'location_code': location_code, 'language_code': 'en'}]).encode()
            req = urllib.request.Request(
                'https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live',
                data=payload_data,
                headers={'Authorization': f'Basic {credentials}', 'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                if result.get('status_code') == 20000:
                    tasks = result.get('tasks', [])
                    if tasks and tasks[0].get('result'):
                        vol = tasks[0]['result'][0].get('search_volume', 0) if tasks[0]['result'][0] else 0
                        return ok(volume=vol, source='dataforseo')
        except Exception as e:
            log.warning(f'DataForSEO error: {e}')

    # Fallback to proxy volumes
    volume = get_proxy_volume(keyword, is_metro)
    return ok(volume=volume, source='proxy')

# ── STRIPE ───────────────────────────────────────────────────
STRIPE_SECRET_KEY      = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET  = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')

# Two price IDs — Stripe handles currency automatically based on customer location
# Fallback to USD for countries outside the 9 configured currencies
STRIPE_PRICES = {
    'Standard': os.environ.get('STRIPE_PRICE_STD', ''),
    'Pro':      os.environ.get('STRIPE_PRICE_PRO', ''),
}

def stripe_request(method, path, payload=None, raw_body=None, extra_headers=None):
    import urllib.request, urllib.parse, base64 as _b64
    key = STRIPE_SECRET_KEY.strip()
    url = f'https://api.stripe.com/v1{path}'
    auth = _b64.b64encode(f'{key}:'.encode()).decode()
    headers = {'Authorization': f'Basic {auth}', 'Content-Type': 'application/x-www-form-urlencoded'}
    if extra_headers:
        headers.update(extra_headers)
    body = urllib.parse.urlencode(payload).encode() if payload else raw_body
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    log.info(f'Stripe {method} {path} | key_len={len(key)} key_prefix={key[:12]}')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()), None
    except urllib.error.HTTPError as e:
        err_body = json.loads(e.read())
        msg = err_body.get('error', {}).get('message', 'Stripe error')
        log.error(f'Stripe error {e.code} on {method} {path}: {msg}')
        return None, msg

@app.route('/api/stripe/checkout', methods=['POST'])
@require_auth
def stripe_checkout():
    d = request.json or {}
    client_id  = d.get('client_id', '')
    plan       = d.get('plan', 'Standard')
    currency   = d.get('currency', 'AU')
    email      = d.get('email', '')
    business   = d.get('business_name', '')
    return_url = d.get('return_url', '')  # Mobile deep-link return; absent = web default

    if not client_id:
        return err('client_id required')
    if not STRIPE_SECRET_KEY:
        return err('Stripe not configured')

    price_id = STRIPE_PRICES.get(plan, '')
    if not price_id:
        return err(f'No price configured for {plan} — check STRIPE_PRICE_STD/PRO env vars')

    # Create or retrieve Stripe customer
    client_res = sb.table('clients').select('stripe_customer_id,contact_email,business_name').eq('client_id', client_id).single().execute()
    client_data = client_res.data or {}
    stripe_customer_id = client_data.get('stripe_customer_id', '')

    if not stripe_customer_id:
        cust_payload = {'email': email or client_data.get('contact_email', ''), 'name': business or client_data.get('business_name', ''), 'metadata[client_id]': client_id}
        cust, cust_err = stripe_request('POST', '/customers', cust_payload)
        if cust_err:
            return err(f'Stripe customer error: {cust_err}')
        stripe_customer_id = cust['id']
        sb.table('clients').update({'stripe_customer_id': stripe_customer_id}).eq('client_id', client_id).execute()

    # Create checkout session with 30-day trial
    base_url = 'https://onboarding.posst.app'
    success_url = return_url if return_url else f'{base_url}/success.html?client_id={client_id}&session_id={{CHECKOUT_SESSION_ID}}'
    session_payload = {
        'customer':                          stripe_customer_id,
        'mode':                              'subscription',
        'line_items[0][price]':              price_id,
        'line_items[0][quantity]':           '1',
        'subscription_data[trial_period_days]': '30',
        'subscription_data[metadata][client_id]': client_id,
        'success_url':                       success_url,
        'cancel_url':                        f'{base_url}/index.html?step=payment&client_id={client_id}',
        'customer_update[address]':          'auto',
        'allow_promotion_codes':             'true',
        'automatic_tax[enabled]':            'true',
        'metadata[client_id]':               client_id,
    }
    # Do NOT set customer_email when customer ID is already set — Stripe rejects both together

    session, sess_err = stripe_request('POST', '/checkout/sessions', session_payload)
    if sess_err:
        return err(f'Stripe session error: {sess_err}')

    # Store stripe_subscription info placeholder
    sb.table('clients').update({'stripe_currency': currency}).eq('client_id', client_id).execute()

    log.info(f'Stripe checkout created: {client_id} → {plan}/{currency}')
    return ok(checkout_url=session['url'], session_id=session['id'])

@app.route('/api/stripe/portal', methods=['POST'])
@require_auth
def stripe_portal():
    d = request.json or {}
    client_id = d.get('client_id', '')
    client_res = sb.table('clients').select('stripe_customer_id').eq('client_id', client_id).single().execute()
    stripe_customer_id = (client_res.data or {}).get('stripe_customer_id', '')
    if not stripe_customer_id:
        return err('No Stripe customer found')
    return_url = d.get('return_url', 'https://onboarding.posst.app/portal.html')
    portal_payload = {
        'customer':   stripe_customer_id,
        'return_url': return_url,
    }
    portal, portal_err = stripe_request('POST', '/billing_portal/sessions', portal_payload)
    if portal_err:
        return err(f'Stripe portal error: {portal_err}')
    return ok(portal_url=portal['url'])

@app.route('/api/stripe/coupon', methods=['POST'])
@require_auth
def stripe_coupon():
    d = request.json or {}
    client_id  = d.get('client_id', '')
    coupon_code = d.get('coupon_code', '').strip()
    if not coupon_code:
        return err('Coupon code is required')
    client_res = sb.table('clients').select('stripe_customer_id,stripe_subscription_id').eq('client_id', client_id).single().execute()
    client_data = client_res.data or {}
    stripe_subscription_id = client_data.get('stripe_subscription_id', '')
    if not stripe_subscription_id:
        return err('No active subscription found')
    # Apply coupon to subscription via Stripe API
    payload = {'coupon': coupon_code}
    result, result_err = stripe_request('POST', f'/subscriptions/{stripe_subscription_id}', payload)
    if result_err:
        return err(result_err)
    # Extract discount details to return to client
    discount = result.get('discount') or {}
    coupon  = discount.get('coupon') or {}
    pct_off = coupon.get('percent_off')
    amt_off = coupon.get('amount_off')
    duration = coupon.get('duration', '')
    duration_months = coupon.get('duration_in_months')
    if pct_off:
        discount_desc = f'{int(pct_off)}% off'
    elif amt_off:
        discount_desc = f'{amt_off/100:.2f} off'
    else:
        discount_desc = 'Discount'
    if duration == 'forever':
        duration_desc = 'forever'
    elif duration == 'repeating' and duration_months:
        duration_desc = f'for {duration_months} month{"s" if duration_months > 1 else ""}'
    else:
        duration_desc = 'once'
    log.info(f'Coupon applied: {client_id} → {coupon_code} ({discount_desc} {duration_desc})')
    return ok(discount=f'{discount_desc} {duration_desc}')

@app.route('/api/stripe/webhook', methods=['POST'])
def stripe_webhook():
    import hmac, hashlib, time as _t
    payload    = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')
    if not STRIPE_WEBHOOK_SECRET:
        return jsonify({'status': 'ok'})

    # Verify signature
    try:
        parts = {k: v for k, v in (p.split('=', 1) for p in sig_header.split(','))}
        ts    = parts.get('t', '')
        v1    = parts.get('v1', '')
        signed = f'{ts}.'.encode() + payload
        expected = hmac.new(STRIPE_WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, v1):
            return jsonify({'error': 'Invalid signature'}), 400
        if abs(_t.time() - int(ts)) > 300:
            return jsonify({'error': 'Timestamp too old'}), 400
    except Exception as e:
        log.error(f'Webhook signature error: {e}')
        return jsonify({'error': 'Signature error'}), 400

    event = json.loads(payload)
    etype = event.get('type', '')
    obj   = event.get('data', {}).get('object', {})
    log.info(f'Stripe webhook: {etype}')

    def get_client_id():
        # Try subscription metadata first, then customer metadata
        meta = obj.get('metadata', {})
        cid = meta.get('client_id', '')
        if not cid:
            cid = (obj.get('subscription_data') or {}).get('metadata', {}).get('client_id', '')
        if not cid:
            # Look up by stripe_customer_id
            cust_id = obj.get('customer', '')
            if cust_id:
                res = sb.table('clients').select('client_id').eq('stripe_customer_id', cust_id).execute()
                if res.data:
                    cid = res.data[0]['client_id']
        return cid

    if etype == 'checkout.session.completed':
        cid = obj.get('metadata', {}).get('client_id', '')
        sub_id = obj.get('subscription', '')
        if cid and sub_id:
            sb.table('clients').update({'stripe_subscription_id': sub_id}).eq('client_id', cid).execute()
            log.info(f'Checkout complete: {cid} subscription {sub_id}')

    elif etype == 'customer.subscription.updated':
        cid = get_client_id()
        status = obj.get('status', '')
        if cid and status == 'active':
            # Trial ended, payment succeeded — ensure still Active
            sb.table('clients').update({'status': 'Active'}).eq('client_id', cid).execute()
            log.info(f'Subscription active (trial ended): {cid}')

    elif etype == 'invoice.payment_failed':
        cid = get_client_id()
        attempt = obj.get('attempt_count', 1)
        if cid:
            if attempt >= 3:
                sb.table('clients').update({'status': 'Paused'}).eq('client_id', cid).execute()
                if EMAIL_AVAILABLE:
                    client = sb.table('clients').select('*').eq('client_id', cid).single().execute().data
                    if client:
                        send_pause_email(client)
                log.info(f'Payment failed x3 — paused: {cid}')
            else:
                log.info(f'Payment failed attempt {attempt}: {cid}')
                if EMAIL_AVAILABLE:
                    send_internal_alert('Payment Failed', f'Client {cid} payment failed (attempt {attempt})', 'alert')

    elif etype == 'customer.subscription.deleted':
        cid = get_client_id()
        if cid:
            sb.table('clients').update({'status': 'Cancelled'}).eq('client_id', cid).execute()
            if EMAIL_AVAILABLE:
                client = sb.table('clients').select('*').eq('client_id', cid).single().execute().data
                if client:
                    send_cancellation_email(client)
            log.info(f'Subscription cancelled: {cid}')

    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5680, debug=False)
