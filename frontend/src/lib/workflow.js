export const AGENT_LABELS = [
  ["search_stays", "Agent 1 · search_stays"],
  ["estimate_transport", "Agent 2 · estimate_transport"],
  ["travel_history", "Agent 4 · travel_history"],
  ["web_search", "web_search tool"],
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
      "Suggest a budget weekend getaway for two",
      "I have been to Tokyo before — plan something new",
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
  ];
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
