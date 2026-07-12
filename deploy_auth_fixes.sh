#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# posst.app — Deploy Endpoint Auth Fixes
# Run on server: bash deploy_auth_fixes.sh
# 
# Patches the LIVE server files (which already have audit logging)
# with 3 security fixes:
#   1. @require_auth on 44 unprotected endpoints (posst_api.py)
#   2. Stripe webhook fail-closed instead of fail-open (posst_api.py)
#   3. CRLF header injection protection (posst_email.py)
# ═══════════════════════════════════════════════════════════════
set -e

echo "=== posst.app Endpoint Auth Fix Deployment ==="
echo ""

# ── BACKUP ──────────────────────────────────────────────────
echo "[1/6] Creating backups..."
cp /opt/posst/posst_api.py /opt/posst/posst_api.py.bak_$(date +%Y%m%d_%H%M%S)
cp /opt/posst/posst_email.py /opt/posst/posst_email.py.bak_$(date +%Y%m%d_%H%M%S)
echo "  ✓ Backups created"

# ── FIX 1: Add @require_auth to all unprotected endpoints ──
echo "[2/6] Adding @require_auth to unprotected endpoints..."

python3 << 'PYEOF'
import re

with open('/opt/posst/posst_api.py', 'r') as f:
    lines = f.readlines()

# Only these routes should NOT get @require_auth
SKIP_ROUTES = {'/health', '/api/stripe/webhook'}

new_lines = []
added = 0
i = 0

while i < len(lines):
    line = lines[i]
    route_match = re.search(r"@app\.route\('([^']+)'", line)
    
    if route_match:
        route_path = route_match.group(1)
        
        if route_path in SKIP_ROUTES:
            new_lines.append(line)
            i += 1
            continue
        
        # Check if next line already has @require_auth
        if i + 1 < len(lines) and '@require_auth' in lines[i + 1]:
            new_lines.append(line)
            i += 1
            continue
        
        new_lines.append(line)
        new_lines.append('@require_auth\n')
        added += 1
        i += 1
        continue
    
    new_lines.append(line)
    i += 1

with open('/opt/posst/posst_api.py', 'w') as f:
    f.writelines(new_lines)

print(f"  ✓ Added @require_auth to {added} endpoints")
PYEOF

# ── FIX 2: Stripe webhook fail-closed ──────────────────────
echo "[3/6] Fixing Stripe webhook fail-open..."
python3 << 'PYEOF'
with open('/opt/posst/posst_api.py', 'r') as f:
    content = f.read()

old = """    if not STRIPE_WEBHOOK_SECRET:
        return jsonify({'status': 'ok'})"""

new = """    if not STRIPE_WEBHOOK_SECRET:
        log.error('STRIPE_WEBHOOK_SECRET not configured — rejecting webhook')
        return jsonify({'error': 'Webhook not configured'}), 500"""

if old in content:
    content = content.replace(old, new)
    with open('/opt/posst/posst_api.py', 'w') as f:
        f.write(content)
    print("  ✓ Stripe webhook now fails closed")
else:
    print("  ⚠ Stripe webhook pattern not found (may already be fixed)")
PYEOF

# ── FIX 3: CRLF header injection protection ────────────────
echo "[4/6] Adding CRLF protection to posst_email.py..."
python3 << 'PYEOF'
with open('/opt/posst/posst_email.py', 'r') as f:
    content = f.read()

old = """def send_email(to, subject, html_body, reply_to=None):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f'{FROM_NAME} <{GMAIL_USER}>'
        msg['To']      = to
        msg['Reply-To'] = reply_to or GMAIL_USER"""

new = """def _sanitize_header(value):
    \"\"\"Strip CRLF from email header values to prevent header injection.\"\"\"
    if not isinstance(value, str):
        return value
    return value.replace('\\r', '').replace('\\n', '')

def send_email(to, subject, html_body, reply_to=None):
    try:
        # Sanitize all header fields to prevent CRLF injection
        to      = _sanitize_header(to)
        subject = _sanitize_header(subject)
        reply_to = _sanitize_header(reply_to) if reply_to else None

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f'{FROM_NAME} <{GMAIL_USER}>'
        msg['To']      = to
        msg['Reply-To'] = reply_to or GMAIL_USER"""

if old in content:
    content = content.replace(old, new)
    with open('/opt/posst/posst_email.py', 'w') as f:
        f.write(content)
    print("  ✓ CRLF protection added to send_email()")
else:
    print("  ⚠ send_email pattern not found (may already be fixed)")
PYEOF

# ── VERIFY ──────────────────────────────────────────────────
echo "[5/6] Verifying..."
echo ""

# Syntax check
python3 -c "import ast; ast.parse(open('/opt/posst/posst_api.py').read()); print('  ✓ posst_api.py syntax OK')"
python3 -c "import ast; ast.parse(open('/opt/posst/posst_email.py').read()); print('  ✓ posst_email.py syntax OK')"

# Count auth decorators
AUTH_COUNT=$(grep -c '@require_auth' /opt/posst/posst_api.py)
echo "  ✓ @require_auth count: $AUTH_COUNT"

# Check only correct routes are unprotected
echo "  Routes WITHOUT @require_auth:"
grep -n -A1 "@app\.route" /opt/posst/posst_api.py | grep "@app\." | while read line; do
  linenum=$(echo "$line" | cut -d: -f1)
  route=$(echo "$line" | sed "s/.*@app\.route('\([^']*\)'.*/\1/")
  next=$((linenum + 1))
  has_auth=$(sed -n "${next}p" /opt/posst/posst_api.py | grep -c "require_auth")
  if [ "$has_auth" -eq 0 ]; then
    echo "    $route"
  fi
done

# Check CRLF protection
CRLF_COUNT=$(grep -c '_sanitize_header' /opt/posst/posst_email.py)
echo "  ✓ _sanitize_header references: $CRLF_COUNT"

echo ""

# ── RESTART SERVICES ────────────────────────────────────────
echo "[6/6] Restarting services..."
sudo systemctl restart posst-api
sleep 2
sudo systemctl restart posst-email 2>/dev/null || true

# Verify services are running
API_STATUS=$(systemctl is-active posst-api)
echo "  posst-api: $API_STATUS"

echo ""
echo "=== DEPLOYMENT COMPLETE ==="
echo ""
echo "Post-deploy verification commands:"
echo "  # Test auth rejection (should return 401):"
echo "  curl -s http://127.0.0.1:5680/api/clients/active -w '\nHTTP:%{http_code}'"
echo ""
echo "  # Test auth acceptance (should return 200):"
echo "  curl -s http://127.0.0.1:5680/api/clients/active -H 'X-API-Key: '\$(grep POSST_API_SECRET /etc/environment | cut -d= -f2) -w '\nHTTP:%{http_code}'"
echo ""
echo "  # Test health (should return 200, no auth needed):"
echo "  curl -s http://127.0.0.1:5680/health -w '\nHTTP:%{http_code}'"
echo ""
echo "  # Check logs for errors:"
echo "  sudo journalctl -u posst-api -n 20 --no-pager"
