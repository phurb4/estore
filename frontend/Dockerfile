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
#     -p 127.0.0.1:8080:8080 estore-frontend:0.1.0
FROM nginxinc/nginx-unprivileged:1.31.7-alpine

# Only these three variables are substituted in templates (addresses, not
# secrets): the public API path and the internal service addresses.
ENV NGINX_ENVSUBST_FILTER=^(API_BASE_URL|PRODUCTS_UPSTREAM|ORDERS_UPSTREAM)$

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
# Runs as the image's non-root user (nginx, uid 101).
