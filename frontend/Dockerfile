# syntax=docker/dockerfile:1

# Builds both web apps and serves them from nginx, proxying /api to the
# backend so the browser sees a single origin.

FROM node:lts-slim AS build

WORKDIR /build

# Workspace manifests first, so the install layer survives source changes.
COPY package.json package-lock.json* ./
COPY apps ./apps
COPY packages ./packages

RUN npm install --no-audit --no-fund

COPY . .
RUN npm run build


FROM nginx:alpine

COPY --from=build /build/apps/deployment/dist /usr/share/nginx/html/deployment
COPY --from=build /build/apps/containers/dist /usr/share/nginx/html/containers
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80