FROM node:20-alpine AS builder
WORKDIR /app

# Copy manifests first for layer caching
COPY package*.json ./
RUN npm install

COPY tsconfig.json ./
COPY app ./app

RUN npm run build

# ─── Runtime stage ────────────────────────────────────────────────────────────
FROM node:20-alpine AS runtime
WORKDIR /app

# Non-root user for security
RUN addgroup -S pmos && adduser -S gateway -G pmos

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY package*.json ./

RUN chown -R gateway:pmos /app
USER gateway

EXPOSE 4000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD wget -qO- http://localhost:4000/health || exit 1

CMD ["node", "dist/app/main.js"]
