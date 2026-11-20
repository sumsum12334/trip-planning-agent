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
      "Plan a 4-day trip to Kyoto in spring",
      "Search accommodation in Tokyo under $200 per night",
      "Check weather in Paris for next week",
      "Estimate transport from Hong Kong to Seoul",
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

// Groups each "Calling <tool>" event with the following result event for the
// same tool so one tool call renders as ONE card. Pure: returns new card
// objects and never mutates the input events. Cards carry `index` (original
// index of the card's primary event) plus `toolName`/`toolLabel` on merged
// call cards. ask_user_question events keep their own cards, unmatched calls
// stay "running", and sequential calls to the same tool pair in order.
export function mergeToolEvents(events) {
  const list = Array.isArray(events) ? events : [];
  const cards = [];
  const openCalls = new Map();
  list.forEach((event, index) => {
    const tool = toolOfEvent(event);
    if (tool === "ask_user_question") {
      cards.push({ ...event, index });
      return;
    }
    if (isToolCallEvent(event)) {
      const card = { ...event, toolName: tool, toolLabel: toolDisplayName(tool), index };
      cards.push(card);
      const queue = openCalls.get(tool) || [];
      queue.push(card);
      openCalls.set(tool, queue);
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

export function workflowState(events, pendingQuestion, status) {
  if (pendingQuestion) return { label: "Waiting for your response", className: "waiting", icon: "?" };
  if (status.includes("Sending your choice")) return { label: "Sending your choice to the assistant...", className: "working", icon: "➜" };
  if (status.includes("Stopping") || status.includes("Stopped")) return { label: "Stopped", className: "ready", icon: "■" };
  if (status.includes("failed") || events.some((event) => event.status === "error")) return { label: "Needs attention", className: "error", icon: "!" };
  const lastEvent = events[events.length - 1];
  if (status === "Working..." || status.includes("Sending") || lastEvent?.status === "running") return { label: "Agent working", className: "working", icon: "✦" };
  return { label: "Ready", className: "ready", icon: "✓" };
}
