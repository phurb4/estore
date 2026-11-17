/*
 * Registration page: sign-up form, then the 6-digit email code step with a
 * resend button. All Cognito calls live in auth.js (EstoreAuth).
 * Security rules for this file:
 *  - Messages are written only with textContent.
 *  - Email, password and code are checked with strict rules before Cognito is
 *    called; a failed check makes no request.
 *  - Passwords are read once, both fields are emptied at once and the value
 *    is handed to EstoreAuth.signUp. Nothing is stored or logged. The email
 *    waiting for its code lives only in this closure, never in a storage.
 *  - The page never says whether an email already has an account: a new
 *    address and a registered one get the same screens and the same text.
 */
(function () {
    "use strict";

    var auth = window.EstoreAuth;
    var MSG_REGISTER_FAIL = "Could not create the account. Check your details and try again.";
    var MSG_CODE_SENT = "If this address can be registered, we sent a 6-digit code to it.";
    var MSG_CONFIRM_FAIL = "Could not confirm the account. Check the code and try again.";
    var MSG_RESENT = "If the address is eligible, a new code was sent.";
    var MSG_RESEND_FAIL = "Could not send a new code. Try again later.";
    var MSG_UNAVAILABLE = "Registration is not available right now.";
    var RESEND_WAIT_S = 30;   // comfort only: Cognito applies its own limits

    function $(id) {
        return document.getElementById(id);
    }

    var regForm = $("register-form");
    var confirmForm = $("confirm-form");
    var doneBox = $("register-done");
    var errorBox = $("register-error");
    var noticeBox = $("register-notice");
    if (!auth || !regForm || !confirmForm || !doneBox || !errorBox || !noticeBox) return;

    var email = $("reg-email");
    var password = $("reg-password");
    var password2 = $("reg-password2");
    var regBtn = $("register-submit");
    var code = $("confirm-code");
    var confirmBtn = $("confirm-submit");
    var resendBtn = $("confirm-resend");
    var pendingEmail = null;
    var timer = null;

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

    function showStep(which) {
        show(regForm, which === "register");
        show(confirmForm, which === "confirm");
        show(doneBox, which === "done");
        if (which === "register") email.focus();
        if (which === "confirm") code.focus();
    }

    function startCooldown() {
        var left = RESEND_WAIT_S;
        resendBtn.disabled = true;
        clearInterval(timer);
        function tick() {
            if (left <= 0) {
                clearInterval(timer);
                resendBtn.disabled = false;
                resendBtn.textContent = "Resend code";
                return;
            }
            resendBtn.textContent = "Resend code (" + left + "s)";
            left -= 1;
        }
        tick();
        timer = setInterval(tick, 1000);
    }

    regForm.addEventListener("submit", function (ev) {
        ev.preventDefault();
        showError("");
        showNotice("");
        var typedEmail = auth.normalizeEmail(email.value);
        var typedPassword = password.value;
        var typedRepeat = password2.value;
        password.value = "";
        password2.value = "";
        if (!auth.validEmail(typedEmail) || typedPassword !== typedRepeat ||
            !auth.validPassword(typedPassword)) {
            typedPassword = typedRepeat = null;
            return showError(MSG_REGISTER_FAIL);
        }
        typedRepeat = null;
        regBtn.disabled = true;
        auth.signUp(typedEmail, typedPassword, {
            onAccepted: function () {
                regBtn.disabled = false;
                pendingEmail = typedEmail;
                code.value = "";
                showStep("confirm");
                showNotice(MSG_CODE_SENT);
                startCooldown();
            },
            onFail: function () {
                regBtn.disabled = false;
                showError(MSG_REGISTER_FAIL);
            }
        });
        typedPassword = null;
    });

    confirmForm.addEventListener("submit", function (ev) {
        ev.preventDefault();
        showError("");
        showNotice("");
        var typedCode = code.value.trim();
        code.value = "";
        if (!pendingEmail || !auth.validCode(typedCode)) return showError(MSG_CONFIRM_FAIL);
        confirmBtn.disabled = true;
        auth.confirmSignUp(pendingEmail, typedCode, {
            onSuccess: function () {
                confirmBtn.disabled = false;
                pendingEmail = null;
                clearInterval(timer);
                showStep("done");
            },
            onFail: function () {
                confirmBtn.disabled = false;
                showError(MSG_CONFIRM_FAIL);
            }
        });
    });

    resendBtn.addEventListener("click", function () {
        showError("");
        showNotice("");
        if (!pendingEmail) return;
        startCooldown();
        auth.resendCode(pendingEmail, {
            onSent: function () { showNotice(MSG_RESENT); },
            onFail: function () { showError(MSG_RESEND_FAIL); }
        });
    });

    if (!auth.available) {
        showStep("none");
        showError(MSG_UNAVAILABLE);
    } else {
        showStep("register");
    }
})();
