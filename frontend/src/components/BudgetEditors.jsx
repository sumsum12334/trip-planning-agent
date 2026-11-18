import { useState } from "react";
import { formatBudget, planBudgetItems, splitLines } from "../lib/planUtils.js";

export function CategoryBudgetEditor({ plan, currency, onCancel, onSave }) {
  const items = planBudgetItems(plan);
  const estimate = plan.budget ?? null;
  const [estimateInput, setEstimateInput] = useState(estimate != null ? String(estimate) : "");
  const [rows, setRows] = useState(items.map((item) => ({ category: item.category, amount: String(item.amount) })));
  const [error, setError] = useState("");
  const itemsTotal = Math.round(rows.reduce((sum, row) => {
    const amount = Number(row.amount);
    return sum + (Number.isFinite(amount) && amount >= 0 ? amount : 0);
  }, 0) * 100) / 100;

  function updateRow(index, field, value) {
    setRows((previous) => previous.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
  }
  function addRow() { setRows((previous) => [...previous, { category: "", amount: "" }]); }
  function removeRow(index) { setRows((previous) => previous.filter((_, i) => i !== index)); }

  function save() {
    const estimateValue = estimateInput.trim() === "" ? null : Number(estimateInput);
    if (estimateValue != null && (!Number.isFinite(estimateValue) || estimateValue < 0)) {
      setError("Enter a non-negative estimated total.");
      return;
    }
    const cleanedItems = rows
      .map((row) => ({ category: row.category.trim(), amount: Number(row.amount) }))
      .filter((row) => row.category && Number.isFinite(row.amount) && row.amount >= 0);
    onSave({
      mode: "category",
      budget: estimateValue,
      currency,
      budget_items: cleanedItems.map((row) => ({ category: row.category, amount: row.amount, currency })),
    });
  }

  return <div className="budget-editor">
    <div className="budget-editor-label">Editing: category items</div>
    <div className="budget-row">
      <label>Estimated total
        <input className="budget-amount" type="number" min="0" step="any" value={estimateInput} onChange={(event) => setEstimateInput(event.target.value)} />
      </label>
    </div>
    <ul className="budget-editor-rows">
      {rows.map((row, index) => <li key={index}>
        <input className="budget-category" placeholder="Category" value={row.category} onChange={(event) => updateRow(index, "category", event.target.value)} />
        <input className="budget-amount" type="number" min="0" step="any" placeholder="0" value={row.amount} onChange={(event) => updateRow(index, "amount", event.target.value)} />
        <button type="button" className="icon-button danger" title="Remove item" onClick={() => removeRow(index)}>×</button>
      </li>)}
    </ul>
    <div className="budget-editor-actions">
      <button type="button" className="plan-tool" onClick={addRow}>＋ Item</button>
      <span className="budget-editor-total">Items total: {formatBudget(itemsTotal, currency)}</span>
    </div>
    {error && <small className="budget-notice warn">{error}</small>}
    <div className="budget-editor-actions">
      <button type="button" className="plan-tool primary" onClick={save}>Save</button>
      <button type="button" className="plan-tool" onClick={onCancel}>Cancel</button>
    </div>
  </div>;
}

export function DayEditor({ day, dayBudget, currency, onCancel, onSave }) {
  const [title, setTitle] = useState(day.title || "");
  const [activities, setActivities] = useState((day.activities || []).join("\n"));
  const [notes, setNotes] = useState((day.notes || []).join("\n"));
  const [places, setPlaces] = useState((day.places || []).map((place) => (place.url ? `${place.name} | ${place.url}` : place.name)).join("\n"));
  const [amount, setAmount] = useState(dayBudget && dayBudget.amount != null ? String(dayBudget.amount) : "");
  const [items, setItems] = useState((dayBudget?.items || []).map((item) => ({ category: item.category, amount: String(item.amount) })));
  const [error, setError] = useState("");

  function updateItem(index, field, value) {
    setItems((previous) => previous.map((item, i) => (i === index ? { ...item, [field]: value } : item)));
  }
  function addItem() { setItems((previous) => [...previous, { category: "", amount: "" }]); }
  function removeItem(index) { setItems((previous) => previous.filter((_, i) => i !== index)); }

  function save() {
    const activityList = splitLines(activities);
    if (!title.trim() || !activityList.length) {
      setError("A day needs a title and at least one activity.");
      return;
    }
    const amountValue = amount.trim() === "" ? null : Number(amount);
    if (amountValue != null && (!Number.isFinite(amountValue) || amountValue < 0)) {
      setError("Enter a non-negative day budget.");
      return;
    }
    const cleanedItems = items
      .map((item) => ({ category: item.category.trim(), amount: Number(item.amount) }))
      .filter((item) => item.category && Number.isFinite(item.amount) && item.amount >= 0);
    const parsedPlaces = splitLines(places)
      .map((line) => {
        const [name, url] = line.split("|").map((part) => part.trim());
        return url ? { name, url } : { name };
      })
      .filter((place) => place.name);
    onSave({
      day: day.day,
      title: title.trim(),
      activities: activityList,
      notes: splitLines(notes),
      places: parsedPlaces,
      coordinates: day.coordinates || null,
      budget: amountValue,
      budget_items: cleanedItems.map((item) => ({ ...item, currency })),
    });
  }

  return <div className="day-editor">
    <label className="day-editor-field">Title<input value={title} onChange={(event) => setTitle(event.target.value)} /></label>
    <label className="day-editor-field">Activities (one per line)<textarea rows={4} value={activities} onChange={(event) => setActivities(event.target.value)} /></label>
    <label className="day-editor-field">Places / route (one per line, optional "Name | url")<textarea rows={2} value={places} onChange={(event) => setPlaces(event.target.value)} /></label>
    <label className="day-editor-field">Notes (one per line)<textarea rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
    <label className="day-editor-field">Day budget<input className="budget-amount" type="number" min="0" step="any" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>
    <div className="budget-editor-label">Day budget items</div>
    <ul className="budget-editor-rows">
      {items.map((item, index) => <li key={index}>
        <input className="budget-category" placeholder="Category" value={item.category} onChange={(event) => updateItem(index, "category", event.target.value)} />
        <input className="budget-amount" type="number" min="0" step="any" placeholder="0" value={item.amount} onChange={(event) => updateItem(index, "amount", event.target.value)} />
        <button type="button" className="icon-button danger" title="Remove item" onClick={() => removeItem(index)}>×</button>
      </li>)}
    </ul>
    <div className="budget-editor-actions">
      <button type="button" className="plan-tool" onClick={addItem}>＋ Item</button>
    </div>
    {error && <small className="budget-notice warn">{error}</small>}
    <div className="budget-editor-actions">
      <button type="button" className="plan-tool primary" onClick={save}>Save day</button>
      <button type="button" className="plan-tool" onClick={onCancel}>Cancel</button>
    </div>
  </div>;
}
