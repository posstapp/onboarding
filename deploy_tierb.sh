#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# posst.app — Tier B Security Deployment
# Patches the LIVE server posst_api.py with:
#   B-030: Global error handler (no stack traces to clients)
#   B-031: Request schema validation (8 critical endpoints)
#   B-032: Admin endpoint separation (23 internal endpoints)
# ═══════════════════════════════════════════════════════════════
set -e

echo "=== posst.app Tier B Security Deployment ==="
echo ""

# ── BACKUP ──────────────────────────────────────────────────
echo "[1/5] Creating backup..."
cp /opt/posst/posst_api.py /opt/posst/posst_api.py.bak_tierb_$(date +%Y%m%d_%H%M%S)
echo "  ✓ Backup created"

# ── B-032: Add ADMIN_SECRET config ──────────────────────────
echo "[2/5] B-032: Adding ADMIN_SECRET config..."
python3 << 'PYEOF'
with open('/opt/posst/posst_api.py', 'r') as f:
    content = f.read()

old = """API_SECRET       = os.environ.get('POSST_API_SECRET', '')
if not API_SECRET:
    raise RuntimeError('[SECURITY] POSST_API_SECRET env var is not set. Refusing to start with no API key.')"""

new = """API_SECRET       = os.environ.get('POSST_API_SECRET', '')
if not API_SECRET:
    raise RuntimeError('[SECURITY] POSST_API_SECRET env var is not set. Refusing to start with no API key.')

# B-032: Separate admin/internal secret. Falls back to API_SECRET if not set,
# so existing deployments continue working. Set POSST_ADMIN_SECRET to a different
# strong value to enforce separation between frontend-proxy and admin/n8n callers.
ADMIN_SECRET = os.environ.get('POSST_ADMIN_SECRET', '') or API_SECRET"""

if old in content:
    content = content.replace(old, new)
    with open('/opt/posst/posst_api.py', 'w') as f:
        f.write(content)
    print("  ✓ ADMIN_SECRET config added")
else:
    print("  ⚠ Config pattern not found (may already be applied)")
PYEOF

# ── B-032: Add require_admin decorator ──────────────────────
echo "[3/5] B-032: Adding require_admin decorator + swapping admin endpoints..."
python3 << 'PYEOF'
import re

with open('/opt/posst/posst_api.py', 'r') as f:
    content = f.read()

# Add require_admin after require_auth decorator
old_decorator = """def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # D1-3 Security: only accept API key from header, never from request body.
        # Body fallback allowed trivial auth bypass via JSON payload.
        auth = request.headers.get('X-API-Key', '')
        if auth != API_SECRET:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated"""

new_decorator = """def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # D1-3 Security: only accept API key from header, never from request body.
        # Body fallback allowed trivial auth bypass via JSON payload.
        auth = request.headers.get('X-API-Key', '')
        if auth != API_SECRET:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    \"\"\"B-032: Stricter auth for admin/internal endpoints (n8n, health checks, data access).
    Accepts POSST_ADMIN_SECRET. Falls back to API_SECRET if ADMIN_SECRET not configured,
    so deployment is non-breaking — but once set, frontend proxy key can't reach admin routes.\"\"\"
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('X-API-Key', '')
        if auth != ADMIN_SECRET:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated"""

if 'def require_admin' not in content:
    if old_decorator in content:
        content = content.replace(old_decorator, new_decorator)
        print("  ✓ require_admin decorator added")
    else:
        print("  ⚠ require_auth pattern not found")
else:
    print("  ⚠ require_admin already exists")

# Swap @require_auth -> @require_admin on admin-only routes
ADMIN_ROUTES = {
    '/api/clients/active', '/api/clients/token_received',
    '/api/style/select', '/api/posts_log', '/api/posts_log/update',
    '/api/posts_log/recent', '/api/notify_error', '/api/provisioning_log',
    '/api/gbp_clients', '/api/review_log', '/api/email/go_live',
    '/api/email/cancel', '/api/email/pause', '/api/prospects/eligible',
    '/api/prospects/mark_reengaged', '/api/email/alert',
    '/api/health_check/dedup', '/api/email/campaigns',
    '/api/email/reconnect_confirmation',
}

lines = content.split('\n')
swapped = 0
for i, line in enumerate(lines):
    route_match = re.search(r"@app\.route\('([^']+)'", line)
    if route_match:
        route = route_match.group(1)
        route_norm = re.sub(r'<[^>]+>', '<client_id>', route)
        if route_norm in ADMIN_ROUTES or route in ADMIN_ROUTES:
            if i + 1 < len(lines) and lines[i + 1].strip() == '@require_auth':
                lines[i + 1] = '@require_admin'
                swapped += 1
        # Also handle GET /api/client/<client_id> and PATCH status/token
        if route_norm in {'/api/client/<client_id>/status', '/api/client/<client_id>/token', '/api/client/<client_id>'}:
            if i + 1 < len(lines) and lines[i + 1].strip() == '@require_auth':
                # Only swap GET (get_client) and specific PATCHes
                method_match = re.search(r"methods=\['(GET|PATCH)'\]", line)
                if method_match:
                    method = method_match.group(1)
                    # get_client (GET), update_status (PATCH /status), update_token (PATCH /token)
                    if method == 'GET' and '/status' not in route and '/token' not in route:
                        lines[i + 1] = '@require_admin'
                        swapped += 1
                    elif route_norm in {'/api/client/<client_id>/status', '/api/client/<client_id>/token'}:
                        lines[i + 1] = '@require_admin'
                        swapped += 1

content = '\n'.join(lines)

with open('/opt/posst/posst_api.py', 'w') as f:
    f.write(content)

print(f"  ✓ Swapped {swapped} endpoints to @require_admin")
PYEOF

# ── B-031: Add validation framework + schemas ──────────────
echo "[4/5] B-031: Adding schema validation..."
python3 << 'PYEOF'
with open('/opt/posst/posst_api.py', 'r') as f:
    content = f.read()

# Add validation framework before CORS section
VALIDATION_CODE = '''
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
_SCHEMA_PORTAL_LOOKUP = {'phone': {'required': True, 'type': str, 'maxlen': 30}}
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

'''

marker = "# ── CORS ALLOWLIST (Form Security Hardening, Jul 5 2026)"
if '_validate(' not in content and marker in content:
    content = content.replace(marker, VALIDATION_CODE + marker)
    print("  ✓ Validation framework added")
else:
    if '_validate(' in content:
        print("  ⚠ Validation already present")
    else:
        print("  ⚠ CORS marker not found")

# Add validation calls to endpoints
VALIDATIONS = [
    # (function signature to find, validation line to add after 'd = request.json or {}')
    ('def create_client_record():', '_SCHEMA_CLIENT'),
    ('def create_prospect():', '_SCHEMA_PROSPECT'),
    ('def portal_lookup():', '_SCHEMA_PORTAL_LOOKUP'),
    ('def style_select():', '_SCHEMA_STYLE_SELECT'),
    ('def log_post():', '_SCHEMA_POSTS_LOG'),
    ('def otp_send():', '_SCHEMA_OTP'),
    ('def chat():', '_SCHEMA_CHAT'),
    ('def stripe_checkout():', '_SCHEMA_STRIPE_CHECKOUT'),
]

added = 0
for func_sig, schema_name in VALIDATIONS:
    # Find the function, then find 'd = request.json or {}' within the next 5 lines
    idx = content.find(func_sig)
    if idx == -1:
        continue
    # Find 'd = request.json or {}' after this function
    search_start = idx
    d_line = 'd = request.json or {}'
    d_idx = content.find(d_line, search_start)
    if d_idx == -1 or d_idx - idx > 500:
        continue
    # Check if validation already added
    next_chunk = content[d_idx:d_idx+200]
    if '_validate(' in next_chunk:
        continue
    # Insert validation after 'd = request.json or {}'
    insert_point = d_idx + len(d_line)
    validation_code = f"\n    # B-031: Schema validation\n    d, val_err = _validate(d, {schema_name})\n    if val_err:\n        return err(val_err)"
    content = content[:insert_point] + validation_code + content[insert_point:]
    added += 1

with open('/opt/posst/posst_api.py', 'w') as f:
    f.write(content)

print(f"  ✓ Added validation to {added} endpoints")
PYEOF

# ── B-030: Add global error handler ────────────────────────
echo "[5/5] B-030: Adding global error handler..."
python3 << 'PYEOF'
with open('/opt/posst/posst_api.py', 'r') as f:
    content = f.read()

ERROR_HANDLER = '''
# ── B-030: GLOBAL ERROR HANDLER (Tier B Security) ────────────
# Catches all unhandled exceptions. Logs full traceback server-side,
# returns generic message to caller — no stack traces, paths, or
# library versions ever leak to the client.
import traceback as _tb

@app.errorhandler(Exception)
def handle_exception(e):
    log.error(f'Unhandled exception on {request.method} {request.path}: '
              f'{type(e).__name__}: {e}\\n{_tb.format_exc()}')
    return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

@app.errorhandler(404)
def handle_404(e):
    return jsonify({'status': 'error', 'message': 'Not found'}), 404

@app.errorhandler(405)
def handle_405(e):
    return jsonify({'status': 'error', 'message': 'Method not allowed'}), 405

'''

marker = "if __name__ == '__main__':"
if '@app.errorhandler(Exception)' not in content and marker in content:
    content = content.replace(marker, ERROR_HANDLER + marker)
    print("  ✓ Global error handler added")
else:
    if '@app.errorhandler' in content:
        print("  ⚠ Error handler already present")
    else:
        print("  ⚠ Main marker not found")

with open('/opt/posst/posst_api.py', 'w') as f:
    f.write(content)
PYEOF

# ── VERIFY ──────────────────────────────────────────────────
echo ""
echo "=== Verification ==="
python3 -c "import ast; ast.parse(open('/opt/posst/posst_api.py').read()); print('  ✓ Syntax OK')"
echo "  require_auth:  $(grep -c '@require_auth' /opt/posst/posst_api.py)"
echo "  require_admin: $(grep -c '@require_admin' /opt/posst/posst_api.py)"
echo "  _validate:     $(grep -c '_validate(' /opt/posst/posst_api.py)"
echo "  errorhandler:  $(grep -c '@app.errorhandler' /opt/posst/posst_api.py)"
echo ""

# ── RESTART ─────────────────────────────────────────────────
echo "Restarting posst-api..."
sudo systemctl restart posst-api
sleep 2
echo "  posst-api: $(systemctl is-active posst-api)"

echo ""
echo "=== DEPLOYMENT COMPLETE ==="
echo ""
echo "Verify:"
echo "  # Auth rejection (401):"
echo "  curl -s -o /dev/null -w 'HTTP:%{http_code}' http://127.0.0.1:5680/api/clients/active"
echo ""
echo "  # Auth with key (200):"
echo "  curl -s -o /dev/null -w 'HTTP:%{http_code}' http://127.0.0.1:5680/api/clients/active -H 'X-API-Key: posst-api-secret-2026'"
echo ""
echo "  # Error handler (generic 404, no stack trace):"
echo "  curl -s http://127.0.0.1:5680/api/nonexistent"
echo ""
echo "  # Validation (400 on missing required field):"
echo "  curl -s -X POST http://127.0.0.1:5680/api/style/select -H 'Content-Type: application/json' -H 'X-API-Key: posst-api-secret-2026' -d '{}'"
