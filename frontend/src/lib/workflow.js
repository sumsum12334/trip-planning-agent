export const AGENT_LABELS = [
  ["search_stays", "Agent 1 · search_stays"],
  ["estimate_transport", "Agent 2 · estimate_transport"],
  ["travel_history", "Agent 4 · travel_history"],
  ["web_search", "web_search tool"],
  ["weather", "weather tool"],
  ["display_trip_plan", "Agent 3 · coordinator"],
  ["trip plan", "Agent 3 · coordinator"],
  ["start_trip_plan", "Agent 3 · coordinator"],
  ["set_trip_day", "Agent 3 · coordinator"],
  ["set_trip_budget", "Agent 3 · coordinator"],
  ["set_trip_references", "Agent 3 · coordinator"],
  ["remove_trip_day", "Agent 3 · coordinator"],
  ["get_trip_plan", "Agent 3 · coordinator"],
  ["ask_user_question", "Agent 3 · coordinator"],
  ["coordinator", "Agent 3 · coordinator"],
  ["model", "Model"],
];

export function agentForEvent(event) {
  const label = (event.label || "").toLowerCase();
  const match = AGENT_LABELS.find(([key]) => label.includes(key));
  return match ? match[1] : null;
}

export function currentAgent(events) {
  const running = [...events].reverse().find((event) => event.status === "running");
  if (!running) return null;
  return agentForEvent(running) || running.label;
}
export function nextStepSuggestions(plan, messages, hasPendingQuestion, busy) {
  if (hasPendingQuestion || busy) return [];
  const hasConversation = messages.some((item) => item.role === "user");
  if (!hasConversation) {
    return [
      "Plan a 4-day trip to Kyoto for $1,200, temples and food",
      "Plan a 5-day trip to Tokyo for $1,500, food and culture",
      "Plan a 3-day trip to Paris for $1,000, art and cafés",
      "Plan a 7-day trip to Rome for $2,000, history and local food",
    ];
  }
  if (plan) {
    return [
      `Make the ${plan.destination} itinerary more budget-friendly`,
      "Add one relaxing afternoon to each day",
      "Suggest local food for each day",
      "Find accommodation near the main sights",
    ];
  }
  return [
    "Turn this into a day-by-day itinerary",
    "Make it more budget-friendly",
    "Add more cultural activities",
    "Search accommodation options for this trip",
  ];
}

const TOOL_RESULT_SUFFIX = " result received";
const TOOL_CALL_PREFIX = "Calling ";
const TOOL_DISPLAY_NAMES = {
  search_stays: "Search accommodation",
  estimate_transport: "Estimate transport",
  web_search: "Web search",
  weather: "Weather lookup",
  search_travel_history: "Search travel history",
  display_trip_plan: "Show trip plan",
  start_trip_plan: "Start trip plan",
  set_trip_day: "Set trip day",
  set_trip_budget: "Set trip budget",
  set_trip_references: "Set trip references",
  remove_trip_day: "Remove trip day",
  get_trip_plan: "Get trip plan",
};

export function toolDisplayName(tool) {
  if (!tool) return "";
  if (TOOL_DISPLAY_NAMES[tool]) return TOOL_DISPLAY_NAMES[tool];
  const pretty = String(tool).replace(/_/g, " ").trim();
  return pretty ? pretty.charAt(0).toUpperCase() + pretty.slice(1) : "";
}

export function toolOfEvent(event) {
  const tool = event?.data?.tool;
  if (typeof tool === "string" && tool) return tool;
  const label = typeof event?.label === "string" ? event.label : "";
  if (label.startsWith(TOOL_CALL_PREFIX)) return label.slice(TOOL_CALL_PREFIX.length) || null;
  if (label.endsWith(TOOL_RESULT_SUFFIX)) {
    return label.slice(0, label.length - TOOL_RESULT_SUFFIX.length) || null;
  }
  return null;
}

export function isToolCallEvent(event) {
  return (
    event?.type === "tool" &&
    typeof event?.label === "string" &&
    event.label.startsWith(TOOL_CALL_PREFIX) &&
    toolOfEvent(event) != null
  );
}

export function isToolResultEvent(event) {
  return (
    event?.type === "tool" &&
    typeof event?.label === "string" &&
    event.label.endsWith(TOOL_RESULT_SUFFIX) &&
    toolOfEvent(event) != null
  );
}

// Request/response pairs that render as ONE card in the Live workflow:
// - model: "Model request queued" / "Model is thinking" / "Retrying
//   continuation" attempts + the matching turn outcome ("Model response
//   received", local stub, failure, empty, continuation failure).
// - agent: "Coordinator agent started" + "Coordinator agent completed" /
//   failure / "Stopped by user".
const MODEL_REQUEST_PATTERN = /^(Model request queued|Preparing model request|Model is thinking|Retrying continuation \(\d\/3\))$/;
const MODEL_RESPONSE_LABELS = new Set([
  "Model response received",
  "Using local model stub",
  "Model request failed",
  "Model returned an empty response",
  "Continuation failed; answer can be retried",
]);
const isModelRequestOpen = (event) =>
  event?.type === "model" && event.status === "running" && MODEL_REQUEST_PATTERN.test(event.label || "");
const isModelResponseClose = (event) =>
  event?.type === "model" && event.status !== "running" && MODEL_RESPONSE_LABELS.has(event.label);
const isAgentRunOpen = (event) =>
  event?.type === "agent" && event.status === "running" && / started$/i.test(event.label || "");
const isAgentRunClose = (event) =>
  event?.type === "agent" &&
  event.status !== "running" &&
  (/ (completed|failed)$/i.test(event.label || "") || event.label === "Stopped by user");

// Groups request/response pairs so one logical step renders as ONE card:
// each "Calling <tool>" with its result, each model call with its response,
// and each agent run with its completion. Pure: returns new card objects and
// never mutates the input events. Cards carry `index` (original index of the
// card's primary event) plus `toolName`/`toolLabel` on merged call cards.
// ask_user_question events keep their own cards, unmatched opens stay
// "running", and sequential calls to the same tool pair in order.
export function mergeToolEvents(events) {
  const list = Array.isArray(events) ? events : [];
  const cards = [];
  const openCalls = new Map();
  const openPair = (kind, card) => {
    const queue = openCalls.get(kind) || [];
    queue.push(card);
    openCalls.set(kind, queue);
  };
  const closePair = (kind, event) => {
    const queue = openCalls.get(kind);
    const open = queue && queue.length ? queue.shift() : null;
    if (!open) return null;
    open.status = event.status || open.status;
    if (event.detail) open.detail = event.detail;
    if (event.timestamp) open.timestamp = event.timestamp;
    open.merged = true;
    return open;
  };
  list.forEach((event, index) => {
    const tool = toolOfEvent(event);
    if (tool === "ask_user_question") {
      cards.push({ ...event, index });
      return;
    }
    if (isModelRequestOpen(event)) {
      // Consolidate repeat attempts (queued → thinking → retries) into the
      // single open card for this model call.
      const queue = openCalls.get("model");
      const open = queue && queue.length ? queue[queue.length - 1] : null;
      if (open) {
        if (event.label !== "Model request queued") open.label = event.label;
        if (event.detail) open.detail = event.detail;
        open.merged = true;
        return;
      }
      const card = { ...event, index };
      cards.push(card);
      openPair("model", card);
      return;
    }
    if (isModelResponseClose(event)) {
      // The most recent attempt produced the outcome; earlier attempt cards
      // belong to the same turn and must not stay "running".
      const queue = openCalls.get("model");
      if (queue && queue.length) {
        const open = queue.pop();
        open.status = event.status || open.status;
        open.label = event.label === "Model response received" ? "Model request → response" : event.label;
        if (event.detail) open.detail = event.detail;
        if (event.timestamp) open.timestamp = event.timestamp;
        open.merged = true;
        while (queue.length) queue.pop().status = open.status;
        return;
      }
    }
    if (isAgentRunOpen(event)) {
      const card = { ...event, index };
      cards.push(card);
      openPair("agent", card);
      return;
    }
    if (isAgentRunClose(event)) {
      const open = closePair("agent", event);
      if (open) {
        if (event.label === "Stopped by user") open.label = event.label;
        else {
          const base = open.label.replace(/\s+started$/i, "");
          open.label = / failed$/i.test(event.label || "") ? `${base} failed` : base;
        }
        return;
      }
    }
    if (isToolCallEvent(event)) {
      const card = { ...event, toolName: tool, toolLabel: toolDisplayName(tool), index };
      cards.push(card);
      openPair(tool, card);
      return;
    }
    if (isToolResultEvent(event)) {
      const queue = openCalls.get(tool);
      const open = queue && queue.length ? queue.shift() : null;
      if (open) {
        open.data = { ...(open.data || {}), result: event.data?.result };
        open.status = event.status || open.status;
        if (event.detail) open.detail = event.detail;
        if (event.timestamp) open.timestamp = event.timestamp;
        open.merged = true;
        return;
      }
    }
    cards.push({ ...event, index });
  });
  return cards;
}

const WORK_LABELS = {
  search_stays: "Searching accommodation",
  estimate_transport: "Estimating transport",
  web_search: "Searching the web",
  weather: "Checking weather",
  search_travel_history: "Checking travel history",
  display_trip_plan: "Updating the trip plan",
  start_trip_plan: "Starting the trip plan",
  set_trip_day: "Updating a trip day",
  set_trip_budget: "Updating the budget",
  set_trip_references: "Adding references",
  remove_trip_day: "Removing a trip day",
  get_trip_plan: "Reading the trip plan",
  ask_user_question: "Asking you a question",
};

function isAnsweredQuestion(event) {
  return event?.data?.tool === "ask_user_question" && Boolean(event?.data?.selected);
}

export function currentWork(events) {
  const list = Array.isArray(events) ? events : [];
  const running = [...list].reverse().find(
    (event) => event.status === "running" && !isAnsweredQuestion(event),
  );
  if (!running) return null;
  const tool = toolOfEvent(running);
  const detail = typeof running.detail === "string" ? running.detail.trim() : "";
  if (tool) {
    return { label: WORK_LABELS[tool] || toolDisplayName(tool) || running.label, detail };
  }
  const label = running.label || "";
  if (/^Retrying continuation/.test(label)) {
    return { label: "Retrying the model…", detail: detail || label };
  }
  if (label === "Model request queued" || label === "Preparing model request") {
    return { label: "Preparing the model…", detail };
  }
  if (label === "Model is thinking") {
    return { label: "Model is thinking", detail };
  }
  if (/travel history/i.test(`${label} ${detail}`)) {
    return { label: "Checking travel history", detail: detail || label };
  }
  if (/stay search|searching accommodations/i.test(`${label} ${detail}`)) {
    return { label: "Searching accommodation", detail: detail || label };
  }
  if (/coordinator/i.test(label)) {
    return { label: "Building the itinerary", detail: detail || label };
  }
  return { label: label || "Agent working", detail };
}

export function workflowState(events, pendingQuestion, status) {
  const text = status || "";
  if (pendingQuestion) {
    return { label: "Waiting for your response", detail: "Choose an option below.", className: "waiting", icon: "?" };
  }
  if (text.includes("Stopping") || text.includes("Stopped")) {
    return { label: "Stopped", detail: "", className: "ready", icon: "■" };
  }
  if (text.includes("failed") || events.some((event) => event.status === "error")) {
    return { label: "Needs attention", detail: text.includes("failed") ? text : "", className: "error", icon: "!" };
  }
  const work = currentWork(events);
  const lastEvent = events[events.length - 1];
  const busy = text === "Working..." || text.includes("Sending") || lastEvent?.status === "running" || Boolean(work);
  if (busy) {
    if (work) {
      return { label: work.label, detail: work.detail, className: "working", icon: "✦" };
    }
    if (text.includes("Sending your choice")) {
      return { label: "Sending your choice to the assistant...", detail: "Waiting for the assistant to continue.", className: "working", icon: "➜" };
    }
    return { label: "Agent working", detail: "Starting the next step…", className: "working", icon: "✦" };
  }
  return { label: "Ready", detail: "", className: "ready", icon: "✓" };
}
