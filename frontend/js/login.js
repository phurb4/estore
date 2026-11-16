/*
 * Login page: email + password form and, when the customer has turned on
 * MFA, the TOTP code step. All sign-in logic lives in auth.js (EstoreAuth).
 * Security rules for this file:
 *  - Messages and the signed-in email are written only with textContent.
 *  - The email is checked with a strict pattern before Cognito is called.
 *  - The password is read once, the field is emptied at once and the value is
 *    handed to EstoreAuth.login; it is never stored or logged.
 *  - Every failure shows the same generic message.
 */
(function () {
    "use strict";

    var auth = window.EstoreAuth;
    var MSG_FAIL = "Could not sign in. Check your details and try again.";
    var MSG_UNAVAILABLE = "Sign-in is not available right now.";

    function $(id) {
        return document.getElementById(id);
    }

    var loginForm = $("login-form");
    var totpForm = $("totp-form");
    var doneBox = $("login-done");
    var errorBox = $("login-error");
    if (!auth || !loginForm || !totpForm || !doneBox || !errorBox) return;

    var email = $("login-email");
    var password = $("login-password");
    var loginBtn = $("login-submit");
    var code = $("totp-code");
    var totpBtn = $("totp-submit");
    var who = $("login-who");
    var logoutBtn = $("login-logout");

    function show(el, visible) {
        el.classList.toggle("d-none", !visible);
    }

    function showError(text) {
        errorBox.textContent = text;
        show(errorBox, !!text);
    }

    function showForm(which) {
        show(loginForm, which === "login");
        show(totpForm, which === "totp");
        show(doneBox, which === "done");
        if (which === "login") email.focus();
        if (which === "totp") code.focus();
    }

    function busy(button, isBusy) {
        button.disabled = isBusy;
    }

    function renderState() {
        showError("");
        if (!auth.available) {
            showForm("none");
            showError(MSG_UNAVAILABLE);
            return;
        }
        auth.currentEmail(function (current) {
            if (current === null) return showForm("login");
            who.textContent = current;
            showForm("done");
        });
    }

    loginForm.addEventListener("submit", function (ev) {
        ev.preventDefault();
        showError("");
        var typedEmail = email.value.trim();
        var typedPassword = password.value;
        password.value = "";
        if (!auth.validEmail(typedEmail) || typedPassword.length < 1 ||
            typedPassword.length > auth.maxPassword) {
            typedPassword = null;
            return showError(MSG_FAIL);
        }
        busy(loginBtn, true);
        auth.login(typedEmail, typedPassword, {
            onSuccess: function () {
                busy(loginBtn, false);
                renderState();
            },
            onTotp: function () {
                busy(loginBtn, false);
                code.value = "";
                showForm("totp");
            },
            onFail: function () {
                busy(loginBtn, false);
                showError(MSG_FAIL);
            }
        });
        typedPassword = null;
    });

    totpForm.addEventListener("submit", function (ev) {
        ev.preventDefault();
        showError("");
        var typedCode = code.value.trim();
        code.value = "";
        if (!auth.validCode(typedCode)) return showError(MSG_FAIL);
        busy(totpBtn, true);
        auth.submitTotp(typedCode, {
            onSuccess: function () {
                busy(totpBtn, false);
                renderState();
            },
            onFail: function () {
                busy(totpBtn, false);
                showForm("login");
                showError(MSG_FAIL);
            }
        });
    });

    logoutBtn.addEventListener("click", function () {
        busy(logoutBtn, true);
        auth.logout(function () {
            busy(logoutBtn, false);
            renderState();
        });
    });

    renderState();
})();
