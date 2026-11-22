import { describe, expect, it } from "vitest";

import {
  buildPlanHtml,
  buildPlanMarkdown,
  escapeHtml,
  formatBudget,
  formatMarkerRanges,
  formatPlanDate,
  markerNumbersForDay,
  planDateRange,
  planEditChanges,
  planFromEvents,
  routePoints,
  splitLines,
  summarizePlanEdit,
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

describe("planDateRange", () => {
  it("returns one ISO date per day starting at the start date", () => {
    expect(planDateRange("2026-11-25", 3)).toEqual([
      "2026-11-25",
      "2026-11-26",
      "2026-11-27",
    ]);
    expect(planDateRange("2026-11-30", 2)).toEqual(["2026-11-30", "2026-12-01"]);
  });

  it("rolls across month and year boundaries", () => {
    expect(planDateRange("2026-12-31", 2)).toEqual(["2026-12-31", "2027-01-01"]);
    expect(planDateRange("2028-02-28", 2)).toEqual(["2028-02-28", "2028-02-29"]);
  });

  it("returns [] for invalid or missing input", () => {
    expect(planDateRange("", 3)).toEqual([]);
    expect(planDateRange(null, 3)).toEqual([]);
    expect(planDateRange("25/11/2026", 3)).toEqual([]);
    expect(planDateRange("2026-02-30", 3)).toEqual([]);
    expect(planDateRange("2026-11-25", 0)).toEqual([]);
    expect(planDateRange("2026-11-25", -1)).toEqual([]);
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

describe("formatMarkerRanges", () => {
  it("collapses contiguous markers into a range", () => {
    expect(formatMarkerRanges([1, 2, 3])).toBe("1-3");
    expect(formatMarkerRanges([2, 3, 4])).toBe("2-4");
  });

  it("keeps non-contiguous runs separate", () => {
    expect(formatMarkerRanges([2, 3, 4, 7])).toBe("2-4, 7");
    expect(formatMarkerRanges([1, 5, 6])).toBe("1, 5-6");
  });

  it("handles single markers and normalises the input", () => {
    expect(formatMarkerRanges([5])).toBe("5");
    expect(formatMarkerRanges([])).toBe("");
    // Unsorted input and duplicates are normalised.
    expect(formatMarkerRanges([3, 1, 2, 2])).toBe("1-3");
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

describe("formatPlanDate", () => {
  it("formats an ISO date for display", () => {
    expect(formatPlanDate("2026-11-20")).toBe("20 Nov 2026");
    expect(formatPlanDate("2027-01-05")).toBe("05 Jan 2027");
  });

  it("renders nothing for missing or invalid dates", () => {
    expect(formatPlanDate(undefined)).toBe("");
    expect(formatPlanDate(null)).toBe("");
    expect(formatPlanDate("")).toBe("");
    expect(formatPlanDate("not-a-date")).toBe("");
    expect(formatPlanDate("2026-13-01")).toBe("");
    expect(formatPlanDate("2026-02-30")).toBe("");
  });
});

describe("summarizePlanEdit", () => {
  it("summarizes category budget edits", () => {
    expect(
      summarizePlanEdit(samplePlan, {
        mode: "category",
        budget: 800,
        budget_items: [{ category: "food", amount: 200, currency: "HKD" }],
      }),
    ).toBe("estimated total, category items");
  });

  it("summarizes per-day edits field by field", () => {
    const editedDay = { ...samplePlan.days[1], budget: 250, title: "Victoria Peak walk" };
    expect(summarizePlanEdit(samplePlan, { mode: "day", days: [editedDay] })).toBe(
      "day 2 title, budget",
    );
  });

  it("returns an empty summary when nothing changed", () => {
    expect(summarizePlanEdit(samplePlan, { mode: "category", budget: 600, budget_items: [{ category: "food", amount: 120, currency: "HKD" }] })).toBe("");
    expect(summarizePlanEdit(samplePlan, { mode: "day", days: [samplePlan.days[0]] })).toBe("");
  });

  it("notes an added day and ignores unrelated modes", () => {
    expect(summarizePlanEdit(samplePlan, { mode: "day", days: [{ day: 3, title: "New" }] })).toBe("day 3 added");
    expect(summarizePlanEdit(samplePlan, { mode: "other" })).toBe("");
    expect(summarizePlanEdit(samplePlan, null)).toBe("");
  });
});

describe("planEditChanges", () => {
  it("lists day edits with the actual before → after values", () => {
    const editedDay = { ...samplePlan.days[1], budget: 250, title: "Victoria Peak walk" };
    const changes = planEditChanges(samplePlan, { mode: "day", days: [editedDay] });
    expect(changes).toContain('Day 2 title: "The Peak" → "Victoria Peak walk"');
    expect(changes).toContain("Day 2 budget: not set → HKD 250");
    expect(changes).toHaveLength(2);
  });

  it("lists added and removed activities, notes, and route stops", () => {
    const editedDay = {
      ...samplePlan.days[1],
      activities: ["Victoria Peak", "Peak Tram ride"],
      notes: ["Bring water"],
      places: [{ name: "Peak Tower" }],
    };
    const changes = planEditChanges(samplePlan, { mode: "day", days: [editedDay] });
    expect(changes).toContain('Day 2 activities: added: "Peak Tram ride"');
    expect(changes).toContain('Day 2 notes: added: "Bring water"');
    expect(changes).toContain('Day 2 route: added: "Peak Tower"; removed: "Victoria Peak"');
  });

  it("describes budget-item diffs and added days", () => {
    const editedDay = {
      ...samplePlan.days[1],
      budget_items: [
        { category: "transport", amount: 80, currency: "HKD" },
        { category: "food", amount: 60, currency: "HKD" },
      ],
    };
    const changes = planEditChanges(samplePlan, { mode: "day", days: [editedDay] });
    expect(changes).toContain("Day 2 budget item transport: HKD 100 → HKD 80");
    expect(changes).toContain("Day 2 budget item food: added HKD 60");

    expect(planEditChanges(samplePlan, { mode: "day", days: [{ day: 3, title: "New" }] })).toEqual([
      'Day 3 added: "New"',
    ]);
  });

  it("describes category edits with the estimated total and item diffs", () => {
    const changes = planEditChanges(samplePlan, {
      mode: "category",
      budget: 800,
      budget_items: [
        { category: "food", amount: 200, currency: "HKD" },
        { category: "transport", amount: 100, currency: "HKD" },
      ],
    });
    expect(changes).toContain("Estimated total: HKD 600 → HKD 800");
    expect(changes).toContain("Category item food: HKD 120 → HKD 200");
    expect(changes).toContain("Category item transport: added HKD 100");
  });

  it("returns an empty list when nothing changed", () => {
    expect(planEditChanges(samplePlan, { mode: "day", days: [samplePlan.days[0]] })).toEqual([]);
    expect(planEditChanges(samplePlan, { mode: "category", budget: 600, budget_items: [{ category: "food", amount: 120, currency: "HKD" }] })).toEqual([]);
    expect(planEditChanges(samplePlan, null)).toEqual([]);
    expect(planEditChanges(null, { mode: "day", days: [] })).toEqual([]);
  });
});
