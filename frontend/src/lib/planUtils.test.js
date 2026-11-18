import { describe, expect, it } from "vitest";

import {
  buildPlanHtml,
  buildPlanMarkdown,
  escapeHtml,
  formatBudget,
  markerNumbersForDay,
  planFromEvents,
  routePoints,
  splitLines,
} from "./planUtils.js";

const samplePlan = {
  destination: "Hong Kong",
  currency: "HKD",
  budget: 600,
  budget_items: [{ category: "food", amount: 120, currency: "HKD" }],
  airport: { name: "Hong Kong Airport", coordinates: { lat: 22.308, lng: 113.918 } },
  notes: ["Pack light"],
  references: [{ title: "Guide", url: "https://example.com/guide" }],
  days: [
    {
      day: 1,
      title: "Arrival",
      activities: ["Check in", "Harbour walk"],
      notes: ["Airport Express is fastest"],
      coordinates: { lat: 22.28, lng: 114.16 },
      places: [],
      budget: 300,
      budget_items: [],
    },
    {
      day: 2,
      title: "The Peak",
      activities: ["Victoria Peak"],
      notes: [],
      places: [
        { name: "Victoria Peak", coordinates: { lat: 22.27, lng: 114.15 }, url: null },
      ],
      budget: null,
      budget_items: [{ category: "transport", amount: 100, currency: "HKD" }],
    },
  ],
};

describe("formatBudget", () => {
  it("formats amounts with currency prefix", () => {
    expect(formatBudget(600, "HKD")).toBe("HKD 600");
    expect(formatBudget(12.345, "USD")).toBe("USD 12.35");
  });

  it("returns null for missing values and omits empty currency", () => {
    expect(formatBudget(null, "HKD")).toBeNull();
    expect(formatBudget(5, "")).toBe("5");
  });
});

describe("escapeHtml", () => {
  it("escapes markup characters", () => {
    expect(escapeHtml('<b class="x">&\'</b>')).toBe(
      "&lt;b class=&quot;x&quot;&gt;&amp;&#39;&lt;/b&gt;",
    );
  });
});

describe("splitLines", () => {
  it("splits, trims, and drops empty lines", () => {
    expect(splitLines("a\n b \n\n c")).toEqual(["a", "b", "c"]);
    expect(splitLines(null)).toEqual([]);
  });
});

describe("routePoints", () => {
  it("starts the route at the arrival airport and includes day stops", () => {
    const points = routePoints(samplePlan);
    expect(points[0].kind).toBe("airport");
    expect(points[0].label).toBe("Hong Kong Airport");
    const kinds = points.map((point) => point.kind);
    expect(kinds).toContain("day");
    expect(kinds).toContain("place");
  });

  it("returns an empty list for plans without coordinates", () => {
    expect(routePoints({ destination: "Nowhere", days: [] })).toEqual([]);
    expect(routePoints(null)).toEqual([]);
  });
});

describe("markerNumbersForDay", () => {
  it("numbers only the markers belonging to the given day", () => {
    const points = [
      { day: 1 },
      { day: 2 },
      { day: 2 },
    ];
    expect(markerNumbersForDay(points, 2)).toEqual([2, 3]);
    expect(markerNumbersForDay(points, 3)).toEqual([]);
  });
});

describe("planFromEvents", () => {
  it("finds the latest trip-plan event and honours the predicate", () => {
    const events = [
      { data: { tool: "display_trip_plan", result: { destination: "Old" } } },
      { data: { tool: "other" } },
      { data: { tool: "display_trip_plan", result: { destination: "New" } } },
    ];
    expect(planFromEvents(events)?.data.result.destination).toBe("New");
    expect(planFromEvents(events, () => false)).toBeUndefined();
  });
});

describe("buildPlanMarkdown", () => {
  it("renders the plan as day-by-day Markdown", () => {
    const markdown = buildPlanMarkdown(samplePlan);
    expect(markdown).toContain("# Hong Kong — Trip plan");
    expect(markdown).toContain("**Estimated budget:** HKD 600");
    expect(markdown).toContain("## Day 1: Arrival");
    expect(markdown).toContain("- [Guide](https://example.com/guide)");
    expect(markdown).toContain("HKD 120");
  });
});

describe("buildPlanHtml", () => {
  it("builds a printable HTML report", () => {
    const html = buildPlanHtml(samplePlan);
    expect(html).toContain("<!doctype html>");
    expect(html).toContain("Hong Kong Airport");
    expect(html).toContain("Victoria Peak");
    expect(html).toContain("Items total");
  });
});
