/**
 * Bahi Chat Widget
 * Drop this script into any website to add an AI copilot.
 * 
 * Usage:
 * <script src="http://localhost:3000/widget.js" data-server="http://localhost:3000"></script>
 */

(function () {
  // Configuration
  const scriptTag = document.currentScript;
  const SERVER_URL = (scriptTag && scriptTag.getAttribute("data-server")) || window.location.origin;
  const WIDGET_TITLE = (scriptTag && scriptTag.getAttribute("data-title")) || "Bahi";
  const ERP_NEXT_ORIGIN =
    (scriptTag && scriptTag.getAttribute("data-erpnext-origin")) ||
    window.location.origin;
  const APP_BOOT_ID = (scriptTag && scriptTag.getAttribute("data-boot-id")) || "default";
  const SUGGESTIONS = [
    "Create an invoice for Priya Patel for 2 items",
    "Show me unpaid sales invoices",
    "What is the stock balance for Laptop?",
    "Show me low stock items",
  ];
  const LANGUAGES = {
    "en-IN": "English",
    "hi-IN": "Hindi",
  };
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const STORAGE_KEY = `bahi_widget_state_${APP_BOOT_ID}`;
  let persistedState = {};
  try {
    persistedState = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || "{}");
  } catch (error) {
    persistedState = {};
  }

  let conversationId = persistedState.conversationId || null;
  let isOpen = Boolean(persistedState.isOpen);
  let isLoading = false;
  let isListening = false;
  let selectedLanguage =
    persistedState.selectedLanguage && persistedState.selectedLanguage in LANGUAGES
      ? persistedState.selectedLanguage
      : "en-IN";
  let voiceRepliesEnabled =
    typeof persistedState.voiceRepliesEnabled === "boolean"
      ? persistedState.voiceRepliesEnabled
      : true;
  let transcript = Array.isArray(persistedState.transcript) ? persistedState.transcript : [];
  let recognition = null;
  let currentAudio = null;
  let currentAudioUrl = null;
  let currentChatController = null;

  // ─────────────────────────────────────────
  // STYLES
  // ─────────────────────────────────────────

  const styles = document.createElement("style");
  styles.textContent = `
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&display=swap');

    #bahi-widget-container * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
      font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* ── Floating Button ── */
    #bahi-fab {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 56px;
      height: 56px;
      border-radius: 16px;
      background: #1a1a2e;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 24px rgba(0, 0, 0, 0.25), 0 0 0 1px rgba(255,255,255,0.05);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
      z-index: 99999;
    }

    #bahi-fab:hover {
      transform: translateY(-2px);
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3), 0 0 0 1px rgba(255,255,255,0.08);
    }

    #bahi-fab svg {
      width: 24px;
      height: 24px;
      fill: white;
      transition: transform 0.3s ease;
    }

    #bahi-fab.open svg {
      transform: rotate(90deg);
    }

    /* ── Chat Window ── */
    #bahi-chat {
      position: fixed;
      bottom: 92px;
      right: 24px;
      width: 380px;
      height: 520px;
      background: #ffffff;
      border-radius: 16px;
      box-shadow: 0 12px 48px rgba(0, 0, 0, 0.15), 0 0 0 1px rgba(0,0,0,0.06);
      display: none;
      flex-direction: column;
      overflow: hidden;
      z-index: 99998;
      animation: bahi-slide-up 0.25s ease-out;
    }

    #bahi-chat.visible {
      display: flex;
    }

    @keyframes bahi-slide-up {
      from {
        opacity: 0;
        transform: translateY(12px) scale(0.97);
      }
      to {
        opacity: 1;
        transform: translateY(0) scale(1);
      }
    }

    /* ── Header ── */
    #bahi-header {
      padding: 16px 20px;
      background: #1a1a2e;
      color: white;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    #bahi-header-main {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }

    #bahi-header-icon {
      width: 32px;
      height: 32px;
      background: rgba(255,255,255,0.12);
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    #bahi-header-icon svg {
      width: 18px;
      height: 18px;
      fill: #6ee7b7;
    }

    #bahi-header-info h3 {
      font-size: 14px;
      font-weight: 600;
      letter-spacing: -0.01em;
      margin: 0;
      color: #ffffff;
    }

    #bahi-header-info p {
      font-size: 11px;
      opacity: 0.6;
      margin-top: 1px;
      margin-bottom: 0;
      color: rgba(255,255,255,0.82);
    }

    #bahi-header-controls {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }

    #bahi-language {
      border: 1px solid rgba(255,255,255,0.18);
      background: rgba(255,255,255,0.08);
      color: white;
      border-radius: 10px;
      font-size: 11px;
      padding: 6px 8px;
      outline: none;
      cursor: pointer;
    }

    #bahi-language option {
      color: #1a1a2e;
    }

    .bahi-icon-btn {
      width: 32px;
      height: 32px;
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,0.18);
      background: rgba(255,255,255,0.08);
      color: white;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: background 0.15s ease, transform 0.15s ease;
    }

    .bahi-icon-btn:hover {
      background: rgba(255,255,255,0.16);
      transform: translateY(-1px);
    }

    .bahi-icon-btn svg {
      width: 16px;
      height: 16px;
      fill: currentColor;
    }

    .bahi-icon-btn.active {
      background: #ef4444;
      border-color: #ef4444;
    }

    .bahi-icon-btn.muted {
      opacity: 0.65;
    }

    /* ── Messages Area ── */
    #bahi-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      background: #fafafa;
    }

    #bahi-messages::-webkit-scrollbar {
      width: 4px;
    }

    #bahi-messages::-webkit-scrollbar-thumb {
      background: #ddd;
      border-radius: 4px;
    }

    .bahi-msg-row {
      max-width: 100%;
      display: flex;
      align-items: flex-end;
      gap: 8px;
    }

    .bahi-msg-row-user {
      align-self: flex-end;
      justify-content: flex-end;
    }

    .bahi-msg-row-bot,
    .bahi-msg-row-nav {
      align-self: flex-start;
      justify-content: flex-start;
    }

    .bahi-avatar {
      width: 28px;
      height: 28px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
    }

    .bahi-avatar-bot {
      background: linear-gradient(135deg, #1a1a2e 0%, #31456a 100%);
      color: #ffffff;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: -0.02em;
    }

    .bahi-avatar-user {
      background: #e0f2fe;
      color: #0f172a;
      border: 1px solid #bae6fd;
    }

    .bahi-avatar-user svg {
      width: 15px;
      height: 15px;
      fill: currentColor;
    }

    .bahi-msg {
      max-width: 85%;
      padding: 10px 14px;
      border-radius: 14px;
      font-size: 13.5px;
      line-height: 1.5;
      word-wrap: break-word;
      box-shadow: 0 6px 20px rgba(15, 23, 42, 0.05);
    }

    .bahi-msg-user {
      background: #e0f2fe;
      color: #111827;
      border: 1px solid #bae6fd;
      border-bottom-right-radius: 4px;
    }

    .bahi-msg-bot {
      background: #ffffff;
      color: #111827;
      border: 1px solid #e8e8ec;
      border-bottom-left-radius: 4px;
    }

    .bahi-msg-bot strong {
      font-weight: 600;
    }

    /* ── Navigation Message ── */
    .bahi-msg-nav {
      background: #ffffff;
      color: #111827;
      padding: 10px 14px;
      border-radius: 14px;
      border-bottom-left-radius: 4px;
      max-width: 85%;
      font-size: 13px;
      border: 1px solid #e8e8ec;
      box-shadow: 0 6px 20px rgba(15, 23, 42, 0.05);
    }

    /* ── Typing Indicator ── */
    .bahi-typing {
      align-self: flex-start;
      display: flex;
      gap: 4px;
      padding: 12px 16px;
      background: #ffffff;
      border: 1px solid #e8e8ec;
      border-radius: 14px;
      border-bottom-left-radius: 4px;
    }

    .bahi-typing-dot {
      width: 6px;
      height: 6px;
      background: #aaa;
      border-radius: 50%;
      animation: bahi-bounce 1.2s ease-in-out infinite;
    }

    .bahi-typing-dot:nth-child(2) { animation-delay: 0.15s; }
    .bahi-typing-dot:nth-child(3) { animation-delay: 0.3s; }

    @keyframes bahi-bounce {
      0%, 60%, 100% { transform: translateY(0); }
      30% { transform: translateY(-4px); }
    }

    /* ── Input Area ── */
    #bahi-input-area {
      padding: 12px 16px;
      border-top: 1px solid #eee;
      display: flex;
      gap: 8px;
      align-items: center;
      background: white;
    }

    #bahi-input {
      flex: 1;
      border: 1px solid #e0e0e5;
      border-radius: 12px;
      padding: 10px 14px;
      font-size: 13.5px;
      font-family: 'DM Sans', sans-serif;
      outline: none;
      transition: border-color 0.15s;
      background: #fafafa;
    }

    #bahi-input:focus {
      border-color: #1a1a2e;
      background: #fff;
    }

    #bahi-input::placeholder {
      color: #aaa;
    }

    #bahi-send {
      width: 38px;
      height: 38px;
      border-radius: 12px;
      background: #1a1a2e;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: opacity 0.15s;
      flex-shrink: 0;
    }

    #bahi-send:hover {
      opacity: 0.85;
    }

    #bahi-send.loading {
      background: #ef4444;
    }

    #bahi-send:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }

    #bahi-send svg {
      width: 16px;
      height: 16px;
      fill: white;
    }

    #bahi-mic {
      width: 38px;
      height: 38px;
      border-radius: 12px;
      background: #eef2ff;
      border: 1px solid #c7d2fe;
      color: #1a1a2e;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s ease;
      flex-shrink: 0;
    }

    #bahi-mic:hover {
      background: #e0e7ff;
    }

    #bahi-mic.listening {
      background: #ef4444;
      border-color: #ef4444;
      color: white;
      box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.12);
    }

    #bahi-mic:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }

    #bahi-mic svg {
      width: 16px;
      height: 16px;
      fill: currentColor;
    }

    /* ── Welcome Message ── */
    .bahi-welcome {
      text-align: center;
      padding: 24px 16px;
      color: #888;
      font-size: 13px;
      line-height: 1.6;
    }

    .bahi-welcome-emoji {
      font-size: 28px;
      margin-bottom: 8px;
    }

    .bahi-welcome strong {
      color: #1a1a2e;
      font-weight: 600;
    }

    .bahi-suggestions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: center;
      margin-top: 16px;
    }

    .bahi-suggestion {
      border: 1px solid #d7d7df;
      background: white;
      color: #1a1a2e;
      border-radius: 999px;
      font-size: 12px;
      padding: 8px 12px;
      cursor: pointer;
      transition: all 0.15s ease;
    }

    .bahi-suggestion:hover {
      border-color: #1a1a2e;
      transform: translateY(-1px);
    }

    .bahi-system {
      align-self: center;
      background: #eef2ff;
      color: #334155;
      border: 1px solid #dbeafe;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 11px;
      max-width: 90%;
    }

    /* ── Powered By ── */
    #bahi-footer {
      padding: 6px;
      text-align: center;
      font-size: 10px;
      color: #bbb;
      background: white;
    }

    /* ── Mobile ── */
    @media (max-width: 480px) {
      #bahi-chat {
        width: calc(100vw - 16px);
        height: calc(100vh - 120px);
        right: 8px;
        bottom: 80px;
        border-radius: 12px;
      }
    }
  `;
  document.head.appendChild(styles);

  // ─────────────────────────────────────────
  // HTML STRUCTURE
  // ─────────────────────────────────────────

  const container = document.createElement("div");
  container.id = "bahi-widget-container";
  container.innerHTML = `
    <!-- Floating Action Button -->
    <button id="bahi-fab" aria-label="Open Bahi chat">
      <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.2L4 17.2V4h16v12z"/>
        <path d="M7 9h2v2H7zm4 0h2v2h-2zm4 0h2v2h-2z"/>
      </svg>
    </button>

    <!-- Chat Window -->
    <div id="bahi-chat">
      <!-- Header -->
      <div id="bahi-header">
        <div id="bahi-header-main">
          <div id="bahi-header-icon">
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
            </svg>
          </div>
          <div id="bahi-header-info">
            <h3>${WIDGET_TITLE}</h3>
            <p>AI Copilot</p>
          </div>
        </div>
        <div id="bahi-header-controls">
          <select id="bahi-language" aria-label="Language">
            ${Object.entries(LANGUAGES).map(
              ([code, label]) =>
                `<option value="${code}" ${code === selectedLanguage ? "selected" : ""}>${label}</option>`
            ).join("")}
          </select>
          <button id="bahi-clear-chat" class="bahi-icon-btn" type="button" aria-label="Clear chat">
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path d="M9 3h6l1 2h4v2H4V5h4l1-2zm1 6h2v8h-2V9zm4 0h2v8h-2V9zM7 9h2v8H7V9zm-1 12h12a2 2 0 0 0 2-2V8H4v11a2 2 0 0 0 2 2z"/>
            </svg>
          </button>
          <button id="bahi-voice-toggle" class="bahi-icon-btn" type="button" aria-label="Toggle voice replies">
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path d="M14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77zm-2 5.77-3-3v12l3-3h4V9h-4z"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- Messages -->
      <div id="bahi-messages">
        <div class="bahi-welcome">
          <div class="bahi-welcome-emoji">👋</div>
          <strong>Hi! I'm ${WIDGET_TITLE}.</strong><br>
          I can help with invoices and inventory in ERPNext, by text or voice.<br>
          Try one of these demo prompts:
          <div class="bahi-suggestions">
            ${SUGGESTIONS.map(
              (suggestion) =>
                `<button class="bahi-suggestion" type="button" data-suggestion="${suggestion.replace(/"/g, "&quot;")}">${suggestion}</button>`
            ).join("")}
          </div>
        </div>
      </div>

      <!-- Input -->
      <div id="bahi-input-area">
        <input id="bahi-input" type="text" placeholder="Type a message..." autocomplete="off" />
        <button id="bahi-mic" type="button" aria-label="Start voice input">
          <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3zm5-3a1 1 0 1 0-2 0 3 3 0 1 1-6 0 1 1 0 1 0-2 0 5 5 0 0 0 4 4.9V20H9a1 1 0 0 0 0 2h6a1 1 0 0 0 0-2h-2v-2.1A5 5 0 0 0 17 11z"/>
          </svg>
        </button>
        <button id="bahi-send" aria-label="Send message">
          <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
          </svg>
        </button>
      </div>

      <div id="bahi-footer">Powered by Bahi AI</div>
    </div>
  `;
  document.body.appendChild(container);

  // ─────────────────────────────────────────
  // ELEMENTS
  // ─────────────────────────────────────────

  const fab = document.getElementById("bahi-fab");
  const chat = document.getElementById("bahi-chat");
  const messagesDiv = document.getElementById("bahi-messages");
  const input = document.getElementById("bahi-input");
  const micBtn = document.getElementById("bahi-mic");
  const sendBtn = document.getElementById("bahi-send");
  const languageSelect = document.getElementById("bahi-language");
  const clearChatBtn = document.getElementById("bahi-clear-chat");
  const voiceToggleBtn = document.getElementById("bahi-voice-toggle");

  function persistState() {
    try {
      window.sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          conversationId: conversationId,
          isOpen: isOpen,
          selectedLanguage: selectedLanguage,
          voiceRepliesEnabled: voiceRepliesEnabled,
          transcript: transcript.slice(-100),
        })
      );
    } catch (error) {
      console.warn("Bahi state persistence failed:", error);
    }
  }

  function getWelcomeMarkup() {
    return `
      <div class="bahi-welcome">
        <div class="bahi-welcome-emoji">👋</div>
        <strong>Hi! I'm ${WIDGET_TITLE}.</strong><br>
        I can help with invoices and inventory in ERPNext, by text or voice.<br>
        Try one of these demo prompts:
        <div class="bahi-suggestions">
          ${SUGGESTIONS.map(
            (suggestion) =>
              `<button class="bahi-suggestion" type="button" data-suggestion="${suggestion.replace(/"/g, "&quot;")}">${suggestion}</button>`
          ).join("")}
        </div>
      </div>
    `;
  }

  function clearChat() {
    stopListening();
    stopSpeaking();
    conversationId = null;
    transcript = [];
    messagesDiv.innerHTML = getWelcomeMarkup();
    input.value = "";
    persistState();
    if (isOpen) {
      input.focus();
    }
  }

  function updateSendButtonState() {
    sendBtn.classList.toggle("loading", isLoading);
    sendBtn.setAttribute("aria-label", isLoading ? "Stop response" : "Send message");
    sendBtn.innerHTML = isLoading
      ? `
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M7 7h10v10H7z"/>
        </svg>
      `
      : `
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
        </svg>
      `;
  }

  function stopAgentThinking() {
    if (!isLoading) return;
    if (currentChatController) {
      currentChatController.abort();
      currentChatController = null;
    }
    removeTyping();
    isLoading = false;
    updateSendButtonState();
    input.focus();
  }

  // ─────────────────────────────────────────
  // TOGGLE CHAT
  // ─────────────────────────────────────────

  fab.addEventListener("click", function () {
    isOpen = !isOpen;
    chat.classList.toggle("visible", isOpen);
    fab.classList.toggle("open", isOpen);
    persistState();
    if (isOpen) {
      input.focus();
    }
  });

  // ─────────────────────────────────────────
  // ADD MESSAGE TO CHAT
  // ─────────────────────────────────────────

  function addMessage(text, sender) {
    // Remove welcome message on first real message
    const welcome = messagesDiv.querySelector(".bahi-welcome");
    if (welcome) welcome.remove();

    const row = document.createElement("div");
    row.className = `bahi-msg-row bahi-msg-row-${sender}`;
    const msg = document.createElement("div");
    msg.className = `bahi-msg bahi-msg-${sender}`;

    // Simple markdown-like formatting for bot messages
    if (sender === "bot") {
      text = text
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/\n/g, "<br>");
      msg.innerHTML = text;
    } else {
      msg.textContent = text;
    }

    const avatar = document.createElement("div");
    avatar.className = `bahi-avatar bahi-avatar-${sender}`;
    if (sender === "bot") {
      avatar.textContent = "N";
      row.appendChild(avatar);
      row.appendChild(msg);
    } else {
      avatar.innerHTML = `
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 12c2.76 0 5-2.24 5-5S14.76 2 12 2 7 4.24 7 7s2.24 5 5 5zm0 2c-3.33 0-10 1.67-10 5v1h20v-1c0-3.33-6.67-5-10-5z"/>
        </svg>
      `;
      row.appendChild(msg);
      row.appendChild(avatar);
    }

    messagesDiv.appendChild(row);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    transcript.push({ type: "message", sender: sender, text: text });
    if (transcript.length > 100) transcript = transcript.slice(-100);
    persistState();
  }

  function showTyping() {
    const typing = document.createElement("div");
    typing.className = "bahi-typing";
    typing.id = "bahi-typing-indicator";
    typing.innerHTML = `
      <div class="bahi-typing-dot"></div>
      <div class="bahi-typing-dot"></div>
      <div class="bahi-typing-dot"></div>
    `;
    messagesDiv.appendChild(typing);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  }

  function removeTyping() {
    const typing = document.getElementById("bahi-typing-indicator");
    if (typing) typing.remove();
  }

  function addSystemMessage(text) {
    const welcome = messagesDiv.querySelector(".bahi-welcome");
    if (welcome) welcome.remove();

    const msg = document.createElement("div");
    msg.className = "bahi-system";
    msg.textContent = text;
    messagesDiv.appendChild(msg);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    transcript.push({ type: "system", text: text });
    if (transcript.length > 100) transcript = transcript.slice(-100);
    persistState();
  }

  function addNavigationMessage(path, description) {
    const welcome = messagesDiv.querySelector(".bahi-welcome");
    if (welcome) welcome.remove();

    const row = document.createElement("div");
    row.className = "bahi-msg-row bahi-msg-row-nav";
    const msg = document.createElement("div");
    msg.className = "bahi-msg bahi-msg-nav";
    msg.innerHTML = `
      <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="#111827" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
        </svg>
        <span style="font-size:11px; color:#111827; font-weight:700;">Navigating</span>
      </div>
      <span style="font-size:12px; color:#111827;">${description || path}</span>
    `;
    const avatar = document.createElement("div");
    avatar.className = "bahi-avatar bahi-avatar-bot";
    avatar.textContent = "N";
    row.appendChild(avatar);
    row.appendChild(msg);
    messagesDiv.appendChild(row);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    transcript.push({ type: "navigation", path: path, description: description || path });
    if (transcript.length > 100) transcript = transcript.slice(-100);
    persistState();
  }

  function renderTranscript() {
    if (!transcript.length) return;

    const welcome = messagesDiv.querySelector(".bahi-welcome");
    if (welcome) welcome.remove();
    messagesDiv.innerHTML = "";

    transcript.forEach(function (entry) {
      if (entry.type === "message") {
        const row = document.createElement("div");
        row.className = `bahi-msg-row bahi-msg-row-${entry.sender}`;
        const msg = document.createElement("div");
        msg.className = `bahi-msg bahi-msg-${entry.sender}`;
        if (entry.sender === "bot") {
          const text = entry.text
            .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
            .replace(/\n/g, "<br>");
          msg.innerHTML = text;
        } else {
          msg.textContent = entry.text;
        }
        const avatar = document.createElement("div");
        avatar.className = `bahi-avatar bahi-avatar-${entry.sender}`;
        if (entry.sender === "bot") {
          avatar.textContent = "N";
          row.appendChild(avatar);
          row.appendChild(msg);
        } else {
          avatar.innerHTML = `
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 12c2.76 0 5-2.24 5-5S14.76 2 12 2 7 4.24 7 7s2.24 5 5 5zm0 2c-3.33 0-10 1.67-10 5v1h20v-1c0-3.33-6.67-5-10-5z"/>
            </svg>
          `;
          row.appendChild(msg);
          row.appendChild(avatar);
        }
        messagesDiv.appendChild(row);
      } else if (entry.type === "system") {
        const msg = document.createElement("div");
        msg.className = "bahi-system";
        msg.textContent = entry.text;
        messagesDiv.appendChild(msg);
      } else if (entry.type === "navigation") {
        const row = document.createElement("div");
        row.className = "bahi-msg-row bahi-msg-row-nav";
        const msg = document.createElement("div");
        msg.className = "bahi-msg bahi-msg-nav";
        msg.innerHTML = `
          <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="#111827" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
            </svg>
            <span style="font-size:11px; color:#111827; font-weight:700;">Navigating</span>
          </div>
          <span style="font-size:12px; color:#111827;">${entry.description || entry.path}</span>
        `;
        const avatar = document.createElement("div");
        avatar.className = "bahi-avatar bahi-avatar-bot";
        avatar.textContent = "N";
        row.appendChild(avatar);
        row.appendChild(msg);
        messagesDiv.appendChild(row);
      }
    });
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  }

  function stopSpeaking() {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    if (currentAudio) {
      currentAudio.pause();
      currentAudio.currentTime = 0;
      currentAudio = null;
    }
    if (currentAudioUrl) {
      URL.revokeObjectURL(currentAudioUrl);
      currentAudioUrl = null;
    }
  }

  function selectVoiceForLanguage(lang) {
    if (!("speechSynthesis" in window)) return null;
    const voices = window.speechSynthesis.getVoices();
    if (!voices.length) return null;

    const exact = voices.find((voice) => voice.lang === lang);
    if (exact) return exact;

    const prefix = lang.split("-")[0];
    return voices.find((voice) => voice.lang && voice.lang.toLowerCase().startsWith(prefix.toLowerCase())) || null;
  }

  function speakReplyWithBrowser(text) {
    if (!("speechSynthesis" in window)) return;

    const spokenText = text.replace(/\*\*/g, "").replace(/<br>/g, " ").replace(/\s+/g, " ").trim();
    if (!spokenText) return;

    const utterance = new SpeechSynthesisUtterance(spokenText);
    utterance.lang = selectedLanguage;
    const voice = selectVoiceForLanguage(selectedLanguage);
    if (voice) utterance.voice = voice;
    window.speechSynthesis.speak(utterance);
  }

  async function speakReply(text) {
    if (!voiceRepliesEnabled) return;

    stopSpeaking();
    const spokenText = text.replace(/\*\*/g, "").replace(/<br>/g, " ").replace(/\s+/g, " ").trim();
    if (!spokenText) return;

    try {
      const response = await fetch(`${SERVER_URL}/api/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: spokenText,
          language: selectedLanguage,
        }),
      });

      if (!response.ok) {
        throw new Error(`TTS error: ${response.status}`);
      }

      const audioBlob = await response.blob();
      const audioUrl = URL.createObjectURL(audioBlob);
      currentAudioUrl = audioUrl;
      currentAudio = new Audio(audioUrl);
      currentAudio.onended = function () {
        URL.revokeObjectURL(audioUrl);
        currentAudio = null;
        currentAudioUrl = null;
      };
      currentAudio.onerror = function () {
        URL.revokeObjectURL(audioUrl);
        currentAudio = null;
        currentAudioUrl = null;
        speakReplyWithBrowser(spokenText);
      };
      await currentAudio.play();
    } catch (error) {
      console.warn("Bahi TTS fallback:", error);
      speakReplyWithBrowser(spokenText);
    }
  }

  function updateVoiceToggle() {
    voiceToggleBtn.classList.toggle("muted", !voiceRepliesEnabled);
    voiceToggleBtn.setAttribute(
      "aria-label",
      voiceRepliesEnabled ? "Mute voice replies" : "Enable voice replies"
    );
  }

  function updateMicState() {
    micBtn.classList.toggle("listening", isListening);
    micBtn.setAttribute("aria-label", isListening ? "Stop voice input" : "Start voice input");
  }

  function stopListening() {
    if (!recognition || !isListening) return;
    isListening = false;
    updateMicState();
    recognition.stop();
  }

  function startListening() {
    if (!SpeechRecognition) {
      addSystemMessage("Voice input is not supported in this browser. Try Chrome or Edge.");
      return;
    }
    if (isLoading) return;

    if (!recognition) {
      recognition = new SpeechRecognition();
      recognition.interimResults = true;
      recognition.continuous = false;

      recognition.onstart = function () {
        isListening = true;
        updateMicState();
        addSystemMessage(selectedLanguage === "hi-IN" ? "मैं सुन रही हूँ..." : "Listening...");
      };

      recognition.onresult = function (event) {
        let transcript = "";
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          transcript += event.results[i][0].transcript;
        }
        input.value = transcript.trim();

        const lastResult = event.results[event.results.length - 1];
        if (lastResult && lastResult.isFinal) {
          sendMessage();
        }
      };

      recognition.onerror = function (event) {
        isListening = false;
        updateMicState();
        if (event.error !== "aborted") {
          addSystemMessage(
            selectedLanguage === "hi-IN"
              ? "Voice input उपलब्ध नहीं है या अनुमति नहीं मिली।"
              : "Voice input failed or microphone permission was not granted."
          );
        }
      };

      recognition.onend = function () {
        isListening = false;
        updateMicState();
      };
    }

    recognition.lang = selectedLanguage;
    stopSpeaking();
    recognition.start();
  }

  function sendPresetMessage(text) {
    if (isLoading) return;
    input.value = text;
    sendMessage();
  }

  // ─────────────────────────────────────────
  // SEND MESSAGE TO SERVER
  // ─────────────────────────────────────────

  async function sendMessage() {
    const text = input.value.trim();
    if (!text || isLoading) return;

    // Show user message
    addMessage(text, "user");
    input.value = "";
    isLoading = true;
    currentChatController = new AbortController();
    updateSendButtonState();
    showTyping();

    try {
      const response = await fetch(`${SERVER_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: currentChatController.signal,
        body: JSON.stringify({
          message: text,
          conversation_id: conversationId,
          language: selectedLanguage,
        }),
      });

      if (!response.ok) {
        throw new Error(`Server error: ${response.status}`);
      }

      const data = await response.json();
      conversationId = data.conversation_id;
      persistState();
      removeTyping();

      // Handle navigation actions
      if (data.actions && data.actions.length > 0) {
        const action = data.actions[data.actions.length - 1];
        if (action.type === "navigate") {
          addNavigationMessage(action.path, action.description);
          navigateToPage(action.path);
        }
      }

      addMessage(data.reply, "bot");
      await speakReply(data.spoken_reply || data.reply);
    } catch (error) {
      removeTyping();
      if (error && error.name === "AbortError") {
        addSystemMessage(
          selectedLanguage === "hi-IN"
            ? "जवाब रोक दिया गया है।"
            : "Response stopped."
        );
      } else {
        addMessage("Sorry, something went wrong. Please try again.", "bot");
        console.error("Bahi error:", error);
      }
    } finally {
      currentChatController = null;
      isLoading = false;
      updateSendButtonState();
      input.focus();
    }
  }

  // ─────────────────────────────────────────
  // NAVIGATION
  // ─────────────────────────────────────────

  function navigateToPage(path) {
    try {
      const questionIdx = path.indexOf('?');
      const cleanPath = questionIdx >= 0 ? path.slice(0, questionIdx) : path;
      const queryString = questionIdx >= 0 ? path.slice(questionIdx + 1) : '';

      if (typeof frappe !== 'undefined' && frappe.set_route) {
        // Always reset old list filters first so they don't leak into later pages.
        frappe.route_options = {};

        if (queryString) {
          // Parse query params into frappe.route_options with proper filter format.
          // ERPNext's list view reads frappe.route_options as [field, operator, value] triples.
          //
          // Supported value formats from the agent:
          //   "2026-04-03"        → equality  → { posting_date: "2026-04-03" }
          //   "like,%Priya%"      → LIKE       → { customer_name: ["like", "%Priya%"] }
          //   ">,0"               → comparison → { outstanding_amount: [">", "0"] }
          //
          // Any value starting with a known operator followed by a comma is split;
          // everything else is treated as a plain equality value.
          const OPERATORS = /^(not like|like|>=|<=|!=|>|<),(.*)$/i;
          frappe.route_options = {};
          new URLSearchParams(queryString).forEach(function (value, key) {
            const m = value.match(OPERATORS);
            frappe.route_options[key] = m ? [m[1], m[2]] : value;
          });
        }

        // SPA navigation — no page reload, widget stays in place.
        var routeParts = cleanPath.replace(/^\/(app|desk)\//, '').split('/').filter(Boolean);
        frappe.set_route.apply(null, routeParts);
      } else {
        const fullPath = path.startsWith('/') ? path : '/app/' + path;
        window.location.href = ERP_NEXT_ORIGIN + fullPath;
      }
    } catch (e) {
      console.error("Navigation failed:", e);
      window.location.href = ERP_NEXT_ORIGIN + path;
    }
  }

  // ─────────────────────────────────────────
  // EVENT LISTENERS
  // ─────────────────────────────────────────

  sendBtn.addEventListener("click", function () {
    if (isLoading) {
      stopAgentThinking();
      return;
    }
    sendMessage();
  });
  micBtn.addEventListener("click", function () {
    if (isListening) {
      stopListening();
      return;
    }
    startListening();
  });

  languageSelect.addEventListener("change", function (event) {
    selectedLanguage = event.target.value;
    persistState();
    stopSpeaking();
    if (isListening) {
      stopListening();
      startListening();
    }
  });

  voiceToggleBtn.addEventListener("click", function () {
    voiceRepliesEnabled = !voiceRepliesEnabled;
    if (!voiceRepliesEnabled) {
      stopSpeaking();
    }
    updateVoiceToggle();
    persistState();
  });

  clearChatBtn.addEventListener("click", function () {
    clearChat();
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  messagesDiv.addEventListener("click", function (event) {
    var suggestion = event.target.closest(".bahi-suggestion");
    if (!suggestion) return;
    sendPresetMessage(suggestion.getAttribute("data-suggestion"));
  });

  micBtn.disabled = !SpeechRecognition;
  chat.classList.toggle("visible", isOpen);
  fab.classList.toggle("open", isOpen);
  renderTranscript();
  updateMicState();
  updateVoiceToggle();
  updateSendButtonState();
  if ("speechSynthesis" in window) {
    window.speechSynthesis.onvoiceschanged = function () {};
    window.speechSynthesis.getVoices();
  }
})();
