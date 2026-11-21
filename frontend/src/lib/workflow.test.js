import { describe, expect, it } from "vitest";

import {
  agentForEvent,
  currentAgent,
  isToolCallEvent,
  isToolResultEvent,
  mergeToolEvents,
  nextStepSuggestions,
  toolDisplayName,
  toolOfEvent,
  currentWork,
  workflowState,
  workflowCards,
} from "./workflow.js";

const callEvent = (tool, args = {}, overrides = {}) => ({
  type: "tool",
  label: `Calling ${tool}`,
  status: "running",
  data: { tool, arguments: args },
  ...overrides,
});

const resultEvent = (tool, result, overrides = {}) => ({
  type: "tool",
  label: `${tool} result received`,
  status: "completed",
  data: { tool, result },
  ...overrides,
});

describe("agentForEvent", () => {
  it("maps tool events to their owning agent", () => {
    expect(agentForEvent({ label: "Trip plan updated (set_trip_day)" })).toBe(
      "Agent 3 · coordinator",
    );
    expect(agentForEvent({ label: "search_stays result received" })).toBe(
      "Agent 1 · search_stays",
    );
    expect(agentForEvent({ label: "Model response received" })).toBe("Model");
    expect(agentForEvent({ label: "Unrelated event" })).toBeNull();
  });
});

describe("currentAgent", () => {
  it("returns the label of the running event's agent", () => {
    const events = [
      { label: "Coordinator agent started", status: "completed" },
      { label: "Trip plan updated (set_trip_day)", status: "running" },
    ];
    expect(currentAgent(events)).toBe("Agent 3 · coordinator");
  });

  it("returns null when nothing is running", () => {
    expect(currentAgent([{ label: "Done", status: "completed" }])).toBeNull();
  });
});

describe("nextStepSuggestions", () => {
  it("suggests complete trip-plan starters for an empty conversation", () => {
    const suggestions = nextStepSuggestions(null, [], false, false);
    expect(suggestions.length).toBe(4);
    suggestions.forEach((suggestion) => {
      // Destination, duration, budget, and interests in one short prompt.
      expect(suggestion).toMatch(/^Plan a \d+-day trip to .+ for \$[\d,]+/);
    });
  });

  it("suggests plan refinements once a plan exists", () => {
    const suggestions = nextStepSuggestions({ destination: "Tokyo" }, [
      { role: "user", content: "hi" },
    ], false, false);
    expect(suggestions.some((text) => text.includes("Tokyo"))).toBe(true);
  });

  it("stays quiet while busy or awaiting an answer", () => {
    expect(nextStepSuggestions(null, [], true, false)).toEqual([]);
    expect(nextStepSuggestions(null, [], false, true)).toEqual([]);
  });
});

describe("workflowState", () => {
  it("reports waiting, working, error, and ready states", () => {
    expect(workflowState([], {}, "").label).toBe("Waiting for your response");
    expect(workflowState([], {}, "").detail).toBe("Choose an option below.");
    expect(workflowState([], null, "Working...").label).toBe("Agent working");
    expect(workflowState([{ status: "error" }], null, "").label).toBe(
      "Needs attention",
    );
    expect(workflowState([], null, "").label).toBe("Ready");
    expect(workflowState([], null, "Stopped.").label).toBe("Stopped");
  });

  it("keeps a generic sending label until work events arrive", () => {
    const state = workflowState([], null, "Sending your choice to the assistant...");
    expect(state.label).toBe("Sending your choice to the assistant...");
    expect(state.detail).toBe("Waiting for the assistant to continue.");
    expect(state.className).toBe("working");
  });

  it("shows the current running step instead of a generic sending status", () => {
    const events = [callEvent("search_stays", { destination: "Kyoto" })];
    const state = workflowState(
      events,
      null,
      "Sending your choice to the assistant...",
    );
    expect(state.label).toBe("Searching accommodation");
    expect(state.className).toBe("working");
  });

  it("ignores a just-answered question when describing current work", () => {
    const events = [
      {
        type: "tool",
        label: "ask_user_question",
        status: "running",
        data: {
          tool: "ask_user_question",
          result: { question: "Budget?" },
          selected: "$2,000–$3,500",
        },
        detail: "Answer selected: $2,000–$3,500",
      },
      { type: "model", label: "Model is thinking", status: "running" },
    ];
    expect(currentWork(events).label).toBe("Model is thinking");
    expect(
      workflowState(events, null, "Sending your choice to the assistant...").label,
    ).toBe("Model is thinking");
  });

  it("reports Ready after a turn whose last tool call already received its result", () => {
    // Regression: every tool call leaves its "Calling X" event running in the
    // raw list, so the old last-running-event scan hung the status bar on the
    // final tool step once the turn had completed.
    const events = [
      { type: "agent", label: "Coordinator agent started", status: "running" },
      { type: "model", label: "Model request queued", status: "running" },
      callEvent("set_trip_references", { references: [{ title: "Guide", url: "https://example.com" }] }),
      { type: "tool", label: "Trip plan updated (set_trip_references)", status: "completed", data: { tool: "display_trip_plan", result: {} } },
      resultEvent("set_trip_references", { ok: true }),
      { type: "model", label: "Model response received", status: "completed" },
      { type: "agent", label: "Coordinator agent completed", status: "completed" },
    ];
    expect(currentWork(events)).toBeNull();
    expect(currentAgent(events)).toBeNull();
    const state = workflowState(events, null, "Model: test-model");
    expect(state.label).toBe("Ready");
    expect(state.className).toBe("ready");
  });

  it("still reports the running step while work is genuinely in progress", () => {
    const events = [
      callEvent("set_trip_day", { day: 1 }),
      resultEvent("set_trip_day", { ok: true }),
      callEvent("set_trip_budget", { budget: 800 }),
    ];
    expect(currentWork(events).label).toBe("Updating the budget");
    expect(currentAgent(events)).toBe("Agent 3 · coordinator");
  });

  it("does not hang on the open waiting-for-answer marker after the answer resolves", () => {
    const events = [
      callEvent("ask_user_question", { question: "Go when?" }),
      resultEvent("ask_user_question", { question: "Go when?", status: "awaiting_user" }),
      { type: "agent", label: "Waiting for your answer", status: "running" },
      { type: "model", label: "Model request queued", status: "running" },
      { type: "model", label: "Model response received", status: "completed" },
      { type: "agent", label: "Coordinator agent completed", status: "completed" },
    ];
    expect(currentWork(events)).toBeNull();
    expect(workflowState(events, null, "Model: test-model").label).toBe("Ready");
  });

  it("reports Ready after a fallback-pipeline turn whose plain agent runs completed", () => {
    // Regression: the fallback pipeline's "Travel History Agent" / "Stay
    // Search Agent" / "Coordinator Agent" events stayed running in the raw
    // list after their same-label completions, so the status bar hung on
    // "Building the itinerary" once the turn had finished.
    const events = [
      { type: "agent", label: "Coordinator agent started", status: "running" },
      { type: "agent", label: "Travel History Agent", status: "running" },
      { type: "agent", label: "Stay Search Agent", status: "running" },
      { type: "agent", label: "Coordinator Agent", status: "running" },
      { type: "tool", label: "Trip plan updated (start_trip_plan)", status: "completed", data: { tool: "display_trip_plan", result: {} } },
      { type: "agent", label: "Travel History Agent", status: "completed" },
      { type: "agent", label: "Stay Search Agent", status: "completed" },
      { type: "agent", label: "Coordinator Agent", status: "completed" },
      { type: "agent", label: "Coordinator agent completed", status: "completed" },
    ];
    expect(currentWork(events)).toBeNull();
    expect(currentAgent(events)).toBeNull();
    const state = workflowState(events, null, "Model: test-model");
    expect(state.label).toBe("Ready");
    expect(state.className).toBe("ready");
  });
});

describe("workflowCards", () => {
  it("hides the plan panel's display_trip_plan mirror events", () => {
    const events = [
      { type: "agent", label: "Coordinator agent started", status: "running" },
      callEvent("set_trip_day", { day: 1 }),
      { type: "tool", label: "Trip plan updated (set_trip_day)", status: "completed", data: { tool: "display_trip_plan", result: {} } },
      resultEvent("set_trip_day", { ok: true }),
    ];
    const cards = workflowCards(events);
    expect(cards).toHaveLength(2);
    expect(cards.every((card) => card.data?.tool !== "display_trip_plan")).toBe(true);
    // mergeToolEvents itself stays complete for the plan panel and tests.
    expect(mergeToolEvents(events)).toHaveLength(3);
  });

  it("keeps question, model, and unmatched events visible", () => {
    const events = [
      { type: "model", label: "Model request queued", status: "running" },
      callEvent("ask_user_question", { question: "Go when?" }),
      resultEvent("ask_user_question", { question: "Go when?", status: "awaiting_user" }),
      { type: "agent", label: "Waiting for your answer", status: "running" },
    ];
    // One question card (call + result + waiting merged) plus the model card.
    expect(workflowCards(events)).toHaveLength(2);
  });

  it("handles empty and missing input", () => {
    expect(workflowCards([])).toEqual([]);
    expect(workflowCards(undefined)).toEqual([]);
  });
});

describe("toolDisplayName / toolOfEvent", () => {
  it("maps known tools to display names and prettifies unknown ones", () => {
    expect(toolDisplayName("search_stays")).toBe("Search accommodation");
    expect(toolDisplayName("custom_tool")).toBe("Custom tool");
    expect(toolDisplayName(null)).toBe("");
  });

  it("prefers data.tool and falls back to parsing the label", () => {
    expect(toolOfEvent(callEvent("weather"))).toBe("weather");
    expect(
      toolOfEvent({ type: "tool", label: "search_stays result received" }),
    ).toBe("search_stays");
    expect(toolOfEvent({ type: "agent", label: "Coordinator started" })).toBeNull();
  });

  it("classifies call and result events", () => {
    expect(isToolCallEvent(callEvent("weather"))).toBe(true);
    expect(isToolCallEvent(resultEvent("weather", {}))).toBe(false);
    expect(isToolResultEvent(resultEvent("weather", {}))).toBe(true);
    expect(
      isToolResultEvent({
        type: "tool",
        label: "Trip plan updated (set_trip_day)",
        data: { tool: "display_trip_plan" },
      }),
    ).toBe(false);
  });
});

describe("mergeToolEvents", () => {
  it("merges a call with its matching result into one completed card", () => {
    const cards = mergeToolEvents([
      callEvent("search_stays", { destination: "Tokyo" }),
      resultEvent("search_stays", { stays: [{ name: "Hotel A" }] }),
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].toolName).toBe("search_stays");
    expect(cards[0].toolLabel).toBe("Search accommodation");
    expect(cards[0].status).toBe("completed");
    expect(cards[0].merged).toBe(true);
    expect(cards[0].index).toBe(0);
    expect(cards[0].data.arguments).toEqual({ destination: "Tokyo" });
    expect(cards[0].data.result).toEqual({ stays: [{ name: "Hotel A" }] });
  });

  it("keeps a call without a result as a running card", () => {
    const cards = mergeToolEvents([callEvent("weather", { destination: "Paris" })]);
    expect(cards).toHaveLength(1);
    expect(cards[0].status).toBe("running");
    expect(cards[0].merged).toBeUndefined();
    expect(cards[0].data.arguments).toEqual({ destination: "Paris" });
  });

  it("keeps an unmatched result as its own card", () => {
    const cards = mergeToolEvents([resultEvent("weather", { condition: "sunny" })]);
    expect(cards).toHaveLength(1);
    expect(cards[0].label).toBe("weather result received");
    expect(cards[0].status).toBe("completed");
    expect(cards[0].data.result).toEqual({ condition: "sunny" });
  });

  it("pairs sequential calls to the same tool in order without cross-pairing", () => {
    const cards = mergeToolEvents([
      callEvent("set_trip_day", { day: 1 }),
      callEvent("set_trip_day", { day: 2 }),
      resultEvent("set_trip_day", { ok: 1 }),
      resultEvent("set_trip_day", { ok: 2 }),
    ]);
    expect(cards).toHaveLength(2);
    expect(cards[0].index).toBe(0);
    expect(cards[0].data.result).toEqual({ ok: 1 });
    expect(cards[1].index).toBe(1);
    expect(cards[1].data.result).toEqual({ ok: 2 });
  });

  it("pairs interleaved call/result rounds for the same tool", () => {
    const cards = mergeToolEvents([
      callEvent("set_trip_day", { day: 1 }),
      resultEvent("set_trip_day", { ok: 1 }),
      callEvent("set_trip_day", { day: 2 }),
      resultEvent("set_trip_day", { ok: 2 }),
    ]);
    expect(cards).toHaveLength(2);
    expect(cards[0].data.arguments).toEqual({ day: 1 });
    expect(cards[0].data.result).toEqual({ ok: 1 });
    expect(cards[1].data.arguments).toEqual({ day: 2 });
    expect(cards[1].data.result).toEqual({ ok: 2 });
  });

  it("folds the question call, result, and waiting marker into one running card", () => {
    const cards = mergeToolEvents([
      callEvent("ask_user_question", { question: "Go when?" }),
      resultEvent("ask_user_question", { question: "Go when?", status: "awaiting_user" }),
      { type: "agent", label: "Waiting for your answer", detail: "Go when?", status: "running" },
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].toolLabel).toBe("Asking you a question");
    // The waiting marker is the card's current status, not a separate event.
    expect(cards[0].status).toBe("running");
    expect(cards[0].detail).toBe("Go when?");
    expect(cards[0].data.result).toEqual({ question: "Go when?", status: "awaiting_user" });
    expect(cards[0].merged).toBe(true);
  });

  it("shows the answered question card as completed with the selected answer", () => {
    const cards = mergeToolEvents([
      callEvent("ask_user_question", { question: "Go when?" }),
      resultEvent("ask_user_question", { question: "Go when?" }, {
        data: { tool: "ask_user_question", result: { question: "Go when?" }, selected: "March" },
        detail: "Answer selected: March",
      }),
      { type: "agent", label: "Waiting for your answer", detail: "Go when?", status: "running" },
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].status).toBe("completed");
    expect(cards[0].detail).toBe("Answer selected: March");
    expect(cards[0].data.selected).toBe("March");
  });

  it("keeps agent, handover, and trip-plan events intact", () => {
    const events = [
      { type: "agent", label: "Coordinator agent started", status: "completed" },
      callEvent("set_trip_day"),
      resultEvent("set_trip_day", { ok: true }),
      { type: "tool", label: "Trip plan updated (set_trip_day)", status: "completed", data: { tool: "display_trip_plan", result: {} } },
      { type: "model", label: "Model response received", status: "completed" },
    ];
    const cards = mergeToolEvents(events);
    expect(cards).toHaveLength(4);
    expect(cards[0].label).toBe("Coordinator agent started");
    expect(cards[1].toolLabel).toBe("Set trip day");
    expect(cards[2].label).toBe("Trip plan updated (set_trip_day)");
    expect(cards[3].label).toBe("Model response received");
  });

  it("propagates an error status and detail from the result event", () => {
    const cards = mergeToolEvents([
      callEvent("web_search", { query: "trains" }),
      resultEvent("web_search", { ok: false }, { status: "error", detail: "Provider failed." }),
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].status).toBe("error");
    expect(cards[0].detail).toBe("Provider failed.");
  });

  it("keeps the running status when only the call exists, then completes", () => {
    const running = mergeToolEvents([callEvent("weather")])[0];
    expect(running.status).toBe("running");
    const done = mergeToolEvents([callEvent("weather"), resultEvent("weather", { condition: "rain" })])[0];
    expect(done.status).toBe("completed");
  });

  it("handles empty and missing input", () => {
    expect(mergeToolEvents([])).toEqual([]);
    expect(mergeToolEvents(undefined)).toEqual([]);
  });
});

describe("mergeToolEvents: model request/response pairs", () => {
  it("merges the request, thinking, and response into one completed card", () => {
    const cards = mergeToolEvents([
      { type: "model", label: "Model request queued", status: "running" },
      { type: "model", label: "Model is thinking", detail: "qwen", status: "running" },
      { type: "model", label: "Model response received", status: "completed" },
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].label).toBe("Model request → response");
    expect(cards[0].status).toBe("completed");
    expect(cards[0].merged).toBe(true);
    expect(cards[0].index).toBe(0);
  });

  it("keeps a request without a response as a running card", () => {
    const cards = mergeToolEvents([{ type: "model", label: "Model is thinking", status: "running" }]);
    expect(cards).toHaveLength(1);
    expect(cards[0].status).toBe("running");
    expect(cards[0].merged).toBeUndefined();
  });

  it("merges the local stub outcome into the queued request", () => {
    const cards = mergeToolEvents([
      { type: "model", label: "Model request queued", status: "running" },
      { type: "model", label: "Using local model stub", status: "completed" },
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].label).toBe("Using local model stub");
    expect(cards[0].status).toBe("completed");
  });

  it("marks a failed request with the failure status and label", () => {
    const cards = mergeToolEvents([
      { type: "model", label: "Model is thinking", status: "running" },
      { type: "model", label: "Model request failed", detail: "boom", status: "error" },
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].label).toBe("Model request failed");
    expect(cards[0].status).toBe("error");
    expect(cards[0].detail).toBe("boom");
  });

  it("absorbs retry attempts so no card stays running forever", () => {
    const cards = mergeToolEvents([
      { type: "model", label: "Model is thinking", status: "running" },
      { type: "model", label: "Retrying continuation (1/3)", status: "running" },
      { type: "model", label: "Retrying continuation (2/3)", status: "running" },
      { type: "model", label: "Model response received", status: "completed" },
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].label).toBe("Model request → response");
    expect(cards[0].status).toBe("completed");
  });

  it("keeps a response without an open request as its own card", () => {
    const cards = mergeToolEvents([{ type: "model", label: "Model response received", status: "completed" }]);
    expect(cards).toHaveLength(1);
    expect(cards[0].label).toBe("Model response received");
    expect(cards[0].merged).toBeUndefined();
  });
});

describe("mergeToolEvents: agent run pairs", () => {
  it("merges the coordinator start and completion into one card", () => {
    const cards = mergeToolEvents([
      { type: "agent", label: "Coordinator agent started", status: "running" },
      callEvent("search_stays", { destination: "Tokyo" }),
      resultEvent("search_stays", { stays: [] }),
      { type: "agent", label: "Coordinator agent completed", status: "completed" },
    ]);
    expect(cards).toHaveLength(2);
    expect(cards[0].label).toBe("Coordinator agent");
    expect(cards[0].status).toBe("completed");
    expect(cards[0].merged).toBe(true);
  });

  it("keeps the failure label when the run fails", () => {
    const cards = mergeToolEvents([
      { type: "agent", label: "Coordinator agent started", status: "running" },
      { type: "agent", label: "Coordinator agent failed", status: "error" },
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].label).toBe("Coordinator agent failed");
    expect(cards[0].status).toBe("error");
  });

  it("merges a user stop into the run card", () => {
    const cards = mergeToolEvents([
      { type: "agent", label: "Coordinator agent started", status: "running" },
      { type: "agent", label: "Stopped by user", status: "completed" },
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].label).toBe("Stopped by user");
    expect(cards[0].status).toBe("completed");
  });

  it("leaves a completed start event without a running status untouched", () => {
    const cards = mergeToolEvents([
      { type: "agent", label: "Coordinator agent started", status: "completed" },
    ]);
    expect(cards).toHaveLength(1);
    expect(cards[0].label).toBe("Coordinator agent started");
    expect(cards[0].merged).toBeUndefined();
  });

  it("pairs the fallback pipeline's plain-label agent runs by label", () => {
    // The deterministic fallback emits "… Agent" running/completed pairs with
    // no "started" suffix; interleaved, they must not steal each other's
    // close event.
    const cards = mergeToolEvents([
      { type: "agent", label: "Travel History Agent", status: "running" },
      { type: "agent", label: "Stay Search Agent", status: "running" },
      { type: "agent", label: "Coordinator Agent", status: "running" },
      { type: "agent", label: "Travel History Agent", status: "completed" },
      { type: "agent", label: "Stay Search Agent", status: "completed" },
      { type: "agent", label: "Coordinator Agent", status: "completed" },
    ]);
    expect(cards).toHaveLength(3);
    expect(cards.map((card) => card.label)).toEqual([
      "Travel History Agent",
      "Stay Search Agent",
      "Coordinator Agent",
    ]);
    expect(cards.every((card) => card.status === "completed")).toBe(true);
  });

  it("merges a user stop into every open agent run", () => {
    const cards = mergeToolEvents([
      { type: "agent", label: "Coordinator agent started", status: "running" },
      { type: "agent", label: "Travel History Agent", status: "running" },
      { type: "agent", label: "Stopped by user", status: "completed" },
    ]);
    expect(cards).toHaveLength(2);
    expect(cards[0].label).toBe("Stopped by user");
    expect(cards[0].status).toBe("completed");
    // The other open run is closed too, so nothing stays running after a stop.
    expect(cards[1].label).toBe("Travel History Agent");
    expect(cards[1].status).toBe("completed");
  });
});
