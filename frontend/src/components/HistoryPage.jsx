import { useEffect, useMemo, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Chip,
  IconButton,
  Paper,
  Stack,
  TextField,
  Typography,
  Tooltip,
} from "@mui/material";
import DeleteOutlinedIcon from "@mui/icons-material/DeleteOutlined";
import EditIcon from "@mui/icons-material/Edit";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import PlaceIcon from "@mui/icons-material/Place";
import SaveIcon from "@mui/icons-material/Save";
import CancelIcon from "@mui/icons-material/Cancel";

export function HistoryPage({ userId }) {
  const [entries, setEntries] = useState([]);
  const [form, setForm] = useState({ country: "", city: "", location: "" });
  const [status, setStatus] = useState("");
  const [editingCountry, setEditingCountry] = useState(null); // { originalCountry, newCountry }
  const [editForm, setEditForm] = useState("");
  
  async function load() {
    const response = await fetch(`/api/travel-history?user_id=${encodeURIComponent(userId)}`);
    if (response.ok) setEntries(await response.json());
  }
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const response = await fetch(`/api/travel-history?user_id=${encodeURIComponent(userId)}`);
      if (!cancelled && response.ok) setEntries(await response.json());
    })();
    return () => { cancelled = true; };
  }, [userId]);
  async function add(event) {
    event.preventDefault();
    setStatus("");
    const response = await fetch("/api/travel-history", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, user_id: userId }),
    });
    if (!response.ok) { setStatus(await response.text()); return; }
    setForm({ country: "", city: "", location: "" }); setStatus("Saved to your travel memory."); await load();
  }
  async function remove(id) {
    const response = await fetch(`/api/travel-history/${id}?user_id=${encodeURIComponent(userId)}`, { method: "DELETE" });
    if (response.ok) await load();
  }
  
  async function updateCountry(originalCountry, newCountry) {
    if (!newCountry.trim() || newCountry.trim() === originalCountry) {
      setEditingCountry(null);
      return;
    }
    // Update all entries with this country
    const entriesToUpdate = entries.filter(e => (e.country || "").trim() === originalCountry || (!e.country && originalCountry === "Unspecified country"));
    for (const entry of entriesToUpdate) {
      const response = await fetch(`/api/travel-history/${entry.id}?user_id=${encodeURIComponent(userId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...entry, country: newCountry.trim() }),
      });
      if (!response.ok) {
        setStatus(`Failed to update ${entry.location}`);
        return;
      }
    }
    setEditingCountry(null);
    setStatus(`Updated ${entriesToUpdate.length} entries to "${newCountry.trim()}"`);
    await load();
  }
  
  function startEditCountry(country) {
    setEditingCountry({ originalCountry: country });
    setEditForm(country);
  }
  
  const countries = useMemo(() => {
    const map = new Map();
    entries.forEach((entry) => {
      const country = (entry.country || "").trim() || "Unspecified country";
      const city = (entry.city || "").trim() || "Unspecified city";
      if (!map.has(country)) map.set(country, new Map());
      const cities = map.get(country);
      if (!cities.has(city)) cities.set(city, []);
      cities.get(city).push(entry);
    });
    return [...map.entries()]
      .map(([country, cities]) => ({
        country,
        count: [...cities.values()].reduce((total, list) => total + list.length, 0),
        cities: [...cities.entries()]
          .map(([city, items]) => ({ city, items }))
          .sort((a, b) => a.city.localeCompare(b.city)),
      }))
      .sort((a, b) => a.country.localeCompare(b.country));
  }, [entries]);
  return <section className="page">
    <div className="page-title"><div><p className="eyebrow">YOUR MEMORY</p><h1>Travel history</h1><p className="muted">Places you have visited, used to make future plans more personal.</p></div><span className="hero-icon">🧭</span></div>
    <div className="history-layout">
      <Paper className="panel history-form" variant="outlined" sx={{ p: 3 }} component="form" onSubmit={add}>
        <Stack direction="row" spacing={1} alignItems="center" className="section-title" sx={{ mb: 2 }}>
          <PlaceIcon color="primary" />
          <Typography variant="h2" sx={{ fontSize: 18, m: 0 }}>Add a place</Typography>
        </Stack>
        <Stack spacing={2}>
          <TextField variant="filled" label="Country" value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })} placeholder="Hong Kong" />
          <TextField variant="filled" label="City" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} placeholder="Hong Kong" />
          <TextField variant="filled" required label="Location visited" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} placeholder="Victoria Peak" />
          <Button type="submit" variant="contained">Save visit</Button>
          {status && <Alert severity="info">{status}</Alert>}
        </Stack>
      </Paper>
      <div className="panel history-list"><div className="section-title"><span>▣</span><h2>Visited places</h2><b>{entries.length}</b></div>
        {!entries.length && <div className="empty-state"><span>✈</span><p>No places saved yet.</p><small>Add a visit or tell the assistant you have been there before.</small></div>}
        <div className="history-countries">
          {countries.map((group) => {
            const isEditing = editingCountry?.originalCountry === group.country;
            return (
              <Accordion key={group.country} disableGutters elevation={0} className="history-country" defaultExpanded>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <PlaceIcon color="primary" fontSize="small" sx={{ mr: 1 }} />
                  {isEditing ? (
                    <Box sx={{ flex: 1, display: 'flex', gap: 1 }}>
                      <TextField
                        size="small"
                        value={editForm}
                        onChange={(e) => setEditForm(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') updateCountry(group.country, editForm); if (e.key === 'Escape') setEditingCountry(null); }}
                        sx={{ flex: 1, minWidth: 150 }}
                        autoFocus
                      />
                      <Tooltip title="Save">
                        <IconButton size="small" onClick={() => updateCountry(group.country, editForm)}>
                          <SaveIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Cancel">
                        <IconButton size="small" onClick={() => setEditingCountry(null)}>
                          <CancelIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  ) : (
                    <>
                      <Typography fontWeight={700} sx={{ flex: 1 }}>{group.country}</Typography>
                      <Chip size="small" label={`${group.count} ${group.count === 1 ? "place" : "places"}`} color="primary" variant="outlined" />
                      <Tooltip title="Edit country">
                        <IconButton size="small" onClick={() => startEditCountry(group.country)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </>
                  )}
                </AccordionSummary>
                <AccordionDetails>
                  {group.cities.map((cityGroup) => (
                    <Box key={cityGroup.city} className="history-city">
                      <Typography variant="caption" className="history-city-name">{cityGroup.city}</Typography>
                      {cityGroup.items.map((entry) => (
                        <div className="history-entry" key={entry.id}>
                          <span className="place-pin">●</span>
                          <div><strong>{entry.location}</strong></div>
                          <IconButton className="icon-button danger" color="error" title="Remove visit" onClick={() => remove(entry.id)} sx={{ ml: "auto" }}>
                            <DeleteOutlinedIcon fontSize="small" />
                          </IconButton>
                        </div>
                      ))}
                    </Box>
                  ))}
                </AccordionDetails>
              </Accordion>
            );
          })}
        </div>
      </div>
    </div>
  </section>;
}
