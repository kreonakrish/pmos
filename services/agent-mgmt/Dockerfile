FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY package*.json ./
EXPOSE 4001
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD wget -qO- http://localhost:4001/health || exit 1
CMD ["node", "dist/app/main.js"]
