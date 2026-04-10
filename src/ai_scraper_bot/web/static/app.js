const state = {
  chats: [],
  chatMessages: new Map(),
  drafts: new Map(),
  activeJobs: new Map(),
  activeChatId: null,
  pollTimerId: null,
  openMenuChatId: null,
  modalConfig: null,
  maxChats: 10,
  openChatRequestId: 0,
  toastTimerId: null,
  bannerHidden: false,
};

const chatListEl = document.getElementById("chat-list");
const chatTitleEl = document.getElementById("chat-title");
const messageListEl = document.getElementById("message-list");
const formEl = document.getElementById("composer-form");
const inputEl = document.getElementById("message-input");
const fileInputEl = document.getElementById("file-input");
const attachmentChipEl = document.getElementById("attachment-chip");
const attachmentNameEl = document.getElementById("attachment-name");
const clearAttachmentEl = document.getElementById("clear-attachment");
const newChatButtonEl = document.getElementById("new-chat-button");
const clearChatsButtonEl = document.getElementById("clear-chats-button");
const sendButtonEl = document.getElementById("send-button");
const statusPillEl = document.getElementById("status-pill");
const fileLimitChipEl = document.getElementById("file-limit-chip");
const hideBannerButtonEl = document.getElementById("hide-banner-button");
const showBannerButtonEl = document.getElementById("show-banner-button");
const heroPanelEl = document.querySelector(".hero-panel");
const bannerCollapsedEl = document.getElementById("banner-collapsed");
const chatMenuEl = document.getElementById("chat-menu");
const modalOverlayEl = document.getElementById("modal-overlay");
const modalTitleEl = document.getElementById("modal-title");
const modalBodyEl = document.getElementById("modal-body");
const modalInputWrapEl = document.getElementById("modal-input-wrap");
const modalInputEl = document.getElementById("modal-input");
const modalCancelEl = document.getElementById("modal-cancel");
const modalConfirmEl = document.getElementById("modal-confirm");
const toastEl = document.getElementById("toast");

async function bootstrap() {
  setStatus("Loading", true);
  state.bannerHidden = false;
  renderBannerState();
  const response = await fetch("/api/bootstrap");
  if (!response.ok) {
    throw new Error("Failed to load the web app bootstrap data.");
  }
  const data = await response.json();
  state.chats = data.chats || [];
  state.maxChats = Number(data.max_chats || 10);
  state.activeJobs.clear();
  for (const job of data.active_jobs || []) {
    state.activeJobs.set(job.id, job);
  }
  fileLimitChipEl.querySelector(".meta-chip__value").textContent =
    `${data.max_file_size_mb} MB Max`;

  renderChatList();
  startPollingJobs();

  if (!state.chats.length) {
    state.activeChatId = null;
    renderCurrentChat();
    renderComposerState();
    syncGlobalStatus();
    return;
  }
  await openChat(state.chats[0].id);
  syncGlobalStatus();
}

async function createChat() {
  if (state.chats.length >= state.maxChats) {
    setStatus("Chat limit reached");
    showToast("You can have up to 10 chats at a time.");
    return;
  }
  setStatus("Creating chat", true);
  const response = await fetch("/api/chats", { method: "POST" });
  const data = await response.json();
  if (!response.ok) {
    showToast(data.detail || "You can have up to 10 chats at a time.");
    throw new Error(data.detail || "Failed to create a new chat.");
  }
  state.chats.unshift(data.chat);
  renderChatList();
  await openChat(data.chat.id);
  syncGlobalStatus();
}

async function clearAllChats() {
  openModal({
    title: "Clear all chats?",
    body: "Do you really want to delete all chats? You will need to create a new chat to start again.",
    confirmLabel: "Yes, clear all",
    danger: true,
    onConfirm: async () => {
      const response = await fetch("/api/chats/clear-all", { method: "POST" });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Failed to clear all chats.");
      }
      state.chats = [];
      state.chatMessages.clear();
      state.drafts.clear();
      state.activeJobs.clear();
      state.activeChatId = null;
      renderChatList();
      renderCurrentChat();
      syncGlobalStatus();
    },
  });
}

async function openChat(chatId) {
  saveCurrentDraft();
  state.activeChatId = chatId;
  state.openChatRequestId += 1;
  const requestId = state.openChatRequestId;
  renderChatList();
  closeChatMenu();
  loadDraft(chatId);
  renderCurrentChat();
  setStatus("Opening chat", true);
  const response = await fetch(`/api/chats/${chatId}`);
  const data = await response.json();
  if (requestId !== state.openChatRequestId) {
    return;
  }
  if (!response.ok) {
    throw new Error(data.detail || "Failed to load chat history.");
  }
  updateChatRecord(data.chat);
  state.chatMessages.set(chatId, data.messages || []);
  if (data.active_job) {
    upsertJobFromServer(data.active_job);
  }
  renderCurrentChat();
  loadDraft(chatId);
  syncGlobalStatus();
}

async function sendMessage(event) {
  event.preventDefault();
  const chatId = state.activeChatId;
  if (!chatId) {
    return;
  }
  if (isBusy()) {
    return;
  }

  const draft = getDraft(chatId);
  const text = draft.text.trim();
  const file = draft.file;
  if (!text && !file) {
    return;
  }

  setStatus("Sending", true);
  renderComposerState();

  const formData = new FormData();
  formData.append("text", text);
  if (file) {
    formData.append("file", file);
  }

  const response = await fetch(`/api/chats/${chatId}/messages`, {
    method: "POST",
    body: formData,
  });
  const payload = await response.json();
  if (!response.ok) {
    setStatus(payload.detail || "Send failed");
    appendEphemeralAssistantError(chatId, payload.detail || "The request failed.");
    renderComposerState();
    return;
  }

  const messages = state.chatMessages.get(chatId) || [];
  messages.push(payload.user_message);
  state.chatMessages.set(chatId, messages);
  updateChatRecord(payload.chat);
  clearDraft(chatId);
  upsertJobFromServer(payload.job);
  if (state.activeChatId === chatId) {
    renderCurrentChat();
  }
  renderChatList();
  renderComposerState();
  syncGlobalStatus();
  startPollingJobs();
}

async function renameChat(chatId) {
  const chat = state.chats.find((item) => item.id === chatId);
  if (!chat) {
    return;
  }
  openModal({
    title: "Rename chat",
    body: "Choose a new name for this chat.",
    confirmLabel: "Save",
    inputValue: chat.title,
    danger: false,
    onConfirm: async (value) => {
      const response = await fetch(`/api/chats/${chatId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: value }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Failed to rename the chat.");
      }
      updateChatRecord(data.chat);
      renderChatList();
      if (state.activeChatId === chatId) {
        chatTitleEl.textContent = data.chat.title;
      }
    },
  });
}

async function clearChat(chatId) {
  closeChatMenu();
  const response = await fetch(`/api/chats/${chatId}/clear`, { method: "POST" });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Failed to clear the chat.");
  }
  updateChatRecord(data.chat);
  state.chatMessages.set(chatId, []);
  removeActiveJobForChat(chatId);
  if (state.activeChatId === chatId) {
    renderCurrentChat();
  }
  renderChatList();
  syncGlobalStatus();
}

async function deleteChat(chatId) {
  const chat = state.chats.find((item) => item.id === chatId);
  if (!chat) {
    return;
  }
  openModal({
    title: "Delete chat?",
    body: `Do you really want to delete "${chat.title}"? This cannot be undone.`,
    confirmLabel: "Yes, delete",
    danger: true,
    onConfirm: async () => {
      const response = await fetch(`/api/chats/${chatId}`, { method: "DELETE" });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Failed to delete the chat.");
      }
      state.chats = state.chats.filter((item) => item.id !== chatId);
      state.chatMessages.delete(chatId);
      state.drafts.delete(chatId);
      removeActiveJobForChat(chatId);
      renderChatList();
      if (state.activeChatId === chatId) {
        if (state.chats.length) {
          await openChat(state.chats[0].id);
        } else {
          state.activeChatId = null;
          renderCurrentChat();
          syncGlobalStatus();
        }
      } else {
        syncGlobalStatus();
      }
    },
  });
}

async function pauseActiveJob() {
  const activeJob = getCurrentRunningJob();
  if (!activeJob) {
    return;
  }
  setStatus("Stopping", true);
  const response = await fetch(`/api/jobs/${activeJob.id}/cancel`, {
    method: "POST",
  });
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.detail || "Failed to stop");
    return;
  }
  upsertJobFromServer(data.job);
  removeActiveJob(activeJob.id);
  if (state.activeChatId === activeJob.chat_id) {
    renderCurrentChat();
  }
  renderComposerState();
  syncGlobalStatus();
}

async function pollJobsOnce() {
  const runningJobs = getRunningJobs();
  if (!runningJobs.length) {
    stopPollingJobs();
    syncGlobalStatus();
    return;
  }

  for (const job of runningJobs) {
    const response = await fetch(`/api/jobs/${job.id}`);
    const data = await response.json();
    if (!response.ok) {
      continue;
    }
    const updatedJob = data.job;
    upsertJobFromServer(updatedJob);
    if (updatedJob.status === "running") {
      if (state.activeChatId === updatedJob.chat_id) {
        updateVisiblePendingStage(updatedJob);
      }
      continue;
    }

    if (updatedJob.assistant_message) {
      const messages = state.chatMessages.get(updatedJob.chat_id) || [];
      if (!messages.some((item) => item.id === updatedJob.assistant_message.id)) {
        messages.push(updatedJob.assistant_message);
        state.chatMessages.set(updatedJob.chat_id, messages);
      }
    }
    if (updatedJob.chat) {
      updateChatRecord(updatedJob.chat);
    }
    removeActiveJob(updatedJob.id);
    if (state.activeChatId === updatedJob.chat_id) {
      renderCurrentChat();
    }
  }

  renderChatList();
  renderComposerState();
  syncGlobalStatus();
}

function startPollingJobs() {
  if (state.pollTimerId !== null) {
    return;
  }
  state.pollTimerId = window.setInterval(() => {
    void pollJobsOnce();
  }, 1200);
}

function stopPollingJobs() {
  if (state.pollTimerId !== null) {
    window.clearInterval(state.pollTimerId);
    state.pollTimerId = null;
  }
}

function renderCurrentChat() {
  if (!state.activeChatId) {
    chatTitleEl.textContent = "No Chats Yet";
    renderMessages([], null);
    renderComposerState();
    return;
  }
  const chat = state.chats.find((item) => item.id === state.activeChatId);
  chatTitleEl.textContent = chat ? chat.title : "Chat";
  const messages = state.chatMessages.get(state.activeChatId) || [];
  const activeJob = getActiveJobForChat(state.activeChatId);
  renderMessages(messages, activeJob);
  renderComposerState();
}

function renderMessages(messages, activeJob) {
  messageListEl.innerHTML = "";
  if (!messages.length && !activeJob) {
    messageListEl.innerHTML = `
      <div class="empty-state">
        <div class="empty-state__orb"></div>
        <h4>Start a new conversation</h4>
        <p>Drop in a website, YouTube link, image, document, audio clip, or video file. You can also just talk to the AI normally.</p>
      </div>
    `;
    return;
  }

  for (const message of messages) {
    messageListEl.appendChild(buildMessageNode(message));
  }
  if (activeJob && activeJob.status === "running") {
    messageListEl.appendChild(buildPendingAssistantNode(activeJob));
  }
  messageListEl.scrollTop = messageListEl.scrollHeight;
}

function buildMessageNode(message) {
  const wrapper = document.createElement("article");
  wrapper.className = `message message--${message.role}`;
  wrapper.dataset.messageRole = message.role;
  wrapper.innerHTML = `
    <div class="message__avatar">${message.role === "assistant" ? "AI" : "You"}</div>
    <div class="message__bubble">
      <div class="message__meta">
        <strong>${message.role === "assistant" ? "Assistant" : "You"}</strong>
        <span>${formatClock(message.created_at)}</span>
      </div>
      <div class="message__content">${renderRichText(message.content || "")}</div>
      ${message.attachment_name ? `<div class="message__attachment">📎 ${escapeHtml(message.attachment_name)}</div>` : ""}
    </div>
  `;
  return wrapper;
}

function buildPendingAssistantNode(job) {
  const wrapper = document.createElement("article");
  wrapper.className = "message message--assistant";
  wrapper.dataset.typing = "true";
  wrapper.dataset.jobId = job.id;
  wrapper.innerHTML = `
    <div class="message__avatar">AI</div>
    <div class="message__bubble">
      <div class="message__meta"><strong>Assistant</strong><span>working</span></div>
      <div class="message__content">
        <p class="message__progress">${escapeHtml(job.stage || "Working on it now.")}</p>
        <div class="message__typing"><span></span><span></span><span></span></div>
      </div>
    </div>
  `;
  return wrapper;
}

function updateVisiblePendingStage(job) {
  const pending = messageListEl.querySelector(`[data-job-id="${job.id}"] .message__progress`);
  if (pending) {
    pending.textContent = job.stage || "Working on it now.";
  }
}

function renderChatList() {
  chatListEl.innerHTML = "";
  if (!state.chats.length) {
    chatListEl.innerHTML = `<div class="chat-list__item"><p class="chat-list__title">No chats yet</p><div class="chat-list__meta"><span>Create one to begin</span></div></div>`;
    newChatButtonEl.disabled = false;
    clearChatsButtonEl.disabled = true;
    return;
  }

  newChatButtonEl.disabled = isBusy() || state.chats.length >= state.maxChats;
  clearChatsButtonEl.disabled = isBusy() || !state.chats.length;

  for (const chat of state.chats) {
    const row = document.createElement("div");
    row.className = "chat-list__row";
    if (chat.id === state.activeChatId) {
      row.classList.add("chat-list__row--active");
    }

    const card = document.createElement("div");
    card.className = "chat-list__item";

    const button = document.createElement("button");
    button.type = "button";
    button.className = "chat-list__main";
    button.innerHTML = `
      <p class="chat-list__title">${escapeHtml(chat.title)}</p>
      <div class="chat-list__meta">
        <span>${chat.message_count} messages</span>
        <span>${formatRelativeTime(chat.updated_at)}</span>
      </div>
    `;
    button.addEventListener("click", () => void openChat(chat.id));

    const menuButton = document.createElement("button");
    menuButton.type = "button";
    menuButton.className = "chat-list__menu-button";
    menuButton.innerHTML = "⋮";
    menuButton.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleChatMenu(chat.id, menuButton);
    });

    card.appendChild(button);
    row.appendChild(card);
    row.appendChild(menuButton);
    chatListEl.appendChild(row);
  }
}

function toggleChatMenu(chatId, anchor) {
  if (state.openMenuChatId === chatId) {
    closeChatMenu();
    return;
  }
  state.openMenuChatId = chatId;
  const rect = anchor.getBoundingClientRect();
  chatMenuEl.classList.remove("hidden");
  chatMenuEl.style.top = `${rect.bottom + 8}px`;
  chatMenuEl.style.left = `${Math.max(16, rect.right - 154)}px`;
  chatMenuEl.innerHTML = `
    <button type="button" class="chat-menu__item" data-action="rename">Rename</button>
    <button type="button" class="chat-menu__item" data-action="clear">Clear</button>
    <button type="button" class="chat-menu__item chat-menu__item--danger" data-action="delete">Delete</button>
  `;
  chatMenuEl.querySelector('[data-action="rename"]').addEventListener("click", () => {
    closeChatMenu();
    void renameChat(chatId);
  });
  chatMenuEl.querySelector('[data-action="clear"]').addEventListener("click", () => {
    closeChatMenu();
    void clearChat(chatId);
  });
  chatMenuEl.querySelector('[data-action="delete"]').addEventListener("click", () => {
    closeChatMenu();
    void deleteChat(chatId);
  });
}

function closeChatMenu() {
  state.openMenuChatId = null;
  chatMenuEl.classList.add("hidden");
  chatMenuEl.innerHTML = "";
}

function openModal(config) {
  state.modalConfig = config;
  modalTitleEl.textContent = config.title;
  modalBodyEl.textContent = config.body;
  modalInputWrapEl.classList.toggle("hidden", !config.inputValue && config.inputValue !== "");
  modalInputEl.value = config.inputValue || "";
  modalConfirmEl.textContent = config.confirmLabel || "Confirm";
  modalConfirmEl.classList.toggle("send-button--danger", Boolean(config.danger));
  modalOverlayEl.classList.remove("hidden");
  if (!modalInputWrapEl.classList.contains("hidden")) {
    window.setTimeout(() => modalInputEl.focus(), 10);
  }
}

function closeModal() {
  state.modalConfig = null;
  modalOverlayEl.classList.add("hidden");
  modalConfirmEl.classList.remove("send-button--danger");
  modalInputWrapEl.classList.add("hidden");
  modalInputEl.value = "";
}

async function confirmModal() {
  if (!state.modalConfig) {
    return;
  }
  const config = state.modalConfig;
  try {
    await config.onConfirm(modalInputWrapEl.classList.contains("hidden") ? null : modalInputEl.value.trim());
    closeModal();
  } catch (error) {
    setStatus(error.message || "Action failed");
    closeModal();
  }
}

function getDraft(chatId) {
  if (!state.drafts.has(chatId)) {
    state.drafts.set(chatId, { text: "", file: null });
  }
  return state.drafts.get(chatId);
}

function saveCurrentDraft() {
  if (!state.activeChatId) {
    return;
  }
  const draft = getDraft(state.activeChatId);
  draft.text = inputEl.value;
}

function loadDraft(chatId) {
  const draft = getDraft(chatId);
  inputEl.value = draft.text || "";
  setSelectedFile(draft.file, { syncToDraft: false });
  autoResizeInput();
}

function clearDraft(chatId) {
  state.drafts.set(chatId, { text: "", file: null });
  if (state.activeChatId === chatId) {
    clearDraftUI();
  }
}

function clearDraftUI() {
  inputEl.value = "";
  setSelectedFile(null, { syncToDraft: false });
  autoResizeInput();
}

function setSelectedFile(file, { syncToDraft = true } = {}) {
  if (syncToDraft && state.activeChatId) {
    const draft = getDraft(state.activeChatId);
    draft.file = file;
  }
  if (!file) {
    attachmentChipEl.classList.add("hidden");
    attachmentNameEl.textContent = "";
    fileInputEl.value = "";
    return;
  }
  attachmentChipEl.classList.remove("hidden");
  attachmentNameEl.textContent = file.name;
  fileInputEl.value = "";
}

function renderComposerState() {
  const busy = isBusy();
  const activeJob = getCurrentRunningJob();
  const hasActiveChat = Boolean(state.activeChatId);
  formEl.classList.toggle("composer--hidden", !hasActiveChat);
  inputEl.disabled = busy;
  fileInputEl.disabled = busy;
  clearAttachmentEl.disabled = busy;
  newChatButtonEl.disabled = busy || state.chats.length >= state.maxChats;
  clearChatsButtonEl.disabled = busy || !state.chats.length;
  sendButtonEl.disabled = !hasActiveChat;
  if (busy && activeJob) {
    sendButtonEl.textContent = "Pause";
    sendButtonEl.type = "button";
    sendButtonEl.classList.add("send-button--pause");
  } else {
    sendButtonEl.textContent = "Send";
    sendButtonEl.type = "submit";
    sendButtonEl.classList.remove("send-button--pause");
  }
}

function isBusy() {
  return getRunningJobs().length > 0;
}

function getRunningJobs() {
  return [...state.activeJobs.values()].filter((job) => job.status === "running");
}

function getCurrentRunningJob() {
  return getRunningJobs()[0] || null;
}

function getActiveJobForChat(chatId) {
  return [...state.activeJobs.values()].find(
    (job) => job.chat_id === chatId && job.status === "running"
  ) || null;
}

function upsertJobFromServer(job) {
  if (!job) {
    return;
  }
  state.activeJobs.set(job.id, job);
}

function removeActiveJob(jobId) {
  state.activeJobs.delete(jobId);
}

function removeActiveJobForChat(chatId) {
  for (const [jobId, job] of state.activeJobs.entries()) {
    if (job.chat_id === chatId) {
      state.activeJobs.delete(jobId);
    }
  }
}

function updateChatRecord(chat) {
  const existingIndex = state.chats.findIndex((item) => item.id === chat.id);
  if (existingIndex >= 0) {
    state.chats[existingIndex] = chat;
  } else {
    state.chats.unshift(chat);
  }
  state.chats.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
}

function appendEphemeralAssistantError(chatId, text) {
  if (!chatId) {
    return;
  }
  const messages = state.chatMessages.get(chatId) || [];
  messages.push({
    id: `local-error-${Date.now()}`,
    role: "assistant",
    content: text,
    attachment_name: null,
    created_at: new Date().toISOString(),
  });
  state.chatMessages.set(chatId, messages);
  if (state.activeChatId === chatId) {
    renderCurrentChat();
  }
}

function syncGlobalStatus() {
  const activeJob = getCurrentRunningJob();
  if (activeJob) {
    setStatus(activeJob.stage || "Working", true);
  } else if (!state.chats.length) {
    setStatus("Create a chat to begin");
  } else {
    setStatus("Ready");
  }
}

function setStatus(label, busy = false) {
  statusPillEl.textContent = label;
  statusPillEl.classList.toggle("status-pill--busy", busy);
}

function renderBannerState() {
  heroPanelEl.classList.toggle("hidden", state.bannerHidden);
  bannerCollapsedEl.classList.toggle("hidden", !state.bannerHidden);
}

function hideBanner() {
  state.bannerHidden = true;
  renderBannerState();
}

function showBanner() {
  state.bannerHidden = false;
  renderBannerState();
}

function showToast(message) {
  if (!toastEl) {
    return;
  }
  toastEl.textContent = message;
  toastEl.classList.remove("hidden");
  if (state.toastTimerId !== null) {
    window.clearTimeout(state.toastTimerId);
  }
  state.toastTimerId = window.setTimeout(() => {
    toastEl.classList.add("hidden");
    state.toastTimerId = null;
  }, 2600);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderRichText(text) {
  const normalized = String(text || "").replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  const html = [];
  let listType = null;
  let inCode = false;
  let codeLines = [];

  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`);
      listType = null;
    }
  };

  const flushCode = () => {
    if (!inCode) {
      return;
    }
    html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    inCode = false;
    codeLines = [];
  };

  for (const rawLine of lines) {
    const line = rawLine || "";
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      closeList();
      if (inCode) {
        flushCode();
      } else {
        inCode = true;
        codeLines = [];
      }
      continue;
    }

    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (!trimmed) {
      closeList();
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,4})\s*(.*)$/);
    if (headingMatch) {
      closeList();
      const level = Math.min(headingMatch[1].length + 1, 5);
      const headingText = headingMatch[2].trim();
      if (headingText) {
        html.push(`<h${level}>${renderInlineMarkdown(headingText)}</h${level}>`);
        continue;
      }
    }

    const boldHeadingMatch = trimmed.match(/^(?:[-*]\s+)?\*\*(.+?)\*\*:?$/);
    if (boldHeadingMatch && boldHeadingMatch[1].length <= 100) {
      closeList();
      html.push(`<h3>${renderInlineMarkdown(boldHeadingMatch[1])}</h3>`);
      continue;
    }

    const plainHeadingMatch = trimmed.match(/^([A-Z][A-Za-z0-9 /&()'-]{2,60}):$/);
    if (plainHeadingMatch) {
      closeList();
      html.push(`<h3>${renderInlineMarkdown(plainHeadingMatch[1])}</h3>`);
      continue;
    }

    const orderedMatch = trimmed.match(/^(\d+)\.\s+(.*)$/);
    if (orderedMatch) {
      if (listType !== "ol") {
        closeList();
        listType = "ol";
        html.push("<ol>");
      }
      html.push(`<li>${renderInlineMarkdown(orderedMatch[2])}</li>`);
      continue;
    }

    const unorderedMatch = trimmed.match(/^[-*]\s+(.*)$/);
    if (unorderedMatch) {
      if (listType !== "ul") {
        closeList();
        listType = "ul";
        html.push("<ul>");
      }
      html.push(`<li>${renderInlineMarkdown(unorderedMatch[1])}</li>`);
      continue;
    }

    const blockquoteMatch = trimmed.match(/^>\s?(.*)$/);
    if (blockquoteMatch) {
      closeList();
      html.push(`<blockquote>${renderInlineMarkdown(blockquoteMatch[1])}</blockquote>`);
      continue;
    }

    closeList();
    html.push(`<p>${renderInlineMarkdown(trimmed)}</p>`);
  }

  closeList();
  flushCode();
  return html.join("") || "<p></p>";
}

function renderInlineMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/\[(.*?)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  html = html.replace(/&lt;u&gt;(.*?)&lt;\/u&gt;/gi, "<u>$1</u>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*\*([^*\n]+)\*\*\*/g, "<strong><em>$1</em></strong>");
  html = html.replace(/___([^_\n]+)___/g, "<strong><u>$1</u></strong>");
  html = html.replace(/__(.+?)__/g, "<u>$1</u>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  html = html.replace(/_([^_\n]+)_/g, "<em>$1</em>");
  html = html.replace(/\+\+([^+]+)\+\+/g, "<u>$1</u>");
  return html;
}

function formatClock(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatRelativeTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "recently";
  }
  const minutes = Math.round((Date.now() - date.getTime()) / 60000);
  if (minutes <= 1) {
    return "Just Now";
  }
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return `${hours}h ago`;
  }
  return `${Math.round(hours / 24)}d ago`;
}

newChatButtonEl.addEventListener("click", () => void createChat());
clearChatsButtonEl.addEventListener("click", () => void clearAllChats());
hideBannerButtonEl.addEventListener("click", hideBanner);
showBannerButtonEl.addEventListener("click", showBanner);
formEl.addEventListener("submit", (event) => void sendMessage(event));
sendButtonEl.addEventListener("click", (event) => {
  if (isBusy()) {
    event.preventDefault();
    void pauseActiveJob();
  }
});
fileInputEl.addEventListener("change", (event) => {
  const file = event.target.files?.[0] || null;
  setSelectedFile(file);
});
clearAttachmentEl.addEventListener("click", () => setSelectedFile(null));
inputEl.addEventListener("input", () => {
  if (state.activeChatId) {
    getDraft(state.activeChatId).text = inputEl.value;
  }
  autoResizeInput();
});
inputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !isBusy()) {
    event.preventDefault();
    formEl.requestSubmit();
  }
});
document.addEventListener("click", (event) => {
  if (!chatMenuEl.contains(event.target)) {
    closeChatMenu();
  }
});
modalCancelEl.addEventListener("click", closeModal);
modalConfirmEl.addEventListener("click", () => void confirmModal());
modalOverlayEl.addEventListener("click", (event) => {
  if (event.target === modalOverlayEl) {
    closeModal();
  }
});

function autoResizeInput() {
  inputEl.style.height = "auto";
  inputEl.style.height = `${Math.min(inputEl.scrollHeight, 220)}px`;
}

bootstrap().catch((error) => {
  setStatus("Needs attention");
  messageListEl.innerHTML = `
    <div class="empty-state">
      <div class="empty-state__orb"></div>
      <h4>Startup failed</h4>
      <p>${escapeHtml(error.message || "The local web app could not start correctly.")}</p>
    </div>
  `;
});
