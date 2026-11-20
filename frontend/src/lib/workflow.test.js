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
  workflowState,
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
  it("suggests starters for an empty conversation", () => {
    const suggestions = nextStepSuggestions(null, [], false, false);
    expect(suggestions.length).toBeGreaterThan(0);
    expect(suggestions[0]).toContain("Plan a 4-day trip");
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
    expect(workflowState([], null, "Working...").label).toBe("Agent working");
    expect(workflowState([{ status: "error" }], null, "").label).toBe(
      "Needs attention",
    );
    expect(workflowState([], null, "").label).toBe("Ready");
    expect(workflowState([], null, "Stopped.").label).toBe("Stopped");
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

  it("keeps ask_user_question events as their own cards", () => {
    const cards = mergeToolEvents([
      callEvent("ask_user_question", { question: "Go when?" }),
      resultEvent("ask_user_question", { question: "Go when?", status: "awaiting_user" }),
      { type: "agent", label: "Waiting for your answer", status: "running" },
    ]);
    expect(cards).toHaveLength(3);
    expect(cards[0].label).toBe("Calling ask_user_question");
    expect(cards[1].label).toBe("ask_user_question result received");
    expect(cards[2].label).toBe("Waiting for your answer");
    expect(cards.every((card) => card.merged === undefined)).toBe(true);
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
});
