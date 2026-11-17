/*
 * Customer sign-in against Amazon Cognito (USER_SRP_AUTH, in the browser).
 * Loaded on every page, after config.js and the Cognito library.
 *
 * Library (vendored, served from this origin, not from a CDN):
 *   lib/amazon-cognito-identity/amazon-cognito-identity.min.js
 *   amazon-cognito-identity-js 6.3.22, Apache-2.0
 *   SHA256 32811F694592E437391FE040D836A474D75F54108CFA5123D67E8A4D30283901
 * Update the version and this hash together when the library is upgraded.
 *
 * Security rules for this file:
 *  - Pool ID, client ID and endpoint come only from window.APP_CONFIG
 *    (config.js). Each value is validated before use; nothing is hard-coded.
 *  - Text shown to the user is only ever written with textContent.
 *  - Tokens: the ID and access tokens live in sessionStorage (never
 *    localStorage). The refresh token is never written anywhere, so a session
 *    lasts as long as the access token (60 minutes) and then asks to sign in.
 *  - The password is passed straight to the library and dropped. It is never
 *    kept in a field of this module or logged.
 *  - Every sign-in failure is reported with the same generic message.
 *  - Emails are lower-cased before every call (the pool is case sensitive).
 *  - Sign-up and resend never reveal whether an email already has an account.
 */
(function () {
    "use strict";

    var POOL_RE = /^[a-z]{2}(?:-[a-z]+)+-[0-9]_[A-Za-z0-9]{1,64}$/;
    var CLIENT_RE = /^[A-Za-z0-9]{1,128}$/;
    var PATH_RE = /^\/[A-Za-z0-9._~\/-]{0,100}$/;
    var EMAIL_RE = /^[A-Za-z0-9._%+-]{1,64}@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$/;
    var CODE_RE = /^[0-9]{6}$/;
    var MAX_EMAIL = 254;
    var MAX_PASSWORD = 256;
    // Sign-up password policy. Convenience check only: Cognito enforces the
    // real policy. Keep PASSWORD_MIN equal to local.password_minimum_length in
    // terraform/cognito.tf (and the character rules to its password_policy).
    var PASSWORD_MIN = 12;
    var LOWER_RE = /[a-z]/;
    var UPPER_RE = /[A-Z]/;
    var DIGIT_RE = /[0-9]/;
    var SYMBOL_RE = /[\^$*.\[\]{}()?"!@#%&\/\\,><':;|_~`=+\-]/;
    var KEY_PREFIX = "CognitoIdentityServiceProvider.";

    var lib = window.AmazonCognitoIdentity;
    var listeners = [];
    var pendingUser = null;   // user waiting for the TOTP code, never stored

    // ---------- Config ----------
    function readEndpoint(raw) {
        if (raw === undefined || raw === null) return null;
        if (typeof raw !== "string") return false;
        raw = raw.trim();
        if (raw === "") return null;                       // use the official endpoint
        if (raw.indexOf("${") !== -1) return false;        // placeholder not substituted
        if (raw.charAt(0) === "/") return PATH_RE.test(raw) && raw.indexOf("//") === -1 ? raw : false;
        var u;
        try {
            u = new URL(raw);
        } catch (e) {
            return false;
        }
        if (u.protocol !== "https:" || u.username || u.password || u.search || u.hash) return false;
        return u.href;
    }

    function readConfig(cfg) {
        var pool = cfg.COGNITO_USER_POOL_ID;
        var client = cfg.COGNITO_CLIENT_ID;
        if (typeof pool !== "string" || !POOL_RE.test(pool)) return null;
        if (typeof client !== "string" || !CLIENT_RE.test(client)) return null;
        var endpoint = readEndpoint(cfg.COGNITO_ENDPOINT);
        if (endpoint === false) return null;
        return { poolId: pool, clientId: client, endpoint: endpoint };
    }

    // ---------- Storage (sessionStorage, never the refresh token) ----------
    function makeStorage() {
        var mem = {};
        var ss = null;
        try {
            ss = window.sessionStorage;
            ss.setItem("estore.probe", "1");
            ss.removeItem("estore.probe");
        } catch (e) {
            ss = null;
        }
        function isRefresh(key) {
            return /\.refreshToken$/.test(String(key));
        }
        function owned(key) {
            return String(key).indexOf(KEY_PREFIX) === 0;
        }
        return {
            setItem: function (key, value) {
                if (isRefresh(key)) return;
                key = String(key);
                value = String(value);
                if (ss) {
                    try { ss.setItem(key, value); return; } catch (e) { /* fall back to memory */ }
                }
                mem[key] = value;
            },
            getItem: function (key) {
                if (isRefresh(key)) return null;
                key = String(key);
                if (ss) {
                    try {
                        var v = ss.getItem(key);
                        if (v !== null) return v;
                    } catch (e) { /* fall back to memory */ }
                }
                return Object.prototype.hasOwnProperty.call(mem, key) ? mem[key] : null;
            },
            removeItem: function (key) {
                key = String(key);
                if (ss) { try { ss.removeItem(key); } catch (e) { /* ignore */ } }
                delete mem[key];
            },
            // Removes only this library's keys, never other data of the page.
            clear: function () {
                var k, i, keys = [];
                if (ss) {
                    try {
                        for (i = 0; i < ss.length; i++) keys.push(ss.key(i));
                        keys.forEach(function (key) { if (owned(key)) ss.removeItem(key); });
                    } catch (e) { /* ignore */ }
                }
                for (k in mem) {
                    if (Object.prototype.hasOwnProperty.call(mem, k) && owned(k)) delete mem[k];
                }
            }
        };
    }

    var CONFIG = lib ? readConfig(window.APP_CONFIG || {}) : null;
    var storage = makeStorage();
    var pool = null;
    if (CONFIG) {
        var poolData = {
            UserPoolId: CONFIG.poolId,
            ClientId: CONFIG.clientId,
            Storage: storage,
            AdvancedSecurityDataCollectionFlag: false
        };
        if (CONFIG.endpoint) poolData.endpoint = CONFIG.endpoint;
        pool = new lib.CognitoUserPool(poolData);
    }

    // ---------- Helpers ----------
    function notify() {
        listeners.forEach(function (fn) { try { fn(); } catch (e) { /* ignore */ } });
    }

    function validEmail(value) {
        return typeof value === "string" && value.length <= MAX_EMAIL && EMAIL_RE.test(value);
    }

    function validCode(value) {
        return typeof value === "string" && CODE_RE.test(value);
    }

    // The pool is case sensitive, so every email is sent in lower case. This
    // keeps "A@x.com" and "a@x.com" as one account for everything done here.
    function normalizeEmail(value) {
        return typeof value === "string" ? value.trim().toLowerCase() : "";
    }

    function validPassword(value) {
        return typeof value === "string" && value.length >= PASSWORD_MIN &&
            value.length <= MAX_PASSWORD && LOWER_RE.test(value) && UPPER_RE.test(value) &&
            DIGIT_RE.test(value) && SYMBOL_RE.test(value);
    }

    // Calls back with the signed-in email, or null when there is no valid session.
    function currentEmail(callback) {
        if (!pool) return callback(null);
        var user = pool.getCurrentUser();
        if (!user) return callback(null);
        user.getSession(function (err, session) {
            if (err || !session || !session.isValid()) {
                storage.clear();
                return callback(null);
            }
            var claims = session.getIdToken().decodePayload() || {};
            callback(validEmail(claims.email) ? claims.email : "");
        });
    }

    function failWith(handlers) {
        pendingUser = null;
        if (handlers && typeof handlers.onFail === "function") handlers.onFail();
    }

    // ---------- Sign in ----------
    // The password parameter goes straight into the library and is dropped.
    function login(email, password, handlers) {
        email = normalizeEmail(email);
        if (!pool || !validEmail(email) || typeof password !== "string" ||
            password.length < 1 || password.length > MAX_PASSWORD) {
            password = null;
            return failWith(handlers);
        }
        var user = new lib.CognitoUser({ Username: email, Pool: pool, Storage: storage });
        var details = new lib.AuthenticationDetails({ Username: email, Password: password });
        password = null;
        function done(fn) {
            return function () {
                details.password = null;
                fn();
            };
        }
        var fail = done(function () { failWith(handlers); });
        user.authenticateUser(details, {
            onSuccess: done(function () {
                pendingUser = null;
                notify();
                if (handlers && typeof handlers.onSuccess === "function") handlers.onSuccess();
            }),
            onFailure: fail,
            totpRequired: done(function () {
                pendingUser = user;
                if (handlers && typeof handlers.onTotp === "function") handlers.onTotp();
            }),
            // Challenges the store does not offer: treated as a failed sign-in.
            mfaRequired: fail,
            mfaSetup: fail,
            selectMFAType: fail,
            newPasswordRequired: fail,
            customChallenge: fail
        });
    }

    function submitTotp(code, handlers) {
        var user = pendingUser;
        if (!user || !validCode(code)) return failWith(handlers);
        user.sendMFACode(code, {
            onSuccess: function () {
                pendingUser = null;
                notify();
                if (handlers && typeof handlers.onSuccess === "function") handlers.onSuccess();
            },
            onFailure: function () { failWith(handlers); }
        }, "SOFTWARE_TOKEN_MFA");
    }

    // ---------- Sign up and confirmation ----------
    // An address that is already registered is answered exactly like a new one
    // (SignUp always reports it, see the Cognito docs), so the page never
    // reveals whether an email has an account.
    function signUp(email, password, handlers) {
        email = normalizeEmail(email);
        if (!pool || !validEmail(email) || !validPassword(password)) {
            password = null;
            return failWith(handlers);
        }
        var attributes = [new lib.CognitoUserAttribute({ Name: "email", Value: email })];
        pool.signUp(email, password, attributes, null, function (err) {
            if (!err || err.code === "UsernameExistsException") {
                if (handlers && typeof handlers.onAccepted === "function") handlers.onAccepted();
            } else {
                failWith(handlers);
            }
        });
        password = null;   // the library holds its own copy until the request ends
    }

    function confirmSignUp(email, code, handlers) {
        email = normalizeEmail(email);
        if (!pool || !validEmail(email) || !validCode(code)) return failWith(handlers);
        var user = new lib.CognitoUser({ Username: email, Pool: pool, Storage: storage });
        user.confirmRegistration(code, true, function (err) {
            if (err) return failWith(handlers);
            if (handlers && typeof handlers.onSuccess === "function") handlers.onSuccess();
        });
    }

    // Always answers the same, whether or not the address has an account. Only
    // rate limits and network failures are reported (they say nothing about it).
    function resendCode(email, handlers) {
        email = normalizeEmail(email);
        if (!pool || !validEmail(email)) return failWith(handlers);
        var user = new lib.CognitoUser({ Username: email, Pool: pool, Storage: storage });
        user.resendConfirmationCode(function (err) {
            var limited = err && (!err.code || err.code === "TooManyRequestsException" ||
                err.code === "LimitExceededException");
            if (limited) return failWith(handlers);
            if (handlers && typeof handlers.onSent === "function") handlers.onSent();
        });
    }

    // ---------- Sign out ----------
    function logout(callback) {
        pendingUser = null;
        function finish() {
            storage.clear();
            notify();
            if (typeof callback === "function") callback();
        }
        var user = pool ? pool.getCurrentUser() : null;
        if (!user) return finish();
        user.getSession(function (err) {
            if (err) {
                user.clearCachedUser();
                return finish();
            }
            // Revokes every token of the user on the server, then clears them here.
            user.globalSignOut({
                onSuccess: finish,
                onFailure: function () {
                    user.clearCachedUser();
                    finish();
                }
            });
        });
    }

    // ---------- Menu (Login / Log Out) ----------
    function refreshMenu() {
        var loginLink = document.getElementById("nav-login");
        var logoutLink = document.getElementById("nav-logout");
        if (!loginLink || !logoutLink) return;
        currentEmail(function (email) {
            var signedIn = email !== null;
            loginLink.classList.toggle("d-none", signedIn);
            logoutLink.classList.toggle("d-none", !signedIn);
        });
    }

    function onChange(fn) {
        if (typeof fn === "function") listeners.push(fn);
    }

    function init() {
        var logoutLink = document.getElementById("nav-logout");
        if (logoutLink) {
            logoutLink.addEventListener("click", function (ev) {
                ev.preventDefault();
                logout();
            });
        }
        onChange(refreshMenu);
        refreshMenu();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    window.EstoreAuth = Object.freeze({
        available: !!pool,
        validEmail: validEmail,
        validCode: validCode,
        validPassword: validPassword,
        normalizeEmail: normalizeEmail,
        maxEmail: MAX_EMAIL,
        maxPassword: MAX_PASSWORD,
        signUp: signUp,
        confirmSignUp: confirmSignUp,
        resendCode: resendCode,
        login: login,
        submitTotp: submitTotp,
        logout: logout,
        currentEmail: currentEmail,
        onChange: onChange
    });
})();
