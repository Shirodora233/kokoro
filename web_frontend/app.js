const state = {
  users: [],
  sessions: [],
  messages: [],
  selectedUsername: localStorage.getItem("kokoro.selectedUsername") || "",
  selectedSessionId: localStorage.getItem("kokoro.selectedSessionId") || "",
  editingSessionId: "",
  deletingSessionId: "",
  busy: false,
};

const els = {
  storeStatus: document.querySelector("#storeStatus"),
  userSelect: document.querySelector("#userSelect"),
  addUserBtn: document.querySelector("#addUserBtn"),
  deleteUserBtn: document.querySelector("#deleteUserBtn"),
  userForm: document.querySelector("#userForm"),
  usernameInput: document.querySelector("#usernameInput"),
  displayNameInput: document.querySelector("#displayNameInput"),
  refreshUsersBtn: document.querySelector("#refreshUsersBtn"),
  addSessionBtn: document.querySelector("#addSessionBtn"),
  chatLog: document.querySelector("#chatLog"),
  messageForm: document.querySelector("#messageForm"),
  messageInput: document.querySelector("#messageInput"),
  sendBtn: document.querySelector("#sendBtn"),
  sessionForm: document.querySelector("#sessionForm"),
  newSessionTitle: document.querySelector("#newSessionTitle"),
  systemPromptInput: document.querySelector("#systemPromptInput"),
  refreshSessionsBtn: document.querySelector("#refreshSessionsBtn"),
  sessionsList: document.querySelector("#sessionsList"),
  currentUserLabel: document.querySelector("#currentUserLabel"),
  currentSessionTitle: document.querySelector("#currentSessionTitle"),
  userDialog: document.querySelector("#userDialog"),
  deleteUserDialog: document.querySelector("#deleteUserDialog"),
  deleteUserForm: document.querySelector("#deleteUserForm"),
  deleteUserName: document.querySelector("#deleteUserName"),
  cascadeUserDelete: document.querySelector("#cascadeUserDelete"),
  sessionDialog: document.querySelector("#sessionDialog"),
  editSessionDialog: document.querySelector("#editSessionDialog"),
  editSessionForm: document.querySelector("#editSessionForm"),
  editSessionTitleInput: document.querySelector("#editSessionTitleInput"),
  deleteSessionDialog: document.querySelector("#deleteSessionDialog"),
  deleteSessionForm: document.querySelector("#deleteSessionForm"),
  deleteSessionName: document.querySelector("#deleteSessionName"),
  toast: document.querySelector("#toast"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

function showToast(message, type = "info") {
  els.toast.textContent = message;
  els.toast.classList.toggle("error", type === "error");
  els.toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    els.toast.classList.remove("show");
  }, 2600);
}

function setBusy(isBusy) {
  state.busy = isBusy;
  [
    els.sendBtn,
    els.addUserBtn,
    els.deleteUserBtn,
    els.addSessionBtn,
  ].forEach((button) => {
    button.disabled = isBusy;
  });
  updateControls();
}

function selectedSession() {
  return state.sessions.find((session) => session.id === state.selectedSessionId) || null;
}

function persistSelection() {
  localStorage.setItem("kokoro.selectedUsername", state.selectedUsername || "");
  localStorage.setItem("kokoro.selectedSessionId", state.selectedSessionId || "");
}

function renderHeader() {
  const user = state.users.find((item) => item.username === state.selectedUsername);
  const session = selectedSession();
  els.currentUserLabel.textContent = user ? user.display_name || user.username : "No user";
  els.currentSessionTitle.textContent = session ? session.title : "No session";
}

function updateControls() {
  const hasSession = Boolean(state.selectedSessionId);
  els.sendBtn.disabled = state.busy || !hasSession;
  els.deleteUserBtn.disabled = state.busy || !state.selectedUsername;
  els.addSessionBtn.disabled = state.busy || !state.selectedUsername;
}

function renderUsers() {
  els.userSelect.innerHTML = "";
  if (state.users.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No users";
    els.userSelect.append(option);
    renderHeader();
    updateControls();
    return;
  }
  state.users.forEach((user) => {
    const option = document.createElement("option");
    option.value = user.username;
    option.textContent = user.display_name ? `${user.display_name} (${user.username})` : user.username;
    els.userSelect.append(option);
  });
  els.userSelect.value = state.selectedUsername;
  renderHeader();
  updateControls();
}

function renderSessions() {
  els.sessionsList.innerHTML = "";
  renderHeader();

  if (!state.selectedUsername) {
    els.sessionsList.append(emptyState("No user"));
    updateControls();
    return;
  }
  if (state.sessions.length === 0) {
    els.sessionsList.append(emptyState("No sessions"));
    updateControls();
    return;
  }

  state.sessions.forEach((session) => {
    const row = document.createElement("div");
    row.className = "session-row";
    if (session.id === state.selectedSessionId) {
      row.classList.add("active");
    }
    row.innerHTML = `
      <button class="session-select" type="button">
        <span class="item-title"></span>
        <span class="item-meta"></span>
      </button>
      <div class="session-actions">
        <button class="icon-button ghost-button edit-session-btn" type="button" aria-label="Edit session" title="Edit session">
          ${iconMarkup("edit")}
        </button>
        <button class="icon-button ghost-button danger-icon delete-session-btn" type="button" aria-label="Delete session" title="Delete session">
          ${iconMarkup("trash")}
        </button>
      </div>
    `;
    row.querySelector(".item-title").textContent = session.title;
    row.querySelector(".item-meta").textContent = new Date(session.updated_at).toLocaleString();
    row.querySelector(".session-select").addEventListener("click", async () => {
      state.selectedSessionId = session.id;
      persistSelection();
      renderSessions();
      await loadMessages();
    });
    row.querySelector(".edit-session-btn").addEventListener("click", () => {
      openEditSessionDialog(session);
    });
    row.querySelector(".delete-session-btn").addEventListener("click", () => {
      openDeleteSessionDialog(session);
    });
    els.sessionsList.append(row);
  });
  els.sessionsList.scrollTop = 0;
  updateControls();
}

function renderMessages() {
  els.chatLog.innerHTML = "";
  renderHeader();
  const session = selectedSession();
  if (!state.selectedUsername) {
    els.chatLog.append(emptyState("No user"));
    return;
  }
  if (!session) {
    els.chatLog.append(emptyState("No session"));
    return;
  }
  if (state.messages.length === 0) {
    els.chatLog.append(emptyState("No messages"));
    return;
  }
  state.messages.forEach((message) => {
    const article = document.createElement("article");
    article.className = `message ${message.role}`;

    const role = document.createElement("div");
    role.className = "message-role";
    role.textContent = message.role;

    const content = document.createElement("div");
    content.className = "message-content";
    content.textContent = message.content;

    article.append(role, content);
    els.chatLog.append(article);
  });
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
}

function emptyState(text) {
  const div = document.createElement("div");
  div.className = "empty-state";
  div.textContent = text;
  return div;
}

function iconMarkup(name) {
  const icons = {
    edit: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 17.5V20h2.5L18 8.5 15.5 6 4 17.5z"></path><path d="M17 4l3 3"></path></svg>',
    trash: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 7h14"></path><path d="M9 7V5h6v2"></path><path d="M8 10v8"></path><path d="M12 10v8"></path><path d="M16 10v8"></path><path d="M7 7l1 13h8l1-13"></path></svg>',
  };
  return icons[name] || "";
}

function openDialog(dialog) {
  if (!dialog) return;
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
}

function closeDialog(dialog) {
  if (!dialog) return;
  if (typeof dialog.close === "function") {
    dialog.close();
  } else {
    dialog.removeAttribute("open");
  }
}

function openEditSessionDialog(session) {
  state.editingSessionId = session.id;
  els.editSessionTitleInput.value = session.title;
  openDialog(els.editSessionDialog);
  els.editSessionTitleInput.focus();
}

function openDeleteSessionDialog(session) {
  state.deletingSessionId = session.id;
  els.deleteSessionName.textContent = `Delete "${session.title}" and all of its messages?`;
  openDialog(els.deleteSessionDialog);
}

function openDeleteUserDialog() {
  if (!state.selectedUsername) {
    showToast("Select a user", "error");
    return;
  }
  const user = state.users.find((item) => item.username === state.selectedUsername);
  const label = user?.display_name
    ? `${user.display_name} (${user.username})`
    : state.selectedUsername;
  els.deleteUserName.textContent = `Delete user "${label}"?`;
  els.cascadeUserDelete.checked = false;
  openDialog(els.deleteUserDialog);
}

async function loadUsers() {
  const data = await api("/api/users");
  state.users = data.users || [];
  if (
    state.selectedUsername &&
    !state.users.some((user) => user.username === state.selectedUsername)
  ) {
    state.selectedUsername = "";
    state.selectedSessionId = "";
  }
  if (!state.selectedUsername && state.users.length > 0) {
    state.selectedUsername = state.users[0].username;
  }
  persistSelection();
  renderUsers();
}

async function loadSessions() {
  if (!state.selectedUsername) {
    state.sessions = [];
    state.messages = [];
    renderSessions();
    renderMessages();
    return;
  }
  const data = await api(`/api/sessions?username=${encodeURIComponent(state.selectedUsername)}`);
  state.sessions = data.sessions || [];
  if (
    state.selectedSessionId &&
    !state.sessions.some((session) => session.id === state.selectedSessionId)
  ) {
    state.selectedSessionId = "";
  }
  if (!state.selectedSessionId && state.sessions.length > 0) {
    state.selectedSessionId = state.sessions[0].id;
  }
  persistSelection();
  renderSessions();
  await loadMessages();
}

async function loadMessages() {
  if (!state.selectedSessionId) {
    state.messages = [];
    renderMessages();
    return;
  }
  const data = await api(`/api/sessions/${encodeURIComponent(state.selectedSessionId)}/messages`);
  state.messages = data.messages || [];
  renderMessages();
}

async function refreshAll() {
  try {
    await loadUsers();
    await loadSessions();
    els.storeStatus.textContent = "JSON store";
  } catch (error) {
    showToast(error.message, "error");
    els.storeStatus.textContent = "Disconnected";
  }
}

els.userForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = els.usernameInput.value.trim();
  if (!username) return;
  try {
    setBusy(true);
    await api("/api/users", {
      method: "POST",
      body: JSON.stringify({
        username,
        display_name: els.displayNameInput.value.trim(),
      }),
    });
    state.selectedUsername = username;
    state.selectedSessionId = "";
    els.userForm.reset();
    closeDialog(els.userDialog);
    await refreshAll();
    showToast("User saved");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(false);
  }
});

els.addUserBtn.addEventListener("click", () => {
  els.userForm.reset();
  openDialog(els.userDialog);
  els.usernameInput.focus();
});

els.deleteUserBtn.addEventListener("click", () => {
  openDeleteUserDialog();
});

els.deleteUserForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.selectedUsername) return;
  try {
    setBusy(true);
    const cascade = els.cascadeUserDelete.checked;
    const path = `/api/users/${encodeURIComponent(state.selectedUsername)}?cascade=${cascade}`;
    await api(path, { method: "DELETE" });
    state.selectedUsername = "";
    state.selectedSessionId = "";
    state.sessions = [];
    state.messages = [];
    closeDialog(els.deleteUserDialog);
    await refreshAll();
    showToast("User deleted");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(false);
  }
});

els.userSelect.addEventListener("change", async () => {
  state.selectedUsername = els.userSelect.value;
  state.selectedSessionId = "";
  persistSelection();
  state.messages = [];
  renderUsers();
  await loadSessions();
});

els.sessionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.selectedUsername) {
    showToast("Select a user", "error");
    return;
  }
  try {
    setBusy(true);
    const data = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({
        username: state.selectedUsername,
        title: els.newSessionTitle.value.trim() || "New chat",
        system_prompt: els.systemPromptInput.value.trim(),
      }),
    });
    state.selectedSessionId = data.session.id;
    els.sessionForm.reset();
    closeDialog(els.sessionDialog);
    await loadSessions();
    showToast("Session created");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(false);
  }
});

els.addSessionBtn.addEventListener("click", () => {
  if (!state.selectedUsername) {
    showToast("Select a user", "error");
    return;
  }
  els.sessionForm.reset();
  openDialog(els.sessionDialog);
  els.newSessionTitle.focus();
});

els.messageForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = els.messageInput.value.trim();
  if (!content || !state.selectedSessionId) return;
  try {
    setBusy(true);
    els.messageInput.value = "";
    const pending = {
      id: "pending",
      role: "user",
      content,
      created_at: new Date().toISOString(),
    };
    state.messages = [...state.messages, pending];
    renderMessages();

    await api(`/api/sessions/${encodeURIComponent(state.selectedSessionId)}/messages`, {
      method: "POST",
      body: JSON.stringify({
        username: state.selectedUsername,
        content,
      }),
    });
    await loadSessions();
    await loadMessages();
  } catch (error) {
    showToast(error.message, "error");
    await loadMessages();
  } finally {
    setBusy(false);
    els.messageInput.focus();
  }
});

els.editSessionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.editingSessionId) return;
  const title = els.editSessionTitleInput.value.trim();
  if (!title) return;
  try {
    setBusy(true);
    await api(`/api/sessions/${encodeURIComponent(state.editingSessionId)}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
    closeDialog(els.editSessionDialog);
    await loadSessions();
    showToast("Session renamed");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(false);
  }
});

els.deleteSessionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.deletingSessionId) return;
  try {
    setBusy(true);
    await api(`/api/sessions/${encodeURIComponent(state.deletingSessionId)}`, {
      method: "DELETE",
    });
    if (state.selectedSessionId === state.deletingSessionId) {
      state.selectedSessionId = "";
    }
    state.deletingSessionId = "";
    state.messages = [];
    closeDialog(els.deleteSessionDialog);
    await loadSessions();
    showToast("Session deleted");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(false);
  }
});

document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.addEventListener("click", () => {
    closeDialog(document.querySelector(`#${button.dataset.closeDialog}`));
  });
});

els.refreshUsersBtn.addEventListener("click", refreshAll);
els.refreshSessionsBtn.addEventListener("click", loadSessions);

refreshAll();
