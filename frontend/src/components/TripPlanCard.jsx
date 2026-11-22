import { useMemo, useState, useEffect, useCallback } from "react";
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Typography } from "@mui/material";
import {
  formatBudget,
  formatMarkerRanges,
  formatPlanDate,
  markerNumbersForDay,
  planDateRange,
  planEditChanges,
  routePoints,
} from "../lib/planUtils.js";
import { downloadPlanMarkdown, printPlanReport } from "../lib/planExport.js";
import { DayEditor, TotalBudgetEditor } from "./BudgetEditors.jsx";
import { TripMap } from "./TripMap.jsx";

export function TripPlanCard({ plan, onSaveBudget, onReconsider, reconsiderEnabled = false, busy = false }) {
  const points = useMemo(() => routePoints(plan), [plan]);
  const currency = plan.currency || "";
  const estimate = plan.budget ?? null;
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
  const [editingBudget, setEditingBudget] = useState(false);
  const [editingDay, setEditingDay] = useState(null);
  const [notice, setNotice] = useState("");
  const [reconsiderPrompt, setReconsiderPrompt] = useState(null);
  const [mapOpen, setMapOpen] = useState(points.length > 0);
  const [mapTouched, setMapTouched] = useState(false);
  const [showReferences, setShowReferences] = useState(true);
  const [expandedDays, setExpandedDays] = useState({});

  // The card mounts on the first `start_trip_plan` event, before day
  // coordinates exist, so open the map as soon as the route has points.
  // A manual show/hide toggle wins from then on.
  useEffect(() => {
    if (!mapTouched && points.length > 0) setMapOpen(true);
  }, [mapTouched, points.length]);
  // The card only renders once the backend has emitted a real plan (the
  // `start_trip_plan` tool event), so show that plan immediately. Placeholder
  // content lives in TripPlanPending and never fakes plan values.
  const allDaysOpen = days.length > 0 && days.every((day) => expandedDays[day.day]);

  // Weather date state. The start date is editable from the plan header
  // (toolbar date input); the end date and per-day dates derive from it.
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

  // Calculate the covered date range (start date + day count)
  useEffect(() => {
    const range = planDateRange(weatherFromDate, days.length);
    setWeatherToDate(range.length ? range[range.length - 1] : "");
  }, [weatherFromDate, days.length]);

  // Sync weather from date with plan (also picks up a changed start_date)
  useEffect(() => {
    if (plan.start_date && plan.start_date !== weatherFromDate) {
      setWeatherFromDate(String(plan.start_date));
    }
  }, [plan.start_date, weatherFromDate]);

  // Auto-fetch weather for all days when fromDate changes
  const fetchAllWeather = useCallback(async () => {
    const range = planDateRange(weatherFromDate, days.length);
    if (range.length === 0) return;

    setWeatherLoading(prev => ({ ...prev, global: true }));
    setWeatherError(prev => ({ ...prev, global: "" }));

    try {
      const dayWeatherPromises = days.map(async (day, index) => {
        const dateStr = range[index];
        
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

  function startBudgetEdit() {
    setEditingDay(null);
    setEditingBudget(true);
    setNotice("");
    setReconsiderPrompt(null);
  }
  function saveBudget(payload) {
    const changes = planEditChanges(plan, payload);
    onSaveBudget?.(payload);
    setEditingBudget(false);
    setNotice("Saved. The assistant will use this on your next message.");
    setReconsiderPrompt(reconsiderEnabled && changes.length ? changes : null);
  }
  function saveDay(dayObject) {
    const changes = planEditChanges(plan, { mode: "day", days: [dayObject] });
    onSaveBudget?.({ mode: "day", budget: estimate, currency, days: [dayObject] });
    setEditingDay(null);
    setNotice("Day saved. The assistant will use this on your next message.");
    setReconsiderPrompt(reconsiderEnabled && changes.length ? changes : null);
  }
  function handleStartDateChange(value) {
    // The end date and per-day weather dates derive from this single input;
    // persisting it keeps the assistant informed on the next turn.
    setWeatherFromDate(value);
    setWeatherData({});
    setWeatherError({});
    onSaveBudget?.({ mode: "date", budget: estimate, currency, start_date: value });
    setNotice(value
      ? "Start date saved; weather now covers this trip."
      : "Start date cleared.");
  }
  function askReconsider() {
    const changes = reconsiderPrompt;
    setReconsiderPrompt(null);
    if (changes?.length) onReconsider?.(changes);
  }

  return <div className="trip-plan-card">
    <div className="trip-plan-header">
      <div>
        <div className="question-kicker">YOUR TRIP PLAN</div>
        <div className="trip-plan-title-row">
          <h3>{plan.destination}</h3>
          {formatPlanDate(plan.start_date) && (
            <span className="plan-start-chip" title="Trip start date">From {formatPlanDate(plan.start_date)}</span>
          )}
        </div>
        {/* Weather summary (direct UI integration, refreshed per plan edit) */}
        {days.length > 0 && weatherFromDate && (
          <div className="weather-date-selector">
            <span className="weather-date-label">🌤 Weather (est.): {weatherFromDate} → {weatherToDate}</span>
            {Object.keys(weatherData).length > 0 && (
              <span className="weather-data-chip">
                {days.map((d) => weatherData[d.day]?.condition && `${d.day}: ${weatherData[d.day].temperature_c != null ? weatherData[d.day].temperature_c + "°C" : "?"}`).join(" · ")}
              </span>
            )}
          </div>
        )}
      </div>
      <span>✦</span>
    </div>
    <div className="trip-plan-toolbar">
      <button type="button" className="plan-tool" aria-pressed={mapOpen} onClick={() => { setMapTouched(true); setMapOpen((value) => !value); }}>🗺 {mapOpen ? "Hide map" : "Map route"}</button>
      {days.length > 1 && (
        <button type="button" className="plan-tool" onClick={() => setExpandedDays(allDaysOpen ? {} : Object.fromEntries(days.map((day) => [day.day, true])))}>
          {allDaysOpen ? "Collapse all" : "Expand all"}
        </button>
      )}
      <button type="button" className="plan-tool" onClick={() => downloadPlanMarkdown(plan)}>⬇ Markdown</button>
      <button type="button" className="plan-tool" onClick={() => printPlanReport(plan)}>🖨 PDF report</button>
      {weatherLoading?.global && <span className="weather-loading-chip">Loading weather…</span>}
      <label className="plan-date-input" title="Trip start date: sets the covered date range and fetches the per-day weather">
        <span className="plan-date-label">🗓 Start</span>
        <input
          type="date"
          value={weatherFromDate}
          onChange={(event) => handleStartDateChange(event.target.value)}
        />
        {weatherToDate && <span className="plan-date-to">→ {weatherToDate}</span>}
      </label>
    </div>
    <div className="trip-plan-content">
      {mapOpen && <TripMap plan={plan} />}
      {/* Single merged view: overview-style rows that expand/collapse in place. */}
      <div className="trip-overview">
        {days.map((day) => {
          const budget = dayBudgets.find((entry) => entry.day === day.day);
          const dayMarkerPoints = points.filter((point) => point.day === day.day);
          const dayMarkers = markerNumbersForDay(points, day.day);
          const dayMarkerNames = dayMarkerPoints.map((point) => point.label).filter(Boolean);
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
              <button type="button" className="day-collapse day-summary" aria-expanded={isOpen} onClick={() => setExpandedDays((previous) => ({ ...previous, [day.day]: !isOpen }))}>
                <span className="day-chevron">{isOpen ? "▾" : "▸"}</span>
                <span className="overview-day">DAY {day.day}</span>
                <strong className="overview-title">{day.title}</strong>
                <span className="overview-meta">{day.activities.length} activities</span>
                <b className="overview-budget">{budget && budget.amount != null ? formatBudget(budget.amount, currency) : "—"}</b>
                {weather && weather.temperature_c != null && <span className="overview-weather">{weather.temperature_c}°C (est.)</span>}
              </button>
              <div className="trip-day-head-actions">
                {dayMarkers.length > 0 && (
                  <span
                    className="day-map-ref"
                    title={dayMarkerNames.length ? `Map markers ${formatMarkerRanges(dayMarkers)}: ${dayMarkerNames.join(", ")}` : "Map reference"}
                  >
                    <span className="day-map-ref-range">🗺 {formatMarkerRanges(dayMarkers)}</span>
                  </span>
                )}
                {!isEditing && <button type="button" className="plan-tool" onClick={() => { setEditingBudget(false); setEditingDay(day.day); setExpandedDays((previous) => ({ ...previous, [day.day]: true })); setNotice(""); setReconsiderPrompt(null); }}>Edit</button>}
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
                      <span className="weather-estimate">(est.)</span>
                      {weather.humidity != null && <span className="day-weather-humidity">💧 {weather.humidity}%</span>}
                      {weather.stub && <span style={{color: '#aa6c16', fontSize: 10, marginLeft: 8}}></span>}
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
                    <span className="stay-price">{formatBudget(stay.nightly_cost, stay.currency || "USD")}/night (est.)</span>
                  )}
                  {stay.rating != null && (
                    <span className="stay-rating">⭐ {stay.rating} (est.)</span>
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
                      Open listing
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

    {/* Reconsider confirmation: a modal listing the concrete edits, asking
        whether the assistant should reconsider the plan (yes / no). */}
    <Dialog
      open={reconsiderEnabled && Array.isArray(reconsiderPrompt)}
      onClose={() => setReconsiderPrompt(null)}
      maxWidth="sm"
      fullWidth
      aria-label="Reconsider plan changes"
    >
      <DialogTitle>Plan changed — ask the AI to reconsider?</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Your edits are saved. Confirm to send them to the assistant so it can review and update the rest of the plan.
        </Typography>
        {(reconsiderPrompt || []).length > 0 && (
          <ul className="reconsider-changes">
            {reconsiderPrompt.map((change, index) => <li key={index}>{change}</li>)}
          </ul>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={() => setReconsiderPrompt(null)} disabled={busy}>No, thanks</Button>
        <Button variant="contained" disabled={busy} onClick={askReconsider}>Yes, ask the AI</Button>
      </DialogActions>
    </Dialog>
    <div className="trip-budget-block">
      <div className="trip-budget-head">
        <span>ESTIMATED BUDGET</span>
        <strong>{estimate == null ? "Not specified" : formatBudget(estimate, currency)}</strong>
        {!editingBudget && <button type="button" className="plan-tool" onClick={startBudgetEdit}>Edit</button>}
      </div>
      {editingBudget && <TotalBudgetEditor estimate={estimate} currency={currency} onCancel={() => setEditingBudget(false)} onSave={saveBudget} />}
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

// Blank plan shell shown as soon as a message is sent. It deliberately
// contains no placeholder values; the real TripPlanCard replaces it when the
// agent starts calling the trip-plan tools.
export function TripPlanPending() {
  return (
    <div
      className="trip-plan-card trip-plan-pending"
      aria-busy="true"
      aria-label="Trip plan is being prepared"
    >
      <div className="trip-plan-header">
        <div>
          <div className="question-kicker">YOUR TRIP PLAN</div>
        </div>
        <span>✦</span>
      </div>
      <div className="trip-plan-blank" aria-hidden="true" />
    </div>
  );
}
