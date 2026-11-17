/*
 * Profile page: turn two-step verification (TOTP, authenticator app) on or off.
 * The page only works with a signed-in session; without one it shows a link to
 * the sign-in page. All Cognito calls live in auth.js (EstoreAuth).
 * Security rules for this file:
 *  - Everything shown is written with textContent. Nothing is built as HTML,
 *    and the otpauth link is plain text, never an href.
 *  - The TOTP secret lives only in the `secret` variable of this closure while
 *    the setup is on screen. It is never written to a storage, the console or
 *    an attribute, and it is wiped when the setup ends, is cancelled or the
 *    session is gone.
 *  - Codes are checked with a strict pattern before Cognito is called.
 *  - Turning TOTP off asks for the password and a current code: the customer
 *    signs in again (SRP) and Cognito checks both. The password is read once,
 *    its field is emptied at once and the value is never kept.
 *  - Failures show short generic messages.
 */
(function () {
    "use strict";

    var auth = window.EstoreAuth;
    var ISSUER = "eStore";   // name shown by the authenticator app
    var MSG_UNAVAILABLE = "Account settings are not available right now.";
    var MSG_LOAD_FAIL = "Could not load your account settings. Try again later.";
    var MSG_ON_FAIL = "Could not turn on two-step verification. Try again.";
    var MSG_CODE_FAIL = "Could not verify the code. Check it and try again.";
    var MSG_OFF_FAIL = "Could not turn off two-step verification. Check your details and try again.";
    var MSG_ON = "Two-step verification is on.";
    var MSG_OFF = "Two-step verification is off.";
    var MSG_COPIED = "Setup link copied.";

    function $(id) {
        return document.getElementById(id);
    }

    var errorBox = $("profile-error");
    var noticeBox = $("profile-notice");
    var signedOutBox = $("profile-signedout");
    var mainBox = $("profile-main");
    var who = $("profile-who");
    var toggle = $("mfa-toggle");
    var setupBox = $("setup-box");
    var keyOut = $("setup-key");
    var uriOut = $("setup-uri");
    var copyBtn = $("setup-copy");
    var setupForm = $("setup-form");
    var setupCode = $("setup-code");
    var setupBtn = $("setup-submit");
    var setupCancel = $("setup-cancel");
    var disableForm = $("disable-form");
    var disablePassword = $("disable-password");
    var disableCode = $("disable-code");
    var disableBtn = $("disable-submit");
    var disableCancel = $("disable-cancel");
    if (!auth || !errorBox || !noticeBox || !signedOutBox || !mainBox || !who || !toggle ||
        !setupBox || !keyOut || !uriOut || !copyBtn || !setupForm || !setupCode || !setupBtn ||
        !setupCancel || !disableForm || !disablePassword || !disableCode || !disableBtn ||
        !disableCancel) return;

    var secret = null;         // TOTP secret while the setup is on screen
    var accountEmail = null;   // signed-in email, needed to sign in again to turn TOTP off

    function show(el, visible) {
        el.classList.toggle("d-none", !visible);
    }

    function showError(text) {
        errorBox.textContent = text;
        show(errorBox, !!text);
    }

    function showNotice(text) {
        noticeBox.textContent = text;
        show(noticeBox, !!text);
    }

    function forgetSecret() {
        secret = null;
        keyOut.textContent = "";
        uriOut.textContent = "";
        setupCode.value = "";
    }

    function hideSteps() {
        forgetSecret();
        disablePassword.value = "";
        disableCode.value = "";
        show(setupBox, false);
        show(disableForm, false);
    }

    // No valid session: nothing about the account is shown.
    function showSignedOut() {
        hideSteps();
        accountEmail = null;
        show(mainBox, false);
        show(signedOutBox, true);
    }

    // Reads the real state from Cognito and shows the matching screen.
    function load() {
        hideSteps();
        toggle.disabled = true;
        show(signedOutBox, false);
        show(mainBox, false);
        auth.currentEmail(function (email) {
            if (email === null) return showSignedOut();
            auth.mfaStatus({
                onStatus: function (enabled) {
                    accountEmail = email;
                    who.textContent = email;
                    toggle.checked = enabled;
                    toggle.disabled = false;
                    show(mainBox, true);
                },
                onSignedOut: showSignedOut,
                onFail: function () {
                    showError(MSG_LOAD_FAIL);
                }
            });
        });
    }

    function groupKey(value) {
        return value.replace(/(.{4})(?=.)/g, "$1 ");
    }

    function otpauthUri(value, email) {
        return "otpauth://totp/" + encodeURIComponent(ISSUER) + ":" + encodeURIComponent(email) +
            "?secret=" + value + "&issuer=" + encodeURIComponent(ISSUER);
    }

    function showSetup(value) {
        secret = value;
        keyOut.textContent = groupKey(value);
        uriOut.textContent = otpauthUri(value, accountEmail || "");
        setupCode.value = "";
        show(setupBox, true);
        setupCode.focus();
    }

    // ---------- Turn on ----------
    function beginSetup() {
        showError("");
        showNotice("");
        toggle.disabled = true;
        auth.startTotpSetup({
            onSecret: showSetup,
            onSignedOut: showSignedOut,
            onFail: function () {
                toggle.checked = false;
                toggle.disabled = false;
                showError(MSG_ON_FAIL);
            }
        });
    }

    setupForm.addEventListener("submit", function (ev) {
        ev.preventDefault();
        showError("");
        var typed = setupCode.value.trim();
        setupCode.value = "";
        if (!auth.validCode(typed)) return showError(MSG_CODE_FAIL);
        setupBtn.disabled = true;
        auth.confirmTotpSetup(typed, {
            onSuccess: function () {
                setupBtn.disabled = false;
                load();
                showNotice(MSG_ON);
            },
            onSignedOut: function () {
                setupBtn.disabled = false;
                showSignedOut();
            },
            onFail: function () {
                setupBtn.disabled = false;
                showError(MSG_CODE_FAIL);
            }
        });
    });

    setupCancel.addEventListener("click", function () {
        showError("");
        showNotice("");
        load();
    });

    copyBtn.addEventListener("click", function () {
        if (!secret || !accountEmail) return;
        var text = otpauthUri(secret, accountEmail);
        if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") return;
        navigator.clipboard.writeText(text).then(function () {
            showNotice(MSG_COPIED);
        }, function () { /* the key is on screen anyway */ });
    });

    // ---------- Turn off ----------
    function beginDisable() {
        showError("");
        showNotice("");
        toggle.checked = true;       // stays on until Cognito confirms
        toggle.disabled = true;
        disablePassword.value = "";
        disableCode.value = "";
        show(disableForm, true);
        disablePassword.focus();
    }

    function disableFailed() {
        disableBtn.disabled = false;
        showError(MSG_OFF_FAIL);
    }

    disableForm.addEventListener("submit", function (ev) {
        ev.preventDefault();
        showError("");
        var typedPassword = disablePassword.value;
        var typedCode = disableCode.value.trim();
        disablePassword.value = "";
        disableCode.value = "";
        if (!accountEmail || typedPassword.length < 1 || typedPassword.length > auth.maxPassword ||
            !auth.validCode(typedCode)) {
            typedPassword = null;
            return showError(MSG_OFF_FAIL);
        }
        disableBtn.disabled = true;
        // Signing in again makes Cognito check the password and the TOTP code.
        auth.login(accountEmail, typedPassword, {
            onTotp: function () {
                auth.submitTotp(typedCode, {
                    onSuccess: function () {
                        auth.disableTotp({
                            onSuccess: function () {
                                disableBtn.disabled = false;
                                load();
                                showNotice(MSG_OFF);
                            },
                            onSignedOut: function () {
                                disableBtn.disabled = false;
                                showSignedOut();
                            },
                            onFail: disableFailed
                        });
                    },
                    onFail: disableFailed
                });
            },
            onSuccess: disableFailed,   // no code was asked for: TOTP is not active
            onFail: disableFailed
        });
        typedPassword = null;
    });

    disableCancel.addEventListener("click", function () {
        showError("");
        showNotice("");
        load();
    });

    toggle.addEventListener("change", function () {
        if (toggle.checked) {
            beginSetup();
        } else {
            beginDisable();
        }
    });

    // The session can end in another tab or by expiring.
    auth.onChange(function () {
        auth.currentEmail(function (email) {
            if (email === null) showSignedOut();
        });
    });

    if (!auth.available) {
        showError(MSG_UNAVAILABLE);
    } else {
        load();
    }
})();
