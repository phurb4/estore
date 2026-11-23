# Frontend image: static site served by unprivileged Nginx on port 8080.
# Build context: frontend/
#
# Test run (read-only FS, no capabilities, no privilege escalation).
# conf.d is tmpfs because the template step writes the rendered config there:
#   docker run --rm -d --name estore-fe `
#     --read-only --cap-drop ALL --security-opt no-new-privileges `
#     --tmpfs /tmp --tmpfs /etc/nginx/conf.d:uid=101,gid=101,mode=0755 `
#     -e API_BASE_URL=$env:API_BASE_URL `
#     -e PRODUCTS_UPSTREAM=$env:PRODUCTS_UPSTREAM `
#     -e ORDERS_UPSTREAM=$env:ORDERS_UPSTREAM `
#     -e COGNITO_UPSTREAM=$env:COGNITO_UPSTREAM `
#     -e COGNITO_USER_POOL_ID=$env:COGNITO_USER_POOL_ID `
#     -e COGNITO_CLIENT_ID=$env:COGNITO_CLIENT_ID `
#     -e COGNITO_ENDPOINT=$env:COGNITO_ENDPOINT `
#     -p 127.0.0.1:8080:8080 estore-frontend:0.1.0
FROM nginxinc/nginx-unprivileged:1.31.7-alpine

# Security fixes: upgrade only the Alpine packages that carry HIGH/CRITICAL
# vulnerabilities with a fix available. Needs root; the final USER 101 below
# brings the container back to non-root.
# nosemgrep: dockerfile.security.last-user-is-root.last-user-is-root -- root only for apk; the last USER (101) is non-root
USER root
RUN apk add --no-cache --upgrade brotli-libs curl libcurl libexpat libxml2 libxslt musl musl-utils zlib

# Only these variables are substituted in templates (addresses, not secrets):
# the public API path and the internal service addresses.
ENV NGINX_ENVSUBST_FILTER=^(API_BASE_URL|PRODUCTS_UPSTREAM|ORDERS_UPSTREAM|COGNITO_UPSTREAM|COGNITO_USER_POOL_ID|COGNITO_CLIENT_ID|COGNITO_ENDPOINT)$

# Site files (explicit list: nothing else from the context enters the image).
COPY --chown=root:root *.html LICENSE.txt /usr/share/nginx/html/
COPY --chown=root:root css/ /usr/share/nginx/html/css/
COPY --chown=root:root img/ /usr/share/nginx/html/img/
COPY --chown=root:root js/ /usr/share/nginx/html/js/
COPY --chown=root:root lib/ /usr/share/nginx/html/lib/

# Templates rendered at start into /etc/nginx/conf.d:
#   default.conf.template -> conf.d/default.conf
#   config.js.template    -> conf.d/config.js (served at /config.js)
COPY --chown=root:root nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --chown=root:root config.js /etc/nginx/templates/config.js.template

EXPOSE 8080
# Explicit non-root user (nginx, uid 101): the base image already uses it, but
# stating it here lets image scanners (Trivy DS-0002) see it.
USER 101
