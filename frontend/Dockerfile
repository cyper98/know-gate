# syntax=docker/dockerfile:1.7
# Multi-stage Dockerfile for KnowGate Next.js frontend

# === Stage 1: deps ===
FROM node:20-alpine AS deps

WORKDIR /app

# Copy dependency files
COPY package.json ./
# Use npm install for compatibility (pnpm optional)
RUN npm install --no-audit --no-fund

# === Stage 2: builder ===
FROM node:20-alpine AS builder

WORKDIR /app

# Copy deps
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Disable telemetry
ENV NEXT_TELEMETRY_DISABLED=1

# Build (standalone output)
RUN npm run build

# === Stage 3: runner ===
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root user
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 --ingroup nodejs nextjs

# Copy built artifacts (standalone includes node_modules)
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1

CMD ["node", "server.js"]
