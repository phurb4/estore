/*
 * Store logic: catalog from the API, cart (localStorage) and checkout.
 * Security rules for this file:
 *  - Data from the API is only ever written with textContent / setAttribute
 *    after validation (no HTML-insertion APIs, no inline handlers).
 *  - User input (search box, ?category=, ?q=) is validated, compared as plain
 *    text and never used as markup, as an href or inside a regular expression.
 *  - The cart stores only {id, qty}. Prices always come from the server.
 *  - The API address comes only from window.APP_CONFIG (see config.js).
 */
(function () {
    "use strict";

    var ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
    var CART_KEY = "estore.cart.v1";
    var MAX_QTY = 99;
    var MAX_LINES = 50;
    var MAX_PRODUCTS = 200;
    var TIMEOUT_MS = 8000;
    var money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

    // ---------- Config ----------
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
        var sameOrigin = raw.charAt(0) === "/";
        if (!sameOrigin) {
            var local = u.hostname === "localhost" || u.hostname === "127.0.0.1";
            if (!(u.protocol === "https:" || (u.protocol === "http:" && local))) return null;
        }
        if (u.username || u.password || u.search || u.hash) return null;
        return { base: u.origin + u.pathname.replace(/\/+$/, ""), origin: u.origin };
    }

    var API = resolveApi((window.APP_CONFIG || {}).API_BASE_URL);

    // ---------- API client ----------
    // token (optional): the Cognito access token, sent only as the
    // Authorization header of this one request. It is never stored here.
    function api(method, path, body, token) {
        if (!API) return Promise.reject(new Error("config"));
        var ctrl = new AbortController();
        var timer = setTimeout(function () { ctrl.abort(); }, TIMEOUT_MS);
        var opts = {
            method: method,
            credentials: "omit",
            cache: "no-store",
            redirect: "error",
            referrerPolicy: "no-referrer",
            signal: ctrl.signal,
            headers: { "Accept": "application/json" }
        };
        if (typeof token === "string" && token) opts.headers["Authorization"] = "Bearer " + token;
        if (body !== undefined) {
            opts.headers["Content-Type"] = "application/json";
            opts.body = JSON.stringify(body);
        }
        return fetch(API.base + path, opts).then(function (res) {
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

    // ---------- Validation ----------
    function safeImage(src) {
        if (typeof src !== "string" || src.length > 300) return null;
        if (/^img\/[\w.\-]+\.(png|jpe?g|webp|gif)$/i.test(src)) return src;
        if (!API || !/^https?:\/\//i.test(src)) return null;
        try {
            var u = new URL(src);
            return (u.origin === API.origin && !u.username && !u.password) ? u.href : null;
        } catch (e) {
            return null;
        }
    }

    function cleanText(v, max) {
        if (typeof v !== "string") return null;
        v = v.trim();
        return (v.length >= 1 && v.length <= max) ? v : null;
    }

    function cleanPrice(v) {
        if (typeof v !== "number" && typeof v !== "string") return null;
        var n = Number(v);
        return (isFinite(n) && n >= 0 && n <= 10000000) ? n : null;
    }

    function cleanProduct(p) {
        if (!p || typeof p !== "object") return null;
        var id = String(p.id);
        var name = cleanText(p.name, 120);
        var price = cleanPrice(p.price);
        if (!ID_RE.test(id) || name === null || price === null) return null;
        return {
            id: id,
            name: name,
            category: cleanText(p.category, 60),
            price: price,
            oldPrice: (p.old_price === undefined || p.old_price === null) ? null : cleanPrice(p.old_price),
            image: safeImage(p.image)
        };
    }

    var productsPromise = null;
    function loadProducts() {
        if (!productsPromise) {
            productsPromise = api("GET", "/products").then(function (data) {
                if (!Array.isArray(data)) throw new Error("shape");
                return data.slice(0, MAX_PRODUCTS).map(cleanProduct).filter(Boolean);
            });
        }
        return productsPromise;
    }

    // ---------- Cart (ids and quantities only) ----------
    function readCart() {
        var out = [], seen = {};
        try {
            var data = JSON.parse(window.localStorage.getItem(CART_KEY) || "[]");
            if (Array.isArray(data)) {
                data.forEach(function (l) {
                    if (!l || !ID_RE.test(String(l.id)) || seen[l.id]) return;
                    var q = Number(l.qty);
                    if (!Number.isInteger(q) || q < 1 || q > MAX_QTY || out.length >= MAX_LINES) return;
                    seen[l.id] = true;
                    out.push({ id: String(l.id), qty: q });
                });
            }
        } catch (e) { /* storage unavailable or corrupt: start empty */ }
        return out;
    }

    function writeCart(lines) {
        try { window.localStorage.setItem(CART_KEY, JSON.stringify(lines)); } catch (e) { /* ignore */ }
    }

    function setQty(id, qty) {
        var lines = readCart().filter(function (l) { return l.id !== id; });
        qty = Math.min(MAX_QTY, qty);
        if (qty >= 1 && lines.length < MAX_LINES) lines.push({ id: id, qty: qty });
        writeCart(lines);
    }

    function addToCart(id) {
        var cur = readCart().filter(function (l) { return l.id === id; })[0];
        setQty(id, cur ? cur.qty + 1 : 1);
    }

    // ---------- DOM helpers ----------
    function firstRow(container) {
        return container.matches(".row") ? container : container.querySelector(".row");
    }

    function setText(el, text) { if (el) el.textContent = text; }

    function stripWow(root) {
        [root].concat([].slice.call(root.querySelectorAll(".wow"))).forEach(function (el) {
            el.classList.remove("wow", "fadeInUp", "fadeIn", "animated");
            el.removeAttribute("data-wow-delay");
            // WOW.js hides every .wow element with inline styles until it is
            // scrolled into view. If the card template was captured while it
            // was hidden, the copies would stay invisible, so clear them.
            el.style.removeProperty("visibility");
            el.style.removeProperty("animation-delay");
            el.style.removeProperty("animation-name");
        });
    }

    function notice(host, kind, text) {
        var old = host.querySelector("[data-notice]");
        if (old) old.remove();
        var div = document.createElement("div");
        div.className = "alert alert-" + kind + " mt-3 w-100";
        div.setAttribute("role", "alert");
        div.setAttribute("data-notice", "");
        div.textContent = text;
        host.appendChild(div);
    }

    // Same as notice() but ends with a fixed link to the login page (the href
    // is a constant, never built from data).
    function loginNotice(host, text) {
        notice(host, "warning", text + " ");
        var div = host.querySelector("[data-notice]");
        var a = document.createElement("a");
        a.setAttribute("href", "login.html");
        a.className = "alert-link";
        a.textContent = "Sign in";
        div.appendChild(a);
    }

    // Resolves with the access token, or null when nobody is signed in.
    function getToken() {
        var auth = window.EstoreAuth;
        if (!auth || !auth.available || typeof auth.getAccessToken !== "function") return Promise.resolve(null);
        return new Promise(function (resolve) { auth.getAccessToken(resolve); });
    }

    // ---------- Catalog ----------
    // Each container keeps its own card template, captured once: the first
    // render replaces the template cards, and filters render the grid again.
    var templates = new WeakMap();

    function renderCatalog(container, products) {
        var row = firstRow(container);
        if (!row) return;
        var tpl = templates.get(container);
        if (!tpl) {
            if (!row.firstElementChild) return;
            tpl = row.firstElementChild.cloneNode(true);
            templates.set(container, tpl);
        }
        var frag = document.createDocumentFragment();

        products.forEach(function (p) {
            var col = tpl.cloneNode(true);
            stripWow(col);
            // Grid cards and list cards (shop.html tab-6) use different class names.
            var img = col.querySelector(".product-item-inner-item img, .products-mini-img img");
            if (img) {
                if (p.image) img.setAttribute("src", p.image);
                img.setAttribute("alt", p.name);
            }
            var links = col.querySelectorAll("a.d-block");
            if (links[0]) links[0].textContent = p.category || "";
            if (links[1]) links[1].textContent = p.name;
            var del = col.querySelector("del");
            if (del) {
                if (p.oldPrice !== null) del.textContent = money.format(p.oldPrice);
                else del.remove();
            }
            setText(col.querySelector("span.text-primary.fs-5"), money.format(p.price));
            var btn = col.querySelector(".product-item-add .btn-primary, .products-mini-add .btn-primary");
            if (btn) btn.setAttribute("data-add-to-cart", p.id);
            frag.appendChild(col);
        });
        row.replaceChildren(frag);
    }

    // ---------- Shop filters (category + keywords) ----------
    var MAX_QUERY = 60;
    // Characters to discard from the search text. Fixed pattern: it is never
    // built from user input. Letters, digits, space and . , ' & + - / " are kept.
    var QUERY_DISCARD = /[^\p{L}\p{N} .,'&+\-\/"]/gu;

    function cleanQuery(raw) {
        if (typeof raw !== "string") return "";
        var q = raw.slice(0, MAX_QUERY * 4)
            .replace(/\s+/g, " ")
            .replace(QUERY_DISCARD, "")
            .replace(/ {2,}/g, " ")
            .trim();
        return Array.from(q).slice(0, MAX_QUERY).join("").trim();
    }

    function categoriesOf(products) {
        var counts = new Map();
        products.forEach(function (p) {
            if (p.category) counts.set(p.category, (counts.get(p.category) || 0) + 1);
        });
        return counts;
    }

    function matchesQuery(p, tokens) {
        var hay = (p.name + " " + (p.category || "")).toLowerCase();
        return tokens.every(function (t) { return hay.indexOf(t) !== -1; });
    }

    function readUrlState(counts) {
        var state = { category: null, query: "" };
        try {
            var params = new URLSearchParams(window.location.search);
            var c = params.get("category");
            if (c !== null && c.length <= 60 && counts.has(c)) state.category = c;
            state.query = cleanQuery(params.get("q") || "");
        } catch (e) { /* ignore a malformed query string */ }
        return state;
    }

    function writeUrlState(state) {
        var params = new URLSearchParams();
        if (state.category) params.set("category", state.category);
        if (state.query) params.set("q", state.query);
        var qs = params.toString();
        try {
            window.history.replaceState(null, "", window.location.pathname + (qs ? "?" + qs : ""));
        } catch (e) { /* history can be unavailable (e.g. file://) */ }
    }

    function wireShopFilters(catalogs, products, statusEl) {
        var counts = categoriesOf(products);
        var state = readUrlState(counts);
        var timer = null;

        // Category controls. The category is the visible text of the link or
        // label; it only counts when it matches a category that came from the API.
        var links = new Map();
        document.querySelectorAll(".categories-item a, .categories-bars-item a").forEach(function (a) {
            var name = a.textContent.replace(/\s+/g, " ").trim();
            if (!counts.has(name)) return;
            links.set(a, name);
            var badge = a.parentNode.querySelector("span");
            if (badge) badge.textContent = "(" + counts.get(name) + ")";
        });
        var radios = new Map();
        document.querySelectorAll('.additional-product-item input[type="radio"]').forEach(function (r) {
            var label = r.parentNode.querySelector("label");
            var name = label ? label.textContent.replace(/\s+/g, " ").trim() : "";
            if (counts.has(name)) radios.set(r, name);
        });
        var searchInput = document.querySelector("[data-search-input]");
        if (searchInput) searchInput.value = state.query;

        function syncControls() {
            links.forEach(function (name, a) {
                var active = name === state.category;
                a.classList.toggle("fw-bold", active);
                if (active) a.setAttribute("aria-current", "true");
                else a.removeAttribute("aria-current");
            });
            radios.forEach(function (name, r) { r.checked = (name === state.category); });
        }

        function clearFilters() {
            state = { category: null, query: "" };
            if (searchInput) searchInput.value = "";
            apply();
        }

        function renderStatus(shown) {
            statusEl.replaceChildren();
            if (!state.category && !state.query) return;
            var box = document.createElement("div");
            var text = document.createElement("span");
            if (shown === 0) {
                box.className = "alert alert-warning mb-0";
                var what = state.query ? ' for "' + state.query + '"' : "";
                var where = state.category ? " in " + state.category : "";
                text.textContent = "No products found" + what + where +
                    ". Try different keywords or clear the filters.";
            } else {
                box.className = "d-flex align-items-center";
                text.textContent = "Showing " + shown + " of " + products.length + " products.";
            }
            var clear = document.createElement("button");
            clear.type = "button";
            clear.className = "btn btn-link p-0 ms-2";
            clear.textContent = "Clear filters";
            clear.addEventListener("click", clearFilters);
            box.appendChild(text);
            box.appendChild(clear);
            statusEl.appendChild(box);
        }

        function apply() {
            var tokens = state.query ? state.query.toLowerCase().split(" ") : [];
            var shown = products.filter(function (p) {
                return (!state.category || p.category === state.category) && matchesQuery(p, tokens);
            });
            catalogs.forEach(function (c) { renderCatalog(c, shown); });
            renderStatus(shown.length);
            syncControls();
            writeUrlState(state);
        }

        function setCategory(name) {
            state = { category: name, query: state.query };
            apply();
        }

        document.addEventListener("click", function (ev) {
            var a = ev.target.closest(".categories-item a, .categories-bars-item a");
            if (!a || !links.has(a)) return;
            ev.preventDefault();
            var name = links.get(a);
            setCategory(state.category === name ? null : name);
        });
        radios.forEach(function (name, r) {
            r.addEventListener("change", function () { if (r.checked) setCategory(name); });
        });
        if (searchInput) {
            var onSearch = function () {
                clearTimeout(timer);
                timer = setTimeout(function () {
                    state = { category: state.category, query: cleanQuery(searchInput.value) };
                    apply();
                }, 150);
            };
            searchInput.addEventListener("input", onSearch);
            searchInput.addEventListener("search", onSearch);
        }

        apply();
    }

    function flashAdded(btn) {
        var node = btn.lastChild;
        if (!node || node.nodeType !== 3) return;
        var original = node.nodeValue;
        node.nodeValue = " Added";
        setTimeout(function () { node.nodeValue = original; }, 1200);
    }

    // ---------- Cart page ----------
    function joinLines(map) {
        return readCart().map(function (l) {
            var p = map[l.id];
            return p ? { p: p, qty: l.qty } : null;
        }).filter(Boolean);
    }

    function subtotalOf(lines) {
        return lines.reduce(function (s, l) { return s + l.p.price * l.qty; }, 0);
    }

    function renderTotals(lines) {
        var sub = money.format(subtotalOf(lines));
        document.querySelectorAll("[data-cart-subtotal],[data-order-subtotal]").forEach(function (el) { el.textContent = sub; });
        document.querySelectorAll("[data-cart-total],[data-order-total]").forEach(function (el) { el.textContent = sub; });
    }

    function renderCart(tbody, tpl, map) {
        var lines = joinLines(map);
        var frag = document.createDocumentFragment();
        lines.forEach(function (l) {
            var tr = tpl.cloneNode(true);
            tr.setAttribute("data-id", l.p.id);
            setText(tr.querySelector("th p"), l.p.name);
            var cells = tr.querySelectorAll("td");
            setText(cells[0].querySelector("p"), l.p.category || "-");
            setText(cells[1].querySelector("p"), money.format(l.p.price));
            var input = cells[2].querySelector("input");
            input.value = String(l.qty);
            input.readOnly = true;
            cells[2].querySelector(".btn-minus").setAttribute("data-cart-action", "dec");
            cells[2].querySelector(".btn-plus").setAttribute("data-cart-action", "inc");
            setText(cells[3].querySelector("p"), money.format(l.p.price * l.qty));
            cells[4].querySelector("button").setAttribute("data-cart-action", "remove");
            frag.appendChild(tr);
        });
        tbody.replaceChildren(frag);
        renderTotals(lines);
    }

    function wireCartPage(tbody, map) {
        var tpl = tbody.querySelector("tr");
        if (!tpl) return;
        tpl = tpl.cloneNode(true);
        renderCart(tbody, tpl, map);
        tbody.addEventListener("click", function (ev) {
            var btn = ev.target.closest("[data-cart-action]");
            var tr = btn && btn.closest("tr");
            var id = tr && tr.getAttribute("data-id");
            if (!id || !ID_RE.test(id)) return;
            ev.preventDefault();
            var cur = readCart().filter(function (l) { return l.id === id; })[0];
            var qty = cur ? cur.qty : 0;
            var action = btn.getAttribute("data-cart-action");
            if (action === "inc") qty += 1;
            else if (action === "dec") qty -= 1;
            else if (action === "remove") qty = 0;
            setQty(id, qty);
            renderCart(tbody, tpl, map);
        });
        var go = document.querySelector("[data-checkout-link]");
        if (go) {
            go.addEventListener("click", function () {
                if (readCart().length) window.location.assign("checkout.html");
                else notice(go.parentNode, "warning", "Your cart is empty.");
            });
        }
    }

    // ---------- Checkout page ----------
    function renderOrder(tbody, tpl, anchor, map) {
        var lines = joinLines(map);
        tbody.querySelectorAll("tr.text-center").forEach(function (tr) { tr.remove(); });
        lines.forEach(function (l) {
            var tr = tpl.cloneNode(true);
            setText(tr.querySelector("th"), l.p.name);
            var cells = tr.querySelectorAll("td");
            setText(cells[0], l.p.category || "-");
            setText(cells[1], money.format(l.p.price));
            setText(cells[2], String(l.qty));
            setText(cells[3], money.format(l.p.price * l.qty));
            tbody.insertBefore(tr, anchor);
        });
        renderTotals(lines);
    }

    function wireCheckoutPage(tbody, map) {
        var tpl = tbody.querySelector("tr.text-center");
        var anchor = tbody.querySelector("tr:not(.text-center)");
        if (!tpl || !anchor) return;
        tpl = tpl.cloneNode(true);
        renderOrder(tbody, tpl, anchor, map);

        var btn = document.querySelector("[data-place-order]");
        if (!btn) return;
        btn.addEventListener("click", function () {
            var lines = readCart();
            var host = btn.parentNode;
            if (!lines.length) return notice(host, "warning", "Your cart is empty.");
            btn.disabled = true;
            var needSignIn = false;
            getToken().then(function (token) {
                if (!token) {
                    needSignIn = true;
                    throw new Error("auth");
                }
                return api("POST", "/orders", {
                    // The Orders service requires a whole number for product_id.
                    // A non-numeric id becomes null and the server answers 422.
                    items: lines.map(function (l) { return { product_id: Number(l.id), quantity: l.qty }; })
                }, token);
            }).then(function (res) {
                writeCart([]);
                renderOrder(tbody, tpl, anchor, map);
                var total = res && cleanPrice(res.total);
                if (total !== null) {
                    document.querySelectorAll("[data-order-total]").forEach(function (el) { el.textContent = money.format(total); });
                }
                var oid = res && ID_RE.test(String(res.id)) ? " Order ID: " + String(res.id) : "";
                notice(host, "success", "Order placed." + oid);
            }).catch(function (err) {
                var status = err && err.status;
                if (needSignIn || status === 401) {
                    return loginNotice(host, "Please sign in to place an order.");
                }
                var msg = status === 429
                    ? "Too many orders. Please wait a while before trying again."
                    : "The order could not be placed. Please try again later.";
                notice(host, "danger", msg);
            }).finally(function () { btn.disabled = false; });
        });
    }

    // ---------- Init ----------
    document.addEventListener("click", function (ev) {
        var btn = ev.target.closest("[data-add-to-cart]");
        if (!btn) return;
        var id = btn.getAttribute("data-add-to-cart");
        if (!ID_RE.test(id)) return;
        ev.preventDefault();
        addToCart(id);
        flashAdded(btn);
    });

    // Price slider (shop.html): only shows the number, it does not filter yet.
    function wirePriceRange() {
        var range = document.getElementById("rangeInput");
        var out = document.getElementById("amount");
        if (!range || !out) return;
        function show() {
            var v = Number(range.value);
            out.textContent = Number.isFinite(v) ? String(v) : "0";
        }
        range.addEventListener("input", show);
        show();
    }

    function init() {
        wirePriceRange();
        var catalogs = document.querySelectorAll("[data-catalog]");
        var cartBody = document.querySelector("[data-cart-body]");
        var orderBody = document.querySelector("[data-order-body]");
        if (!catalogs.length && !cartBody && !orderBody) return;

        loadProducts().then(function (products) {
            var map = {};
            products.forEach(function (p) { map[p.id] = p; });
            if (products.length) {
                var statusEl = document.querySelector("[data-catalog-status]");
                if (statusEl) wireShopFilters(catalogs, products, statusEl);
                else catalogs.forEach(function (c) { renderCatalog(c, products); });
            }
            if (cartBody) wireCartPage(cartBody, map);
            if (orderBody) wireCheckoutPage(orderBody, map);
        }).catch(function () {
            // Fail closed: the static template content stays as it is.
            if (window.console) console.warn("Catalog unavailable.");
        });
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})();
