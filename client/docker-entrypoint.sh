#!/bin/bash
# =============================================================================
# PMOS Client — runtime config injector
#
# Templates /usr/share/nginx/html/config.js from environment variables at
# container start, so the same image can be deployed to any environment
# without rebuilding. The browser loads /config.js before main.tsx and reads
# values from window.__PMOS_CONFIG__.
#
# Env vars consumed (all optional; empty means "use same-origin"):
#   PMOS_API_BASE_URL   absolute URL of the gateway, e.g. https://api.example.com
#                       Empty → relative URLs (nginx proxies /v1 → gateway)
#   PMOS_WS_BASE_URL    absolute ws(s):// URL for the gateway WS endpoint
#                       Empty → derived from window.location at runtime
#   PMOS_ENV            free-form environment label (dev / staging / prod)
# =============================================================================
set -eu

CONFIG_FILE="/usr/share/nginx/html/config.js"

cat > "$CONFIG_FILE" <<EOF
// Generated at container start by docker-entrypoint.sh — do not edit.
window.__PMOS_CONFIG__ = {
  apiBaseUrl: "${PMOS_API_BASE_URL:-}",
  wsBaseUrl:  "${PMOS_WS_BASE_URL:-}",
  env:        "${PMOS_ENV:-production}"
};
EOF

echo "[pmos-client] runtime config written to $CONFIG_FILE (env=${PMOS_ENV:-production})"
