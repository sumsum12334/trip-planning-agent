import { useMemo, useState } from "react";
import {
  formatBudget,
  markerNumbersForDay,
  planBudgetItems,
  routePoints,
} from "../lib/planUtils.js";
import { downloadPlanMarkdown, printPlanReport } from "../lib/planExport.js";
import { CategoryBudgetEditor, DayEditor } from "./BudgetEditors.jsx";
import { TripMap } from "./TripMap.jsx";

export function TripPlanCard({ plan, onSaveBudget, onCollapse }) {
  const points = useMemo(() => routePoints(plan), [plan]);
  const currency = plan.currency || "";
  const items = planBudgetItems(plan);
  const estimate = plan.budget ?? null;
  const itemsTotal = items.length
    ? Math.round(items.reduce((sum, item) => sum + (Number(item.amount) || 0), 0) * 100) / 100
    : null;
  const days = plan.days || [];
  const derivedDay = estimate != null && days.length ? Math.round((estimate / days.length) * 100) / 100 : null;
  const dayBudgets = days.map((day) => {
    const dayItems = Array.isArray(day.budget_items) ? day.budget_items : [];
    const dayItemsTotal = dayItems.length
      ? Math.round(dayItems.reduce((sum, item) => sum + (Number(item.amount) || 0), 0) * 100) / 100
      : null;
    return {
      day: day.day,
      amount: day.budget ?? dayItemsTotal ?? derivedDay,
      derived: day.budget == null && dayItemsTotal == null && derivedDay != null,
      items: dayItems,
    };
  });
  const [editingCategory, setEditingCategory] = useState(false);
  const [editingDay, setEditingDay] = useState(null);
  const [notice, setNotice] = useState("");
  const [mapOpen, setMapOpen] = useState(points.length > 0);
  const [showReferences, setShowReferences] = useState(true);
  const [planView, setPlanView] = useState("overview");
  const [expandedDays, setExpandedDays] = useState({});
  const allDaysOpen = days.length > 0 && days.every((day) => expandedDays[day.day]);

  function startCategoryEdit() {
    setEditingDay(null);
    setEditingCategory(true);
    setNotice("");
  }
  function saveCategory(payload) {
    onSaveBudget?.(payload);
    setEditingCategory(false);
    setNotice("Saved. The assistant will use this on your next message.");
  }
  function saveDay(dayObject) {
    onSaveBudget?.({ mode: "day", budget: estimate, currency, days: [dayObject] });
    setEditingDay(null);
    setNotice("Day saved. The assistant will use this on your next message.");
  }

  return <div className="trip-plan-card">
    <div className="trip-plan-header">
      <div>
        <div className="question-kicker">YOUR TRIP PLAN</div>
        <h3>{plan.destination}</h3>
      </div>
      <span>✦</span>
    </div>
    <div className="trip-plan-toolbar">
      <button type="button" className="plan-tool" aria-pressed={mapOpen} onClick={() => setMapOpen((value) => !value)}>🗺 {mapOpen ? "Hide map" : "Map route"}</button>
      {days.length > 0 && (
        <div className="plan-view-toggle" role="tablist" aria-label="Plan view">
          <button type="button" role="tab" aria-selected={planView === "overview"} className={planView === "overview" ? "active" : ""} onClick={() => setPlanView("overview")}>Overview</button>
          <button type="button" role="tab" aria-selected={planView === "days"} className={planView === "days" ? "active" : ""} onClick={() => setPlanView("days")}>Day by day</button>
        </div>
      )}
      {planView === "days" && days.length > 0 && (
        <button type="button" className="plan-tool" onClick={() => setExpandedDays(allDaysOpen ? {} : Object.fromEntries(days.map((day) => [day.day, true])))}>
          {allDaysOpen ? "Collapse all" : "Expand all"}
        </button>
      )}
      <button type="button" className="plan-tool" onClick={() => downloadPlanMarkdown(plan)}>⬇ Markdown</button>
      <button type="button" className="plan-tool" onClick={() => printPlanReport(plan)}>🖨 PDF report</button>
      {onCollapse && (
        <button type="button" className="plan-tool plan-collapse-toggle" onClick={onCollapse} aria-label="Collapse trip plan panel">▸ Hide panel</button>
      )}
    </div>
    <div className="trip-plan-content">
      {mapOpen && <TripMap plan={plan} />}
      {planView === "overview" && days.length > 0 ? (
        <div className="trip-overview">
          {days.map((day) => {
            const budget = dayBudgets.find((entry) => entry.day === day.day);
            const dayMarkers = markerNumbersForDay(points, day.day);
            return <button type="button" className="trip-overview-row" key={`overview-${day.day}`} onClick={() => { setPlanView("days"); setExpandedDays((previous) => ({ ...previous, [day.day]: true })); }}>
              <span className="overview-day">Day {day.day}</span>
              <span className="overview-title">{day.title}</span>
              <span className="overview-meta">{day.activities.length} activities{dayMarkers.length ? ` · 🗺 ${dayMarkers.join("·")}` : ""}</span>
              <b className="overview-budget">{budget && budget.amount != null ? formatBudget(budget.amount, currency) : "—"}</b>
            </button>;
          })}
        </div>
      ) : (
        <div className="trip-days">
        {days.map((day) => {
          const budget = dayBudgets.find((entry) => entry.day === day.day);
          const dayMarkers = markerNumbersForDay(points, day.day);
          const markerFor = (name) => {
            const index = points.findIndex((point) => point.kind === "place" && point.day === day.day && point.label === name);
            return index >= 0 ? index + 1 : null;
          };
          const isEditing = editingDay === day.day;
          const isOpen = Boolean(expandedDays[day.day]) || isEditing;
          return <article className="trip-day" key={`${day.day}-${day.title}`}>
            <div className="trip-day-head">
              <button type="button" className="day-collapse" aria-expanded={isOpen} onClick={() => setExpandedDays((previous) => ({ ...previous, [day.day]: !isOpen }))}>
                <span className="day-chevron">{isOpen ? "▾" : "▸"}</span>
                <span className="day-number">DAY {day.day}</span>
                <strong>{day.title}</strong>
              </button>
              <div className="trip-day-head-actions">
                {dayMarkers.length > 0 && <span className="day-map-ref" title="Map reference">🗺 {dayMarkers.join(" · ")}</span>}
                {!isEditing && <button type="button" className="plan-tool" onClick={() => { setEditingCategory(false); setEditingDay(day.day); setExpandedDays((previous) => ({ ...previous, [day.day]: true })); setNotice(""); }}>Edit</button>}
              </div>
            </div>
            {isOpen && (isEditing ? <DayEditor day={day} dayBudget={budget} currency={currency} onCancel={() => setEditingDay(null)} onSave={saveDay} /> : <>
              <ul>{day.activities.map((activity) => <li key={activity}>{activity}</li>)}</ul>
              {day.places?.length > 0 && <div className="trip-places">
                {day.places.map((place, index) => {
                  const marker = markerFor(place.name);
                  const label = <>{marker ? <span className="place-marker-ref">{marker}</span> : null}📍 {place.name}</>;
                  return place.url
                    ? <a key={`${place.name}-${index}`} href={place.url} target="_blank" rel="noopener noreferrer">{label}</a>
                    : <span key={`${place.name}-${index}`}>{label}</span>;
                })}
              </div>}
              {day.notes?.length > 0 && <small>{day.notes.join(" · ")}</small>}
              {budget && (budget.amount != null || budget.items.length > 0) && <div className="day-budget">
                <div className="day-budget-head"><span>Budget</span><b>{budget.amount == null ? "—" : formatBudget(budget.amount, currency)}{budget.derived ? " (est.)" : ""}</b></div>
                {budget.items.length > 0 && <ul className="budget-items budget-day-items">
                  {budget.items.map((item, index) => <li key={`${item.category}-${index}`}>
                    <span>{item.category}</span><b>{formatBudget(item.amount, item.currency || currency)}</b>
                  </li>)}
                </ul>}
              </div>}
            </>)}
          </article>;
        })}
        </div>
      )}
    </div>
    <div className="trip-budget-block">
      <div className="trip-budget-head">
        <span>ESTIMATED BUDGET</span>
        <strong>{estimate == null ? "Not specified" : formatBudget(estimate, currency)}</strong>
        {!editingCategory && <button type="button" className="plan-tool" onClick={startCategoryEdit}>Edit</button>}
      </div>
      {editingCategory ? (
        <CategoryBudgetEditor plan={plan} currency={currency} onCancel={() => setEditingCategory(false)} onSave={saveCategory} />
      ) : (
        items.length > 0 ? <>
          <div className="budget-subhead">Category items</div>
          <ul className="budget-items">
            {items.map((item, index) => <li key={`${item.category}-${index}`}>
              <span>{item.category}</span><b>{formatBudget(item.amount, item.currency || currency)}</b>
            </li>)}
          </ul>
          <div className="budget-total-row"><span>Items total</span><b>{formatBudget(itemsTotal, currency)}</b></div>
          {estimate != null && itemsTotal != null && Math.abs(estimate - itemsTotal) > 0.001 && (
            <small className="budget-notice warn">Items total {formatBudget(itemsTotal, currency)} differs from the estimated budget {formatBudget(estimate, currency)}.</small>
          )}
        </> : <small className="budget-notice">No category items yet — use Edit to add them. Each day has its own budget in its card.</small>
      )}
      {notice && <small className="budget-notice">{notice}</small>}
    </div>
    {plan.notes?.length > 0 && <small className="trip-notes">{plan.notes.join(" · ")}</small>}
    {plan.references?.length > 0 && <div className="trip-references">
      <button type="button" className="references-toggle" onClick={() => setShowReferences((value) => !value)}>
        🔗 References ({plan.references.length}) {showReferences ? "▾" : "▸"}
      </button>
      {showReferences && <ul>
        {plan.references.map((ref, index) => <li key={`${ref.url}-${index}`}>
          <a href={ref.url} target="_blank" rel="noopener noreferrer">{ref.title}</a>
        </li>)}
      </ul>}
    </div>}
  </div>;
}
