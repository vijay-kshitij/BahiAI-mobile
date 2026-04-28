(function () {
  "use strict";

  // ── Config ──
  const SERVER_URL = window.location.origin;
  const SUGGESTIONS = [
    "Create an invoice for Priya Patel for 2 laptops at 75000 each",
    "Show me unpaid invoices",
    "Record payment for Rajesh's invoice",
    "List all customers",
  ];
  const LANGUAGES = { "en-IN": "English", "hi-IN": "Hindi" };
  const STORAGE_KEY = "bahi_chat_state";

  // ── State ──
  let persisted = {};
  try { persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); } catch (_) { persisted = {}; }

  let conversationId = persisted.conversationId || null;
  let selectedLanguage = persisted.selectedLanguage && persisted.selectedLanguage in LANGUAGES
    ? persisted.selectedLanguage : "en-IN";
  let voiceEnabled = typeof persisted.voiceEnabled === "boolean" ? persisted.voiceEnabled : true;
  let chatTranscript = Array.isArray(persisted.chatTranscript) ? persisted.chatTranscript : [];
  let pendingState = persisted.pendingState || null;
  let isLoading = false;
  let isListening = false;
  let mediaRecorder = null;
  let mediaStream = null;
  let recordedChunks = [];
  let currentAudio = null;
  let currentAudioUrl = null;
  let abortController = null;
  let audioUnlocked = false;
  let audioContext = null;

  // ── Elements ──
  const messagesEl = document.getElementById("messages");
  const inputEl = document.getElementById("input");
  const sendBtn = document.getElementById("send-btn");
  const micBtn = document.getElementById("mic-btn");
  const langSelect = document.getElementById("lang-select");
  const clearBtn = document.getElementById("clear-btn");
  const voiceToggle = document.getElementById("voice-toggle");
  const pendingBannerEl = document.getElementById("pending-banner");
  const pendingTextEl = document.getElementById("pending-banner-text");
  const pendingConfirmBtn = document.getElementById("pending-confirm");
  const pendingCancelBtn = document.getElementById("pending-cancel");

  // ── Persistence ──
  function save() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        conversationId: conversationId,
        selectedLanguage: selectedLanguage,
        voiceEnabled: voiceEnabled,
        chatTranscript: chatTranscript.slice(-100),
        pendingState: pendingState,
      }));
    } catch (_) {}
  }

  function setPending(pending) {
    pendingState = pending || null;
    if (pendingState && pendingState.summary) {
      pendingTextEl.textContent = pendingState.summary;
      pendingBannerEl.classList.add("visible");
    } else {
      pendingTextEl.textContent = "";
      pendingBannerEl.classList.remove("visible");
    }
    save();
  }

  // ── HTML Escaping ──
  function escapeHtml(text) {
    var div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function formatBotText(text) {
    var escaped = escapeHtml(text);
    return escaped
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br>");
  }

  // ── Status helpers ──
  function statusClass(status) {
    if (!status) return "status-draft";
    var s = status.toLowerCase();
    if (s === "paid") return "status-paid";
    if (s === "unpaid") return "status-unpaid";
    if (s === "overdue") return "status-overdue";
    if (s.indexOf("partly") >= 0) return "status-partly-paid";
    return "status-draft";
  }

  // ── Welcome ──
  function renderWelcome() {
    return '<div class="welcome">' +
      '<div class="welcome-emoji">&#128075;</div>' +
      '<strong>Hi! I\'m Akash.</strong><br>' +
      'I can help you create invoices, record payments, and manage customers.<br>' +
      '<div class="suggestions">' +
      SUGGESTIONS.map(function (s) {
        return '<button class="suggestion" type="button" data-suggestion="' + escapeHtml(s) + '">' + escapeHtml(s) + '</button>';
      }).join("") +
      '</div></div>';
  }

  // ── Render transcript from saved state ──
  function renderTranscript() {
    if (!chatTranscript.length) {
      messagesEl.innerHTML = renderWelcome();
      return;
    }
    messagesEl.innerHTML = "";
    chatTranscript.forEach(function (entry) {
      if (entry.type === "message") appendMessageDOM(entry.text, entry.sender, false);
      else if (entry.type === "system") appendSystemDOM(entry.text, false);
      else if (entry.type === "invoice-card") appendInvoiceCardDOM(entry.data, false);
      else if (entry.type === "payment-card") appendPaymentCardDOM(entry.data, false);
      else if (entry.type === "send-invoice") appendSendInvoiceCardDOM(entry.data, false);
    });
    scrollBottom();
  }

  // ── DOM helpers ──
  function removeWelcome() {
    var w = messagesEl.querySelector(".welcome");
    if (w) w.remove();
  }

  function scrollBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function appendMessageDOM(text, sender, doScroll) {
    removeWelcome();
    var row = document.createElement("div");
    row.className = "msg-row msg-row-" + sender;

    var msg = document.createElement("div");
    msg.className = "msg msg-" + sender;
    if (sender === "bot") {
      msg.innerHTML = formatBotText(text);
    } else {
      msg.textContent = text;
    }

    var avatar = document.createElement("div");
    avatar.className = "avatar avatar-" + sender;
    if (sender === "bot") {
      avatar.textContent = "N";
      row.appendChild(avatar);
      row.appendChild(msg);
    } else {
      avatar.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 12c2.76 0 5-2.24 5-5S14.76 2 12 2 7 4.24 7 7s2.24 5 5 5zm0 2c-3.33 0-10 1.67-10 5v1h20v-1c0-3.33-6.67-5-10-5z"/></svg>';
      row.appendChild(msg);
      row.appendChild(avatar);
    }

    messagesEl.appendChild(row);
    if (doScroll !== false) scrollBottom();
  }

  function appendSystemDOM(text, doScroll) {
    removeWelcome();
    var el = document.createElement("div");
    el.className = "system-msg";
    el.textContent = text;
    messagesEl.appendChild(el);
    if (doScroll !== false) scrollBottom();
  }

  function appendInvoiceCardDOM(data, doScroll) {
    removeWelcome();
    var row = document.createElement("div");
    row.className = "msg-row msg-row-bot";

    var avatar = document.createElement("div");
    avatar.className = "avatar avatar-bot";
    avatar.textContent = "N";

    var card = document.createElement("div");
    card.className = "invoice-card";

    var status = data.status || "Draft";
    var sClass = statusClass(status);

    card.innerHTML =
      '<div class="invoice-card-header">' +
        '<span class="invoice-card-id">' + escapeHtml(data.name || "Invoice") + '</span>' +
        '<span class="invoice-card-status ' + sClass + '">' + escapeHtml(status) + '</span>' +
      '</div>' +
      '<div class="invoice-card-row"><span>Customer</span><span>' + escapeHtml(data.customer || "-") + '</span></div>' +
      '<div class="invoice-card-row"><span>Date</span><span>' + escapeHtml(data.posting_date || "-") + '</span></div>' +
      (data.due_date ? '<div class="invoice-card-row"><span>Due</span><span>' + escapeHtml(data.due_date) + '</span></div>' : '') +
      (data.outstanding_amount !== undefined ? '<div class="invoice-card-row"><span>Outstanding</span><span>' + escapeHtml("\u20B9" + data.outstanding_amount) + '</span></div>' : '') +
      '<div class="invoice-card-total"><span>Total</span><span>' + escapeHtml("\u20B9" + (data.grand_total || 0)) + '</span></div>' +
      (data.name ? '<div class="invoice-card-actions"><a class="invoice-card-btn invoice-card-btn-primary" href="/invoice/' + encodeURIComponent(data.name) + '">View Invoice</a></div>' : '');

    row.appendChild(avatar);
    row.appendChild(card);
    messagesEl.appendChild(row);
    if (doScroll !== false) scrollBottom();
  }

  function appendSendInvoiceCardDOM(data, doScroll) {
    removeWelcome();
    var row = document.createElement("div");
    row.className = "msg-row msg-row-bot";

    var avatar = document.createElement("div");
    avatar.className = "avatar avatar-bot";
    avatar.textContent = "N";

    var card = document.createElement("div");
    card.className = "invoice-card";

    var origin = window.location.origin;
    var previewUrl = data.preview_path ? origin + data.preview_path : "";
    var message = "Hi " + (data.customer || "") + ", here's your invoice " +
      (data.invoice_name || "") + " for \u20B9" + (data.grand_total || 0) + "." +
      (previewUrl ? "\nView: " + previewUrl : "");
    var whatsappUrl = "https://wa.me/" + encodeURIComponent(data.phone || "") +
      "?text=" + encodeURIComponent(message);

    card.innerHTML =
      '<div class="invoice-card-header">' +
        '<span class="invoice-card-id">Send ' + escapeHtml(data.invoice_name || "") + '</span>' +
        '<span class="invoice-card-status status-draft">Draft</span>' +
      '</div>' +
      '<div class="invoice-card-row"><span>To</span><span>' + escapeHtml(data.customer || "-") + '</span></div>' +
      '<div class="invoice-card-row"><span>Number</span><span>+' + escapeHtml(data.phone || "-") + '</span></div>' +
      '<div class="invoice-card-total"><span>Amount</span><span>' + escapeHtml("\u20B9" + (data.grand_total || 0)) + '</span></div>' +
      '<div class="invoice-card-actions">' +
        '<a class="invoice-card-btn" href="' + previewUrl + '" target="_blank" rel="noopener">Preview</a>' +
        '<a class="invoice-card-btn invoice-card-btn-primary send-wa-btn" data-invoice="' + escapeHtml(data.invoice_name || "") + '" href="' + whatsappUrl + '" target="_blank" rel="noopener">Send on WhatsApp</a>' +
      '</div>';

    row.appendChild(avatar);
    row.appendChild(card);
    messagesEl.appendChild(row);
    if (doScroll !== false) scrollBottom();
  }

  function appendPaymentCardDOM(data, doScroll) {
    removeWelcome();
    var row = document.createElement("div");
    row.className = "msg-row msg-row-bot";

    var avatar = document.createElement("div");
    avatar.className = "avatar avatar-bot";
    avatar.textContent = "N";

    var card = document.createElement("div");
    card.className = "payment-card";
    card.innerHTML =
      '<div class="payment-card-header"><svg width="16" height="16" viewBox="0 0 24 24" fill="#166534"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg> Payment Recorded</div>' +
      '<div class="payment-card-row"><span>Invoice</span><span>' + escapeHtml(data.invoice_name || "-") + '</span></div>' +
      '<div class="payment-card-row"><span>Customer</span><span>' + escapeHtml(data.customer || "-") + '</span></div>' +
      '<div class="payment-card-row"><span>Amount</span><span>' + escapeHtml("\u20B9" + (data.amount || 0)) + '</span></div>' +
      '<div class="payment-card-row"><span>Mode</span><span>' + escapeHtml(data.mode_of_payment || "Cash") + '</span></div>' +
      '<div class="payment-card-row"><span>Remaining</span><span>' + escapeHtml("\u20B9" + (data.outstanding_after || 0)) + '</span></div>';

    row.appendChild(avatar);
    row.appendChild(card);
    messagesEl.appendChild(row);
    if (doScroll !== false) scrollBottom();
  }

  // ── Add to transcript ──
  function addMessage(text, sender) {
    appendMessageDOM(text, sender);
    chatTranscript.push({ type: "message", sender: sender, text: text });
    if (chatTranscript.length > 100) chatTranscript = chatTranscript.slice(-100);
    save();
  }

  function addSystem(text) {
    appendSystemDOM(text);
    chatTranscript.push({ type: "system", text: text });
    if (chatTranscript.length > 100) chatTranscript = chatTranscript.slice(-100);
    save();
  }

  function addInvoiceCard(data) {
    appendInvoiceCardDOM(data);
    chatTranscript.push({ type: "invoice-card", data: data });
    if (chatTranscript.length > 100) chatTranscript = chatTranscript.slice(-100);
    save();
  }

  function addPaymentCard(data) {
    appendPaymentCardDOM(data);
    chatTranscript.push({ type: "payment-card", data: data });
    if (chatTranscript.length > 100) chatTranscript = chatTranscript.slice(-100);
    save();
  }

  function addSendInvoiceCard(data) {
    appendSendInvoiceCardDOM(data);
    chatTranscript.push({ type: "send-invoice", data: data });
    if (chatTranscript.length > 100) chatTranscript = chatTranscript.slice(-100);
    save();
  }

  // ── Typing indicator ──
  function showTyping() {
    var el = document.createElement("div");
    el.className = "typing";
    el.id = "typing-indicator";
    el.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
    messagesEl.appendChild(el);
    scrollBottom();
  }

  function removeTyping() {
    var el = document.getElementById("typing-indicator");
    if (el) el.remove();
  }

  // ── Send/stop button state ──
  function updateSendBtn() {
    sendBtn.classList.toggle("loading", isLoading);
    sendBtn.setAttribute("aria-label", isLoading ? "Stop" : "Send");
    sendBtn.innerHTML = isLoading
      ? '<svg viewBox="0 0 24 24"><path d="M7 7h10v10H7z"/></svg>'
      : '<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>';
  }

  function stopAgent() {
    if (!isLoading) return;
    if (abortController) { abortController.abort(); abortController = null; }
    removeTyping();
    isLoading = false;
    updateSendBtn();
    inputEl.focus();
  }

  // ── Audio ──
  // iOS needs HTMLAudio elements to be .play()'d synchronously inside a user
  // gesture at least once per session. We reuse the same element for all TTS
  // playback so it stays "primed" across the async fetch/play gap.
  var primedPlayer = null;
  var SILENT_WAV = "data:audio/wav;base64,UklGRjIAAABXQVZFZm10IBIAAAABAAEAQB8AAEAfAAABAAgAAABmYWN0BAAAAAAAAABkYXRhAAAAAA==";

  function unlockAudio() {
    if (audioUnlocked) return;
    try {
      if (!primedPlayer) {
        primedPlayer = new Audio();
        primedPlayer.preload = "auto";
      }
      primedPlayer.src = SILENT_WAV;
      var p = primedPlayer.play();
      if (p && typeof p.then === "function") {
        p.then(function () { audioUnlocked = true; })
         .catch(function (err) { console.warn("HTMLAudio unlock rejected:", err); });
      } else {
        audioUnlocked = true;
      }

      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (Ctx) {
        audioContext = audioContext || new Ctx();
        if (audioContext.state === "suspended") audioContext.resume().catch(function () {});
      }
    } catch (err) {
      console.warn("Audio unlock failed:", err);
    }
  }

  function stopSpeaking() {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    if (currentAudio) {
      try { currentAudio.pause(); currentAudio.currentTime = 0; } catch (_) {}
      currentAudio = null;
    }
    if (currentAudioUrl) { URL.revokeObjectURL(currentAudioUrl); currentAudioUrl = null; }
  }

  function speakBrowser(text) {
    if (!("speechSynthesis" in window)) return;
    var clean = text.replace(/\*\*/g, "").replace(/<br>/g, " ").replace(/\s+/g, " ").trim();
    if (!clean) return;
    var utt = new SpeechSynthesisUtterance(clean);
    utt.lang = selectedLanguage;
    window.speechSynthesis.speak(utt);
  }

  async function speakReply(text) {
    if (!voiceEnabled) return;
    stopSpeaking();
    var clean = text.replace(/\*\*/g, "").replace(/<br>/g, " ").replace(/\s+/g, " ").trim();
    if (!clean) return;

    try {
      var resp = await fetch(SERVER_URL + "/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: clean, language: selectedLanguage }),
      });
      if (!resp.ok) throw new Error("TTS " + resp.status);
      var blob = await resp.blob();
      var url = URL.createObjectURL(blob);
      currentAudioUrl = url;
      if (!primedPlayer) primedPlayer = new Audio();
      currentAudio = primedPlayer;
      currentAudio.onended = function () { if (currentAudioUrl) { URL.revokeObjectURL(currentAudioUrl); currentAudioUrl = null; } currentAudio = null; };
      currentAudio.onerror = function () { if (currentAudioUrl) { URL.revokeObjectURL(currentAudioUrl); currentAudioUrl = null; } currentAudio = null; speakBrowser(clean); };
      currentAudio.src = url;
      try {
        await currentAudio.play();
      } catch (playErr) {
        console.warn("Audio play rejected:", playErr);
        speakBrowser(clean);
      }
    } catch (_) {
      speakBrowser(clean);
    }
  }

  // ── Voice input ──
  function updateMic() {
    micBtn.classList.toggle("listening", isListening);
    micBtn.setAttribute("aria-label", isListening ? "Stop listening" : "Voice input");
  }

  function pickMimeType() {
    if (typeof MediaRecorder === "undefined") return "";
    var candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/aac", "audio/mpeg"];
    for (var i = 0; i < candidates.length; i++) {
      if (MediaRecorder.isTypeSupported(candidates[i])) return candidates[i];
    }
    return "";
  }

  function releaseStream() {
    if (mediaStream) {
      mediaStream.getTracks().forEach(function (t) { t.stop(); });
      mediaStream = null;
    }
  }

  function stopListening() {
    if (!mediaRecorder || mediaRecorder.state === "inactive") {
      isListening = false; updateMic();
      return;
    }
    try { mediaRecorder.stop(); } catch (_) {}
    isListening = false;
    updateMic();
  }

  async function transcribeAndSend(blob) {
    if (!blob || blob.size === 0) {
      addSystem("Didn't catch that — try again.");
      return;
    }
    addSystem("Transcribing...");
    var form = new FormData();
    var ext = (blob.type && blob.type.indexOf("mp4") >= 0) ? "mp4"
            : (blob.type && blob.type.indexOf("mpeg") >= 0) ? "mp3"
            : "webm";
    form.append("file", blob, "voice." + ext);

    try {
      var resp = await fetch(SERVER_URL + "/api/voice/transcribe?language=" + encodeURIComponent(selectedLanguage), {
        method: "POST",
        body: form,
      });
      if (!resp.ok) {
        var errText = await resp.text().catch(function () { return ""; });
        throw new Error("Transcribe " + resp.status + " " + errText);
      }
      var data = await resp.json();
      var text = (data.text || "").trim();
      if (!text) { addSystem("Didn't catch that — try again."); return; }
      inputEl.value = text;
      sendMessage();
    } catch (err) {
      console.error("Transcribe failed:", err);
      addSystem("Transcription failed. Check your connection or API key.");
    }
  }

  async function startListening() {
    if (isLoading) return;
    if (isListening) { stopListening(); return; }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      addSystem("Voice input not supported on this browser.");
      return;
    }
    if (typeof MediaRecorder === "undefined") {
      addSystem("Voice recording not supported on this browser.");
      return;
    }

    stopSpeaking();

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      console.error("getUserMedia failed:", err);
      var msg = "Microphone access denied.";
      if (err && err.name === "NotFoundError") msg = "No microphone found.";
      else if (err && err.name === "NotAllowedError") msg = "Microphone permission denied — allow it in browser settings.";
      else if (err && err.message) msg = "Mic error: " + err.message;
      addSystem(msg);
      return;
    }

    var mimeType = pickMimeType();
    try {
      mediaRecorder = mimeType ? new MediaRecorder(mediaStream, { mimeType: mimeType })
                               : new MediaRecorder(mediaStream);
    } catch (err) {
      console.error("MediaRecorder init failed:", err);
      addSystem("Could not start recording: " + (err && err.message ? err.message : err));
      releaseStream();
      return;
    }

    recordedChunks = [];
    mediaRecorder.ondataavailable = function (e) {
      if (e.data && e.data.size > 0) recordedChunks.push(e.data);
    };
    mediaRecorder.onstop = function () {
      var type = mediaRecorder.mimeType || mimeType || "audio/webm";
      var blob = new Blob(recordedChunks, { type: type });
      recordedChunks = [];
      releaseStream();
      transcribeAndSend(blob);
    };
    mediaRecorder.onerror = function (e) {
      console.error("MediaRecorder error:", e);
      addSystem("Recording error.");
      releaseStream();
      isListening = false; updateMic();
    };

    try {
      mediaRecorder.start();
      isListening = true;
      updateMic();
      addSystem("Listening… tap the mic again to stop.");
    } catch (err) {
      console.error("mediaRecorder.start threw:", err);
      addSystem("Couldn't start mic: " + (err && err.message ? err.message : err));
      releaseStream();
      isListening = false; updateMic();
    }
  }

  // ── Send message ──
  async function sendMessage() {
    var text = inputEl.value.trim();
    if (!text || isLoading) return;

    addMessage(text, "user");
    inputEl.value = "";
    isLoading = true;
    abortController = new AbortController();
    updateSendBtn();
    showTyping();

    try {
      var resp = await fetch(SERVER_URL + "/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: abortController.signal,
        body: JSON.stringify({
          message: text,
          conversation_id: conversationId,
          language: selectedLanguage,
        }),
      });

      if (!resp.ok) throw new Error("Server " + resp.status);
      var data = await resp.json();
      conversationId = data.conversation_id;
      save();
      removeTyping();

      // Handle actions from server
      if (data.actions && data.actions.length) {
        data.actions.forEach(function (action) {
          if (action.type === "invoice-card") addInvoiceCard(action.data);
          else if (action.type === "payment-card") addPaymentCard(action.data);
          else if (action.type === "send-invoice") addSendInvoiceCard(action.data);
          else if (action.type === "system") addSystem(action.text || "");
          else if (action.type === "navigate") {
            // Navigate after a short delay so the user sees the reply first
            setTimeout(function () { window.location.href = action.path; }, 800);
          }
        });
      }

      setPending(data.pending || null);

      addMessage(data.reply, "bot");
      await speakReply(data.spoken_reply || data.reply);
    } catch (err) {
      removeTyping();
      if (err && err.name === "AbortError") {
        addSystem("Response stopped.");
      } else {
        addMessage("Sorry, something went wrong. Please try again.", "bot");
      }
    } finally {
      abortController = null;
      isLoading = false;
      updateSendBtn();
      inputEl.focus();
    }
  }

  // ── Clear chat ──
  function clearChat() {
    stopListening();
    stopSpeaking();
    chatTranscript = [];
    setPending(null);
    messagesEl.innerHTML = renderWelcome();
    inputEl.value = "";
    save();
    inputEl.focus();
  }

  function sendQuickReply(text) {
    if (isLoading) return;
    inputEl.value = text;
    sendMessage();
  }

  // ── Events ──
  sendBtn.addEventListener("click", function () {
    unlockAudio();
    if (isLoading) { stopAgent(); return; }
    sendMessage();
  });

  micBtn.addEventListener("click", function () {
    unlockAudio();
    if (isListening) { stopListening(); return; }
    startListening();
  });

  langSelect.addEventListener("change", function (e) {
    selectedLanguage = e.target.value;
    save();
    stopSpeaking();
  });

  voiceToggle.addEventListener("click", function () {
    voiceEnabled = !voiceEnabled;
    if (!voiceEnabled) stopSpeaking();
    voiceToggle.classList.toggle("muted", !voiceEnabled);
    save();
  });

  clearBtn.addEventListener("click", clearChat);

  pendingConfirmBtn.addEventListener("click", function () {
    unlockAudio();
    sendQuickReply(selectedLanguage === "hi-IN" ? "haan kar do" : "yes, go ahead");
  });

  pendingCancelBtn.addEventListener("click", function () {
    unlockAudio();
    sendQuickReply(selectedLanguage === "hi-IN" ? "rehne do" : "cancel");
  });

  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  messagesEl.addEventListener("click", function (e) {
    var waBtn = e.target.closest(".send-wa-btn");
    if (waBtn) {
      var invoiceName = waBtn.getAttribute("data-invoice");
      if (invoiceName && !waBtn.dataset.marked) {
        waBtn.dataset.marked = "1";
        fetch(SERVER_URL + "/api/invoice/" + encodeURIComponent(invoiceName) + "/mark-sent", {
          method: "POST",
        }).then(function (r) { return r.ok ? r.json() : null; })
          .then(function (data) {
            if (!data) return;
            var status = data.invoice_status || "Unpaid";
            var card = waBtn.closest(".invoice-card");
            if (card) {
              var badge = card.querySelector(".invoice-card-status");
              if (badge) {
                badge.textContent = status;
                badge.className = "invoice-card-status " + statusClass(status);
              }
            }
            addSystem("Invoice " + invoiceName + " marked as " + status + ".");
          })
          .catch(function () {});
      }
      return; // Let the default anchor navigation proceed (opens WhatsApp)
    }

    var btn = e.target.closest(".suggestion");
    if (!btn || isLoading) return;
    unlockAudio();
    inputEl.value = btn.getAttribute("data-suggestion");
    sendMessage();
  });

  // ── Init ──
  var hasMic = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) && typeof MediaRecorder !== "undefined";
  micBtn.disabled = !hasMic;
  langSelect.value = selectedLanguage;
  voiceToggle.classList.toggle("muted", !voiceEnabled);
  setPending(pendingState);
  renderTranscript();
  if ("speechSynthesis" in window) { window.speechSynthesis.getVoices(); }
})();
