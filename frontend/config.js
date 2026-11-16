/*
 * Runtime configuration. This file is a template: the container start-up
 * step (Nginx envsubst, restricted to the variables named below) replaces
 * each placeholder with the value of the environment variable of the same
 * name. Never hard-code an address or an ID here.
 * Must be public values only: no credentials, tokens or secrets.
 * The Cognito pool and client IDs are public identifiers (the client has no
 * secret). COGNITO_ENDPOINT is a same-origin path for the emulator and empty
 * for real AWS, where the library uses the official Cognito endpoint.
 */
window.APP_CONFIG = Object.freeze({
    API_BASE_URL: "${API_BASE_URL}",
    COGNITO_USER_POOL_ID: "${COGNITO_USER_POOL_ID}",
    COGNITO_CLIENT_ID: "${COGNITO_CLIENT_ID}",
    COGNITO_ENDPOINT: "${COGNITO_ENDPOINT}"
});
