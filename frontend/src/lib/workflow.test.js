import { describe, expect, it } from "vitest";

import {
  agentForEvent,
  currentAgent,
  nextStepSuggestions,
  workflowState,
} from "./workflow.js";

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
