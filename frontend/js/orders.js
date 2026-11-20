/*
 * Orders page: the signed-in customer's own order history (GET /orders).
 * Without a session it shows a link to the sign-in page. The Cognito session
 * lives in auth.js (EstoreAuth).
 * Security rules for this file:
 *  - The access token is read from EstoreAuth for each request and sent only
 *    as the Authorization header of that request, never stored.
 *  - Every field of the response is validated (strict UUID, amounts, quantity,
 *    text length, date) before it is shown; invalid orders are skipped.
 *  - Everything shown is written with textContent. Nothing is built as HTML
 *    and no href is built from data.
 *  - The API address comes only from window.APP_CONFIG (see config.js).
 *  - Failures show short generic messages.
 */
(function () {
    "use strict";

    var auth = window.EstoreAuth;

    function $(id) {
        return document.getElementById(id);
    }

    var signedOutBox = $("orders-signedout");
    var MSG_UNAVAILABLE = "Orders are not available right now.";
    if (!auth || !signedOutBox || !$("orders-box") || !$("orders-error") || !$("orders-loading") ||
        !$("orders-empty") || !$("orders-list")) return;

    function show(el, visible) {
        el.classList.toggle("d-none", !visible);
    }

    var ORDERS_MAX = 50;       // the API never returns more than 50
    var LINES_MAX = 50;
    var UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    var AMOUNT_RE = /^\d{1,10}(\.\d{1,2})?$/;
    var TIMEOUT_MS = 8000;
    var MSG_ORDERS_FAIL = "Could not load your orders. Try again later.";
    var MSG_ORDERS_AUTH = "Your session has expired. Sign in again to see your orders.";
    var MSG_ORDERS_LIMIT = "Too many requests. Try again in a minute.";
    var money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
    var ordersBox = $("orders-box");
    var ordersError = $("orders-error");
    var ordersLoading = $("orders-loading");
    var ordersEmpty = $("orders-empty");
    var ordersList = $("orders-list");
    var ordersSeq = 0;         // ignores an answer that arrives after a newer request

    // Same address rules as store.js: same-origin path, or https (http only for
    // localhost); no credentials, query or fragment.
    function resolveApi(raw) {
        if (typeof raw !== "string") return null;
        raw = raw.trim();
        if (!raw || raw.indexOf("${") !== -1 || raw.indexOf("//") === 0) return null;
        var u;
        try {
            u = new URL(raw, window.location.origin);
        } catch (e) {
            return null;
        }
        if (raw.charAt(0) !== "/") {
            var local = u.hostname === "localhost" || u.hostname === "127.0.0.1";
            if (!(u.protocol === "https:" || (u.protocol === "http:" && local))) return null;
        }
        if (u.username || u.password || u.search || u.hash) return null;
        return u.origin + u.pathname.replace(/\/+$/, "");
    }

    var apiBase = resolveApi((window.APP_CONFIG || {}).API_BASE_URL);

    function hideOrders() {
        ordersSeq += 1;
        show(ordersBox, false);
        ordersList.textContent = "";
        show(ordersError, false);
        show(ordersEmpty, false);
    }

    // The API sends amounts as strings with up to two decimals (exact decimals).
    function amount(v) {
        var n = null;
        if (typeof v === "string" && AMOUNT_RE.test(v)) n = Number(v);
        else if (typeof v === "number") n = v;
        return (n !== null && Number.isFinite(n) && n >= 0 && n <= 10000000000) ? n : null;
    }

    function cleanName(v) {
        if (typeof v !== "string") return null;
        v = v.trim();
        return (v.length >= 1 && v.length <= 120) ? v : null;
    }

    // Returns a clean copy of one order, or null if anything is off.
    function cleanOrder(o) {
        if (!o || typeof o !== "object") return null;
        if (typeof o.id !== "string" || !UUID_RE.test(o.id)) return null;
        var total = amount(o.total);
        if (total === null) return null;
        if (typeof o.created_at !== "string" || o.created_at.length > 40) return null;
        var when = new Date(o.created_at);
        if (isNaN(when.getTime())) return null;
        if (!Array.isArray(o.items) || o.items.length < 1 || o.items.length > LINES_MAX) return null;
        var lines = [];
        for (var i = 0; i < o.items.length; i++) {
            var l = o.items[i];
            if (!l || typeof l !== "object") return null;
            var name = cleanName(l.name);
            var unit = amount(l.unit_price);
            var sum = amount(l.line_total);
            if (name === null || unit === null || sum === null) return null;
            if (!Number.isInteger(l.quantity) || l.quantity < 1 || l.quantity > 99) return null;
            lines.push({ name: name, quantity: l.quantity, unit: unit, sum: sum });
        }
        return { id: o.id, total: total, when: when, lines: lines };
    }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function renderOrder(order) {
        var card = el("div", "card mb-3");
        var head = el("div", "card-header d-flex justify-content-between flex-wrap");
        head.appendChild(el("span", "text-dark",
            order.when.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })));
        head.appendChild(el("strong", "text-dark", money.format(order.total)));
        card.appendChild(head);

        var body = el("div", "card-body");
        body.appendChild(el("p", "text-muted small text-break mb-2", "Order " + order.id));
        var wrap = el("div", "table-responsive");
        var table = el("table", "table table-sm mb-0");
        var thead = el("thead");
        var hr = el("tr");
        ["Product", "Qty", "Price", "Total"].forEach(function (h) {
            hr.appendChild(el("th", "", h));
        });
        thead.appendChild(hr);
        table.appendChild(thead);
        var tbody = el("tbody");
        order.lines.forEach(function (l) {
            var tr = el("tr");
            tr.appendChild(el("td", "", l.name));
            tr.appendChild(el("td", "", String(l.quantity)));
            tr.appendChild(el("td", "", money.format(l.unit)));
            tr.appendChild(el("td", "", money.format(l.sum)));
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        body.appendChild(wrap);
        card.appendChild(body);
        return card;
    }

    function ordersFail(text) {
        show(ordersLoading, false);
        ordersError.textContent = text;
        show(ordersError, true);
    }

    function fetchOrders(token) {
        var ctrl = new AbortController();
        var timer = setTimeout(function () { ctrl.abort(); }, TIMEOUT_MS);
        return fetch(apiBase + "/orders", {
            method: "GET",
            credentials: "omit",
            cache: "no-store",
            redirect: "error",
            referrerPolicy: "no-referrer",
            signal: ctrl.signal,
            headers: { "Accept": "application/json", "Authorization": "Bearer " + token }
        }).then(function (res) {
            if (!res.ok) {
                var err = new Error("http");
                err.status = res.status;
                throw err;
            }
            if ((res.headers.get("Content-Type") || "").indexOf("application/json") !== 0) {
                throw new Error("type");
            }
            return res.json();
        }).finally(function () { clearTimeout(timer); });
    }

    function loadOrders() {
        var seq = ++ordersSeq;
        ordersList.textContent = "";
        show(ordersError, false);
        show(ordersEmpty, false);
        show(ordersLoading, true);
        show(ordersBox, true);
        if (!apiBase) return ordersFail(MSG_ORDERS_FAIL);
        auth.getAccessToken(function (token) {
            if (seq !== ordersSeq) return;
            if (typeof token !== "string" || !token) return ordersFail(MSG_ORDERS_AUTH);
            fetchOrders(token).then(function (data) {
                if (seq !== ordersSeq) return;
                if (!Array.isArray(data) || data.length > ORDERS_MAX) return ordersFail(MSG_ORDERS_FAIL);
                var shown = 0;
                data.forEach(function (raw) {
                    var order = cleanOrder(raw);
                    if (order === null) return;
                    ordersList.appendChild(renderOrder(order));
                    shown += 1;
                });
                if (data.length > 0 && shown === 0) return ordersFail(MSG_ORDERS_FAIL);
                show(ordersLoading, false);
                show(ordersEmpty, shown === 0);
            }).catch(function (err) {
                if (seq !== ordersSeq) return;
                if (err && err.status === 401) return ordersFail(MSG_ORDERS_AUTH);
                if (err && err.status === 429) return ordersFail(MSG_ORDERS_LIMIT);
                ordersFail(MSG_ORDERS_FAIL);
            });
        });
    }

    function showSignedOut() {
        hideOrders();
        show(signedOutBox, true);
    }

    function start() {
        show(signedOutBox, false);
        auth.currentEmail(function (email) {
            if (email === null) return showSignedOut();
            loadOrders();
        });
    }

    // The session can end in another tab or by expiring.
    auth.onChange(function () {
        auth.currentEmail(function (email) {
            if (email === null) showSignedOut();
        });
    });

    if (!auth.available) {
        ordersFail(MSG_UNAVAILABLE);
        show($("orders-box"), true);
    } else {
        start();
    }
})();
