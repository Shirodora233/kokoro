const state = {
  users: [],
  sessions: [],
  messages: [],
  checkpoints: [],
  checkpointsByAssistantMessageId: new Map(),
  checkpointsUnavailable: false,
  turnDebug: [],
  turnDebugByUserMessageId: new Map(),
  turnDebugUnavailable: false,
  traceDetailsById: new Map(),
  checkpointMemoryById: new Map(),
  selectedUsername: localStorage.getItem("kokoro.selectedUsername") || "",
  selectedSessionId: localStorage.getItem("kokoro.selectedSessionId") || "",
  editingSessionId: "",
  deletingSessionId: "",
  editingCheckpointId: "",
  branchingCheckpointId: "",
  viewingCheckpointId: "",
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
  currentBranchLabel: document.querySelector("#currentBranchLabel"),
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
  editCheckpointDialog: document.querySelector("#editCheckpointDialog"),
  editCheckpointForm: document.querySelector("#editCheckpointForm"),
  editCheckpointName: document.querySelector("#editCheckpointName"),
  editCheckpointLabelInput: document.querySelector("#editCheckpointLabelInput"),
  branchDialog: document.querySelector("#branchDialog"),
  branchForm: document.querySelector("#branchForm"),
  branchCheckpointName: document.querySelector("#branchCheckpointName"),
  branchTitleInput: document.querySelector("#branchTitleInput"),
  checkpointMemoryDialog: document.querySelector("#checkpointMemoryDialog"),
  checkpointMemoryTitle: document.querySelector("#checkpointMemoryTitle"),
  checkpointMemoryContent: document.querySelector("#checkpointMemoryContent"),
  toast: document.querySelector("#toast"),
};

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

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
    throw new ApiError(
      data.error || `Request failed: ${response.status}`,
      response.status,
      data,
    );
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
  const branchText = branchLabel(session);
  els.currentUserLabel.textContent = user ? user.display_name || user.username : "No user";
  els.currentSessionTitle.textContent = session ? session.title : "No session";
  els.currentBranchLabel.textContent = branchText;
  els.currentBranchLabel.hidden = !branchText;
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
    const metaParts = [new Date(session.updated_at).toLocaleString()];
    const branchText = branchLabel(session);
    if (branchText) {
      metaParts.unshift(branchText);
      row.classList.add("branch-session");
    }
    row.querySelector(".item-meta").textContent = metaParts.join(" · ");
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
    if (message.role === "user") {
      const debug = state.turnDebugByUserMessageId.get(message.id);
      if (debug) {
        els.chatLog.append(processDebugCard(debug));
      }
    }
    if (message.role === "assistant") {
      const checkpoint = state.checkpointsByAssistantMessageId.get(message.id);
      if (checkpoint) {
        article.append(savepointFooter(checkpoint));
      }
    }
  });
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
}

function processDebugCard(debug) {
  const details = document.createElement("details");
  details.className = "process-card";

  const summary = document.createElement("summary");
  summary.className = "process-summary";

  const title = document.createElement("span");
  title.className = "process-title";
  title.textContent = "Memory process";

  const meta = document.createElement("span");
  meta.className = "process-meta";
  meta.textContent = processSummaryText(debug);

  summary.append(title, meta);

  const body = document.createElement("div");
  body.className = "process-body";
  body.textContent = "Loading...";

  details.append(summary, body);
  details.addEventListener("toggle", () => {
    if (details.open) {
      loadTraceDetails(debug.trace_id, body);
    }
  });
  return details;
}

function processSummaryText(debug) {
  const active = debug.active_counts || {};
  const activeTotal = ["events", "entities", "properties", "other"]
    .reduce((sum, key) => sum + Number(active[key] || 0), 0);
  return [
    `Extractor ${debug.candidate_count || 0}`,
    `Retrieval ${debug.search_hit_count || 0}`,
    `Active ${activeTotal}`,
    `Context ${debug.memory_context_count || 0}`,
    debug.memory_status === "failed" ? "Memory failed" : "",
  ].filter(Boolean).join(" · ");
}

async function loadTraceDetails(traceId, container) {
  if (!traceId) {
    container.textContent = "No trace id";
    return;
  }
  if (state.traceDetailsById.has(traceId)) {
    renderTraceDetails(container, state.traceDetailsById.get(traceId));
    return;
  }
  container.textContent = "Loading...";
  try {
    const data = await api(`/api/debug/memory/traces/${encodeURIComponent(traceId)}`);
    state.traceDetailsById.set(traceId, data.trace);
    renderTraceDetails(container, data.trace);
  } catch (error) {
    container.textContent = error.message;
  }
}

function renderTraceDetails(container, trace) {
  container.innerHTML = "";
  const extraction = trace?.extraction || {};
  const retrieval = trace?.retrieval || {};
  const searchResult = retrieval.search_result || {};

  container.append(
    debugSection(
      "Extracted candidates",
      extraction.normalized_records || [],
      (record) => `${record.memory_type || "memory"} · ${record.text || ""}`,
    ),
    debugSection(
      "Retrieval hits",
      searchResult.hits || [],
      (hit) => `${scoreText(hit.score)} · ${hit.reason || "match"} · ${hit.matched_text || hit.object_ref?.object_id || ""}`,
    ),
    debugSection(
      "Active context",
      activeContextRecords(retrieval.active_memory_context),
      (record) => `${record.memory_type || "memory"} · ${record.text || ""}`,
    ),
    debugSection(
      "Memory context sent to LLM",
      retrieval.memory_context || [],
      (block) => `${block.kind || "memory"} · ${block.content || ""}`,
    ),
  );
}

function debugSection(title, items, formatter) {
  const section = document.createElement("section");
  section.className = "debug-section";
  const heading = document.createElement("h3");
  heading.textContent = `${title} (${items.length})`;
  section.append(heading);
  if (items.length === 0) {
    section.append(emptyState("None"));
    return section;
  }
  const list = document.createElement("div");
  list.className = "debug-list";
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "debug-row";
    row.textContent = formatter(item);
    list.append(row);
  });
  section.append(list);
  return section;
}

function activeContextRecords(activeContext) {
  if (!activeContext) return [];
  return [
    ...(activeContext.event_memories || []),
    ...(activeContext.entity_memories || []),
    ...(activeContext.property_memories || []),
    ...(activeContext.other_memories || []),
  ];
}

function scoreText(score) {
  return typeof score === "number" ? score.toFixed(2) : "0.00";
}

function savepointFooter(checkpoint) {
  const footer = document.createElement("div");
  footer.className = "savepoint-footer";

  const info = document.createElement("div");
  info.className = "savepoint-info";

  const title = document.createElement("span");
  title.className = "savepoint-title";
  title.textContent = checkpointLabel(checkpoint);

  const meta = document.createElement("span");
  meta.className = "savepoint-meta";
  meta.textContent = checkpoint.label ? savepointNumberLabel(checkpoint) : formatDate(checkpoint.created_at);

  info.append(title, meta);

  const actions = document.createElement("div");
  actions.className = "savepoint-actions";

  const editButton = document.createElement("button");
  editButton.className = "icon-button ghost-button";
  editButton.type = "button";
  editButton.title = "Name savepoint";
  editButton.setAttribute("aria-label", "Name savepoint");
  editButton.innerHTML = iconMarkup("edit");
  editButton.addEventListener("click", () => openEditCheckpointDialog(checkpoint));

  const branchButton = document.createElement("button");
  branchButton.className = "icon-button ghost-button";
  branchButton.type = "button";
  branchButton.title = "Branch from this savepoint";
  branchButton.setAttribute("aria-label", "Branch from this savepoint");
  branchButton.innerHTML = iconMarkup("branch");
  branchButton.addEventListener("click", () => openBranchDialog(checkpoint));

  const memoryButton = document.createElement("button");
  memoryButton.className = "icon-button ghost-button";
  memoryButton.type = "button";
  memoryButton.title = "View checkpoint memory";
  memoryButton.setAttribute("aria-label", "View checkpoint memory");
  memoryButton.innerHTML = iconMarkup("memory");
  memoryButton.addEventListener("click", () => openCheckpointMemoryDialog(checkpoint));

  actions.append(editButton, memoryButton, branchButton);
  footer.append(info, actions);
  return footer;
}

function emptyState(text) {
  const div = document.createElement("div");
  div.className = "empty-state";
  div.textContent = text;
  return div;
}

function iconMarkup(name) {
  const icons = {
    branch: '<svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="6" cy="6" r="3"></circle><circle cx="18" cy="6" r="3"></circle><circle cx="6" cy="18" r="3"></circle><path d="M6 9v6"></path><path d="M9 6h3a6 6 0 0 1 6 6v3"></path></svg>',
    edit: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 17.5V20h2.5L18 8.5 15.5 6 4 17.5z"></path><path d="M17 4l3 3"></path></svg>',
    memory: '<svg aria-hidden="true" viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="7" ry="3"></ellipse><path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5"></path><path d="M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"></path></svg>',
    trash: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 7h14"></path><path d="M9 7V5h6v2"></path><path d="M8 10v8"></path><path d="M12 10v8"></path><path d="M16 10v8"></path><path d="M7 7l1 13h8l1-13"></path></svg>',
  };
  return icons[name] || "";
}

function branchLabel(session) {
  const branch = session?.metadata?.branch;
  if (!branch) {
    return "";
  }
  return "Branch session";
}

function checkpointLabel(checkpoint) {
  return checkpoint.label || savepointNumberLabel(checkpoint);
}

function savepointNumberLabel(checkpoint) {
  return `Savepoint #${checkpoint.ui_number || "?"}`;
}

function checkpointSequenceLabel(checkpoint) {
  return `message sequence ${checkpoint.sequence}`;
}

function formatDate(value) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleString();
}

function createIdempotencyKey() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `web_${Date.now()}_${Math.random().toString(16).slice(2)}`;
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

function openEditCheckpointDialog(checkpoint) {
  state.editingCheckpointId = checkpoint.id;
  els.editCheckpointName.textContent = `Rename ${checkpointLabel(checkpoint)} (${checkpointSequenceLabel(checkpoint)})`;
  els.editCheckpointLabelInput.value = checkpoint.label || "";
  openDialog(els.editCheckpointDialog);
  els.editCheckpointLabelInput.focus();
}

function openBranchDialog(checkpoint) {
  const session = selectedSession();
  state.branchingCheckpointId = checkpoint.id;
  els.branchCheckpointName.textContent = `Create a new session from ${checkpointLabel(checkpoint)}.`;
  els.branchTitleInput.value = session
    ? `${session.title} from ${savepointNumberLabel(checkpoint)}`
    : `Branch from ${savepointNumberLabel(checkpoint)}`;
  openDialog(els.branchDialog);
  els.branchTitleInput.focus();
}

async function openCheckpointMemoryDialog(checkpoint) {
  state.viewingCheckpointId = checkpoint.id;
  els.checkpointMemoryTitle.textContent = `${checkpointLabel(checkpoint)} memory`;
  els.checkpointMemoryContent.innerHTML = "";
  els.checkpointMemoryContent.append(emptyState("Loading memory..."));
  openDialog(els.checkpointMemoryDialog);
  try {
    const memory = await loadCheckpointMemory(checkpoint.id);
    if (state.viewingCheckpointId === checkpoint.id) {
      renderCheckpointMemory(memory);
    }
  } catch (error) {
    els.checkpointMemoryContent.innerHTML = "";
    els.checkpointMemoryContent.append(emptyState(error.message));
  }
}

async function loadCheckpointMemory(checkpointId) {
  if (state.checkpointMemoryById.has(checkpointId)) {
    return state.checkpointMemoryById.get(checkpointId);
  }
  const data = await api(`/api/checkpoints/${encodeURIComponent(checkpointId)}/memory?limit=100`);
  state.checkpointMemoryById.set(checkpointId, data.memory);
  return data.memory;
}

function renderCheckpointMemory(memory) {
  els.checkpointMemoryContent.innerHTML = "";
  const normalized = memory.normalized_memories || {};
  const grouped = groupNormalizedMemory(normalized);
  const activeRecords = activeContextRecords(memory.active_memory_snapshot);
  const genericRecords = memory.generic_memories || [];

  const sections = [
    hierarchicalMemorySection(
      "Entities",
      grouped.entities,
      entitySummary,
      (entity) => entityDetailRows(entity, grouped.propertiesByEntityId.get(entity.id) || []),
    ),
    hierarchicalMemorySection(
      "Events",
      grouped.events,
      eventSummary,
      (event) => eventDetailRows(event, grouped.descriptionsByEventId.get(event.id) || []),
    ),
  ];

  if (grouped.unlinkedProperties.length || grouped.unlinkedDescriptions.length) {
    sections.push(memorySection(
      "Unlinked details",
      [...grouped.unlinkedProperties, ...grouped.unlinkedDescriptions],
      (item) => item.content || item.text || item.id || "",
    ));
  }
  if (activeRecords.length) {
    sections.push(memorySection(
      "Active context snapshot",
      activeRecords,
      (record) => `${record.memory_type || "memory"} · ${record.text || ""}`,
    ));
  }
  if (genericRecords.length && grouped.entities.length + grouped.events.length === 0) {
    sections.push(memorySection(
      "Generic memories",
      genericRecords,
      (record) => `${record.memory_type || "memory"} · ${record.text || ""}`,
    ));
  }

  els.checkpointMemoryContent.append(...sections);
}

function memorySection(title, items, formatter) {
  const section = document.createElement("section");
  section.className = "memory-section";
  const heading = document.createElement("h3");
  heading.textContent = `${title} (${items.length})`;
  section.append(heading);
  if (items.length === 0) {
    section.append(emptyState("None"));
    return section;
  }
  const list = document.createElement("div");
  list.className = "memory-list";
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "memory-row";
    row.textContent = formatter(item);
    list.append(row);
  });
  section.append(list);
  return section;
}

function hierarchicalMemorySection(title, items, summaryFormatter, detailsFormatter) {
  const section = document.createElement("section");
  section.className = "memory-section";
  const heading = document.createElement("h3");
  heading.textContent = `${title} (${items.length})`;
  section.append(heading);
  if (items.length === 0) {
    section.append(emptyState("None"));
    return section;
  }
  const list = document.createElement("div");
  list.className = "memory-tree";
  items.forEach((item) => {
    const details = document.createElement("details");
    details.className = "memory-node";

    const summary = document.createElement("summary");
    summary.className = "memory-node-summary";
    const summaryParts = summaryFormatter(item);
    const titleSpan = document.createElement("span");
    titleSpan.className = "memory-node-title";
    titleSpan.textContent = summaryParts.title;
    const metaSpan = document.createElement("span");
    metaSpan.className = "memory-node-meta";
    metaSpan.textContent = summaryParts.meta;
    summary.append(titleSpan, metaSpan);

    const body = document.createElement("div");
    body.className = "memory-node-body";
    const rows = detailsFormatter(item);
    if (rows.length === 0) {
      body.append(emptyState("No details"));
    } else {
      rows.forEach((row) => {
        const div = document.createElement("div");
        div.className = "memory-child-row";
        div.textContent = row;
        body.append(div);
      });
    }
    details.append(summary, body);
    list.append(details);
  });
  section.append(list);
  return section;
}

function groupNormalizedMemory(normalized) {
  const events = normalized.events || [];
  const descriptions = normalized.descriptions || [];
  const entities = normalized.entities || [];
  const properties = normalized.properties || [];
  const eventIds = new Set(events.map((event) => event.id).filter(Boolean));
  const entityIds = new Set(entities.map((entity) => entity.id).filter(Boolean));
  const descriptionsByEventId = groupBy(descriptions, "event_id");
  const propertiesByEntityId = groupBy(properties, "entity_id");
  return {
    events,
    entities,
    descriptionsByEventId,
    propertiesByEntityId,
    unlinkedDescriptions: descriptions.filter((item) => !eventIds.has(item.event_id)),
    unlinkedProperties: properties.filter((item) => !entityIds.has(item.entity_id)),
  };
}

function groupBy(items, key) {
  const grouped = new Map();
  items.forEach((item) => {
    const value = item[key];
    if (!value) return;
    if (!grouped.has(value)) {
      grouped.set(value, []);
    }
    grouped.get(value).push(item);
  });
  return grouped;
}

function entitySummary(entity) {
  return {
    title: entity.name || entity.id || "Unnamed entity",
    meta: [entity.entity_type, entity.identity_summary].filter(Boolean).join(" · "),
  };
}

function eventSummary(event) {
  return {
    title: event.title || event.id || "Untitled event",
    meta: [event.event_type, event.summary].filter(Boolean).join(" · "),
  };
}

function entityDetailRows(entity, properties) {
  const rows = [];
  if (entity.identity_summary) {
    rows.push(entity.identity_summary);
  }
  properties.forEach((property) => {
    rows.push(property.content || property.id || "");
  });
  return rows.filter(Boolean);
}

function eventDetailRows(event, descriptions) {
  const rows = [];
  if (event.summary) {
    rows.push(event.summary);
  }
  descriptions.forEach((description) => {
    rows.push(description.content || description.id || "");
  });
  return rows.filter(Boolean);
}

function resetCheckpoints() {
  state.checkpoints = [];
  state.checkpointsByAssistantMessageId = new Map();
}

function resetTurnDebug() {
  state.turnDebug = [];
  state.turnDebugByUserMessageId = new Map();
}

function resetSessionDebugState() {
  resetCheckpoints();
  resetTurnDebug();
  state.checkpointsUnavailable = false;
  state.turnDebugUnavailable = false;
  state.traceDetailsById = new Map();
  state.checkpointMemoryById = new Map();
}

function indexCheckpoints() {
  state.checkpointsByAssistantMessageId = new Map();
  state.checkpoints.forEach((checkpoint) => {
    if (checkpoint.assistant_message_id) {
      state.checkpointsByAssistantMessageId.set(checkpoint.assistant_message_id, checkpoint);
    }
  });
}

function indexTurnDebug() {
  state.turnDebugByUserMessageId = new Map();
  state.turnDebug.forEach((debug) => {
    if (debug.user_message_id) {
      state.turnDebugByUserMessageId.set(debug.user_message_id, debug);
    }
  });
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
    resetSessionDebugState();
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
    resetSessionDebugState();
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
    resetSessionDebugState();
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
    resetSessionDebugState();
    renderMessages();
    return;
  }
  const sessionId = state.selectedSessionId;
  const data = await api(`/api/sessions/${encodeURIComponent(sessionId)}/messages`);
  if (sessionId !== state.selectedSessionId) {
    return;
  }
  state.messages = data.messages || [];
  await Promise.all([
    loadCheckpoints(sessionId),
    loadTurnDebug(sessionId),
  ]);
  if (sessionId !== state.selectedSessionId) {
    return;
  }
  renderMessages();
}

async function loadCheckpoints(sessionId = state.selectedSessionId) {
  if (!sessionId) {
    resetCheckpoints();
    return;
  }
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(sessionId)}/checkpoints?limit=50`);
    if (sessionId !== state.selectedSessionId) {
      return;
    }
    state.checkpointsUnavailable = false;
    state.checkpoints = (data.checkpoints || []).map((checkpoint, index) => ({
      ...checkpoint,
      ui_number: index + 1,
    }));
    indexCheckpoints();
  } catch (error) {
    if (error.status === 501) {
      state.checkpointsUnavailable = true;
      resetCheckpoints();
      return;
    }
    throw error;
  }
}

async function loadTurnDebug(sessionId = state.selectedSessionId) {
  if (!sessionId) {
    resetTurnDebug();
    return;
  }
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(sessionId)}/turn-debug?limit=100`);
    if (sessionId !== state.selectedSessionId) {
      return;
    }
    state.turnDebugUnavailable = false;
    state.turnDebug = data.turn_debug || [];
    indexTurnDebug();
  } catch (error) {
    if (error.status === 501) {
      state.turnDebugUnavailable = true;
      resetTurnDebug();
      return;
    }
    throw error;
  }
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
    resetSessionDebugState();
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
  resetSessionDebugState();
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
        idempotency_key: createIdempotencyKey(),
      }),
    });
    await loadSessions();
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
    resetSessionDebugState();
    closeDialog(els.deleteSessionDialog);
    await loadSessions();
    showToast("Session deleted");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(false);
  }
});

els.editCheckpointForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.editingCheckpointId) return;
  try {
    setBusy(true);
    await api(`/api/checkpoints/${encodeURIComponent(state.editingCheckpointId)}`, {
      method: "PATCH",
      body: JSON.stringify({
        label: els.editCheckpointLabelInput.value.trim() || null,
      }),
    });
    closeDialog(els.editCheckpointDialog);
    state.editingCheckpointId = "";
    await loadCheckpoints();
    renderMessages();
    showToast("Savepoint updated");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setBusy(false);
  }
});

els.branchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.branchingCheckpointId || !state.selectedSessionId) return;
  const sourceSessionId = state.selectedSessionId;
  try {
    setBusy(true);
    const data = await api(`/api/sessions/${encodeURIComponent(sourceSessionId)}/branches`, {
      method: "POST",
      body: JSON.stringify({
        checkpoint_id: state.branchingCheckpointId,
        title: els.branchTitleInput.value.trim() || null,
      }),
    });
    state.branchingCheckpointId = "";
    state.selectedSessionId = data.session.id;
    persistSelection();
    closeDialog(els.branchDialog);
    await loadSessions();
    showToast("Branch created");
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
