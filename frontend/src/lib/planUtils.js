// Pure trip-plan helpers shared by the UI components and the unit tests.

export const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]
  ));
export const slugify = (value) =>
  String(value ?? "trip-plan").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "trip-plan";
export const formatAmount = (value) => {
  if (value == null || value === "") return "";
  const number = Number(value);
  return Number.isFinite(number) ? String(Math.round(number * 100) / 100) : String(value);
};
export const formatBudget = (value, currency) =>
  value == null ? null : `${currency ? `${currency} ` : ""}${formatAmount(value)}`;

export const eventIcon = (event) => {
  if (event.status === "error") return "⚠";
  if (event.label.toLowerCase().includes("history")) return "🧠";
  if (event.label.toLowerCase().includes("weather")) return "🌤";
  if (event.type === "model") return "✦";
  if (event.label.toLowerCase().includes("tool")) return "⚙";
  return "✓";
};

export const planBudgetItems = (plan) => (Array.isArray(plan?.budget_items) ? plan.budget_items : []);
export const planFromEvents = (events, predicate = () => true) =>
  [...(events || [])].reverse().find(
    (event) => event.data?.tool === "display_trip_plan" && event.data?.result && predicate(event.data.result),
  );

export function routePoints(plan) {
  if (!plan) return [];
  const points = [];
  if (plan.airport?.coordinates) {
    points.push({ ...plan.airport.coordinates, label: plan.airport.name, sub: "Arrival airport", kind: "airport" });
  } else if (plan.destination_coordinates) {
    points.push({ ...plan.destination_coordinates, label: plan.destination, sub: "Destination", kind: "destination" });
  }
  (plan.days || []).forEach((day) => {
    const placePoints = (day.places || []).filter((place) => place.coordinates);
    if (placePoints.length) {
      placePoints.forEach((place) => points.push({ ...place.coordinates, label: place.name, sub: `Day ${day.day}`, kind: "place", day: day.day }));
    } else if (day.coordinates) {
      points.push({ ...day.coordinates, label: `Day ${day.day}: ${day.title}`, sub: "Day stop (approximate)", kind: "day", day: day.day });
    }
  });
  return points.filter((point) => typeof point.lat === "number" && typeof point.lng === "number");
}

export function markerNumbersForDay(points, dayNumber) {
  return points
    .map((point, index) => (point.day === dayNumber ? index + 1 : null))
    .filter((number) => number != null);
}
export function splitLines(value) {
  return String(value || "").split("\n").map((line) => line.trim()).filter(Boolean);
}
export function buildPlanMarkdown(plan) {
  const currency = plan.currency || "";
  const items = planBudgetItems(plan);
  const lines = [`# ${plan.destination} — Trip plan`, ""];
  const estimate = plan.budget ?? null;
  if (estimate != null) lines.push(`**Estimated budget:** ${formatBudget(estimate, currency)}`, "");
  const dayBudgets = (plan.days || []).filter((day) => day.budget != null);
  if (dayBudgets.length) {
    lines.push("**Per-day estimate:**", "");
    dayBudgets.forEach((day) => lines.push(`- Day ${day.day}: ${formatBudget(day.budget, currency)}`));
    lines.push("");
  }
  if (items.length) {
    lines.push("**Budget breakdown:**", "");
    items.forEach((item) => lines.push(`- ${item.category}: ${formatBudget(item.amount, item.currency || currency)}`));
    lines.push("");
  }
  const points = routePoints(plan);
  if (points.length) lines.push(`**Route:** ${points.map((point) => point.label).join(" → ")}`, "");
  (plan.days || []).forEach((day) => {
    lines.push(`## Day ${day.day}: ${day.title}`, "");
    (day.activities || []).forEach((activity) => lines.push(`- ${activity}`));
    if (day.places?.length) lines.push("", `_Places: ${day.places.map((place) => place.name).join(", ")}_`);
    if (day.notes?.length) lines.push("", `> ${day.notes.join(" · ")}`);
    lines.push("");
  });
  if (plan.notes?.length) lines.push("## Notes", "", ...plan.notes.map((note) => `- ${note}`), "");
  if (plan.references?.length) {
    lines.push("## References", "", ...plan.references.map((ref) => `- [${ref.title}](${ref.url})`), "");
  }
  lines.push("_Prices, coordinates, and availability are approximate and should be confirmed before booking._");
  return lines.join("\n");
}
export function buildPlanHtml(plan) {
  const currency = plan.currency || "";
  const items = planBudgetItems(plan);
  const estimate = plan.budget ?? null;
  const days = plan.days || [];
  const points = routePoints(plan);
  const itemsTotal = items.length
    ? Math.round(items.reduce((sum, item) => sum + (Number(item.amount) || 0), 0) * 100) / 100
    : null;
  const markerForPlace = (dayNumber, name) => {
    const index = points.findIndex((point) => point.kind === "place" && point.day === dayNumber && point.label === name);
    return index >= 0 ? index + 1 : null;
  };
  const generated = new Date().toLocaleDateString();
  const budgetText = estimate == null ? "Not specified" : formatBudget(estimate, currency);

  const daySections = days.map((day) => {
    const dayItems = Array.isArray(day.budget_items) ? day.budget_items : [];
    const dayItemsTotal = dayItems.length
      ? Math.round(dayItems.reduce((sum, item) => sum + (Number(item.amount) || 0), 0) * 100) / 100
      : null;
    const dayTotal = day.budget ?? dayItemsTotal;
    return `<section class="day">
      <header class="day-head">
        <span class="day-num">Day ${escapeHtml(day.day)}</span>
        <h3>${escapeHtml(day.title)}</h3>
        ${dayTotal != null ? `<span class="day-total">${escapeHtml(formatBudget(dayTotal, currency))}</span>` : ""}
      </header>
      <ul class="activities">${(day.activities || []).map((activity) => `<li>${escapeHtml(activity)}</li>`).join("")}</ul>
      ${(day.places || []).length ? `<p class="route"><span class="label">Route</span> ${day.places.map((place) => {
        const marker = markerForPlace(day.day, place.name);
        return `${marker ? `<span class="mk">${marker}</span>` : ""}${escapeHtml(place.name)}`;
      }).join(' <span class="arrow">→</span> ')}</p>` : ""}
      ${dayItems.length ? `<table class="mini"><tbody>${dayItems.map((item) => `<tr><td>${escapeHtml(item.category)}</td><td class="amt">${escapeHtml(formatBudget(item.amount, item.currency || currency))}</td></tr>`).join("")}</tbody></table>` : ""}
      ${(day.notes || []).length ? `<p class="notes">${day.notes.map(escapeHtml).join(" · ")}</p>` : ""}
    </section>`;
  }).join("");

  const routeRows = [
    plan.airport?.name ? `<li><span class="mk airport">✈</span><div><strong>${escapeHtml(plan.airport.name)}</strong><br/><span class="muted">Arrival airport</span></div></li>` : "",
    ...days.map((day) => {
      const markers = points.map((point, index) => (point.day === day.day ? index + 1 : null)).filter((value) => value != null);
      return `<li><span class="mk">${escapeHtml(day.day)}</span><div><strong>Day ${escapeHtml(day.day)} · ${escapeHtml(day.title)}</strong><br/><span class="muted">${(day.activities || []).length} activities${markers.length ? ` · map markers ${markers.join(", ")}` : ""}</span></div></li>`;
    }),
  ].join("");

  const categoryHtml = items.length
    ? `<section class="card"><h2>Category budget</h2><table class="budget"><tbody>${items.map((item) => `<tr><td>${escapeHtml(item.category)}</td><td class="amt">${escapeHtml(formatBudget(item.amount, item.currency || currency))}</td></tr>`).join("")}<tr class="total"><td>Items total</td><td class="amt">${escapeHtml(formatBudget(itemsTotal, currency))}</td></tr></tbody></table></section>`
    : "";
  const notesHtml = (plan.notes || []).length
    ? `<section class="card"><h2>Notes</h2><ul>${plan.notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul></section>`
    : "";
  const referencesHtml = (plan.references || []).length
    ? `<section class="card"><h2>References</h2><ul class="refs">${plan.references.map((ref) => `<li><a href="${escapeHtml(ref.url)}">${escapeHtml(ref.title)}</a></li>`).join("")}</ul></section>`
    : "";

  return `<!doctype html><html lang="en"><head><meta charset="utf-8"/>
    <title>${escapeHtml(plan.destination)} trip plan</title>
    <style>
      *{box-sizing:border-box}
      :root{--brand:#6c63ff;--ink:#1f2a44;--muted:#6b7793;--line:#e6eaf3}
      body{font:13px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);margin:0;padding:28px 36px}
      a{color:#3b5ecb;text-decoration:none}
      .hero{background:linear-gradient(135deg,#eef2ff,#f7f9ff);border:1px solid var(--line);border-radius:16px;padding:20px 24px;margin-bottom:18px}
      .hero h1{margin:0;font-size:27px;letter-spacing:-.02em}
      .hero .sub{color:var(--muted);margin:4px 0 14px}
      .stats{display:flex;gap:12px;flex-wrap:wrap}
      .stat{flex:1 1 150px;background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px 12px}
      .stat .k{color:var(--muted);font-size:10px;font-weight:800;letter-spacing:1px;text-transform:uppercase}
      .stat .v{font-size:15px;font-weight:700;margin-top:3px}
      .card{border:1px solid var(--line);border-radius:14px;padding:14px 18px;margin:16px 0;break-inside:avoid}
      .card h2{font-size:13px;margin:0 0 10px;color:#334568;text-transform:uppercase;letter-spacing:1px}
      .timeline{list-style:none;margin:0;padding:0}
      .timeline li{display:flex;gap:10px;align-items:flex-start;padding:6px 0;border-top:1px solid var(--line)}
      .timeline li:first-child{border-top:0}
      .mk{display:inline-grid;place-items:center;min-width:22px;height:22px;padding:0 6px;border-radius:999px;background:var(--brand);color:#fff;font-size:11px;font-weight:700}
      .mk.airport{background:#2f9e6f;min-width:26px}
      .muted{color:var(--muted)}
      .day{break-inside:avoid;border:1px solid var(--line);border-radius:14px;padding:14px 18px;margin:12px 0}
      .day-head{display:flex;align-items:baseline;gap:10px}
      .day-num{background:#eef2ff;color:#3b5ecb;border-radius:8px;padding:2px 8px;font-size:11px;font-weight:800;letter-spacing:.5px}
      .day-head h3{margin:0;font-size:16px;flex:1}
      .day-total{color:#3b5ecb;font-weight:700;font-size:13px}
      .activities{margin:10px 0 0;padding-left:18px}
      .activities li{margin:3px 0}
      .route{color:var(--muted);margin:10px 0 0}
      .route .label{font-weight:800;color:#334568;margin-right:4px}
      .arrow{color:#a9b3cc;padding:0 2px}
      table{width:100%;border-collapse:collapse;margin-top:8px}
      table td{padding:5px 6px;border-bottom:1px solid var(--line);text-align:left}
      table .amt{text-align:right;font-variant-numeric:tabular-nums;color:#334568}
      table .total td{font-weight:800;color:#3b5ecb;border-bottom:0;border-top:2px solid #dbe3f7}
      .mini{max-width:320px}
      .notes{color:var(--muted);margin:10px 0 0;font-size:12px}
      .refs{margin:0;padding-left:18px}
      footer{margin-top:24px;color:#8a94aa;font-size:11px;border-top:1px solid var(--line);padding-top:10px}
      @media print{ body{padding:10mm} .hero,.card,.day{break-inside:avoid} }
    </style></head><body>
    <section class="hero">
      <h1>${escapeHtml(plan.destination)}</h1>
      <p class="sub">Trip plan · generated ${escapeHtml(generated)}</p>
      <div class="stats">
        <div class="stat"><div class="k">Estimated budget</div><div class="v">${escapeHtml(budgetText)}</div></div>
        <div class="stat"><div class="k">Days</div><div class="v">${escapeHtml(days.length)}</div></div>
        ${plan.airport?.name ? `<div class="stat"><div class="k">Arrival airport</div><div class="v">${escapeHtml(plan.airport.name)}</div></div>` : ""}
      </div>
    </section>
    ${days.length ? `<section class="card"><h2>Route by day</h2><ul class="timeline">${routeRows}</ul></section>` : ""}
    ${daySections}
    ${categoryHtml}
    ${notesHtml}
    ${referencesHtml}
    <footer>Generated by Tripwise. Coordinates, prices, and availability are approximate and should be confirmed before booking.</footer>
  </body></html>`;
}
