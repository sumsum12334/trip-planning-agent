import { useMemo, useState, useEffect, useCallback } from "react";
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Typography } from "@mui/material";
import {
  formatBudget,
  markerNumbersForDay,
  planBudgetItems,
  routePoints,
} from "../lib/planUtils.js";
import { downloadPlanMarkdown, printPlanReport } from "../lib/planExport.js";
import { CategoryBudgetEditor, DayEditor } from "./BudgetEditors.jsx";
import { TripMap } from "./TripMap.jsx";

export function TripPlanCard({ plan, onSaveBudget }) {
  const points = useMemo(() => routePoints(plan), [plan]);
  const currency = plan.currency || "";
  const items = planBudgetItems(plan);
  const estimate = plan.budget ?? null;
  const itemsTotal = items.length
    ? Math.round(items.reduce((sum, item) => sum + (Number(item.amount) || 0), 0) * 100) / 100
    : null;
  const days = useMemo(() => plan.days || [], [plan.days]);
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

  // Weather date state - read-only display
  const [weatherFromDate, setWeatherFromDate] = useState(() => plan.start_date ? String(plan.start_date) : "");
  const [weatherToDate, setWeatherToDate] = useState("");
  const [weatherData, setWeatherData] = useState({});
  const [weatherLoading, setWeatherLoading] = useState({});
  const [weatherError, setWeatherError] = useState({});

  // Accommodation state
  const [staysData, setStaysData] = useState(null);
  const [staysLoading, setStaysLoading] = useState(false);
  const [staysError, setStaysError] = useState("");
  const [staysDialogOpen, setStaysDialogOpen] = useState(false);

  // Calculate to-date from from-date + days count
  useEffect(() => {
    if (weatherFromDate && days.length > 0) {
      const from = new Date(weatherFromDate + "T00:00:00");
      const to = new Date(from);
      to.setDate(from.getDate() + days.length - 1);
      setWeatherToDate(to.toISOString().split("T")[0]);
    } else {
      setWeatherToDate("");
    }
  }, [weatherFromDate, days.length]);

  // Sync weather from date with plan
  useEffect(() => {
    if (plan.start_date && !weatherFromDate) {
      setWeatherFromDate(String(plan.start_date));
    }
  }, [plan.start_date, weatherFromDate]);

  // Auto-fetch weather for all days when fromDate changes
  const fetchAllWeather = useCallback(async () => {
    if (!weatherFromDate || days.length === 0) return;
    
    setWeatherLoading(prev => ({ ...prev, global: true }));
    setWeatherError(prev => ({ ...prev, global: "" }));
    
    try {
      const fromDate = new Date(weatherFromDate + "T00:00:00");
      const dayWeatherPromises = days.map(async (day, index) => {
        const dayDate = new Date(fromDate);
        dayDate.setDate(fromDate.getDate() + index);
        const dateStr = dayDate.toISOString().split("T")[0];
        
        try {
          const response = await fetch("/agents/weather", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              destination: plan.destination,
              start_date: dateStr,
              end_date: dateStr,
            }),
          });
          if (!response.ok) throw new Error("Failed to fetch weather");
          const data = await response.json();
          return { day: day.day, date: dateStr, data };
        } catch (error) {
          return { day: day.day, date: dateStr, error: error.message };
        }
      });
      
      const results = await Promise.all(dayWeatherPromises);
      const newWeatherData = {};
      const newErrors = {};
      results.forEach(r => {
        if (r.error) {
          newErrors[r.day] = r.error;
        } else {
          newWeatherData[r.day] = { ...r.data, date: r.date };
        }
      });
      setWeatherData(newWeatherData);
      setWeatherError(newErrors);
    } catch (error) {
      setWeatherError(prev => ({ ...prev, global: error.message }));
    } finally {
      setWeatherLoading(prev => ({ ...prev, global: false }));
    }
  }, [weatherFromDate, days, plan.destination]);

  useEffect(() => {
    fetchAllWeather();
  }, [fetchAllWeather]);

  const fetchStays = useCallback(async () => {
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
  }, [plan.destination, plan.budget, days.length, plan.interests]);

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
      {/* Weather date selector aligned right */}
      {days.length > 0 && weatherFromDate && (
        <div className="weather-date-selector">
          <span className="weather-date-label">🌤 Weather: {weatherFromDate} → {weatherToDate}</span>
          {weatherData && Object.keys(weatherData).length > 0 && (
            <span className="weather-data-chip">
              {days.map(d => weatherData[d.day]?.condition && `${d.day}: ${weatherData[d.day].temperature_c != null ? weatherData[d.day].temperature_c + "°C" : "?"}`).join(" · ")}
            </span>
          )}
        </div>
      )}
      {weatherLoading?.global && <span className="weather-loading-chip">Loading weather…</span>}
      <button type="button" className="plan-tool" onClick={() => downloadPlanMarkdown(plan)}>⬇ Markdown</button>
      <button type="button" className="plan-tool" onClick={() => printPlanReport(plan)}>🖨 PDF report</button>
    </div>
    <div className="trip-plan-content">
      {mapOpen && <TripMap plan={plan} />}
      {planView === "overview" && days.length > 0 ? (
        <div className="trip-overview">
          {days.map((day) => {
            const budget = dayBudgets.find((entry) => entry.day === day.day);
            const dayMarkers = markerNumbersForDay(points, day.day);
            const weather = weatherData[day.day];
            return <button type="button" className="trip-overview-row" key={`overview-${day.day}`} onClick={() => { setPlanView("days"); setExpandedDays((previous) => ({ ...previous, [day.day]: true })); }}>
              <span className="overview-day">Day {day.day}</span>
              <span className="overview-title">{day.title}</span>
              <span className="overview-meta">{day.activities.length} activities{dayMarkers.length ? ` · 🗺 ${dayMarkers.join("·")}` : ""}</span>
              <b className="overview-budget">{budget && budget.amount != null ? formatBudget(budget.amount, currency) : "—"}</b>
              {weather && (
                <span className="overview-weather">
                  {weather.temperature_c != null ? `${weather.temperature_c}°C` : "?"}
                </span>
              )}
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
          const weather = weatherData[day.day];
          const weatherLoadingDay = weatherLoading[day.day];
          const weatherErrorDay = weatherError[day.day];
          
          return <article className="trip-day" key={`${day.day}-${day.title}`}>
            <div className="trip-day-head">
              <button type="button" className="day-collapse" aria-expanded={isOpen} onClick={() => setExpandedDays((previous) => ({ ...previous, [day.day]: !isOpen }))}>
                <span className="day-chevron">{isOpen ? "▾" : "▸"}</span>
                <span className="day-number">DAY {day.day}</span> <strong>{day.title}</strong>
              </button>
              <div className="trip-day-head-actions">
                {dayMarkers.length > 0 && <span className="day-map-ref" title="Map reference">🗺 {dayMarkers.join(" · ")}</span>}
                {!isEditing && <button type="button" className="plan-tool" onClick={() => { setEditingCategory(false); setEditingDay(day.day); setExpandedDays((previous) => ({ ...previous, [day.day]: true })); setNotice(""); }}>Edit</button>}
              </div>
            </div>
            {isOpen && (isEditing ? <DayEditor day={day} dayBudget={budget} currency={currency} onCancel={() => setEditingDay(null)} onSave={saveDay} /> : <>
              {/* Inline weather for this day */}
              {(weather || weatherLoadingDay || weatherErrorDay) && (
                <div className="day-weather-inline">
                  <span className="day-weather-icon">🌤</span>
                  {weatherLoadingDay ? (
                    <span className="day-weather-temp">Loading…</span>
                  ) : weatherErrorDay ? (
                    <span style={{color: '#aa6c16', fontSize: '11px'}}>Weather unavailable</span>
                  ) : (
                    <>
                      <span className="day-weather-condition">{weather.condition}</span>
                      <span className="day-weather-temp">
                        {weather.temperature_c != null ? `${weather.temperature_c}°C` : ""}
                        {weather.temperature_f != null ? ` (${weather.temperature_f}°F)` : ""}
                      </span>
                      {weather.humidity != null && <span className="day-weather-humidity">💧 {weather.humidity}%</span>}
                      {weather.stub && <span style={{color: '#aa6c16', fontSize: 10, marginLeft: 8}}>(stub)</span>}
                    </>
                  )}
                </div>
              )}
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

    {/* Accommodation button (opens popup) */}
    <div className="trip-stays-action">
      <button type="button" className="plan-tool primary" onClick={() => { fetchStays(); setStaysDialogOpen(true); }} disabled={staysLoading}>
        {staysLoading ? "Loading stays…" : "Find Accommodation"}
      </button>
    </div>

    {/* Accommodation popup */}
    <Dialog open={staysDialogOpen} onClose={() => setStaysDialogOpen(false)} maxWidth="lg" fullWidth>
      <DialogTitle sx={{ p: 2, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Typography variant="h6" fontWeight={700}>🏨 Accommodation Options for {plan.destination}</Typography>
        <Button size="small" onClick={() => setStaysDialogOpen(false)}>Close</Button>
      </DialogTitle>
      <DialogContent sx={{ p: 2, maxHeight: "50vh", overflow: "auto" }}>
        {staysError && <div className="weather-error" style={{ marginBottom: 12 }}>{staysError}</div>}
        {staysLoading && <div className="budget-notice">Loading accommodation options…</div>}
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
                <div style={{display: 'flex', gap: 8, alignItems: 'center'}}>
                  {stay.source_url && (
                    <a href={stay.source_url} target="_blank" rel="noopener noreferrer" className="stay-book-link">
                      View / Book
                    </a>
                  )}
                  {stay.coordinates && (
                    <a href={`https://www.openstreetmap.org/?mlat=${stay.coordinates.lat}&mlon=${stay.coordinates.lng}#map=16/${stay.coordinates.lat}/${stay.coordinates.lng}`} 
                       target="_blank" rel="noopener noreferrer" className="stay-map-link">
                      🗺 Map
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        {staysData && staysData.length === 0 && !staysLoading && (
          <div className="budget-notice">No stays found for this destination.</div>
        )}
        {!staysData && !staysLoading && !staysError && (
          <div className="budget-notice">Click "Find Accommodation" to search for options.</div>
        )}
      </DialogContent>
      <DialogActions sx={{ p: 1 }}>
        <Button onClick={() => setStaysDialogOpen(false)}>Done</Button>
      </DialogActions>
    </Dialog>

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