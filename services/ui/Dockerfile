# UI build stage
#
# IMPORTANT: This Dockerfile expects the *build context* to be a directory that
# contains BOTH:
#   - midena/
#   - mosp-design-system/
# (i.e. siblings).
#
# Example:
#   /workspace/
#     midena/
#     mosp-design-system/
#
# Build with:
#   docker build -f midena/services/ui/Dockerfile -t midena-ui /workspace

FROM node:20-alpine AS ui-assets
WORKDIR /ui

COPY midena/services/ui/package.json midena/services/ui/package-lock.json* ./
COPY midena/services/ui/scripts ./scripts
RUN npm install

# Inject MOSP design system (local codebase, no npm registry)
COPY mosp-design-system/ /tmp/mosp-design-system/
RUN (cd /tmp/mosp-design-system && node scripts/build.mjs) \
 && mkdir -p /ui/node_modules/@FERCBusters \
 && rm -rf /ui/node_modules/@FERCBusters/mosp-design-system \
 && cp -a /tmp/mosp-design-system /ui/node_modules/@FERCBusters/mosp-design-system \
 && rm -rf /ui/node_modules/@FERCBusters/mosp-design-system/node_modules

COPY midena/services/ui/public ./public
RUN npm run vendor-assets

FROM nginx:1.30.4-alpine

COPY midena/services/ui/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY midena/services/ui/public /usr/share/nginx/html
COPY --from=ui-assets /ui/public/vendor /usr/share/nginx/html/vendor
