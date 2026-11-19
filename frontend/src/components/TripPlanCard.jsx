/* eslint-disable react-hooks/set-state-in-effect -- sync weather dates with plan props */
import { useMemo, useState, useEffect } from "react";
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

  // Weather state
  const [weatherData, setWeatherData] = useState(null);
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [weatherError, setWeatherError] = useState("");
  const [weatherFromDate, setWeatherFromDate] = useState(() => plan.start_date ? String(plan.start_date) : "");
  const [weatherToDate, setWeatherToDate] = useState(() => plan.end_date ? String(plan.end_date) : "");

  // Accommodation state
  const [staysData, setStaysData] = useState(null);
  const [staysLoading, setStaysLoading] = useState(false);
  const [staysError, setStaysError] = useState("");

  // Sync weather dates with plan changes
  useEffect(() => {
    if (plan.start_date && plan.end_date) {
      setWeatherFromDate(String(plan.start_date));
      setWeatherToDate(String(plan.end_date));
    }
  }, [plan.start_date, plan.end_date]);

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

  async function fetchWeather() {
    if (!weatherFromDate || !weatherToDate) {
      setWeatherError("Please select both from and to dates");
      return;
    }
    setWeatherLoading(true);
    setWeatherError("");
    try {
      const response = await fetch("/agents/weather", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          destination: plan.destination,
          start_date: weatherFromDate,
          end_date: weatherToDate,
        }),
      });
      if (!response.ok) throw new Error("Failed to fetch weather");
      const data = await response.json();
      setWeatherData(data);
    } catch (error) {
      setWeatherError(error.message);
      setWeatherData(null);
    } finally {
      setWeatherLoading(false);
    }
  }

  async function fetchStays() {
    setStaysLoading(true);
    setStaysError("");
    try {
      const response = await fetch("/agents/search_stays", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          destination: plan.destination,
          budget: plan.budget,
          days: days.length || 3,
          interests: plan.interests || [],
        }),
      });
      if (!response.ok) throw new Error("Failed to fetch stays");
      const data = await response.json();
      setStaysData(data);
    } catch (error) {
      setStaysError(error.message);
      setStaysData(null);
    } finally {
      setStaysLoading(false);
    }
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

    {/* Weather Section */}
    <div className="trip-weather-block">
      <div className="trip-weather-head">
        <span>🌤 WEATHER FORECAST</span>
        <div className="weather-date-inputs">
          <label>
            From
            <input type="date" value={weatherFromDate} onChange={(e) => setWeatherFromDate(e.target.value)} />
          </label>
          <label>
            To
            <input type="date" value={weatherToDate} onChange={(e) => setWeatherToDate(e.target.value)} />
          </label>
          <button type="button" className="plan-tool primary" onClick={fetchWeather} disabled={weatherLoading || !weatherFromDate || !weatherToDate}>
            {weatherLoading ? "Loading..." : "Get Weather"}
          </button>
        </div>
      </div>
      {weatherError && <div className="weather-error">{weatherError}</div>}
      {weatherData && (
        <div className="weather-result">
          <div className="weather-main">
            <span className="weather-condition">{weatherData.condition || "Unknown"}</span>
            <span className="weather-temp">
              {weatherData.temperature_c != null ? `${weatherData.temperature_c}°C` : ""}
              {weatherData.temperature_f != null ? ` (${weatherData.temperature_f}°F)` : ""}
            </span>
          </div>
          <div className="weather-details">
            {weatherData.humidity != null && <span>💧 Humidity: {weatherData.humidity}%</span>}
            {weatherData.notes && <span className="weather-notes">{weatherData.notes}</span>}
            {weatherData.stub && <span className="weather-stub">(Stub data - not live)</span>}
          </div>
        </div>
      )}
      {!weatherData && !weatherLoading && !weatherError && (
        <small className="budget-notice">Select date range and click "Get Weather" to see forecast.</small>
      )}
    </div>

    {/* Accommodation Section */}
    <div className="trip-stays-block">
      <div className="trip-stays-head">
        <span>🏨 ACCOMMODATION OPTIONS</span>
        <button type="button" className="plan-tool" onClick={fetchStays} disabled={staysLoading}>
          {staysLoading ? "Loading..." : staysData ? "Refresh" : "Find Stays"}
        </button>
      </div>
      {staysError && <div className="weather-error">{staysError}</div>}
      {staysData && staysData.length > 0 && (
        <ul className="stays-list">
          {staysData.map((stay, index) => (
            <li key={`${stay.name}-${index}`} className="stay-item">
              <div className="stay-info">
                <strong>{stay.name}</strong>
                <span className="stay-location">📍 {stay.location}</span>
                {stay.nightly_cost != null && (
                  <span className="stay-price">{formatBudget(stay.nightly_cost, stay.currency || "USD")}/night</span>
                )}
                {stay.rating != null && (
                  <span className="stay-rating">⭐ {stay.rating}</span>
                )}
                {stay.amenities?.length > 0 && (
                  <span className="stay-amenities">{stay.amenities.join(", ")}</span>
                )}
                {stay.cancellation_policy && (
                  <span className="stay-cancellation">🔄 {stay.cancellation_policy}</span>
                )}
              </div>
              {stay.source_url && (
                <a href={stay.source_url} target="_blank" rel="noopener noreferrer" className="stay-book-link">
                  View / Book
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
      {staysData && staysData.length === 0 && !staysLoading && (
        <small className="budget-notice">No stays found for this destination.</small>
      )}
      {!staysData && !staysLoading && !staysError && (
        <small className="budget-notice">Click "Find Stays" to search for accommodation options.</small>
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