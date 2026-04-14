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
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const STORAGE_KEY = "navi_chat_state";

  // ── State ──
  let persisted = {};
  try { persisted = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "{}"); } catch (_) { persisted = {}; }

  let conversationId = persisted.conversationId || null;
  let selectedLanguage = persisted.selectedLanguage && persisted.selectedLanguage in LANGUAGES
    ? persisted.selectedLanguage : "en-IN";
  let voiceEnabled = typeof persisted.voiceEnabled === "boolean" ? persisted.voiceEnabled : true;
  let chatTranscript = Array.isArray(persisted.chatTranscript) ? persisted.chatTranscript : [];
  let isLoading = false;
  let isListening = false;
  let recognition = null;
  let currentAudio = null;
  let currentAudioUrl = null;
  let abortController = null;

  // ── Elements ──
  const messagesEl = document.getElementById("messages");
  const inputEl = document.getElementById("input");
  const sendBtn = document.getElementById("send-btn");
  const micBtn = document.getElementById("mic-btn");
  const langSelect = document.getElementById("lang-select");
  const clearBtn = document.getElementById("clear-btn");
  const voiceToggle = document.getElementById("voice-toggle");

  // ── Persistence ──
  function save() {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
        conversationId: conversationId,
        selectedLanguage: selectedLanguage,
        voiceEnabled: voiceEnabled,
        chatTranscript: chatTranscript.slice(-100),
      }));
    } catch (_) {}
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
      '<strong>Hi! I\'m Navi.</strong><br>' +
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
  function stopSpeaking() {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    if (currentAudio) { currentAudio.pause(); currentAudio.currentTime = 0; currentAudio = null; }
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
      currentAudio = new Audio(url);
      currentAudio.onended = function () { URL.revokeObjectURL(url); currentAudio = null; currentAudioUrl = null; };
      currentAudio.onerror = function () { URL.revokeObjectURL(url); currentAudio = null; currentAudioUrl = null; speakBrowser(clean); };
      await currentAudio.play();
    } catch (_) {
      speakBrowser(clean);
    }
  }

  // ── Voice input ──
  function updateMic() {
    micBtn.classList.toggle("listening", isListening);
    micBtn.setAttribute("aria-label", isListening ? "Stop listening" : "Voice input");
  }

  function stopListening() {
    if (!recognition || !isListening) return;
    isListening = false;
    updateMic();
    recognition.stop();
  }

  function startListening() {
    if (!SpeechRecognition) { addSystem("Voice input not supported. Try Chrome or Edge."); return; }
    if (isLoading) return;

    if (!recognition) {
      recognition = new SpeechRecognition();
      recognition.interimResults = true;
      recognition.continuous = false;

      recognition.onstart = function () { isListening = true; updateMic(); addSystem(selectedLanguage === "hi-IN" ? "Listening..." : "Listening..."); };
      recognition.onresult = function (e) {
        var text = "";
        for (var i = e.resultIndex; i < e.results.length; i++) text += e.results[i][0].transcript;
        inputEl.value = text.trim();
        if (e.results[e.results.length - 1].isFinal) sendMessage();
      };
      recognition.onerror = function (e) {
        isListening = false; updateMic();
        if (e.error !== "aborted") addSystem("Voice input failed.");
      };
      recognition.onend = function () { isListening = false; updateMic(); };
    }

    recognition.lang = selectedLanguage;
    stopSpeaking();
    recognition.start();
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
          else if (action.type === "navigate") {
            // Navigate after a short delay so the user sees the reply first
            setTimeout(function () { window.location.href = action.path; }, 800);
          }
        });
      }

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
    conversationId = null;
    chatTranscript = [];
    messagesEl.innerHTML = renderWelcome();
    inputEl.value = "";
    save();
    inputEl.focus();
  }

  // ── Events ──
  sendBtn.addEventListener("click", function () {
    if (isLoading) { stopAgent(); return; }
    sendMessage();
  });

  micBtn.addEventListener("click", function () {
    if (isListening) { stopListening(); return; }
    startListening();
  });

  langSelect.addEventListener("change", function (e) {
    selectedLanguage = e.target.value;
    save();
    stopSpeaking();
    if (isListening) { stopListening(); startListening(); }
  });

  voiceToggle.addEventListener("click", function () {
    voiceEnabled = !voiceEnabled;
    if (!voiceEnabled) stopSpeaking();
    voiceToggle.classList.toggle("muted", !voiceEnabled);
    save();
  });

  clearBtn.addEventListener("click", clearChat);

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
    inputEl.value = btn.getAttribute("data-suggestion");
    sendMessage();
  });

  // ── Init ──
  micBtn.disabled = !SpeechRecognition;
  langSelect.value = selectedLanguage;
  voiceToggle.classList.toggle("muted", !voiceEnabled);
  renderTranscript();
  if ("speechSynthesis" in window) { window.speechSynthesis.getVoices(); }
})();
