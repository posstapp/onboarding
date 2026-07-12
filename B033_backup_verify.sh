#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# B-033: Supabase Backup Verification
# Verifies database connectivity and table integrity monthly.
# Cron: 0 10 1 * *  (1st of month, 10am UTC)
# ═══════════════════════════════════════════════════════════════
set -e

LOG="/var/log/posst-backup-verify.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S UTC')
PASS=0
FAIL=0

echo "=== posst.app Backup Verification — $TIMESTAMP ===" >> "$LOG"

# Load env
source /opt/posst/oauth/.env 2>/dev/null || true
for line in $(grep -v '^#' /etc/environment 2>/dev/null); do
  export "$line" 2>/dev/null || true
done

SUPABASE_URL="${SUPABASE_URL:-}"
SUPABASE_KEY="${SUPABASE_SERVICE_KEY:-}"

if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ]; then
  echo "FAIL: Missing SUPABASE_URL or SUPABASE_SERVICE_KEY" >> "$LOG"
  exit 1
fi

check_table() {
  TABLE=$1
  MIN_ROWS=$2
  RESULT=$(curl -s -w "\n%{http_code}" \
    -H "apikey: $SUPABASE_KEY" \
    -H "Authorization: Bearer $SUPABASE_KEY" \
    -H "Prefer: count=exact" \
    -H "Range: 0-0" \
    "$SUPABASE_URL/rest/v1/$TABLE?select=id")
  
  HTTP_CODE=$(echo "$RESULT" | tail -1)
  
  if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "206" ]; then
    # Extract count from content-range header
    COUNT=$(curl -s -D - \
      -H "apikey: $SUPABASE_KEY" \
      -H "Authorization: Bearer $SUPABASE_KEY" \
      -H "Prefer: count=exact" \
      -H "Range: 0-0" \
      "$SUPABASE_URL/rest/v1/$TABLE?select=id" 2>/dev/null | grep -i "content-range" | sed 's/.*\///' | tr -d '\r')
    
    if [ -n "$COUNT" ] && [ "$COUNT" -ge "$MIN_ROWS" ] 2>/dev/null; then
      echo "  ✓ $TABLE: $COUNT rows (min: $MIN_ROWS)" >> "$LOG"
      PASS=$((PASS + 1))
    else
      echo "  ✗ $TABLE: ${COUNT:-unknown} rows (expected min: $MIN_ROWS)" >> "$LOG"
      FAIL=$((FAIL + 1))
    fi
  else
    echo "  ✗ $TABLE: HTTP $HTTP_CODE" >> "$LOG"
    FAIL=$((FAIL + 1))
  fi
}

# Core tables with minimum expected row counts
check_table "clients" 2
check_table "prospects" 1
check_table "posts_log" 10
check_table "prompt_style_library" 12
check_table "style_routing_map" 55
check_table "email_campaign_log" 1
check_table "provisioning_log" 1
check_table "audit_log" 1

echo "  --- Result: $PASS passed, $FAIL failed ---" >> "$LOG"
echo "" >> "$LOG"

if [ "$FAIL" -gt 0 ]; then
  # Send alert via posst-api
  curl -s -X POST http://127.0.0.1:5680/api/email/alert \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $(grep POSST_API_SECRET /proc/$(pgrep -f 'gunicorn.*posst_api' | head -1)/environ | tr '\0' '\n' | grep POSST_API_SECRET | cut -d= -f2)" \
    -d "{\"title\": \"Backup Verification FAILED\", \"message\": \"$FAIL table(s) failed verification. Check $LOG\", \"level\": \"alert\"}" \
    > /dev/null 2>&1
  exit 1
fi

exit 0
