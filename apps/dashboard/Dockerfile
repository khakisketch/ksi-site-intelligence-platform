FROM node:22.18-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22.18-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22.18-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
RUN addgroup --system --gid 10001 ksi-dashboard \
    && adduser --system --uid 10001 --ingroup ksi-dashboard ksi-dashboard
COPY --from=builder --chown=ksi-dashboard:ksi-dashboard /app/public ./public
COPY --from=builder --chown=ksi-dashboard:ksi-dashboard /app/.next/standalone ./
COPY --from=builder --chown=ksi-dashboard:ksi-dashboard /app/.next/static ./.next/static
COPY --chown=ksi-dashboard:ksi-dashboard scripts/start-production.mjs ./scripts/start-production.mjs
USER ksi-dashboard
EXPOSE 3000
CMD ["node", "scripts/start-production.mjs"]
