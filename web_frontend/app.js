const state = {
  users: [],
  sessions: [],
  messages: [],
  checkpoints: [],
  checkpointsByAssistantMessageId: new Map(),
  turnDebug: [],
  turnDebugByUserMessageId: new Map(),
  traceDetailsById: new Map(),
  processCardOpen: new Set(),
  processNodeOpen: new Set(),
  liveProcess: null,
  liveProcessTimer: null,
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
      if (state.selectedSessionId !== session.id) {
        resetSessionDebugState();
      }
      state.selectedSessionId = session.id;
      persistSelection();
      renderSessions();
      await loadMessages({ stickToBottom: true });
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

function renderMessages(options = {}) {
  const stickToBottom = options.stickToBottom ?? isChatNearBottom();
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
      } else if (message.id === "pending" && state.liveProcess) {
        els.chatLog.append(liveProcessCard(state.liveProcess));
      }
    }
    if (message.role === "assistant") {
      const checkpoint = state.checkpointsByAssistantMessageId.get(message.id);
      if (checkpoint) {
        article.append(savepointFooter(checkpoint));
      }
    }
  });
  if (stickToBottom) {
    els.chatLog.scrollTop = els.chatLog.scrollHeight;
  }
}

function isChatNearBottom() {
  const distance = els.chatLog.scrollHeight - els.chatLog.scrollTop - els.chatLog.clientHeight;
  return distance < 80;
}

function processDebugCard(debug) {
  const details = document.createElement("details");
  details.className = "process-card";
  const cardKey = processCardKey(debug);
  if (cardKey && state.processCardOpen.has(cardKey)) {
    details.open = true;
  }

  const summary = document.createElement("summary");
  summary.className = "process-summary";

  const title = document.createElement("span");
  title.className = "process-title";
  title.textContent = "Memory process";

  summary.append(title);
  const summaryText = processSummaryText(debug);
  if (summaryText) {
    const meta = document.createElement("span");
    meta.className = "process-meta";
    meta.textContent = summaryText;
    summary.append(meta);
  }

  const body = document.createElement("div");
  body.className = "process-body";
  body.textContent = "Loading...";

  details.append(summary, body);
  details.addEventListener("toggle", () => {
    if (cardKey) {
      if (details.open) {
        state.processCardOpen.add(cardKey);
      } else {
        state.processCardOpen.delete(cardKey);
      }
    }
    if (details.open) {
      loadTraceDetails(debug.trace_id, body);
    }
  });
  if (details.open) {
    loadTraceDetails(debug.trace_id, body);
  }
  return details;
}

function processCardKey(debug) {
  if (debug?.trace_id) {
    return `trace:${debug.trace_id}`;
  }
  if (debug?.user_message_id) {
    return `message:${debug.user_message_id}`;
  }
  return "";
}

function processSummaryText(debug) {
  return debug.memory_status === "failed" ? "Memory failed" : "";
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
  container.append(...traceDetailSections(trace));
}

function traceDetailSections(trace) {
  if (!hasTraceData(trace)) {
    return [];
  }
  return [
    ...memoryProcessSections(trace),
    developerDetailsSection(trace),
  ];
}

function hasTraceData(trace) {
  return Boolean(trace?.extraction || trace?.retrieval || trace?.write);
}

function memoryProcessSections(trace) {
  const tree = buildMemoryProcessTree(trace);
  const sections = [
    processTreeSection("Entities", tree.entities),
    processTreeSection("Events", tree.events),
  ];
  if (tree.other.length) {
    sections.push(processTreeSection("Other", tree.other));
  }
  if (tree.merged.length) {
    sections.push(processTreeSection("Merged", tree.merged));
  }
  return sections;
}

function developerDetailsSection(trace) {
  const details = document.createElement("details");
  details.className = "developer-details";
  const summary = document.createElement("summary");
  summary.textContent = "Developer details";
  details.append(summary, ...rawTraceSections(trace));
  return details;
}

function rawTraceSections(trace) {
  const extraction = trace?.extraction || {};
  const retrieval = trace?.retrieval || {};
  const write = trace?.write || {};
  const searchResult = retrieval.search_result || {};
  const candidateMatching = write.candidate_matching || {};
  const writePlan = write.write_plan || {};
  const writeResult = write.write_result || {};

  return [
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
    debugSection(
      "Reconciliation groups",
      candidateMatching.groups || [],
      candidateGroupText,
    ),
    debugSection(
      "Write operations",
      writePlan.operations || [],
      writeOperationText,
    ),
    debugSection(
      "Write result",
      writeResultRows(writeResult),
      (row) => row,
    ),
  ];
}

function buildMemoryProcessTree(trace) {
  const records = trace?.extraction?.normalized_records || [];
  const operations = trace?.write?.write_plan?.operations || [];
  const opIndex = buildOperationIndex(operations);
  const byId = new Map();
  const attached = new Set();

  records.forEach((record) => {
    const id = recordCandidateId(record);
    if (id) {
      byId.set(id, record);
    }
  });

  const links = records.filter((record) => record.memory_type === "link");
  const timeLinks = records.filter((record) => record.memory_type === "time_link");
  const timeById = new Map(
    records
      .filter((record) => record.memory_type === "time_ref")
      .map((record) => [recordCandidateId(record), record])
      .filter(([id]) => Boolean(id)),
  );
  const propertiesByEntity = groupChildRecords(
    records,
    links,
    "property",
    "entity_client_id",
    "entity",
    "property",
  );
  const descriptionsByEvent = groupChildRecords(
    records,
    links,
    "description",
    "event_client_id",
    "event",
    "description",
  );
  const involvedByEvent = groupInvolvedEntities(records, links, opIndex);
  const eventsByEntity = groupEventsByEntity(
    records,
    links,
    opIndex,
    timeLinks,
    timeById,
  );

  const entities = records
    .filter((record) => record.memory_type === "entity")
    .map((record) => {
      const id = recordCandidateId(record);
      const children = [
        ...(propertiesByEntity.get(id) || []).map((property) => {
          attached.add(recordCandidateId(property));
          return nodeForRecord(
            property,
            opIndex,
            [],
            null,
            timeMetaForTarget(recordCandidateId(property), timeLinks, timeById, attached),
          );
        }),
        ...(eventsByEntity.get(id) || []),
      ];
      const node = nodeForRecord(
        record,
        opIndex,
        children,
        null,
        timeMetaForTarget(id, timeLinks, timeById, attached),
      );
      node.label = displayRecordText(record);
      return node;
    });

  const events = records
    .filter((record) => record.memory_type === "event")
    .map((record) => {
      const id = recordCandidateId(record);
      const children = [
        ...(descriptionsByEvent.get(id) || []).map((description) => {
          attached.add(recordCandidateId(description));
          return nodeForRecord(
            description,
            opIndex,
            [],
            null,
            timeMetaForTarget(recordCandidateId(description), timeLinks, timeById, attached),
          );
        }),
        ...(involvedByEvent.get(id) || []),
      ];
      const node = nodeForRecord(
        record,
        opIndex,
        children,
        null,
        timeMetaForTarget(id, timeLinks, timeById, attached),
      );
      node.label = displayRecordText(record);
      return node;
    });

  const visibleTopLevel = new Set(
    records
      .filter((record) => ["entity", "event"].includes(record.memory_type))
      .map(recordCandidateId)
      .filter(Boolean),
  );
  const structuralTypes = new Set(["entity", "event", "property", "description", "time_ref"]);
  const other = records
    .filter((record) => structuralTypes.has(record.memory_type))
    .filter((record) => {
      const id = recordCandidateId(record);
      return id && !visibleTopLevel.has(id) && !attached.has(id);
    })
    .map((record) => nodeForRecord(record, opIndex));

  return {
    entities,
    events,
    other,
    merged: mergeNodes(operations, byId),
  };
}

function buildOperationIndex(operations) {
  const byCandidateId = new Map();
  const byTypeAndText = new Map();
  (operations || []).forEach((operation) => {
    if (operation.candidate_id) {
      byCandidateId.set(operation.candidate_id, operation);
    }
    if (operation.candidate_type || operation.candidate_text) {
      byTypeAndText.set(
        `${operation.candidate_type || ""}\n${operation.candidate_text || ""}`,
        operation,
      );
    }
  });
  return { byCandidateId, byTypeAndText };
}

function groupChildRecords(records, links, childType, metadataKey, parentType, linkChildType) {
  const grouped = new Map();
  records
    .filter((record) => record.memory_type === childType)
    .forEach((record) => {
      const parentId = record.metadata?.[metadataKey];
      if (parentId) {
        pushGrouped(grouped, parentId, record);
      }
    });
  links.forEach((link) => {
    const metadata = link.metadata || {};
    if (metadata.from_type === parentType && metadata.to_type === linkChildType) {
      const child = records.find((record) => recordCandidateId(record) === metadata.to_client_id);
      if (child) {
        pushGrouped(grouped, metadata.from_client_id, child);
      }
    }
  });
  return grouped;
}

function groupInvolvedEntities(records, links, opIndex) {
  const grouped = new Map();
  links.forEach((link) => {
    const metadata = link.metadata || {};
    if (
      metadata.from_type !== "event" ||
      metadata.to_type !== "entity" ||
      metadata.relation_type !== "involves"
    ) {
      return;
    }
    const entity = records.find((record) => recordCandidateId(record) === metadata.to_client_id);
    if (!entity) {
      return;
    }
    pushGrouped(grouped, metadata.from_client_id, {
      label: `entity · ${displayRecordText(entity)}`,
      key: `relation:${metadata.from_client_id}:involves:${metadata.to_client_id}`,
      meta: "",
      badges: badgesForRecord(entity, opIndex),
      children: [],
    });
  });
  return grouped;
}

function groupEventsByEntity(records, links, opIndex, timeLinks, timeById) {
  const grouped = new Map();
  links.forEach((link) => {
    const metadata = link.metadata || {};
    if (
      metadata.from_type !== "event" ||
      metadata.to_type !== "entity" ||
      metadata.relation_type !== "involves"
    ) {
      return;
    }
    const event = records.find((record) => recordCandidateId(record) === metadata.from_client_id);
    if (!event) {
      return;
    }
    pushGrouped(grouped, metadata.to_client_id, {
      label: `event · ${displayRecordText(event)}`,
      key: `relation:${metadata.to_client_id}:event:${metadata.from_client_id}`,
      meta: timeMetaForTarget(metadata.from_client_id, timeLinks, timeById),
      badges: badgesForRecord(event, opIndex),
      children: [],
    });
  });
  return grouped;
}

function pushGrouped(grouped, key, value) {
  if (!key) return;
  if (!grouped.has(key)) {
    grouped.set(key, []);
  }
  const values = grouped.get(key);
  if (!values.includes(value)) {
    values.push(value);
  }
}

function timeMetaForTarget(targetId, timeLinks, timeById, attached = null) {
  if (!targetId) return "";
  const labels = timeLinks
    .filter((link) => link.metadata?.target_client_id === targetId)
    .map((link) => {
      const time = timeById.get(link.metadata?.time_ref_client_id);
      if (!time) {
        return null;
      }
      if (attached) {
        attached.add(recordCandidateId(time));
      }
      return displayTimeText(time);
    })
    .filter(Boolean);
  return uniqueValues(labels).join(", ");
}

function nodeForRecord(record, opIndex, children = [], fallbackOperation = null, meta = "") {
  return {
    label: `${typeLabel(record.memory_type)} · ${displayRecordText(record)}`,
    key: `record:${record.memory_type || "memory"}:${recordCandidateId(record) || displayRecordText(record)}`,
    meta,
    badges: badgesForRecord(record, opIndex, fallbackOperation),
    children,
  };
}

function uniqueValues(values) {
  return [...new Set((values || []).filter(Boolean))];
}

function mergeNodes(operations, byId) {
  return (operations || [])
    .filter((operation) => operation.action === "merge" || (operation.merge_source_record_ids || []).length)
    .map((operation) => {
      const sources = operation.merge_source_record_ids || [];
      const sourceText = sources
        .map((id) => displayRecordText(byId.get(id)) || id)
        .join(", ");
      const targetText = operation.candidate_text || operation.existing_record_id || operation.candidate_id || "";
      return {
        label: sourceText ? `${sourceText} -> ${targetText}` : targetText,
        badges: [badgeLabel("merge")],
        children: [],
      };
    });
}

function operationForRecord(record, opIndex) {
  if (!record || !opIndex) return null;
  const candidateId = recordCandidateId(record);
  if (candidateId && opIndex.byCandidateId.has(candidateId)) {
    return opIndex.byCandidateId.get(candidateId);
  }
  return opIndex.byTypeAndText.get(`${record.memory_type || ""}\n${record.text || ""}`) || null;
}

function badgesForRecord(record, opIndex, fallbackOperation = null) {
  const operation = operationForRecord(record, opIndex) || fallbackOperation;
  return operation?.action ? [badgeLabel(operation.action)] : [];
}

function badgeLabel(action) {
  return {
    create: "new",
    reuse: "reuse",
    attach: "attach",
    update: "update",
    merge: "merge",
    invalidate: "stale",
    ignore: "ignored",
    flag_conflict: "conflict",
  }[action] || action;
}

function typeLabel(type) {
  return {
    entity: "entity",
    event: "event",
    property: "property",
    description: "description",
    time_ref: "time",
  }[type] || type || "memory";
}

function recordCandidateId(record) {
  return record?.metadata?.candidate_client_id || record?.id || "";
}

function displayRecordText(record) {
  if (!record) return "";
  return record.text || record.metadata?.summary || record.metadata?.raw_text || record.id || "";
}

function displayTimeText(record) {
  if (!record) return "";
  const metadata = record.metadata || {};
  return metadata.raw_text
    || metadata.description
    || metadata.resolved_start
    || record.text
    || "";
}

function processTreeSection(title, nodes) {
  const section = document.createElement("section");
  section.className = "memory-section process-tree-section";
  const heading = document.createElement("h3");
  heading.textContent = `${title} (${nodes.length})`;
  section.append(heading);
  if (nodes.length === 0) {
    section.append(emptyState("None"));
    return section;
  }
  const list = document.createElement("div");
  list.className = "memory-tree";
  nodes.forEach((node) => {
    list.append(processTreeNode(node));
  });
  section.append(list);
  return section;
}

function processTreeNode(node) {
  if (!(node.children || []).length) {
    return processLeafNode(node);
  }
  const details = document.createElement("details");
  details.className = "memory-node process-memory-node";
  if (node.key && state.processNodeOpen.has(node.key)) {
    details.open = true;
  }
  const summary = document.createElement("summary");
  summary.className = "memory-node-summary";

  const title = document.createElement("span");
  title.className = "memory-node-title";
  title.textContent = node.label;

  const meta = document.createElement("span");
  meta.className = "memory-node-meta";
  appendNodeMeta(meta, node);

  summary.append(title, meta);
  details.append(summary);

  const body = document.createElement("div");
  body.className = "memory-node-body";
  node.children.forEach((child) => {
    if ((child.children || []).length > 0) {
      body.append(processTreeNode(child));
    } else {
      body.append(processChildRow(child));
    }
  });
  details.append(body);
  details.addEventListener("toggle", () => {
    if (!node.key) {
      return;
    }
    if (details.open) {
      state.processNodeOpen.add(node.key);
    } else {
      state.processNodeOpen.delete(node.key);
    }
  });
  return details;
}

function processLeafNode(node) {
  const row = document.createElement("div");
  row.className = "memory-node process-memory-node memory-node-leaf";
  const summary = document.createElement("div");
  summary.className = "memory-node-summary";

  const title = document.createElement("span");
  title.className = "memory-node-title";
  title.textContent = node.label;

  const meta = document.createElement("span");
  meta.className = "memory-node-meta";
  appendNodeMeta(meta, node);

  summary.append(title, meta);
  row.append(summary);
  return row;
}

function processChildRow(node) {
  const row = document.createElement("div");
  row.className = "memory-child-row process-child-row";
  const text = document.createElement("span");
  text.textContent = node.label;
  const meta = document.createElement("span");
  meta.className = "process-row-meta";
  appendNodeMeta(meta, node);
  row.append(text, meta);
  return row;
}

function appendNodeMeta(container, node) {
  container.textContent = "";
  if (node.meta) {
    const meta = document.createElement("span");
    meta.className = "process-meta-text";
    meta.textContent = node.meta;
    container.append(meta);
  }
  appendBadges(container, node.badges);
}

function appendBadges(container, badges) {
  (badges || []).forEach((badge) => {
    const span = document.createElement("span");
    span.className = `process-badge badge-${badge}`;
    span.textContent = badge;
    container.append(span);
  });
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

function liveProcessCard(progress) {
  const details = document.createElement("details");
  details.className = "process-card live-process-card";
  details.dataset.liveProcessCard = "true";
  details.open = Boolean(progress.open);

  const summary = document.createElement("summary");
  summary.className = "process-summary";

  const title = document.createElement("span");
  title.className = "process-title";
  title.textContent = "Memory process";

  summary.append(title);
  const meta = document.createElement("span");
  meta.className = "process-meta";
  meta.textContent = liveProcessSummaryText(progress);
  summary.append(meta);

  const body = document.createElement("div");
  body.className = "process-body";
  body.append(
    debugSection("Process steps", liveProcessRows(progress), (row) => row),
    ...traceDetailSections(progress.trace || {}),
  );

  details.append(summary, body);
  details.addEventListener("toggle", () => {
    if (state.liveProcess) {
      state.liveProcess = {
        ...state.liveProcess,
        open: details.open,
      };
    }
  });
  return details;
}

function renderLiveProcessUpdate() {
  if (!state.liveProcess) {
    return;
  }
  const existing = els.chatLog.querySelector("[data-live-process-card='true']");
  if (!existing) {
    renderMessages();
    return;
  }
  existing.replaceWith(liveProcessCard(state.liveProcess));
}

function rememberLiveProcessOpenState() {
  if (state.liveProcess?.open && state.liveProcess.traceId) {
    state.processCardOpen.add(`trace:${state.liveProcess.traceId}`);
  }
}

function liveProcessSummaryText(progress) {
  const current = currentLiveStep(progress);
  return `${current.status} · ${current.label}`;
}

function currentLiveStep(progress) {
  const trace = progress.trace || {};
  const extraction = trace.extraction || null;
  const retrieval = trace.retrieval || null;
  const write = trace.write || null;
  if (write) {
    const operations = write.write_plan?.operations || [];
    return {
      status: "Done",
      label: "Write",
      detail: `${operations.length} operations`,
    };
  }
  if (retrieval) {
    return {
      status: "Running",
      label: "Assistant and reconciliation",
      detail: "waiting for final write",
    };
  }
  if (extraction) {
    return {
      status: "Running",
      label: "Retrieval",
      detail: "searching memory context",
    };
  }
  return {
    status: "Running",
    label: "Extraction",
    detail: progress.status || "waiting for memory trace",
  };
}

function liveProcessRows(progress) {
  const trace = progress.trace || {};
  const extraction = trace.extraction || null;
  const retrieval = trace.retrieval || null;
  const write = trace.write || null;
  const searchHits = retrieval?.search_result?.hits || [];
  const memoryContext = retrieval?.memory_context || [];
  const writePlan = write?.write_plan || {};
  const operations = writePlan.operations || [];
  const rows = [];

  rows.push(stepText(
    extraction ? "done" : progress.trace ? "running" : "pending",
    "Extraction",
    extraction
      ? `${(extraction.normalized_records || []).length} candidates`
      : "waiting for candidate extraction",
  ));
  rows.push(stepText(
    retrieval ? "done" : extraction ? "running" : "pending",
    "Retrieval",
    retrieval
      ? `${searchHits.length} hits, ${memoryContext.length} context blocks`
      : "waiting for memory search",
  ));
  rows.push(stepText(
    write ? "done" : retrieval ? "running" : "pending",
    "Assistant and reconciliation",
    write
      ? `${writePlan.metadata?.reconciler || "reconciler"} completed`
      : retrieval
        ? "assistant response or reconciliation in progress"
        : "waiting for retrieval",
  ));
  rows.push(stepText(
    write ? "done" : retrieval ? "running" : "pending",
    "Write",
    write
      ? `${operations.length} operations${actionCountsSummary(processWriteActionCounts(operations))}`
      : "waiting for write result",
  ));
  return rows;
}

function stepText(status, label, detail) {
  return `${status.toUpperCase()} · ${label} · ${detail}`;
}

function processWriteActionCounts(operations) {
  return (operations || []).reduce((counts, operation) => {
    const action = operation?.action;
    if (action) {
      counts[action] = (counts[action] || 0) + 1;
    }
    return counts;
  }, {});
}

function scoreText(score) {
  return typeof score === "number" ? score.toFixed(2) : "0.00";
}

function actionCountsSummary(counts) {
  const parts = Object.entries(counts || {})
    .filter(([, count]) => Number(count) > 0)
    .map(([action, count]) => `${action}:${count}`);
  return parts.length ? ` (${parts.join(", ")})` : "";
}

function candidateGroupText(group) {
  const direct = group.direct_matches || [];
  const expanded = group.expanded_context || [];
  const pieces = [
    group.candidate_id || "candidate",
    group.candidate_type || "",
    group.candidate_text || "",
    `direct ${direct.length}`,
    expanded.length ? `expanded ${expanded.length}` : "",
  ];
  return pieces.filter(Boolean).join(" · ");
}

function writeOperationText(operation) {
  const pieces = [
    operation.action || "write",
    operation.candidate_id || operation.candidate_type || "",
    operation.candidate_text || "",
    operation.existing_record_id ? `existing ${operation.existing_record_id}` : "",
    operation.target_record_id ? `target ${operation.target_record_id}` : "",
    operation.target_candidate_id ? `target candidate ${operation.target_candidate_id}` : "",
    operation.relation_type ? `relation ${operation.relation_type}` : "",
    operation.reason || "",
  ];
  return pieces.filter(Boolean).join(" · ");
}

function writeResultRows(result) {
  if (!result || typeof result !== "object") {
    return [];
  }
  const buckets = [
    ["created_records", "Created"],
    ["reused_records", "Reused"],
    ["attached_records", "Attached"],
    ["updated_records", "Updated"],
    ["merged_records", "Merged"],
    ["invalidated_records", "Invalidated"],
    ["ignored_operations", "Ignored"],
    ["conflict_operations", "Conflicts"],
    ["failed_operations", "Failures"],
  ];
  const rows = [];
  buckets.forEach(([key, label]) => {
    const items = Array.isArray(result[key]) ? result[key] : [];
    if (items.length === 0) {
      return;
    }
    rows.push(`${label} ${items.length}`);
    items.slice(0, 6).forEach((item) => {
      rows.push(`- ${recordOrOperationText(item)}`);
    });
    if (items.length > 6) {
      rows.push(`- ${items.length - 6} more`);
    }
  });
  return rows;
}

function recordOrOperationText(item) {
  const operation = item.operation || item;
  const memoryType = item.memory_type || operation.candidate_type || "";
  const text = item.text || operation.candidate_text || operation.reason || "";
  const action = item.metadata?.write_action || operation.action || "";
  return [action, memoryType, text].filter(Boolean).join(" · ");
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
  stopLiveProcessPolling();
  state.liveProcess = null;
  state.processCardOpen = new Set();
  state.processNodeOpen = new Set();
  resetCheckpoints();
  resetTurnDebug();
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
  await loadMessages({ stickToBottom: true });
}

async function loadMessages(options = {}) {
  if (!state.selectedSessionId) {
    state.messages = [];
    resetSessionDebugState();
    renderMessages(options);
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
  renderMessages(options);
}

async function loadCheckpoints(sessionId = state.selectedSessionId) {
  if (!sessionId) {
    resetCheckpoints();
    return;
  }
  const data = await api(`/api/sessions/${encodeURIComponent(sessionId)}/checkpoints?limit=50`);
  if (sessionId !== state.selectedSessionId) {
    return;
  }
  state.checkpoints = (data.checkpoints || []).map((checkpoint, index) => ({
    ...checkpoint,
    ui_number: index + 1,
  }));
  indexCheckpoints();
}

async function loadTurnDebug(sessionId = state.selectedSessionId) {
  if (!sessionId) {
    resetTurnDebug();
    return;
  }
  const data = await api(`/api/sessions/${encodeURIComponent(sessionId)}/turn-debug?limit=100`);
  if (sessionId !== state.selectedSessionId) {
    return;
  }
  state.turnDebug = data.turn_debug || [];
  indexTurnDebug();
}

function startLiveProcessPolling(sessionId, startedAt) {
  stopLiveProcessPolling();
  state.liveProcess = {
    sessionId,
    startedAt,
    status: "Queued",
    summary: null,
    trace: null,
    traceId: null,
  };
  pollLiveProcess(sessionId, startedAt);
  state.liveProcessTimer = window.setInterval(() => {
    pollLiveProcess(sessionId, startedAt);
  }, 700);
}

function stopLiveProcessPolling() {
  if (state.liveProcessTimer) {
    window.clearInterval(state.liveProcessTimer);
    state.liveProcessTimer = null;
  }
}

async function pollLiveProcess(sessionId, startedAt) {
  if (!state.liveProcess || state.liveProcess.sessionId !== sessionId) {
    return;
  }
  try {
    const data = await api(`/api/debug/memory/traces?session_id=${encodeURIComponent(sessionId)}&limit=6`);
    if (!state.liveProcess || state.liveProcess.sessionId !== sessionId) {
      return;
    }
    const summary = newestTraceAfter(data.traces || [], startedAt);
    if (!summary) {
      state.liveProcess = {
        ...state.liveProcess,
        status: "Waiting for memory trace",
      };
      renderLiveProcessUpdate();
      return;
    }
    let trace = state.liveProcess.trace;
    if (summary.trace_id && summary.trace_id !== state.liveProcess.traceId) {
      trace = null;
    }
    if (summary.trace_id) {
      const detail = await api(`/api/debug/memory/traces/${encodeURIComponent(summary.trace_id)}`);
      if (!state.liveProcess || state.liveProcess.sessionId !== sessionId) {
        return;
      }
      trace = detail.trace || trace;
    }
    state.liveProcess = {
      ...state.liveProcess,
      status: summary.status || "Running",
      summary,
      trace,
      traceId: summary.trace_id || state.liveProcess.traceId,
    };
    renderLiveProcessUpdate();
  } catch (error) {
    state.liveProcess = {
      ...state.liveProcess,
      status: `Debug polling failed: ${error.message}`,
    };
    renderLiveProcessUpdate();
  }
}

function newestTraceAfter(traces, startedAt) {
  const lowerBound = Date.parse(startedAt) - 5000;
  return (traces || []).find((trace) => {
    const createdAt = Date.parse(trace.created_at || "");
    return Number.isFinite(createdAt) && createdAt >= lowerBound;
  }) || null;
}

async function refreshAll() {
  try {
    await loadUsers();
    await loadSessions();
    els.storeStatus.textContent = "PostgreSQL";
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
  const sessionId = state.selectedSessionId;
  const startedAt = new Date().toISOString();
  const idempotencyKey = createIdempotencyKey();
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
    startLiveProcessPolling(sessionId, startedAt);
    renderMessages({ stickToBottom: true });

    await api(`/api/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: "POST",
      body: JSON.stringify({
        username: state.selectedUsername,
        content,
        idempotency_key: idempotencyKey,
      }),
    });
    stopLiveProcessPolling();
    rememberLiveProcessOpenState();
    state.liveProcess = null;
    await loadSessions();
  } catch (error) {
    stopLiveProcessPolling();
    state.liveProcess = null;
    showToast(error.message, "error");
    await loadMessages({ stickToBottom: true });
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
