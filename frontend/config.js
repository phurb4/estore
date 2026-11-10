/*
 * Runtime configuration. This file is a template: the container start-up
 * step (Nginx envsubst, restricted to the single variable named below)
 * replaces the placeholder with the real value of the API_BASE_URL
 * environment variable. Never hard-code an address here.
 * Must be a public URL only: no credentials, tokens or secrets.
 */
window.APP_CONFIG = Object.freeze({
    API_BASE_URL: "${API_BASE_URL}"
});
