# --- build: compile the Vite/React app to static assets --------------------
FROM node:20-slim AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite has no runtime env — every VITE_* var is baked into the static
# bundle at build time (see vite.config.ts / src/lib/api.ts), so it has to
# arrive as a build ARG, not a container-run-time environment variable.
# Pass it at build time: `docker build --build-arg VITE_API_URL=https://api.example.com`.
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
# Never bake the dev-login panel into a production bundle — the real gate
# is server-side (backend DEV_LOGIN_ENABLED), but there's no reason to
# even show the button. See .env.example's own note on this being cosmetic.
ENV VITE_DEV_LOGIN_ENABLED=false

RUN npm run build

# --- serve: static files behind nginx, SPA fallback routing ---------------
FROM nginx:1.29-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O- http://localhost/health || exit 1
