#!/usr/bin/env python3
"""
posst.app — Full Google Sheets → Supabase Migration
Reads all tabs from Google Sheet and inserts into Supabase
"""
import json
import requests
from supabase import create_client
from google.oauth2.service_account import Credentials
import gspread

SHEET_ID     = '1lV6d5OqNJ7QY44oQbxaDP0WZSCQCxpOGI3y_JxMjvuY'
SUPABASE_URL = 'https://itlndeorkphlorvcohaw.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml0bG5kZW9ya3BobG9ydmNvaGF3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MDY0Nzk1MCwiZXhwIjoyMDk2MjIzOTUwfQ.78bbEVkIIbh_BpXohe5Y8VBK7LOsYBbYdaIAov5QnOQ'
SERVICE_ACCOUNT_FILE = '/opt/posst/service_account.json'

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# Connect to Google Sheets
scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds  = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
gc     = gspread.authorize(creds)
ss     = gc.open_by_key(SHEET_ID)

print('Connected to Google Sheets and Supabase')
print('='*50)

# ── MIGRATE CLIENTS ───────────────────────────────────────────
print('\n[1] Migrating Clients...')
ws   = ss.worksheet('Clients')
rows = ws.get_all_values()
headers = rows[0]
migrated = 0
skipped  = 0

for row in rows[1:]:
    if not row[0]:  # skip empty rows
        continue
    def col(n): return row[n-1] if len(row) >= n else ''

    client_id = col(1).strip()
    if not client_id:
        continue

    # Check if already exists
    existing = sb.table('clients').select('client_id').eq('client_id', client_id).execute()
    if existing.data:
        print(f'  SKIP (exists): {client_id}')
        skipped += 1
        continue

    # Parse notes JSON
    notes = {}
    try:
        raw_notes = col(31)
        if raw_notes:
            notes = json.loads(raw_notes)
    except:
        pass

    # Parse drive categories
    drive_cats = []
    try:
        raw_cats = col(35)
        if raw_cats:
            drive_cats = json.loads(raw_cats)
    except:
        pass

    # Parse posting time (handle Date objects stored as strings)
    posting_time = col(21) or '11:00'
    if 'Dec 30 1899' in posting_time or 'GMT' in posting_time:
        posting_time = '11:00'

    # Parse go_live_sent
    go_live = col(29).strip().upper() in ('TRUE', '1', 'YES')

    # Parse monthly_report_day
    try:
        monthly_day = int(col(30)) if col(30) else 1
    except:
        monthly_day = 1

    record = {
        'client_id':           client_id,
        'status':              col(2) or 'Pending_Token',
        'phone':               col(4).lstrip("'"),
        'business_name':       col(5),
        'business_city':       col(6),
        'contact_email':       col(7),
        'business_type':       col(8),
        'business_desc':       col(9),
        'brand_keywords':      col(10),
        'plan':                col(11) or 'Standard',
        'platforms':           col(12),
        'fb_page_name':        col(13),
        'fb_page_url':         col(14),
        'fb_page_id':          col(15),
        'ig_handle':           col(16),
        'ig_business_id':      col(17),
        'gbp_name':            col(18),
        'gbp_location_id':     col(19),
        'posting_days':        col(20) or 'Mon,Tue,Wed,Thu,Fri,Sat,Sun',
        'posting_time':        posting_time,
        'timezone':            col(22) or 'Australia/Melbourne',
        'posting_time_utc':    col(23) or '01:00',
        'meta_token':          col(24),
        'meta_token_expiry':   col(25),
        'gbp_refresh_token':   col(26),
        'n8n_workflow_id':     col(27),
        'go_live_email_sent':  go_live,
        'monthly_report_day':  monthly_day,
        'notes':               notes,
        'business_suburb':     col(32),
        'business_country':    col(33) or 'Australia',
        'google_drive_url':    col(34),
        'drive_categories':    drive_cats,
        'google_drive_intent': col(36),
        'pending_token':       col(37),
        'caption_email':       col(38),
        'caption_phone':       notes.get('caption_phone', ''),
    }

    # Handle provisioned_at
    prov_at = col(28)
    if prov_at and prov_at.strip():
        record['provisioned_at'] = prov_at

    try:
        sb.table('clients').insert(record).execute()
        print(f'  OK: {client_id} — {col(5)}')
        migrated += 1
    except Exception as e:
        print(f'  ERROR: {client_id} — {e}')

print(f'Clients: {migrated} migrated, {skipped} skipped')

# ── MIGRATE PROSPECTS ─────────────────────────────────────────
print('\n[2] Migrating Prospects...')
try:
    ws   = ss.worksheet('Prospects')
    rows = ws.get_all_values()
    migrated = skipped = 0
    for row in rows[1:]:
        if not row[1]: continue  # skip if no phone
        def col(n): return row[n-1] if len(row) >= n else ''

        phone = col(2).strip()
        if not phone: continue

        existing = sb.table('prospects').select('id').eq('phone', phone).execute()
        if existing.data:
            skipped += 1
            continue

        form_state = {}
        try:
            if col(18): form_state = json.loads(col(18))
        except: pass

        record = {
            'session_id':    col(1),
            'phone':         phone,
            'business_name': col(4),
            'business_city': col(5),
            'business_type': col(6),
            'last_step_reached': col(13) or 'landing',
            'status':        col(14) or 'prospect',
            'form_state':    form_state,
        }
        try:
            if col(15): record['converted_at'] = col(15)
        except: pass

        try:
            sb.table('prospects').insert(record).execute()
            migrated += 1
        except Exception as e:
            print(f'  ERROR: {phone} — {e}')

    print(f'Prospects: {migrated} migrated, {skipped} skipped')
except Exception as e:
    print(f'Prospects tab error: {e}')

# ── MIGRATE POSTS LOG ─────────────────────────────────────────
print('\n[3] Migrating Posts_Log...')
try:
    ws   = ss.worksheet('Posts_Log')
    rows = ws.get_all_values()
    migrated = 0
    for row in rows[1:]:
        if not row[0] and not row[2]: continue
        def col(n): return row[n-1] if len(row) >= n else ''
        record = {
            'business_name': col(4),
            'pillar':        col(5),
            'fb_status':     col(6),
            'ig_status':     col(7),
            'gbp_status':    col(8) or 'N/A',
            'image_url':     col(9),
            'fb_post_id':    col(10),
            'ig_post_id':    col(11),
            'gbp_post_id':   col(12) if len(row) >= 12 else '',
        }
        client_id = col(3).strip()
        if client_id: record['client_id'] = client_id
        try:
            sb.table('posts_log').insert(record).execute()
            migrated += 1
        except Exception as e:
            print(f'  ERROR row: {e}')
    print(f'Posts_Log: {migrated} migrated')
except Exception as e:
    print(f'Posts_Log tab error: {e}')

# ── MIGRATE GBP CLIENTS ───────────────────────────────────────
print('\n[4] Migrating GBP_Clients...')
try:
    ws   = ss.worksheet('GBP_Clients')
    rows = ws.get_all_values()
    migrated = skipped = 0
    for row in rows[1:]:
        if not row[0]: continue
        def col(n): return row[n-1] if len(row) >= n else ''
        record = {
            'client_name':      col(1),
            'active':           col(2).upper() in ('TRUE','1','YES'),
            'gbp_enabled':      col(3).upper() in ('TRUE','1','YES'),
            'gbp_location_id':  col(4),
            'gbp_credential':   col(5),
            'business_type':    col(6),
            'business_location':col(7),
            'website_url':      col(8) if len(row) >= 8 else '',
            'reply_sign_off':   col(9) if len(row) >= 9 else '',
        }
        try:
            sb.table('gbp_clients').insert(record).execute()
            migrated += 1
        except Exception as e:
            print(f'  ERROR: {col(1)} — {e}')
    print(f'GBP_Clients: {migrated} migrated, {skipped} skipped')
except Exception as e:
    print(f'GBP_Clients tab error: {e}')

# ── MIGRATE PROVISIONING LOG ──────────────────────────────────
print('\n[5] Migrating Provisioning_Log...')
try:
    ws   = ss.worksheet('Provisioning_Log')
    rows = ws.get_all_values()
    migrated = 0
    for row in rows[1:]:
        if not row[0]: continue
        def col(n): return row[n-1] if len(row) >= n else ''
        record = {
            'client_id':    col(3),
            'business_name':col(4),
            'plan':         col(5),
            'platforms':    col(6),
            'workflow_id':  col(7),
            'status':       col(8),
            'error':        col(9) if len(row) >= 9 else '',
        }
        try:
            sb.table('provisioning_log').insert(record).execute()
            migrated += 1
        except Exception as e:
            print(f'  ERROR: {e}')
    print(f'Provisioning_Log: {migrated} migrated')
except Exception as e:
    print(f'Provisioning_Log tab error: {e}')

print('\n' + '='*50)
print('Migration complete!')

# Verify
total = sb.table('clients').select('count').execute()
print(f'Supabase clients: {total.data}')
