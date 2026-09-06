FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev --ignore-scripts || npm install --omit=dev --ignore-scripts

FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts || npm install --ignore-scripts
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
# Next.js standalone binds to $HOSTNAME, which Docker sets to the container id.
# That resolves to the container's own IP, so the server listens there and NOT on
# loopback -- proxying works but every localhost healthcheck fails. Bind all
# interfaces explicitly.
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -g 10002 -S tbx && adduser -u 10002 -S tbx -G tbx

# `output: standalone` emits a self-contained server with only the runtime deps.
COPY --from=builder --chown=tbx:tbx /app/.next/standalone ./
COPY --from=builder --chown=tbx:tbx /app/.next/static ./.next/static

USER tbx
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
