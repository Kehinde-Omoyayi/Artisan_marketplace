/**
 * webchat/chat.js — the browser side of the chat box that replaces the old
 * WhatsApp-only flow. Talks only to /webchat/* (see webchat/urls.py).
 *
 * Reliability notes (deliberate, not accidental):
 *  - every fetch() has a .catch() — a dropped connection shows a friendly bubble,
 *    never a silent failure or an uncaught promise rejection in the console.
 *  - the poll loop is a single setTimeout chain (not setInterval), so a slow
 *    response can't cause overlapping requests to pile up.
 *  - nothing here uses localStorage/sessionStorage — identity lives in the
 *    server-side session cookie, which is also what makes it survive a reload.
 */
(function () {
  "use strict";

  var scriptEl = document.currentScript;
  var POLL_INTERVAL_MS = parseInt((scriptEl && scriptEl.dataset.pollInterval) || "2500", 10);
  var RESEND_COOLDOWN_S = parseInt((scriptEl && scriptEl.dataset.resendSeconds) || "45", 10);

  var widget = document.getElementById("chat-widget");
  if (!widget) return; // widget partial not included on this page — nothing to do

  var els = {
    bubble: widget.querySelector("[data-chat-toggle]"),
    closeBtn: widget.querySelector(".chat-panel-close"),
    panel: widget.querySelector("[data-chat-panel]"),
    status: widget.querySelector("[data-chat-status]"),
    messages: widget.querySelector("[data-chat-messages]"),
    phoneForm: widget.querySelector("[data-chat-verify-phone-form]"),
    phoneInput: widget.querySelector("#chat-phone"),
    phoneError: widget.querySelector('[data-chat-error="phone"]'),
    codeForm: widget.querySelector("[data-chat-verify-code-form]"),
    codeInput: widget.querySelector("#chat-code"),
    codeError: widget.querySelector('[data-chat-error="code"]'),
    resendBtn: widget.querySelector("[data-chat-resend]"),
    messageForm: widget.querySelector("[data-chat-message-form]"),
    textInput: widget.querySelector("[data-chat-text-input]"),
    locationBtn: widget.querySelector("[data-chat-location]"),
    uploadInput: widget.querySelector("[data-chat-upload]"),
  };

  var state = {
    verified: false,
    lastMessageId: 0,
    pendingPhone: "",
    pollHandle: null,
    polling: false,
    intent: null,
  };

  // ---------------------------------------------------------------- helpers

  function getCookie(name) {
    var match = document.cookie.match("(?:^|; )" + name + "=([^;]*)");
    return match ? decodeURIComponent(match[1]) : "";
  }

  function apiFetch(url, options) {
    options = options || {};
    var headers = options.headers || {};
    var method = (options.method || "GET").toUpperCase();
    if (method !== "GET") {
      headers["X-CSRFToken"] = getCookie("csrftoken");
    }
    options.headers = headers;
    options.credentials = "same-origin";

    return fetch(url, options)
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            // Non-JSON response (e.g. a proxy error page) — treat as a generic failure
            // rather than letting a JSON.parse exception escape uncaught.
            return { ok: false, error: "Unexpected response from the server." };
          })
          .then(function (data) {
            return { httpStatus: res.status, data: data };
          });
      })
      .catch(function () {
        // Network failure — offline, DNS, CORS, timeout, etc.
        return { httpStatus: 0, data: { ok: false, error: "Connection problem — check your internet and try again." } };
      });
  }

  function scrollToBottom() {
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function appendBubble(text, cssClass) {
    var div = document.createElement("div");
    div.className = "chat-bubble-msg " + cssClass;
    var p = document.createElement("p");
    p.style.margin = "0";
    p.textContent = text;
    div.appendChild(p);
    els.messages.appendChild(div);
    scrollToBottom();
    return div;
  }

  function appendSystem(text) {
    appendBubble(text, "chat-bubble-system");
  }

  var directionClass = { in: "chat-bubble-in", out: "chat-bubble-out" };

  function renderServerMessages(list) {
    if (!list || !list.length) return;
    list.forEach(function (msg) {
      if (msg.id <= state.lastMessageId) return; // already rendered — poll/response overlap
      appendBubble(msg.body, directionClass[msg.direction] || "chat-bubble-out");
      if (msg.id > state.lastMessageId) state.lastMessageId = msg.id;
    });
  }

  var typingEl = null;
  function showTyping() {
    if (typingEl) return;
    typingEl = document.createElement("div");
    typingEl.className = "chat-typing";
    typingEl.innerHTML = "<span></span><span></span><span></span>";
    els.messages.appendChild(typingEl);
    scrollToBottom();
  }
  function hideTyping() {
    if (typingEl && typingEl.parentNode) typingEl.parentNode.removeChild(typingEl);
    typingEl = null;
  }

  function setFieldError(el, message) {
    el.textContent = message || "";
  }

  // ---------------------------------------------------------------- panel open/close

  function openPanel() {
    widget.setAttribute("data-state", "open");
    els.bubble.setAttribute("aria-expanded", "true");
    els.panel.setAttribute("aria-hidden", "false");
    var target = state.verified ? els.textInput : els.phoneInput;
    if (target) window.setTimeout(function () { target.focus(); }, 150);
  }

  function closePanel() {
    widget.setAttribute("data-state", "closed");
    els.bubble.setAttribute("aria-expanded", "false");
    els.panel.setAttribute("aria-hidden", "true");
  }

  function togglePanel() {
    if (widget.getAttribute("data-state") === "open") closePanel();
    else openPanel();
  }

  // ---------------------------------------------------------------- verification

  function normalizePhoneDisplay(v) {
    return v.trim();
  }

  function startResendCooldown(seconds) {
    var remaining = seconds;
    els.resendBtn.disabled = true;
    var tick = function () {
      if (remaining <= 0) {
        els.resendBtn.disabled = false;
        els.resendBtn.textContent = "Didn't get it? Resend code";
        return;
      }
      els.resendBtn.textContent = "Resend code in " + remaining + "s";
      remaining -= 1;
      window.setTimeout(tick, 1000);
    };
    tick();
  }

  function requestCode(phone, isResend) {
    setFieldError(els.phoneError, "");
    setFieldError(els.codeError, "");
    var submitBtn = els.phoneForm.querySelector("button[type=submit]");
    if (submitBtn) submitBtn.disabled = true;

    return apiFetch("/webchat/verify/request-code/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: phone }),
    }).then(function (res) {
      if (submitBtn) submitBtn.disabled = false;
      if (!res.data.ok) {
        var msg = res.data.error || "Couldn't send a code — try again.";
        if (isResend) setFieldError(els.codeError, msg);
        else setFieldError(els.phoneError, msg);
        if (res.data.retry_after_seconds) startResendCooldown(res.data.retry_after_seconds);
        return false;
      }
      state.pendingPhone = phone;
      els.phoneForm.hidden = true;
      els.codeForm.hidden = false;
      els.codeInput.value = "";
      if (res.data.debug_code) {
        // Only ever present when DEBUG=True and no SMS provider is configured
        // (see webchat/services.py) — a dev/test convenience, never live in prod.
        els.codeInput.value = res.data.debug_code;
        appendSystem("Dev mode: no SMS provider configured, code pre-filled (" + res.data.debug_code + ").");
      }
      startResendCooldown(RESEND_COOLDOWN_S);
      window.setTimeout(function () { els.codeInput.focus(); }, 100);
      return true;
    });
  }

  function confirmCode(phone, code) {
    setFieldError(els.codeError, "");
    var submitBtn = els.codeForm.querySelector("button[type=submit]");
    if (submitBtn) submitBtn.disabled = true;

    return apiFetch("/webchat/verify/confirm-code/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: phone, code: code }),
    }).then(function (res) {
      if (submitBtn) submitBtn.disabled = false;
      if (!res.data.ok) {
        setFieldError(els.codeError, res.data.error || "Verification failed.");
        return false;
      }
      onVerified();
      return true;
    });
  }

  function onVerified() {
    state.verified = true;
    els.codeForm.hidden = true;
    els.phoneForm.hidden = true;
    els.messageForm.hidden = false;
    els.status.textContent = "Connected";
    appendSystem("You're verified. How can we help?");
    if (state.intent === "artisan") {
      // A visitor who clicked "I'm an artisan" doesn't need to know the ARTISAN
      // keyword — send it on their behalf, once, right after verification. It
      // renders like any other message once the server echoes it back, which is
      // accurate: it's genuinely what the conversation engine received.
      sendMessage("ARTISAN");
    }
    startPolling();
    window.setTimeout(function () { els.textInput.focus(); }, 100);
  }

  // ---------------------------------------------------------------- messaging

  function sendMessage(text) {
    text = text.trim();
    if (!text) return;
    els.textInput.value = "";
    els.textInput.disabled = true;
    showTyping();

    apiFetch("/webchat/message/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    }).then(function (res) {
      hideTyping();
      els.textInput.disabled = false;
      els.textInput.focus();
      if (res.httpStatus === 401) return onSessionLost();
      if (!res.data.ok) {
        appendSystem(res.data.error || "That message didn't go through — try again.");
        return;
      }
      // The server response includes the just-logged inbound message alongside any
      // reply, so this — not a client-side echo — is what renders it. Rendering an
      // optimistic copy here too would double it up the moment this response
      // lands, since the client can't predict the server-assigned message id
      // needed to de-duplicate against it.
      renderServerMessages(res.data.messages);
    });
  }

  function shareLocation() {
    if (!navigator.geolocation) {
      appendSystem("Your browser doesn't support sharing location — type your address instead.");
      return;
    }
    appendSystem("Requesting your location\u2026");
    navigator.geolocation.getCurrentPosition(
      function (position) {
        var lat = position.coords.latitude;
        var lng = position.coords.longitude;
        showTyping();
        apiFetch("/webchat/location/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lat: lat, lng: lng }),
        }).then(function (res) {
          hideTyping();
          if (res.httpStatus === 401) return onSessionLost();
          if (!res.data.ok) {
            appendSystem(res.data.error || "Couldn't share your location — try again.");
            return;
          }
          renderServerMessages(res.data.messages);
        });
      },
      function () {
        appendSystem("We couldn't get your location — check your browser's location permission, or just type your address.");
      },
      { timeout: 10000 }
    );
  }

  function uploadFile(file) {
    if (!file) return;
    showTyping();
    var formData = new FormData();
    formData.append("file", file);

    apiFetch("/webchat/upload-id/", { method: "POST", body: formData }).then(function (res) {
      hideTyping();
      if (res.httpStatus === 401) return onSessionLost();
      if (!res.data.ok) {
        appendSystem(res.data.error || "That upload didn't go through — try again.");
        return;
      }
      // As in sendMessage: the server response carries the inbound "[uploaded ID
      // photo]" entry plus any reply, so that's the single source rendered —
      // no separate client-side echo to keep in sync with it.
      renderServerMessages(res.data.messages);
    });
  }

  // ---------------------------------------------------------------- polling

  function onSessionLost() {
    if (!state.verified) return; // already handled
    state.verified = false;
    stopPolling();
    els.messageForm.hidden = true;
    els.codeForm.hidden = true;
    els.phoneForm.hidden = false;
    els.status.textContent = "Tell us what you need";
    appendSystem("Your session needs re-verifying — enter your number again to continue.");
  }

  function pollOnce() {
    apiFetch("/webchat/messages/?since=" + state.lastMessageId).then(function (res) {
      if (res.httpStatus === 401) {
        onSessionLost();
        return;
      }
      if (res.data.ok) renderServerMessages(res.data.messages);
      if (state.polling) {
        state.pollHandle = window.setTimeout(pollOnce, POLL_INTERVAL_MS);
      }
    });
  }

  function startPolling() {
    if (state.polling) return;
    state.polling = true;
    // Fire immediately rather than waiting a full interval — this is also what
    // restores the visible transcript right after a page reload of an
    // already-verified session: `since=0` is a deliberate "give me everything"
    // contract (see webchat/services.py:messages_since / the falsy-0 check
    // mirrored in webchat/views.py), not an accident of JS's default zero.
    pollOnce();
  }

  function stopPolling() {
    state.polling = false;
    if (state.pollHandle) {
      window.clearTimeout(state.pollHandle);
      state.pollHandle = null;
    }
  }

  // Pause polling while the tab is hidden — no point spending requests (or
  // battery) on a chat window nobody's looking at, and it cuts steady-state
  // server load roughly in proportion to how many tabs are backgrounded.
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      stopPolling();
    } else if (state.verified) {
      startPolling();
    }
  });

  // ---------------------------------------------------------------- wiring

  els.bubble.addEventListener("click", togglePanel);
  els.closeBtn.addEventListener("click", closePanel);

  document.querySelectorAll("[data-chat-open]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (btn.dataset.chatIntent) state.intent = btn.dataset.chatIntent;
      openPanel();
    });
  });

  els.phoneForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var phone = normalizePhoneDisplay(els.phoneInput.value);
    if (!phone) return;
    requestCode(phone, false);
  });

  els.codeForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var code = els.codeInput.value.trim();
    if (!code) return;
    confirmCode(state.pendingPhone, code);
  });

  els.resendBtn.addEventListener("click", function () {
    if (els.resendBtn.disabled) return;
    requestCode(state.pendingPhone, true);
  });

  els.messageForm.addEventListener("submit", function (e) {
    e.preventDefault();
    sendMessage(els.textInput.value);
  });

  els.locationBtn.addEventListener("click", shareLocation);

  els.uploadInput.addEventListener("change", function () {
    var file = els.uploadInput.files && els.uploadInput.files[0];
    uploadFile(file);
    els.uploadInput.value = "";
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && widget.getAttribute("data-state") === "open") closePanel();
  });

  // ---------------------------------------------------------------- bootstrap

  apiFetch("/webchat/session/").then(function (res) {
    if (res.data && res.data.verified) {
      onVerified();
    }
  });
})();
