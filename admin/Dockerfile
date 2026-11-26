# Builds the admin dashboard's static files (decision D.6), and nothing else: the
# final stage is the files themselves. deploy/vps/deploy.sh runs it on the VPS for
# the commit being deployed, the same commit CI has tested and built:
#
#   docker build -f admin/Dockerfile --build-arg VITE_API_BASE_URL=https://... \
#     --output type=local,dest=/srv/myradius-admin/releases/<sha> admin
#
# Pinned, like everything here, so a new Node release can't change a build silently.
FROM node:24.22.3-alpine AS build
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG VITE_API_BASE_URL
ARG VITE_IDLE_TIMEOUT_MINUTES=15
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} VITE_IDLE_TIMEOUT_MINUTES=${VITE_IDLE_TIMEOUT_MINUTES}
RUN test -n "$VITE_API_BASE_URL" && npm run build

FROM scratch
COPY --from=build /app/dist /
