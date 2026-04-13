# =============================================================================
# PMOS Client — Production multi-stage build
# Stage 1: build the React app with Vite
# Stage 2: serve with nginx; runtime config injected via /config.js
# =============================================================================

FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
RUN apk add --no-cache bash
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.d/40-pmos-runtime-config.sh
RUN chmod +x /docker-entrypoint.d/40-pmos-runtime-config.sh
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -q -O - http://localhost/healthz || exit 1
