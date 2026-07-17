#!/usr/bin/env python3
"""
posst.app — Main API v1.0
Replaces Google Apps Script as the backend for all posst.app operations.
Connects to Supabase for data storage.
"""

import os
import json
import logging
import threading
from datetime import datetime, timedelta
from urllib.parse import quote
from flask import Flask, request, jsonify
from supabase import create_client, Client
import sys
sys.path.insert(0, '/opt/posst')
try:
    from posst_email import (
        send_go_live_email, send_cancellation_email, send_pause_email, send_resume_email,
        send_day1_email, send_day7_standard_email, send_day7_pro_email,
        send_trial_ending_email, send_monthly_email, send_missing_platform_email,
        send_reengagement_email, send_internal_alert, send_upgrade_email,
        send_connection_error_email, send_reconnect_confirmation_email,
        send_teaser_start_email, send_teaser_end_email,
    )
    EMAIL_AVAILABLE = True
except Exception as e:
    EMAIL_AVAILABLE = False
from functools import wraps

app = Flask(__name__)
# D2-10 Security: reject request bodies larger than 1MB before any processing.
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB — covers logo upload base64 overhead
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────
SUPABASE_URL     = os.environ.get('SUPABASE_URL', 'https://itlndeorkphlorvcohaw.supabase.co')
SUPABASE_KEY     = os.environ.get('SUPABASE_SERVICE_KEY', '')
API_SECRET       = os.environ.get('POSST_API_SECRET', '')
if not API_SECRET:
    raise RuntimeError('[SECURITY] POSST_API_SECRET env var is not set. Refusing to start with no API key.')

# B-032: Separate admin/internal secret. Falls back to API_SECRET if not set,
# so existing deployments continue working. Set POSST_ADMIN_SECRET to a different
# strong value to enforce separation between frontend-proxy and admin/n8n callers.
ADMIN_SECRET = os.environ.get('POSST_ADMIN_SECRET', '') or API_SECRET

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── AUDIT LOGGING (A2 Security, Jul 11 2026) ─────────────────
# Non-blocking: fires in background thread, never slows requests or crashes on failure.
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
        'detail': detail or {}, 'server': 'posst-api',
    }
    def _insert():
        try:
            sb.table('audit_log').insert(row).execute()
        except Exception as e:
            print(f'[AUDIT-WARN] Failed to write audit_log: {e}', flush=True)
    threading.Thread(target=_insert, daemon=True).start()

# ── IMAGE STYLE ROUTING (Phase B, Jul 1 2026) ─────────────────
# See ai/style_library.md, ai/style_routing_map.md, ai/subject_nature_map.md.
# Lesson 178: kept as Python dict (Beta mode) because it mirrors BIZ_CATEGORIES
# in onboarding/index.html and is protected by _sanity_check_style_mapping() below.
# Update this dict whenever a new business_type is added to onboarding.

BUSINESS_TYPE_TO_CATEGORY = {
    # Food & Hospitality
    'Bakery': 'Food & Hospitality', 'Brewery / Craft Beer': 'Food & Hospitality',
    'Butcher': 'Food & Hospitality', 'Cafe / Coffee Shop': 'Food & Hospitality',
    'Catering': 'Food & Hospitality', 'Catering Equipment Hire': 'Food & Hospitality',
    'Deli': 'Food & Hospitality', 'Dessert Shop': 'Food & Hospitality',
    'Fish & Chips': 'Food & Hospitality', 'Food Truck': 'Food & Hospitality',
    'Ice Cream Shop': 'Food & Hospitality', 'Juice Bar': 'Food & Hospitality',
    'Meal Prep / Delivery': 'Food & Hospitality', 'Pizza Shop': 'Food & Hospitality',
    'Restaurant': 'Food & Hospitality', 'Takeaway / Fast Food': 'Food & Hospitality',
    'Wine Bar': 'Food & Hospitality',
    # Beauty & Health
    'Barber Shop': 'Beauty & Health', 'Beauty Salon': 'Beauty & Health',
    'Brow & Lash Studio': 'Beauty & Health', 'Chiropractor': 'Beauty & Health',
    'Cosmetic Tattoo': 'Beauty & Health', 'Dental Clinic': 'Beauty & Health',
    'Dietitian / Nutritionist': 'Beauty & Health', 'Hair Salon / Hairdresser': 'Beauty & Health',
    'Hearing Clinic': 'Beauty & Health', 'Health Spa': 'Beauty & Health',
    'Massage Therapist': 'Beauty & Health', 'Medical Practice': 'Beauty & Health',
    'Nail Salon': 'Beauty & Health', 'Natural Therapies': 'Beauty & Health',
    'Occupational Therapist': 'Beauty & Health', 'Optical': 'Beauty & Health',
    'Osteopath': 'Beauty & Health', 'Pharmacy': 'Beauty & Health',
    'Podiatrist': 'Beauty & Health', 'Psychologist / Counsellor': 'Beauty & Health',
    'Skin Clinic': 'Beauty & Health', 'Speech Therapist': 'Beauty & Health',
    # Fitness & Leisure
    'Boxing / MMA Gym': 'Fitness & Leisure', 'CrossFit / Functional Fitness': 'Fitness & Leisure',
    'Cycling Studio': 'Fitness & Leisure', 'Dance Studio': 'Fitness & Leisure',
    'Golf Coaching': 'Fitness & Leisure', 'Gym / Fitness Studio': 'Fitness & Leisure',
    'Martial Arts': 'Fitness & Leisure',
    'Personal Trainer': 'Fitness & Leisure',
    'Pilates Studio': 'Fitness & Leisure', 'Rock Climbing': 'Fitness & Leisure',
    'Sports Complex': 'Fitness & Leisure', 'Swimming School': 'Fitness & Leisure',
    'Tennis Coaching': 'Fitness & Leisure', 'Yoga Studio': 'Fitness & Leisure',
    # Pet Services
    'Aquarium & Fish': 'Pet Services', 'Aviary & Bird Services': 'Pet Services', 'Boarding Kennels': 'Pet Services',
    'Dog Grooming': 'Pet Services', 'Dog Training': 'Pet Services',
    'Exotic Pets': 'Pet Services', 'Fresh Pet Food': 'Pet Services',
    'Pet Grooming (Cats)': 'Pet Services', 'Pet Photography': 'Pet Services',
    'Pet Shop': 'Pet Services', 'Pet Sitting / Dog Walking': 'Pet Services',
    'Veterinary Clinic': 'Pet Services',
    # Retail
    'Appliances': 'Retail', 'Baby & Kids': 'Retail', 'Bookshop': 'Retail',
    'Clothing & Fashion': 'Retail', 'Craft & Hobby': 'Retail', 'Electronics': 'Retail',
    'Florist': 'Retail', 'Furniture': 'Retail', 'Gift Shop': 'Retail',
    'Health Food Store': 'Retail', 'Homewares': 'Retail', 'Jewellery': 'Retail',
    'Newsagency': 'Retail', 'Phone & Tech Accessories': 'Retail',
    'Sporting Goods': 'Retail',
    'Supplement Store': 'Retail', 'Toy Shop': 'Retail',
    'Vape & Smoke Shop': 'Retail', 'Vintage & Secondhand': 'Retail',
    # Automotive
    'Auto Parts': 'Automotive', 'Car Dealership': 'Automotive',
    'Car Detailing': 'Automotive', 'Car Wash': 'Automotive',
    'Caravan & RV': 'Automotive', 'Mechanic / Auto Repair': 'Automotive',
    'Motorcycle Dealer / Repair': 'Automotive', 'Panel Beating': 'Automotive',
    'Roadside Assistance': 'Automotive', 'Second Hand Car Sales': 'Automotive',
    'Tyres & Accessories': 'Automotive', 'Vehicle Wrapping': 'Automotive',
    # Home & Garden
    'Air Conditioning / HVAC': 'Home & Garden', 'Building & Construction': 'Home & Garden',
    'Carpet & Flooring': 'Home & Garden', 'Cleaning Services': 'Home & Garden',
    'Electrical': 'Home & Garden', 'Fencing': 'Home & Garden',
    'Interior Design': 'Home & Garden', 'Landscaping / Gardening': 'Home & Garden',
    'Painting & Decorating': 'Home & Garden', 'Pest Control': 'Home & Garden',
    'Plumbing': 'Home & Garden', 'Pool Services': 'Home & Garden',
    'Removalist': 'Home & Garden', 'Roofing': 'Home & Garden',
    'Security Systems': 'Home & Garden', 'Skip Bin Hire': 'Home & Garden',
    'Solar & Energy': 'Home & Garden', 'Tiling': 'Home & Garden',
    # Professional Services
    'Accounting / Bookkeeping': 'Professional Services', 'Architecture': 'Professional Services',
    'Consulting': 'Professional Services',
    'Copywriting': 'Professional Services', 'Engineering': 'Professional Services',
    'Event Planning': 'Professional Services', 'Financial Planning': 'Professional Services',
    'Graphic Design': 'Professional Services', 'Insurance': 'Professional Services',
    'IT / Technology': 'Professional Services', 'Legal': 'Professional Services',
    'Marketing Agency': 'Professional Services', 'Photography': 'Professional Services',
    'PR & Communications': 'Professional Services', 'Real Estate': 'Professional Services',
    'Recruitment': 'Professional Services', 'Social Media Marketing': 'Professional Services',
    'Surveying': 'Professional Services', 'Translation': 'Professional Services',
    'Video Production': 'Professional Services', 'Web Design & Development': 'Professional Services',
    # Education & Childcare
    'After School Care': 'Education & Childcare', 'Art Classes': 'Education & Childcare',
    'Child Care / Daycare': 'Education & Childcare', 'Coding School': 'Education & Childcare',
    'Driving School': 'Education & Childcare', 'Early Childhood / Kindergarten': 'Education & Childcare',
    'Language School': 'Education & Childcare', 'Music School': 'Education & Childcare',
    'Sports Coaching (Kids)': 'Education & Childcare', 'Tutoring': 'Education & Childcare',
    'Vocational Training': 'Education & Childcare',
    # Accommodation & Tourism
    'Amusement / Entertainment Centre': 'Accommodation & Tourism',
    'B&B / Guest House': 'Accommodation & Tourism', 'Escape Room': 'Accommodation & Tourism',
    'Event / Function Centre': 'Accommodation & Tourism',
    'Glamping / Eco Stays': 'Accommodation & Tourism',
    'Holiday Park / Caravan Park': 'Accommodation & Tourism',
    'Hotel / Motel': 'Accommodation & Tourism',
    'Serviced Apartments': 'Accommodation & Tourism',
    'Tour Operator': 'Accommodation & Tourism', 'Travel Agency': 'Accommodation & Tourism',
    # Online & eCommerce
    'Digital Products': 'Online & eCommerce', 'Dropshipping': 'Online & eCommerce',
    'Marketplace Seller': 'Online & eCommerce', 'Online Courses / Education': 'Online & eCommerce',
    'Online Store': 'Online & eCommerce', 'Print on Demand': 'Online & eCommerce',
    'SaaS / Software': 'Online & eCommerce', 'Subscription Box': 'Online & eCommerce',
    # Health & Wellness
    'Aged Care': 'Health & Wellness', 'Community Services': 'Health & Wellness',
    'Disability Services': 'Health & Wellness', 'Fertility Clinic': 'Health & Wellness',
    'Life Coaching': 'Health & Wellness', 'Meditation & Mindfulness': 'Health & Wellness',
    'Sleep Clinic': 'Health & Wellness',
    # Spiritual & Alternative Wellness
    'Acupuncture': 'Spiritual & Alternative Wellness',
    'Aromatherapy': 'Spiritual & Alternative Wellness',
    'Astrologer': 'Spiritual & Alternative Wellness',
    'Crystal Healing': 'Spiritual & Alternative Wellness',
    'Herbalist': 'Spiritual & Alternative Wellness',
    'Hypnotherapy': 'Spiritual & Alternative Wellness',
    'Kinesiology': 'Spiritual & Alternative Wellness',
    'Naturopath': 'Spiritual & Alternative Wellness',
    'Numerologist': 'Spiritual & Alternative Wellness',
    'Psychic / Clairvoyant': 'Spiritual & Alternative Wellness',
    'Reiki / Energy Healing': 'Spiritual & Alternative Wellness',
    'Sound Healing': 'Spiritual & Alternative Wellness',
    'Spiritual Coaching': 'Spiritual & Alternative Wellness',
    'Tarot Reader': 'Spiritual & Alternative Wellness',
    # Events & Entertainment
    'Comedy Club': 'Events & Entertainment', 'Cinema': 'Events & Entertainment',
    'DJ / Entertainment': 'Events & Entertainment',
    'Festival / Market Organiser': 'Events & Entertainment',
    'Live Music Venue': 'Events & Entertainment',
    'Photography Studio': 'Events & Entertainment', 'Theatre': 'Events & Entertainment',
    'Wedding Venue': 'Events & Entertainment',
    # Food & Drink Production
    'Artisan Food Producer': 'Food & Drink Production',
    'Distillery': 'Food & Drink Production',
    'Farmers Market Vendor': 'Food & Drink Production',
    'Specialty Coffee Roaster': 'Food & Drink Production',
    'Winery': 'Food & Drink Production',
    # Kids & Family
    'Childrens Clothing': 'Kids & Family', 'Jumping Castle Hire': 'Kids & Family',
    'Kids Gym / Play Centre': 'Kids & Family', 'Party Entertainment': 'Kids & Family',
    'Toy Library': 'Kids & Family',
    # Trade & Industrial
    'Crane & Heavy Equipment': 'Trade & Industrial',
    'Industrial Cleaning': 'Trade & Industrial',
    'Scaffolding': 'Trade & Industrial',
    'Waste Management': 'Trade & Industrial',
    'Welding & Fabrication': 'Trade & Industrial',
}

SAFE_FALLBACK_POOL = ['documentary_candid', 'wide_environment', 'macro_detail']
ABSOLUTE_FALLBACK_TEMPLATE = 'Photorealistic mid-action shot. Natural indoor daylight. No human faces.'


def _sanity_check_style_mapping():
    """
    Boot-time check: verify every business_type in BIZ_CATEGORIES (onboarding/index.html)
    is mapped in BUSINESS_TYPE_TO_CATEGORY. Fails loud on mismatch, warns on GitHub outage.
    Lessons 178, 179.
    """
    import re, base64, requests
    gh_token = os.environ.get('GH_ONBOARDING_TOKEN', '')
    headers = {'Authorization': f'token {gh_token}'} if gh_token else {}
    try:
        r = requests.get(
            'https://api.github.com/repos/posstapp/onboarding/contents/index.html',
            headers=headers, timeout=10
        )
        r.raise_for_status()
        content = base64.b64decode(r.json()['content']).decode()
        start = content.find('BIZ_CATEGORIES')
        end = content.find('];', start)
        if start < 0 or end < 0:
            log.warning('[SANITY CHECK SKIPPED] BIZ_CATEGORIES block not found in index.html')
            return
        block = content[start:end]
        # Types appear as single-quoted strings inside `types: [...]` arrays.
        # Exclude keys ('group','types') and group names by filtering against known categories.
        strings = re.findall(r"'([^']+)'", block)
        known_categories = set(BUSINESS_TYPE_TO_CATEGORY.values())
        live_types = [s for s in strings if s not in ('group', 'types') and s not in known_categories]
        missing = sorted(set(t for t in live_types if t not in BUSINESS_TYPE_TO_CATEGORY))
        if missing:
            raise RuntimeError(
                f'[SANITY CHECK FAILED] BIZ_CATEGORIES has {len(missing)} unmapped types: '
                f'{missing[:10]}{"..." if len(missing) > 10 else ""}. '
                f'Add them to BUSINESS_TYPE_TO_CATEGORY in posst_api.py.'
            )
        log.info(f'[SANITY CHECK OK] All {len(set(live_types))} BIZ_CATEGORIES types mapped.')
    except RuntimeError:
        raise
    except Exception as e:
        log.warning(f'[SANITY CHECK SKIPPED] Could not verify BIZ_CATEGORIES: {e}')


_sanity_check_style_mapping()


# ── AUTH MIDDLEWARE ───────────────────────────────────────────
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # D1-3 Security: only accept API key from header, never from request body.
        # Body fallback allowed trivial auth bypass via JSON payload.
        auth = request.headers.get('X-API-Key', '')
        if auth != API_SECRET:
            _audit_log('auth_failed', detail={'reason': 'invalid_api_key'}, status_code=401)
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    from functools import wraps as _wraps
    @_wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('X-API-Key', '')
        if auth != ADMIN_SECRET:
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

# ── INPUT SANITIZATION (Form Security Hardening, Jul 5 2026) ─
import html as _html

# Field-level max lengths — server-side enforcement
_FIELD_LIMITS = {
    'business_name': 200, 'business_city': 200, 'business_suburb': 200,
    'business_country': 200, 'business_desc': 3000, 'business_description': 3000,
    'contact_email': 254, 'business_type': 200, 'fb_page_name': 200,
    'facebook_page_url': 500, 'ig_handle': 200, 'ig_url': 500,
    'gbp_name': 200, 'brand_keywords': 500, 'business_phone': 30,
    'phone': 30, 'email': 254, 'google_drive_url': 500,
    'caption_email': 254, 'caption_phone': 30,
}

def _sanitize(value, maxlen=1000):
    """Escape HTML entities and truncate. Safe for all string fields."""
    if not isinstance(value, str):
        return value
    return _html.escape(value.strip(), quote=True)[:maxlen]

def _sanitize_dict(d, fields=None):
    """Sanitize all string values in a dict, respecting per-field max lengths."""
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        if isinstance(v, str):
            maxlen = _FIELD_LIMITS.get(k, 1000)
            if fields is None or k in fields:
                out[k] = _sanitize(v, maxlen)
            else:
                out[k] = v
        else:
            out[k] = v
    return out


# ── B-031: REQUEST SCHEMA VALIDATION ─────────────────────────
# Lightweight validator — no pydantic/marshmallow dependency needed.
def _validate(d, schema):
    """Validate a request dict against a schema.
    Schema: { 'field': {'required': bool, 'type': str|int|list|dict|bool, 'maxlen': int} }
    Returns (cleaned_dict, error_message). error_message is None if valid.
    """
    if not isinstance(d, dict):
        return None, 'Request body must be JSON object'
    errors = []
    for field, rules in schema.items():
        val = d.get(field)
        if rules.get('required') and (val is None or val == ''):
            errors.append(f'{field} is required')
            continue
        if val is not None and val != '':
            expected_type = rules.get('type')
            if expected_type and not isinstance(val, expected_type):
                errors.append(f'{field} must be {expected_type.__name__}')
                continue
            maxlen = rules.get('maxlen')
            if maxlen and isinstance(val, str) and len(val) > maxlen:
                errors.append(f'{field} exceeds max length ({maxlen})')
    if errors:
        return None, '; '.join(errors)
    return d, None

_SCHEMA_CLIENT = {
    'phone': {'required': True, 'type': str, 'maxlen': 30},
    'business_name': {'required': True, 'type': str, 'maxlen': 200},
    'business_type': {'required': True, 'type': str, 'maxlen': 200},
    'contact_email': {'required': True, 'type': str, 'maxlen': 254},
}
_SCHEMA_PROSPECT = {'phone': {'required': True, 'type': str, 'maxlen': 30}}
_SCHEMA_PORTAL_LOOKUP = {'session_token': {'required': True, 'type': str, 'maxlen': 64}}
_SCHEMA_CHAT = {'messages': {'required': True, 'type': list}}
_SCHEMA_OTP = {'phone': {'required': True, 'type': str, 'maxlen': 30}}
_SCHEMA_POSTS_LOG = {'client_id': {'required': True, 'type': str, 'maxlen': 30}}
_SCHEMA_STYLE_SELECT = {
    'client_id': {'required': True, 'type': str, 'maxlen': 30},
    'business_type': {'required': True, 'type': str, 'maxlen': 200},
}
_SCHEMA_STRIPE_CHECKOUT = {
    'client_id': {'required': True, 'type': str, 'maxlen': 30},
    'plan': {'required': False, 'type': str, 'maxlen': 20},
    'email': {'required': False, 'type': str, 'maxlen': 254},
}

# ── CORS ALLOWLIST (Form Security Hardening, Jul 5 2026) ─────
_CORS_ALLOWED_ORIGINS = [
    'https://posst.app',
    'https://www.posst.app',
    'https://onboarding.posst.app',
    'https://connect.posst.app',
]

def _cors_origin():
    """Return the Origin header if it's in the allowlist, else empty string."""
    origin = request.headers.get('Origin', '')
    # Allow localhost in dev
    if origin.startswith('http://localhost:') or origin.startswith('http://127.0.0.1:'):
        return origin
    return origin if origin in _CORS_ALLOWED_ORIGINS else ''

# ── HEALTH ────────────────────────────────────────────────────
@app.route('/health')
def health():
    return ok(version='1.3', service='posst-api')

# ── CLIENT CRUD ───────────────────────────────────────────────
@app.route('/api/client', methods=['POST'])
@require_auth
def create_client_record():
    """Create new client — called from onboarding form submit."""
    d = request.json or {}
    # B-031: Schema validation
    d, val_err = _validate(d, _SCHEMA_CLIENT)
    if val_err:
        return err(val_err)
    # Rate limit: 10 client creations per IP per hour
    client_ip = request.headers.get('X-Real-IP', request.remote_addr or 'unknown')
    if not _check_rate('create_client_ip_' + str(client_ip), 10):
        return err('Too many requests. Please try again later.', 429)
    # Sanitize all string inputs before storage
    d = _sanitize_dict(d)
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
        'caption_email':       d.get('caption_email', '') or d.get('caption_cta_email', ''),
        'caption_phone':       d.get('caption_phone', '') or d.get('caption_cta_phone', ''),
    }

    result = sb.table('clients').insert(row).execute()
    if not result.data:
        return err('Failed to create client')

    log.info(f'Client created: {client_id} — {d.get("business_name")}')
    _audit_log('client_created', actor=client_id, detail={'plan': d.get('tier', 'Standard'), 'business': d.get('business_name', '')})

    # Convert the prospect server-side so it never depends on a
    # fire-and-forget frontend call. Without this, a network blip or
    # closed tab leaves the prospect unconverted with stale form_state,
    # which loadProgress then restores on the next visit — even if the
    # client row was deleted in the meantime.
    phone = d.get('business_phone', '')
    if phone:
        try:
            sb.table('prospects').update({
                'status': 'converted',
                'converted_at': datetime.now().isoformat(),
                'form_state': {}
            }).eq('phone', phone).neq('status', 'converted').execute()
            log.info(f'Prospect converted server-side for phone={phone}')
        except Exception as e:
            log.warning(f'Prospect conversion failed for phone={phone}: {e}')

    return ok(client_id=client_id, pending_token=pending_token)

# D1-5 Security: strip sensitive fields from client data for non-internal callers.
# Internal callers (n8n, OAuth server) pass X-API-Key header + ?full=1 to get all fields.
_SENSITIVE_FIELDS = {
    'meta_token', 'meta_user_token', 'meta_token_expiry',
    'stripe_customer_id', 'stripe_subscription_id', 'stripe_currency',
    'gbp_refresh_token', 'pending_token',
}

def _safe_client(row):
    """Return client data with sensitive fields stripped."""
    if not row:
        return row
    return {k: v for k, v in row.items() if k not in _SENSITIVE_FIELDS}

def _is_internal():
    """Check if caller authenticated via X-API-Key and requesting full data."""
    return request.headers.get('X-API-Key', '') == API_SECRET and request.args.get('full') == '1'

@app.route('/api/client/<client_id>', methods=['GET'])
@require_admin
def get_client(client_id):
    result = sb.table('clients').select('*').eq('client_id', client_id).single().execute()
    if not result.data:
        return err('Client not found', 404)
    if _is_internal():
        return ok(result.data)
    return ok(_safe_client(result.data))

@app.route('/api/client/<client_id>/status', methods=['PATCH'])
@require_admin
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
@require_auth
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
@require_auth
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
@require_auth
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
@require_admin
def update_token(client_id):
    d = request.json or {}
    update = {}
    if d.get('meta_token'):        update['meta_token'] = d['meta_token']
    if d.get('meta_token_expiry'): update['meta_token_expiry'] = d['meta_token_expiry']
    if d.get('fb_page_id'):        update['fb_page_id'] = d['fb_page_id']
    if d.get('fb_page_name'):      update['fb_page_name'] = d['fb_page_name']
    if d.get('ig_business_id'):    update['ig_business_id'] = d['ig_business_id']
    if d.get('ig_handle'):         update['ig_handle'] = d['ig_handle']
    if d.get('meta_user_token'):   update['meta_user_token'] = d['meta_user_token']
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
@require_auth
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
@require_auth
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
    if EMAIL_AVAILABLE:
        client_data = sb.table('clients').select('*').eq('client_id', client_id).single().execute().data
        if client_data:
            send_cancellation_email(client_data)
    return ok()

@app.route('/api/client/<client_id>/pause', methods=['POST'])
@require_auth
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
    if EMAIL_AVAILABLE:
        client_data = sb.table('clients').select('*').eq('client_id', client_id).single().execute().data
        if client_data:
            send_pause_email(client_data)
    return ok()

@app.route('/api/client/<client_id>/resume', methods=['POST'])
@require_auth
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
    if EMAIL_AVAILABLE:
        client_data = sb.table('clients').select('*').eq('client_id', client_id).single().execute().data
        if client_data:
            send_resume_email(client_data)
    return ok()

# ── PORTAL LOOKUP ─────────────────────────────────────────────
@app.route('/api/portal_lookup', methods=['POST'])
@require_auth
def portal_lookup():
    d = request.json or {}
    # v43: Session token auth (clean cut — no phone-based access)
    d, val_err = _validate(d, _SCHEMA_PORTAL_LOOKUP)
    if val_err:
        return err(val_err)
    session_token = (d.get('session_token') or '').strip()
    if not session_token:
        return err('Session token required')

    # Look up token in portal_sessions
    try:
        token_row = sb.table('portal_sessions').select('phone, client_id, expires_at') \
            .eq('token', session_token).maybe_single().execute()
    except Exception as e:
        log.error(f'portal_lookup session query failed: {e}')
        return err('Session error', 500)

    if not token_row or not token_row.data:
        return jsonify({'status': 'error', 'code': 'SESSION_INVALID', 'message': 'Session expired or invalid. Please log in again.'}), 401

    # Check expiry
    from datetime import datetime, timezone
    expires_at = token_row.data.get('expires_at', '')
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > exp_dt:
                # Clean up expired token
                sb.table('portal_sessions').delete().eq('token', session_token).execute()
                return jsonify({'status': 'error', 'code': 'SESSION_EXPIRED', 'message': 'Session expired. Please log in again.'}), 401
        except Exception:
            pass

    phone_raw = token_row.data.get('phone', '')
    if not phone_raw:
        return err('Session has no phone')

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
    def get_latest_post_status(client_id, client_updated_at=None, meta_token=None):
        """Query posts_log for the most recent row — derive error flags from it.

        If a FAILED row exists but the client has a valid meta_token AND updated_at
        is after the failure, the error is stale — clear it so the portal stops
        showing Reconnect after a successful OAuth flow.

        IMPORTANT: Only clear the stale error if meta_token is non-empty.
        If meta_token is empty (manually cleared or genuinely missing), always
        show the error so the Reconnect button appears correctly.
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

                # Only suppress stale errors when:
                # 1. meta_token is present (token actually exists — not manually cleared)
                # 2. updated_at is after the failed post (genuine reconnect happened)
                # If meta_token is empty, always show the error (Reconnect button needed)
                has_valid_token = bool(meta_token and str(meta_token).strip())
                if (fb_failed or ig_failed or gbp_failed) and has_valid_token and client_updated_at and row.get('posted_at'):
                    try:
                        import dateutil.parser
                        def _parse(ts):
                            return dateutil.parser.parse(ts)
                        t_updated = _parse(str(client_updated_at))
                        t_posted  = _parse(str(row['posted_at']))
                        if t_updated > t_posted:
                            log.info(f'get_latest_post_status: clearing stale error for {client_id} '
                                     f'(token refreshed {t_updated} after failure {t_posted})')
                            fb_failed  = False
                            ig_failed  = False
                            gbp_failed = False
                    except Exception as te:
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
        post_status = get_latest_post_status(client['client_id'], client.get('updated_at'), client.get('meta_token'))
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
            'contact_email':    client.get('caption_email', ''),
            'caption_email':    client.get('caption_email', ''),
            'caption_phone':    client.get('caption_phone', ''),
            'logo_url':         client.get('logo_url', ''),
            'business_type':    client.get('business_type', ''),
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
    # D1-5 / Scalability: filter prospects by phone in the DB query instead of
    # loading the entire prospects table into memory. At 100+ prospects the full
    # table scan was already slow and leaked all prospect data into server RAM.
    draft_prospect = None
    prospect_res = sb.table('prospects').select('id,phone,business_name,last_step_reached,status') \
        .eq('phone', phone).neq('status', 'converted').execute()
    for prow in (prospect_res.data or []):
        if prow.get('business_name'):
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
@require_auth
def get_pending_token(client_id):
    result = sb.table('clients').select('pending_token').eq('client_id', client_id).single().execute()
    if not result.data:
        return err('Client not found', 404)
    return ok(token=result.data.get('pending_token', ''))

@app.route('/api/client/<client_id>/pending_token', methods=['POST'])
@require_auth
def generate_pending_token(client_id):
    token = generate_token()
    sb.table('clients').update({'pending_token': token}).eq('client_id', client_id).execute()
    return ok(token=token)

# ── ACTIVE CLIENTS FOR POSTING ────────────────────────────────
@app.route('/api/clients/active', methods=['GET'])
@require_admin
def get_active_clients():
    result = sb.table('clients').select('*').eq('status', 'Active').execute()
    return ok(result.data, count=len(result.data))

@app.route('/api/clients/token_received', methods=['GET'])
@require_admin
def get_token_received_clients():
    result = sb.table('clients').select('*').eq('status', 'Token_Received').execute()
    return ok(result.data, count=len(result.data))

# ── PROSPECTS ─────────────────────────────────────────────────
@app.route('/api/prospect', methods=['POST'])
@require_auth
def create_prospect():
    d = request.json or {}
    # B-031: Schema validation
    d, val_err = _validate(d, _SCHEMA_PROSPECT)
    if val_err:
        return err(val_err)
    phone = _sanitize(d.get('phone', ''), 30)
    if not phone:
        return err('Phone required')
    # Rate limit: 10 prospect creations per IP per hour
    client_ip = request.headers.get('X-Real-IP', request.remote_addr or 'unknown')
    if not _check_rate('create_prospect_ip_' + str(client_ip), 10):
        return err('Too many requests. Please try again later.', 429)
    # Sanitize all string inputs
    d = _sanitize_dict(d)
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
@require_auth
def save_progress():
    d = request.json or {}
    phone = _sanitize(d.get('phone', ''), 30)
    if not phone:
        return err('Phone required')
    # Sanitize the nested form object if present
    form = d.get('form', {})
    if isinstance(form, dict):
        form = _sanitize_dict(form)
        d['form'] = form
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
@require_auth
def load_progress():
    phone = request.args.get('phone', '').strip()
    if not phone:
        return err('Phone required')
    result = sb.table('prospects').select('*').eq('phone', phone).execute()
    if not result.data:
        return jsonify({'success': False, 'error': 'no saved progress'})
    # Use the same active_row pattern as create_prospect and save_progress.
    # Taking result.data[0] blindly could pick a converted row or the wrong
    # row entirely when multiple prospect rows exist for the same phone.
    row = next((r for r in result.data if r.get('status') != 'converted'), None)
    if not row:
        return jsonify({'success': False, 'error': 'already converted'})
    form_state = row.get('form_state', {})
    if isinstance(form_state, str):
        try: form_state = json.loads(form_state)
        except: form_state = {}
    if not form_state:
        return jsonify({'success': False, 'error': 'no saved progress'})
    return jsonify({'success': True, 'step': form_state.get('step', 0), 'form': form_state.get('form', {}), 'saved_at': form_state.get('saved_at', ''), 'business_name': row.get('business_name', '')})

@app.route('/api/prospect/convert', methods=['POST'])
@require_auth
def convert_prospect():
    d = request.json or {}
    phone = d.get('phone', '')
    if not phone:
        return err('Phone required')
    sb.table('prospects').update({'status': 'converted', 'converted_at': datetime.now().isoformat(), 'form_state': {}}).eq('phone', phone).execute()
    return ok(action='converted')

# ── IMAGE STYLE SELECTION ─────────────────────────────────────
# Called by n8n sub-workflow v8 Select Style node (Phase C, Jul 1 2026).
# Returns one style chosen from the client's category/business_type routing
# pool, excluding the last 2 styles used (anti-repeat). All fallbacks logged.
# See ai/style_library.md, ai/style_routing_map.md.

def _fetch_style_pool(category, business_type):
    """Type-override wins over category default. Empty list if no rule."""
    try:
        r = sb.table('style_routing_map') \
            .select('style_ids') \
            .eq('category', category) \
            .eq('business_type', business_type) \
            .limit(1) \
            .execute()
        if r.data:
            return r.data[0]['style_ids']
        r = sb.table('style_routing_map') \
            .select('style_ids') \
            .eq('category', category) \
            .is_('business_type', 'null') \
            .limit(1) \
            .execute()
        return r.data[0]['style_ids'] if r.data else []
    except Exception as e:
        log.error(f'[style/select] pool fetch failed for {category!r}/{business_type!r}: {e}')
        return []


def _fetch_recent_styles(client_id, limit=2):
    """Return last N style_id_used for this client (newest first). Empty on first post."""
    try:
        r = sb.table('posts_log') \
            .select('style_id_used,posted_at') \
            .eq('client_id', client_id) \
            .not_.is_('style_id_used', 'null') \
            .order('posted_at', desc=True) \
            .limit(limit) \
            .execute()
        return [row['style_id_used'] for row in r.data if row.get('style_id_used')]
    except Exception as e:
        log.warning(f'[style/select] recent-styles fetch failed for {client_id}: {e}')
        return []


def _resolve_style_row(style_id):
    """Look up the style_template. Returns (style_id, style_template) or absolute fallback."""
    try:
        r = sb.table('prompt_style_library') \
            .select('style_id,style_template') \
            .eq('style_id', style_id) \
            .limit(1) \
            .execute()
        if r.data:
            return r.data[0]['style_id'], r.data[0]['style_template']
    except Exception as e:
        log.error(f'[style/select] style resolve failed for {style_id!r}: {e}')
    # Referential integrity failure — routing points at a missing library row.
    log.error(f'[style/select] REFERENTIAL INTEGRITY: style_id {style_id!r} missing from prompt_style_library')
    return style_id, ABSOLUTE_FALLBACK_TEMPLATE


@app.route('/api/style/select', methods=['POST'])
@require_admin
def style_select():
    """
    Pick an image style for the next post.
    Body: { "client_id": "...", "business_type": "..." }
    Returns: { "style_id": "...", "style_template": "...", "source": "primary|fallback_pool|absolute" }
    """
    import random
    d = request.json or {}
    # B-031: Schema validation
    d, val_err = _validate(d, _SCHEMA_STYLE_SELECT)
    if val_err:
        return err(val_err)
    client_id     = d.get('client_id', '')
    business_type = d.get('business_type', '') or ''

    if not client_id:
        return err('client_id required', 400)

    # Step 1: business_type → category (Beta lookup; Lesson 178).
    category = BUSINESS_TYPE_TO_CATEGORY.get(business_type)
    if not category:
        log.warning(
            f"[style/select] Unmapped business_type '{business_type}' for {client_id}. "
            f'Using SAFE_FALLBACK_POOL.'
        )
        chosen = random.choice(SAFE_FALLBACK_POOL)
        sid, tpl = _resolve_style_row(chosen)
        return jsonify({'status': 'success', 'style_id': sid, 'style_template': tpl,
                        'source': 'fallback_pool'})

    # Step 2: routing lookup (type override first, category default fallback).
    pool = _fetch_style_pool(category, business_type)
    if not pool:
        log.warning(
            f"[style/select] No routing rule for category={category!r}, "
            f'business_type={business_type!r}. Using SAFE_FALLBACK_POOL.'
        )
        chosen = random.choice(SAFE_FALLBACK_POOL)
        sid, tpl = _resolve_style_row(chosen)
        return jsonify({'status': 'success', 'style_id': sid, 'style_template': tpl,
                        'source': 'fallback_pool'})

    # Step 3: anti-repeat — exclude last 2 styles.
    recent = _fetch_recent_styles(client_id, limit=2)
    eligible = [s for s in pool if s not in recent]
    if not eligible:
        log.info(f'[style/select] Anti-repeat exhausted pool for {client_id}; using full pool.')
        eligible = pool

    # Step 4: pick + resolve.
    chosen = random.choice(eligible)
    sid, tpl = _resolve_style_row(chosen)
    return jsonify({'status': 'success', 'style_id': sid, 'style_template': tpl,
                    'source': 'primary'})


# ── POSTS LOG ─────────────────────────────────────────────────
@app.route('/api/posts_log', methods=['POST'])
@require_admin
def log_post():
    d = request.json or {}
    # B-031: Schema validation
    d, val_err = _validate(d, _SCHEMA_POSTS_LOG)
    if val_err:
        return err(val_err)
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
        'style_id_used':d.get('style_id_used', '') or None,  # Image style rotation (Phase B/C, Jul 1 2026)
        'artistic_style_used': d.get('artistic_style_used', '') or None,  # Artistic style (v41, Jul 14 2026)
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


@app.route('/api/posts_log/update', methods=['POST'])
@require_admin
def update_post_log():
    """
    Update an existing posts_log row after a same-day retry.
    Matches by client_id + posted_at (the original failed row).
    Called by n8n Retry Post node after token recovery.
    """
    d          = request.json or {}
    client_id  = d.get('client_id', '')
    posted_at  = d.get('posted_at', '')
    fb_status  = d.get('fb_status', '')
    ig_status  = d.get('ig_status', '')

    if not client_id or not posted_at:
        return err('client_id and posted_at required', 400)

    update = {
        'fb_status':    fb_status,
        'ig_status':    ig_status,
        'fb_post_id':   d.get('fb_post_id', ''),
        'ig_post_id':   d.get('ig_post_id', ''),
        'fb_error':     fb_status  == 'FAILED',
        'fb_error_msg': d.get('fb_error_msg', '') if fb_status  == 'FAILED' else '',
        'ig_error':     ig_status  == 'FAILED',
        'ig_error_msg': d.get('ig_error_msg', '') if ig_status  == 'FAILED' else '',
    }

    sb.table('posts_log') \
        .update(update) \
        .eq('client_id', client_id) \
        .eq('posted_at', posted_at) \
        .execute()

    return ok()


# Returns the most recent posts_log row per active client — used by health check
@app.route('/api/posts_log/recent', methods=['GET'])
@require_admin
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
@require_admin
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
@require_admin
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
@require_admin
def get_gbp_clients():
    result = sb.table('gbp_clients').select('*').eq('active', True).eq('gbp_enabled', True).execute()
    return ok(result.data, count=len(result.data))

@app.route('/api/gbp_clients', methods=['POST'])
@require_admin
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
@require_admin
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
@require_auth
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
@require_admin
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
@require_admin
def email_cancel():
    d = request.json or {}
    cid = d.get('client_id')
    r = sb.table('clients').select('*').eq('client_id', cid).single().execute()
    if r.data and EMAIL_AVAILABLE: send_cancellation_email(r.data)
    return ok()

@app.route('/api/email/pause', methods=['POST'])
@require_admin
def email_pause():
    d = request.json or {}
    cid = d.get('client_id')
    r = sb.table('clients').select('*').eq('client_id', cid).single().execute()
    if r.data and EMAIL_AVAILABLE: send_pause_email(r.data)
    return ok()

@app.route('/api/prospects/eligible', methods=['GET'])
@require_admin
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
@require_admin
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
@require_auth
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
@require_admin
def email_alert():
    d = request.json or {}
    if EMAIL_AVAILABLE:
        send_internal_alert(d.get('title','Alert'), d.get('message',''), d.get('level','alert'))
    return ok()

@app.route('/api/health_check/dedup', methods=['POST'])
@require_admin
def health_check_dedup():
    """
    Called by n8n Health Check before sending an alert email.
    Returns already_sent=True if health alert already sent today -> n8n skips email.
    Returns already_sent=False and records it -> n8n sends email.
    Uses client_id='SYSTEM' in email_campaign_log. Resets daily.
    """
    from datetime import date
    camp_key = f"health_check_{date.today().isoformat()}"
    try:
        already = bool(
            sb.table('email_campaign_log')
              .select('id')
              .eq('client_id', 'SYSTEM')
              .eq('campaign', camp_key)
              .execute().data
        )
        if already:
            return ok(already_sent=True)
        sb.table('email_campaign_log').insert({
            'client_id': 'SYSTEM',
            'campaign':  camp_key,
            'email':     'chief@posst.app',
        }).execute()
        return ok(already_sent=False)
    except Exception as e:
        log.error(f'health_check_dedup error: {e}')
        return ok(already_sent=False)

@app.route('/api/email/campaigns', methods=['POST'])
@require_admin
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
@require_admin
def send_reconnect_email():
    d          = request.json or {}
    client_id  = d.get('client_id')
    if not client_id:
        return err('Missing client_id', 400)
    client_row = sb.table('clients').select('*').eq('client_id', client_id).single().execute()
    if not client_row.data:
        return err('Client not found', 404)
    # Dedup: one reconnect confirmation email per client per day
    from datetime import date
    camp_key = f"reconnect_confirm_{date.today().isoformat()}"
    already  = bool(sb.table('email_campaign_log').select('id')
                      .eq('client_id', client_id).eq('campaign', camp_key).execute().data)
    if already:
        log.info(f'send_reconnect_email: already sent today for {client_id}, skipping')
        return ok(sent=False, skipped=True)
    if EMAIL_AVAILABLE:
        send_reconnect_confirmation_email(
            client_row.data,
            d.get('posting_time', client_row.data.get('posting_time', '')),
            d.get('timezone',     client_row.data.get('timezone', 'Australia/Melbourne')),
            d.get('platforms',    ['Facebook', 'Instagram']),
        )
        sb.table('email_campaign_log').insert({
            'client_id': client_id,
            'campaign':  camp_key,
            'email':     client_row.data.get('contact_email', ''),
        }).execute()
    return ok(sent=EMAIL_AVAILABLE)

# ── PORTAL SESSION TOKENS (v43 Security) ─────────────────────
import secrets as _secrets
from datetime import datetime as _dt, timezone as _tz, timedelta as _td

def _create_portal_session(phone):
    """Create a session token for portal access. Returns the token string.
    Invalidates any previous tokens for this phone. Expires in 24 hours."""
    token = _secrets.token_hex(32)  # 64-char hex string
    expires = (_dt.now(_tz.utc) + _td(hours=24)).isoformat()

    # Delete previous sessions for this phone
    try:
        sb.table('portal_sessions').delete().eq('phone', phone).execute()
    except Exception:
        pass  # OK if table is empty

    # Clean up expired sessions (housekeeping)
    try:
        sb.table('portal_sessions').delete().lt('expires_at', _dt.now(_tz.utc).isoformat()).execute()
    except Exception:
        pass

    # Create new session
    sb.table('portal_sessions').insert({
        'token': token,
        'phone': phone,
        'expires_at': expires,
    }).execute()

    _audit_log('portal_session_created', detail={'phone': phone[:6] + '***'})
    return token


@app.route('/api/session/create', methods=['POST'])
@require_auth
def create_session():
    """Create a portal session token for a given phone. Used by post-OAuth redirect."""
    d = request.json or {}
    phone = (d.get('phone') or '').strip()
    if not phone:
        return err('Phone required')
    token = _create_portal_session(phone)
    return ok(session_token=token)


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
_last_rate_cleanup = 0

def _check_rate(key, max_per_hour):
    global _last_rate_cleanup
    now = _time.time()
    # D2-9: Purge expired entries every 10 minutes to prevent unbounded memory growth.
    # At 100+ clients with portal logins, thousands of entries accumulate with no cleanup.
    if now - _last_rate_cleanup > 600:
        expired = [k for k, v in _otp_rate.items() if now > v.get('window_end', 0)]
        for k in expired:
            del _otp_rate[k]
        expired_a = [k for k, v in _otp_attempts.items() if v.get('locked_until', 0) > 0 and now > v['locked_until']]
        for k in expired_a:
            del _otp_attempts[k]
        _last_rate_cleanup = now
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
@require_auth
def otp_send():
    d = request.json or {}
    # B-031: Schema validation
    d, val_err = _validate(d, _SCHEMA_OTP)
    if val_err:
        return err(val_err)
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
        _audit_log('auth_rate_limited', detail={'type': 'otp_ip', 'phone': phone[:6] + '***'}, status_code=429)
        return jsonify({'status': 'error', 'code': 'RATE_LIMITED', 'message': 'Too many requests. Please try again later.'}), 429
    if not _check_rate('phone_' + phone, MAX_OTP_PER_PHONE):
        return jsonify({'status': 'error', 'code': 'RATE_LIMITED', 'message': 'Too many requests for this number. Try again in an hour.'}), 429
    # Twilio Verify requires strict E.164 (no spaces) — Supabase/app format includes a space (e.g. "+61 414208895")
    phone_e164 = phone.replace(' ', '')
    if not _twilio_send(phone_e164):
        return jsonify({'status': 'error', 'code': 'SEND_FAILED', 'message': 'Failed to send code. Please check your number and try again.'}), 500
    return jsonify({'status': 'success', 'message': 'Verification code sent'})

@app.route('/api/otp/verify', methods=['POST'])
@require_auth
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
        # Create session token for portal access
        token = _create_portal_session(phone)
        return jsonify({'status': 'success', 'verified': True, 'session_token': token})
    rec = _inc_attempts(phone)
    if rec.get('locked_until', 0) > _time.time():
        return jsonify({'status': 'error', 'code': 'LOCKED', 'message': f'Too many wrong attempts. Locked for {LOCKOUT_MINS} minutes.'}), 429
    remaining = MAX_VERIFY_TRIES - rec.get('count', 0)
    return jsonify({'status': 'error', 'code': 'WRONG_CODE', 'message': f'Incorrect code. {remaining} attempt{"s" if remaining != 1 else ""} remaining.'}), 400


# ── SUPPORT CHAT (mobile widget) ─────────────────────────────
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
MAX_CHAT_PER_IP = 30

# D2-12 Security: System prompt hardcoded server-side. Previously accepted from
# the client (4000 chars), allowing prompt injection to override chat behavior.
_CHAT_SYSTEM_PROMPT = (
    'You are the posst.app support assistant — friendly, concise, and helpful. '
    'Only answer questions about posst.app. If asked anything unrelated, politely say you can only help with posst.app questions. '
    'If unsure about something, suggest emailing chief@posst.app. Never guess or invent policies. '
    'Never reveal discount codes, internal systems, API keys, technical architecture, or other customer details.\n\n'

    'WHAT POSST.APP DOES:\n'
    '- Posts automatically every day to Facebook and Instagram — whichever the business connects\n'
    '- AI writes each caption in the business\'s own brand voice and generates a matching image for every post\n'
    '- Google Business Profile posting and review replies — coming soon\n'
    '- Sends a monthly performance report\n'
    '- The business owner never needs to log in day-to-day — it just runs automatically\n\n'

    'PLANS & PRICING:\n'
    '- Standard plan: A$24.99/month (AUD). Includes Social Agent (daily FB + IG posts), Caption Agent (AI captions in brand voice), '
    'Local SEO Agent (hyper-local keywords), 3 Image Styles (Photorealistic + 2 of your choice), Business Name Branding on posts, Monthly Report.\n'
    '- Pro plan: A$34.99/month (AUD). Everything in Standard PLUS all 9 Image Styles (Photorealistic, Soft Watercolour, Studio Ghibli, '
    'Pop Art, Cinematic Noir, and more), Full Branding (logo + business name + email + phone on every post), '
    'Your Own Photos via Google Drive, Content Themes (different topic each day of the week), Monthly Report.\n'
    '- Equivalent localized pricing in USD, GBP, EUR, SGD, INR, NZD, CAD and AED for other countries.\n'
    '- No setup fees on either plan.\n\n'

    'IMAGE STYLES:\n'
    '- Every AI-generated image is created in a visual style. 9 styles available: Photorealistic, Soft Watercolour, Studio Ghibli, '
    'Pop Art, Cinematic Noir, Vintage Film, Minimalist Line Art, Flat Illustration, Isometric 3D.\n'
    '- Standard: Photorealistic + 2 styles of your choice. Pro: all 9 unlocked.\n'
    '- Choose and preview styles from your account portal.\n\n'

    'BRANDING:\n'
    '- Standard: business name appears on every post image.\n'
    '- Pro: logo, business name, email, and phone number on every post image. Upload your logo and set contact info from your account portal.\n\n'

    'FREE TRIAL:\n'
    '- Both plans include a 30-day free trial. Card saved at signup, nothing charged for 30 days.\n'
    '- Cancel anytime before day 30 by emailing chief@posst.app — no charge.\n\n'

    'SIGNING UP:\n'
    '- Login via phone number + one-time SMS code (OTP) — no password needed.\n'
    '- Signup takes about 5 minutes. After signup, connect Facebook/Instagram via a quick secure login — takes under 2 minutes.\n'
    '- Posting schedule (days + time) is fully customizable and can be changed anytime from your account portal.\n\n'

    'MANAGING YOUR ACCOUNT:\n'
    '- From your account portal you can change posting schedule, pick image styles, upload your logo (Pro), update contact branding (Pro), and manage billing.\n'
    '- One phone number can manage multiple businesses.\n'
    '- Cancel anytime by emailing chief@posst.app.\n\n'

    'SUPPORT: for anything not covered above, contact chief@posst.app.'
)

@app.route('/api/chat', methods=['POST'])
@require_auth
def chat():
    d = request.json or {}
    # B-031: Schema validation
    d, val_err = _validate(d, _SCHEMA_CHAT)
    if val_err:
        return err(val_err)
    messages = d.get('messages') or []
    if not isinstance(messages, list) or not messages:
        return jsonify({'status': 'error', 'message': 'messages required'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'status': 'error', 'message': 'Chat is not configured yet.'}), 503
    client_ip = request.headers.get('X-Real-IP', request.remote_addr or 'unknown')
    if not _check_rate('chat_ip_' + str(client_ip), MAX_CHAT_PER_IP):
        _audit_log('auth_rate_limited', detail={'type': 'chat'}, status_code=429)
        return jsonify({'status': 'error', 'message': 'Too many messages. Please try again later.'}), 429
    # Cap history to last 20 messages to control cost/payload size
    # Cap each message content to 2000 chars to prevent abuse
    messages = [{'role': m.get('role', 'user'), 'content': (m.get('content') or '')[:2000]}
                for m in messages[-20:] if isinstance(m, dict)]
    import urllib.request as _ur
    payload = json.dumps({
        'model': 'claude-sonnet-4-6',
        'max_tokens': 500,
        'system': _CHAT_SYSTEM_PROMPT,
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
@require_auth
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
    # B-031: Schema validation
    d, val_err = _validate(d, _SCHEMA_STRIPE_CHECKOUT)
    if val_err:
        return err(val_err)
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
        log.error('STRIPE_WEBHOOK_SECRET not configured — rejecting webhook')
        return jsonify({'error': 'Webhook not configured'}), 500

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



# ── B-030: GLOBAL ERROR HANDLER (Tier B Security) ────────────
# Catches all unhandled exceptions. Logs full traceback server-side,
# returns generic message to caller — no stack traces, paths, or
# library versions ever leak to the client.
import traceback as _tb

@app.errorhandler(Exception)
def handle_exception(e):
    log.error(f'Unhandled exception on {request.method} {request.path}: '
              f'{type(e).__name__}: {e}\n{_tb.format_exc()}')
    return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

@app.errorhandler(404)
def handle_404(e):
    return jsonify({'status': 'error', 'message': 'Not found'}), 404

@app.errorhandler(405)
def handle_405(e):
    return jsonify({'status': 'error', 'message': 'Method not allowed'}), 405


# ============================================================
# ARTISTIC STYLE ENDPOINTS (Phase 1 - Jul 13 2026)
# ============================================================

def _pick_artistic_style(client_id):
    from datetime import datetime
    try:
        resp = sb.table("client_artistic_styles").select("style_id").eq("client_id", client_id).eq("is_active", True).execute()
        if not resp.data:
            return "", "none"
        style_ids = [r["style_id"] for r in resp.data]
        styles_resp = sb.table("artistic_styles").select("slug, prompt_prefix").in_("id", style_ids).order("sort_order").execute()
        if not styles_resp.data:
            return "", "none"
        styles = styles_resp.data
        client_resp = sb.table("clients").select("teaser_style_id, teaser_start_date, teaser_end_date").eq("client_id", client_id).maybe_single().execute()
        if client_resp.data:
            cd = client_resp.data
            today = datetime.now().strftime("%Y-%m-%d")
            if cd.get("teaser_style_id") and cd.get("teaser_start_date") and cd.get("teaser_end_date") and cd["teaser_start_date"] <= today <= cd["teaser_end_date"]:
                teaser_resp = sb.table("artistic_styles").select("slug, prompt_prefix").eq("id", cd["teaser_style_id"]).maybe_single().execute()
                if teaser_resp.data:
                    styles.append(teaser_resp.data)
        day_of_year = datetime.now().timetuple().tm_yday
        idx = day_of_year % len(styles)
        chosen = styles[idx]
        return chosen["prompt_prefix"], chosen["slug"]
    except Exception as e:
        app.logger.error(f"Error picking artistic style: {e}")
        return "", "error"

@app.route("/api/artistic-styles", methods=["GET"])
@require_auth
def get_artistic_styles():
    try:
        resp = sb.table("artistic_styles").select("id, name, slug, description, category_affinity, tier, sort_order, is_default").order("sort_order").execute()
        return jsonify({"status": "ok", "styles": resp.data})
    except Exception as e:
        app.logger.error(f"Error fetching artistic styles: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch styles"}), 500

@app.route("/api/client/<client_id>/artistic-styles", methods=["GET"])
@require_auth
def get_client_artistic_styles(client_id):
    try:
        resp = sb.table("client_artistic_styles").select("style_id, is_active").eq("client_id", client_id).execute()
        return jsonify({"status": "ok", "selections": resp.data})
    except Exception as e:
        app.logger.error(f"Error fetching client styles: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch client styles"}), 500

@app.route("/api/client/<client_id>/artistic-styles", methods=["POST"])
@require_auth
def set_client_artistic_styles(client_id):
    try:
        data = request.get_json()
        style_ids = data.get("style_ids", [])
        if not style_ids:
            return jsonify({"status": "error", "message": "At least one style required"}), 400
        client_resp = sb.table("clients").select("plan").eq("client_id", client_id).maybe_single().execute()
        if not client_resp.data:
            return jsonify({"status": "error", "message": "Client not found"}), 404
        plan = (client_resp.data.get("plan") or "standard").lower()
        if plan != "pro" and len(style_ids) > 3:
            return jsonify({"status": "error", "message": "Standard plan allows photorealistic + 2 styles. Upgrade to Pro for all 8."}), 400
        photo_resp = sb.table("artistic_styles").select("id").eq("slug", "photorealistic").maybe_single().execute()
        if photo_resp.data and photo_resp.data["id"] not in style_ids:
            return jsonify({"status": "error", "message": "Photorealistic style must always be included"}), 400
        sb.table("client_artistic_styles").delete().eq("client_id", client_id).execute()
        for sid in style_ids:
            sb.table("client_artistic_styles").insert({"client_id": client_id, "style_id": sid, "is_active": True}).execute()
        return jsonify({"status": "ok", "count": len(style_ids)})
    except Exception as e:
        app.logger.error(f"Error setting client styles: {e}")
        return jsonify({"status": "error", "message": "Failed to update styles"}), 500

@app.route("/api/artistic-style/pick/<client_id>", methods=["GET"])
@require_admin
def pick_artistic_style(client_id):
    prefix, slug = _pick_artistic_style(client_id)
    return jsonify({"status": "ok", "prompt_prefix": prefix, "style_slug": slug})


# ──────────────────────────────────────────────────────────────────────
# Phase 5: Teaser / Upgrade Emails (v44, Jul 16 2026)
# ──────────────────────────────────────────────────────────────────────

R2_PREVIEW_BASE = 'https://pub-f5f1d08da66048808d14f48cb78ebb36.r2.dev/style_previews'

def _get_teased_styles(notes):
    """Extract list of previously teased style IDs from client notes JSON."""
    try:
        n = notes if isinstance(notes, dict) else json.loads(notes or '{}')
        return n.get('teased_styles', [])
    except Exception:
        return []

def _save_teased_style(client_id, style_id, current_notes):
    """Append style_id to the teased_styles list in client notes."""
    try:
        n = current_notes if isinstance(current_notes, dict) else json.loads(current_notes or '{}')
    except Exception:
        n = {}
    teased = n.get('teased_styles', [])
    if style_id not in teased:
        teased.append(style_id)
    n['teased_styles'] = teased
    sb.table('clients').update({'notes': json.dumps(n)}).eq('client_id', client_id).execute()

def _get_preview_url_for_teaser(client_business_type, style_slug):
    """Build the R2 preview URL for a style + business type combo."""
    try:
        group = get_preview_group(client_business_type)
    except Exception:
        group = 'professional_creative'  # safe fallback
    return f'{R2_PREVIEW_BASE}/{group}/{style_slug}.jpg'


@app.route('/api/teaser/activate', methods=['POST'])
@require_admin
def teaser_activate():
    """
    Monthly cron: activate a 3-day style teaser for each Standard client.
    Picks the next locked style they haven't been teased with yet.
    Sends teaser start email. Audit logs each activation.
    """
    from datetime import datetime, timedelta
    activated = []
    errors = []
    try:
        # Get all active Standard clients
        clients_resp = sb.table('clients').select(
            'client_id, plan, business_name, business_type, contact_email, notes, teaser_style_id'
        ).eq('status', 'Active').execute()
        if not clients_resp.data:
            return ok(message='No active clients found', activated=[])

        standard_clients = [
            c for c in clients_resp.data
            if (c.get('plan') or '').lower() == 'standard'
            and not c.get('teaser_style_id')  # skip if already in a teaser window
        ]
        if not standard_clients:
            return ok(message='No eligible Standard clients', activated=[])

        # Get all artistic styles
        all_styles = sb.table('artistic_styles').select('id, name, slug, is_default').order('sort_order').execute()
        if not all_styles.data:
            return err('No artistic styles found in database')

        # Get photorealistic ID to exclude from teaser candidates
        photo_id = None
        for st in all_styles.data:
            if st.get('slug') == 'photorealistic':
                photo_id = st['id']
                break

        for client in standard_clients:
            try:
                cid = client['client_id']
                # Get client's currently assigned styles (to exclude from teaser)
                assigned_resp = sb.table('client_artistic_styles').select('style_id').eq('client_id', cid).eq('is_active', True).execute()
                assigned_ids = {r['style_id'] for r in (assigned_resp.data or [])}

                # Previously teased styles
                teased_ids = _get_teased_styles(client.get('notes'))

                # Candidate = all styles minus assigned minus photorealistic minus already teased
                candidates = [
                    st for st in all_styles.data
                    if st['id'] not in assigned_ids
                    and st['id'] != photo_id
                    and st['id'] not in teased_ids
                ]
                # If all styles have been teased, reset rotation and start over
                if not candidates:
                    candidates = [
                        st for st in all_styles.data
                        if st['id'] not in assigned_ids
                        and st['id'] != photo_id
                    ]
                    # Clear teased list for fresh rotation
                    if candidates:
                        try:
                            n = client.get('notes')
                            n = n if isinstance(n, dict) else json.loads(n or '{}')
                        except Exception:
                            n = {}
                        n['teased_styles'] = []
                        sb.table('clients').update({'notes': json.dumps(n)}).eq('client_id', cid).execute()

                if not candidates:
                    continue  # no locked styles to tease (shouldn't happen for Standard)

                # Pick the first candidate (deterministic, ordered by sort_order)
                chosen = candidates[0]
                today_str = datetime.now().strftime('%Y-%m-%d')
                end_str = (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')

                sb.table('clients').update({
                    'teaser_style_id': chosen['id'],
                    'teaser_start_date': today_str,
                    'teaser_end_date': end_str,
                }).eq('client_id', cid).execute()

                # Send teaser start email
                if EMAIL_AVAILABLE and client.get('contact_email'):
                    preview_url = _get_preview_url_for_teaser(client.get('business_type', ''), chosen['slug'])
                    try:
                        from posst_email import send_teaser_start_email
                        send_teaser_start_email(client, chosen['name'], preview_url)
                    except Exception as email_err:
                        log.error(f'[teaser/activate] Email failed for {cid}: {email_err}')

                _audit_log('teaser_activated', actor=cid, detail={
                    'style_id': chosen['id'], 'style_name': chosen['name'],
                    'start': today_str, 'end': end_str,
                })
                activated.append({'client_id': cid, 'style': chosen['name'], 'end': end_str})

            except Exception as client_err:
                log.error(f'[teaser/activate] Error for {client.get("client_id")}: {client_err}')
                errors.append({'client_id': client.get('client_id'), 'error': str(client_err)})

    except Exception as e:
        log.error(f'[teaser/activate] Fatal error: {e}')
        return err(f'Teaser activation failed: {e}')

    return ok(activated=activated, errors=errors, count=len(activated))


@app.route('/api/teaser/expire', methods=['POST'])
@require_admin
def teaser_expire():
    """
    Daily cron: expire teasers whose teaser_end_date has passed.
    Clears teaser fields, records used style, sends end email.
    """
    from datetime import datetime
    expired = []
    errors = []
    try:
        today_str = datetime.now().strftime('%Y-%m-%d')
        # Find clients with active teasers that have expired
        resp = sb.table('clients').select(
            'client_id, business_name, business_type, contact_email, notes, teaser_style_id, teaser_end_date'
        ).not_.is_('teaser_style_id', 'null').lt('teaser_end_date', today_str).execute()

        if not resp.data:
            return ok(message='No expired teasers', expired=[])

        for client in resp.data:
            try:
                cid = client['client_id']
                style_id = client['teaser_style_id']

                # Look up style name for email
                style_resp = sb.table('artistic_styles').select('name, slug').eq('id', style_id).maybe_single().execute()
                style_name = style_resp.data['name'] if style_resp and style_resp.data else 'Unknown'
                style_slug = style_resp.data['slug'] if style_resp and style_resp.data else 'photorealistic'

                # Record this style as teased (for rotation tracking)
                _save_teased_style(cid, style_id, client.get('notes'))

                # Clear teaser fields
                sb.table('clients').update({
                    'teaser_style_id': None,
                    'teaser_start_date': None,
                    'teaser_end_date': None,
                }).eq('client_id', cid).execute()

                # Send teaser end email
                if EMAIL_AVAILABLE and client.get('contact_email'):
                    preview_url = _get_preview_url_for_teaser(client.get('business_type', ''), style_slug)
                    try:
                        from posst_email import send_teaser_end_email
                        send_teaser_end_email(client, style_name, preview_url)
                    except Exception as email_err:
                        log.error(f'[teaser/expire] Email failed for {cid}: {email_err}')

                _audit_log('teaser_expired', actor=cid, detail={
                    'style_id': style_id, 'style_name': style_name,
                })
                expired.append({'client_id': cid, 'style': style_name})

            except Exception as client_err:
                log.error(f'[teaser/expire] Error for {client.get("client_id")}: {client_err}')
                errors.append({'client_id': client.get('client_id'), 'error': str(client_err)})

    except Exception as e:
        log.error(f'[teaser/expire] Fatal error: {e}')
        return err(f'Teaser expiry failed: {e}')

    return ok(expired=expired, errors=errors, count=len(expired))


# ──────────────────────────────────────────────────────────────────────
# Phase 4: Portal UI endpoints (v43, Jul 15 2026)
# ──────────────────────────────────────────────────────────────────────

# Preview group mapping — maps 208 business types to 29 visual groups
from preview_group_mapping import get_preview_group, get_all_preview_urls, PREVIEW_GROUPS, ARTISTIC_STYLES

@app.route('/api/client/<client_id>/style-gallery', methods=['GET'])
@require_auth
def style_gallery(client_id):
    """Return style gallery data for the portal: all artistic styles with
    lock/unlock status per plan, and preview image URLs for client's business type."""
    try:
        # Get client info
        cr = sb.table('clients').select('business_type, plan').eq('client_id', client_id).maybe_single().execute()
        if not cr.data:
            return err('Client not found', 404)
        business_type = cr.data.get('business_type', '')
        plan = (cr.data.get('plan') or 'standard').lower()

        # Get all artistic styles from Supabase
        styles_resp = sb.table('artistic_styles').select(
            'id, name, slug, description, tier, sort_order, is_default'
        ).order('sort_order').execute()
        all_styles = styles_resp.data or []

        # Get client's current selections
        sel_resp = sb.table('client_artistic_styles').select('style_id, is_active').eq('client_id', client_id).execute()
        selected_ids = {r['style_id'] for r in (sel_resp.data or []) if r.get('is_active')}

        # Get preview image URLs for this business type
        preview_urls = get_all_preview_urls(business_type)

        # Build gallery items
        gallery = []
        for s in all_styles:
            slug = s.get('slug', '')
            tier = (s.get('tier') or 'standard').lower()
            is_locked = (tier == 'pro' and plan != 'pro')
            gallery.append({
                'id': s['id'],
                'name': s['name'],
                'slug': slug,
                'description': s.get('description', ''),
                'is_selected': s['id'] in selected_ids,
                'is_locked': is_locked,
                'is_default': s.get('is_default', False),
                'preview_url': preview_urls.get(slug, ''),
            })

        return ok(data={
            'gallery': gallery,
            'plan': plan,
            'business_type': business_type,
            'preview_group': get_preview_group(business_type),
        })
    except Exception as e:
        log.error(f'[style-gallery] {client_id}: {e}')
        return err('Failed to load style gallery', 500)


@app.route('/api/client/<client_id>/logo', methods=['POST'])
@require_auth
def upload_logo(client_id):
    """Upload a logo image for a Pro client.
    Security: magic bytes check, Pillow re-encode, EXIF strip, UUID filename,
    dimension cap, size cap, rate limit, audit log."""
    import base64
    import uuid
    import io as _io
    import time as _time
    import requests as http_req

    try:
        # Rate limit: 5 uploads per client per hour
        rate_key = f'logo_upload_{client_id}'
        if not _check_rate(rate_key, 5):
            _audit_log('logo_upload_rate_limited', actor=client_id, status_code=429)
            return err('Too many uploads. Try again later.', 429)

        # Verify client exists and is Pro
        cr = sb.table('clients').select('plan').eq('client_id', client_id).maybe_single().execute()
        if not cr.data:
            return err('Client not found', 404)
        if (cr.data.get('plan') or 'standard').lower() != 'pro':
            _audit_log('logo_upload_denied', actor=client_id, detail={'reason': 'not_pro'}, status_code=403)
            return err('Logo upload is a Pro feature. Upgrade to Pro to add your logo.', 403)

        d = request.get_json() or {}
        image_b64 = d.get('image_b64', '')
        if not image_b64:
            return err('No image data provided')

        # Decode base64
        try:
            raw_bytes = base64.b64decode(image_b64)
        except Exception:
            _audit_log('logo_upload_failed', actor=client_id, detail={'reason': 'invalid_base64'}, status_code=400)
            return err('Invalid image data')

        # Size check: max 500KB raw (plenty for a logo)
        if len(raw_bytes) > 500 * 1024:
            _audit_log('logo_upload_failed', actor=client_id, detail={'reason': 'too_large', 'size': len(raw_bytes)}, status_code=400)
            return err('Logo must be under 500KB')

        # Magic bytes check — only PNG and JPEG accepted
        png_magic = b'\x89PNG\r\n\x1a\n'
        jpg_magic = (b'\xff\xd8\xff',)
        if raw_bytes[:8] == png_magic:
            detected_format = 'PNG'
        elif raw_bytes[:3] in jpg_magic:
            detected_format = 'JPEG'
        else:
            _audit_log('logo_upload_failed', actor=client_id, detail={'reason': 'invalid_type'}, status_code=400)
            return err('Only PNG and JPG images are accepted')

        # Re-encode through Pillow — strips EXIF, embedded scripts, polyglot payloads
        try:
            from PIL import Image as _PILImage
            img = _PILImage.open(_io.BytesIO(raw_bytes))

            # Dimension check: max 4096×4096
            if img.width > 4096 or img.height > 4096:
                _audit_log('logo_upload_failed', actor=client_id, detail={'reason': 'too_large_dims', 'w': img.width, 'h': img.height}, status_code=400)
                return err('Logo dimensions must be under 4096×4096 pixels')

            # Convert to RGBA (handle transparency) then re-save as PNG
            img = img.convert('RGBA')
            buf = _io.BytesIO()
            img.save(buf, format='PNG', optimize=True)
            clean_bytes = buf.getvalue()

        except Exception as pil_err:
            _audit_log('logo_upload_failed', actor=client_id, detail={'reason': 'corrupt_image', 'error': str(pil_err)}, status_code=400)
            return err('Image appears to be corrupt or invalid')

        # Upload to R2 — isolated path per client, UUID filename
        logo_filename = f'logos/{client_id}/{uuid.uuid4().hex}.png'
        logo_b64 = base64.b64encode(clean_bytes).decode()

        r2_resp = http_req.post('http://172.17.0.1:5679/upload', json={
            'filename': logo_filename,
            'image_b64': logo_b64,
        }, timeout=30)

        if r2_resp.status_code != 200:
            _audit_log('logo_upload_failed', actor=client_id, detail={'reason': 'r2_error', 'status': r2_resp.status_code}, status_code=500)
            return err('Failed to store logo. Please try again.', 500)

        logo_url = f'https://pub-f5f1d08da66048808d14f48cb78ebb36.r2.dev/{logo_filename}'

        # Save URL to clients table
        sb.table('clients').update({'logo_url': logo_url}).eq('client_id', client_id).execute()

        _audit_log('logo_uploaded', actor=client_id, detail={
            'size': len(clean_bytes), 'dims': f'{img.width}x{img.height}', 'format': detected_format
        })
        log.info(f'[logo] {client_id} uploaded — {len(clean_bytes)} bytes — {img.width}x{img.height}')
        return ok(logo_url=logo_url)

    except Exception as e:
        log.error(f'[logo] {client_id} failed: {e}')
        _audit_log('logo_upload_failed', actor=client_id, detail={'reason': 'exception', 'error': str(e)}, status_code=500)
        return err('Logo upload failed. Please try again.', 500)


@app.route('/api/client/<client_id>/portal-onboarded', methods=['PATCH'])
@require_auth
def set_portal_onboarded(client_id):
    """Mark the 'Make it yours' card as dismissed."""
    try:
        # Read current notes JSON and add portal_onboarded flag
        cr = sb.table('clients').select('notes').eq('client_id', client_id).maybe_single().execute()
        if not cr.data:
            return err('Client not found', 404)
        notes = cr.data.get('notes') or {}
        if isinstance(notes, str):
            import json as _json
            try:
                notes = _json.loads(notes)
            except Exception:
                notes = {}
        notes['portal_onboarded'] = True
        sb.table('clients').update({'notes': notes}).eq('client_id', client_id).execute()
        return ok()
    except Exception as e:
        log.error(f'[portal-onboarded] {client_id}: {e}')
        return err('Failed to update', 500)


@app.route('/api/client/<client_id>/branding', methods=['PATCH'])
@require_auth
def update_branding(client_id):
    """Update branding contact info (caption_email, caption_phone) — Pro only."""
    try:
        cr = sb.table('clients').select('plan').eq('client_id', client_id).maybe_single().execute()
        if not cr.data:
            return err('Client not found', 404)
        if (cr.data.get('plan') or 'standard').lower() != 'pro':
            return err('Branding contact info is a Pro feature', 403)

        d = request.get_json() or {}
        update = {}

        if 'caption_email' in d:
            val = _sanitize(d['caption_email'], _FIELD_LIMITS.get('caption_email', 254))
            # Basic email format check
            if val and ('@' not in val or '.' not in val.split('@')[-1]):
                return err('Invalid email format')
            update['caption_email'] = val

        if 'caption_phone' in d:
            val = _sanitize(d['caption_phone'], _FIELD_LIMITS.get('caption_phone', 30))
            update['caption_phone'] = val

        if not update:
            return err('Nothing to update')

        sb.table('clients').update(update).eq('client_id', client_id).execute()
        _audit_log('branding_updated', actor=client_id, detail=update)
        return ok()
    except Exception as e:
        log.error(f'[branding] {client_id}: {e}')
        return err('Failed to update branding', 500)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5680, debug=False)


# ──────────────────────────────────────────────────────────────────────
# /api/composite — Apply branding overlay to generated image (Phase 3, v41)
# Called by n8n between image generation and Meta posting.
# ──────────────────────────────────────────────────────────────────────
@app.route('/api/composite', methods=['POST'])
@require_admin
def composite_image():
    """
    Download image from R2, apply branding overlay, upload branded image back to R2.
    Request:  { image_url, client_id, composition_style }
    Response: { branded_url, status: 'ok' } or { branded_url: <original>, status: 'fallback' }
    Failsafe: on ANY error, returns original image_url so posting continues unbranded.
    """
    import base64
    import time as _time
    import requests as http_req
    from template_engine import composite

    d = request.json or {}
    image_url  = d.get('image_url', '')
    client_id  = d.get('client_id', '')
    comp_style = d.get('composition_style', '')

    # Failsafe wrapper — never break the posting pipeline
    try:
        if not image_url or not client_id:
            log.info(f'[composite] skip — missing params')
            return jsonify({'branded_url': image_url, 'status': 'skip', 'reason': 'missing params'})

        # Look up client
        cr = sb.table('clients').select(
            'business_name,business_suburb,plan,logo_url,brand_colors,'
            'caption_email,caption_phone,business_type'
        ).eq('client_id', client_id).execute()

        if not cr.data:
            log.warning(f'[composite] client {client_id} not found — fallback')
            return jsonify({'branded_url': image_url, 'status': 'fallback', 'reason': 'client not found'})

        client = cr.data[0]
        plan = client.get('plan', 'Standard')

        # Download image from R2
        img_resp = http_req.get(image_url, timeout=15)
        if img_resp.status_code != 200:
            log.warning(f'[composite] download failed ({img_resp.status_code}) — fallback')
            return jsonify({'branded_url': image_url, 'status': 'fallback', 'reason': 'download failed'})

        # Contact info (Pro only)
        contact_parts = [
            client.get('caption_email', '') or '',
            client.get('caption_phone', '') or '',
        ]
        contact_info = ' | '.join(p for p in contact_parts if p) if plan == 'Pro' else ''

        # Logo (Pro only)
        logo_bytes = None
        logo_url = client.get('logo_url', '') or ''
        if plan == 'Pro' and logo_url:
            try:
                logo_resp = http_req.get(logo_url, timeout=10)
                if logo_resp.status_code == 200:
                    logo_bytes = logo_resp.content
            except Exception as le:
                log.warning(f'[composite] logo download failed: {le}')

        # Brand colours (Pro only, from clients table)
        brand_colours = None
        if plan == 'Pro' and client.get('brand_colors'):
            bc = client['brand_colors']
            brand_colours = bc if isinstance(bc, dict) else None

        # Default category colours (neutral professional — category-specific in Phase 4)
        category_colours = {'primary': '#1A1A2E', 'secondary': '#E8E8E8', 'text': '#FFFFFF'}

        # Run compositing
        branded_bytes = composite(img_resp.content, {
            'business_name':    client.get('business_name', ''),
            'suburb':           client.get('business_suburb', ''),
            'plan':             plan,
            'composition_style': comp_style,
            'category_colours': category_colours,
            'logo_bytes':       logo_bytes,
            'brand_colours':    brand_colours,
            'contact_info':     contact_info,
        })

        # If composite returned the same bytes (failsafe triggered), skip re-upload
        if branded_bytes == img_resp.content:
            log.info(f'[composite] no change — using original')
            return jsonify({'branded_url': image_url, 'status': 'unchanged'})

        # Upload branded image to R2
        branded_b64 = base64.b64encode(branded_bytes).decode()

        # Build branded filename from original
        if 'r2.dev/' in image_url:
            original_filename = image_url.split('r2.dev/')[-1]
            parts = original_filename.rsplit('.', 1)
            branded_filename = f"{parts[0]}_branded.png"
        else:
            branded_filename = f"clients/{client_id}/{int(_time.time())}_branded.png"

        r2_resp = http_req.post('http://172.17.0.1:5679/upload', json={
            'filename': branded_filename,
            'image_b64': branded_b64,
        }, timeout=30)

        if r2_resp.status_code != 200:
            log.warning(f'[composite] R2 upload failed ({r2_resp.status_code}) — fallback')
            return jsonify({'branded_url': image_url, 'status': 'fallback', 'reason': 'r2 upload failed'})

        branded_url = f"https://pub-f5f1d08da66048808d14f48cb78ebb36.r2.dev/{branded_filename}"
        log.info(f'[composite] {client_id} branded OK — {comp_style} — {plan}')
        return jsonify({'branded_url': branded_url, 'status': 'ok'})

    except Exception as e:
        log.error(f'[composite] {client_id} failed: {e} — returning original')
        return jsonify({'branded_url': image_url, 'status': 'fallback', 'reason': str(e)})
