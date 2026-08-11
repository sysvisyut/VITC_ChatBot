# syntax=docker/dockerfile:1

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: builder — compile the React + Vite app
# ─────────────────────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Copy manifests first for better layer caching
COPY package.json package-lock.json ./

# Install deps (ci = clean install, exact from lock file)
RUN npm ci

# Copy source and build
COPY . .

# VITE_API_URL must point to /api (nginx proxy path) in Docker
# This ensures the frontend talks to nginx, which proxies to backend
ARG VITE_API_URL=/api
ARG VITE_API_KEY=dev_key_123
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_API_KEY=${VITE_API_KEY}

RUN npm run build

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: serve — tiny nginx image, only static assets
# ─────────────────────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Remove the default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy our config
COPY nginx.conf /etc/nginx/conf.d/app.conf

# Copy compiled static assets from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# nginx runs as root to bind port 80, but serves files as www-data (nginx default)
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
