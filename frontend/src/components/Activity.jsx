import { useEffect, useRef, useState, useMemo } from "react";
import { Box, Button, Chip, Dialog, DialogTitle, DialogContent, Paper, IconButton, Typography } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { eventIcon, formatBudget } from "../lib/planUtils.js";
import { agentForEvent, currentAgent, mergeToolEvents } from "../lib/workflow.js";

const AGENT_COLORS = {
  "Agent 1 · search_stays": { light: "#e8f5e9", dark: "#1b5e20", border: "#81c784", text: "#2e7d32" },
  "Agent 2 · estimate_transport": { light: "#e3f2fd", dark: "#0d47a1", border: "#64b5f6", text: "#1976d2" },
  "Agent 3 · coordinator": { light: "#f3e5f5", dark: "#4a148c", border: "#ce93d8", text: "#7b1fa2" },
  "Agent 4 · travel_history": { light: "#fff3e0", dark: "#e65100", border: "#ffb74d", text: "#ef6c00" },
  "web_search tool": { light: "#fce4ec", dark: "#880e4f", border: "#f48fb1", text: "#c2185b" },
  "weather tool": { light: "#e3f2fd", dark: "#0d47a1", border: "#64b5f6", text: "#1976d2" },
  "Model": { light: "#e8eaf6", dark: "#1a237e", border: "#9fa8da", text: "#3f51b5" },
};

function agentColor(agent) {
  return agent && AGENT_COLORS[agent] ? AGENT_COLORS[agent] : { light: "#f5f5f5", dark: "#424242", border: "#bdbdbd", text: "#616161" };
}

function formatToolArgs(args) {
  if (!args || typeof args !== "object") return "";
  return Object.entries(args)
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v, null, 2) : String(v).slice(0, 200)}`)
    .join("\n");
}

function formatToolResult(result) {
  if (!result) return "";
  if (typeof result === "string") return result.slice(0, 500);
  if (Array.isArray(result)) return `[${result.length} items]`;
  if (typeof result === "object") {
    if (result.stays) return `🏨 ${result.stays.length} stays`;
    if (result.legs) return `🚌 ${result.legs.length} legs`;
    if (result.condition) return `🌤 ${result.condition} · ${result.temperature_c != null ? result.temperature_c + "°C" : ""}${result.temperature_f != null ? " (" + result.temperature_f + "°F)" : ""}`;
    if (result.destination) return `📍 ${result.destination}`;
    return JSON.stringify(result, null, 2).slice(0, 500);
  }
  return String(result).slice(0, 500);
}

function StaysSummary({ result, color }) {
  const stays = Array.isArray(result?.stays) ? result.stays : null;
  if (!stays || !stays.length) return null;
  const shown = stays.slice(0, 5);
  const hidden = stays.length - shown.length;
  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="subtitle2" color={color.text} gutterBottom fontWeight={700}>Found stays</Typography>
      <Typography variant="caption" color="textSecondary" sx={{ display: "block", mb: 1 }}>
        Nightly costs are estimates from the stay search.
      </Typography>
      <ul className="event-stays-list">
        {shown.map((stay, index) => (
          <li key={`${stay?.name || "stay"}-${index}`}>
            <span className="event-stay-name">{stay?.name || "Unnamed stay"}</span>
            {stay?.nightly_cost != null && (
              <span className="event-stay-price">
                {formatBudget(stay.nightly_cost, stay.currency || "")}/night (est.)
              </span>
            )}
          </li>
        ))}
        {hidden > 0 && <li className="event-stays-more">+{hidden} more</li>}
      </ul>
    </Box>
  );
}

function EventDetailDialog({ event, agent, open, onClose }) {
  if (!open || !event) return null;
  const color = agentColor(agent);
  const hasArgs = event.data?.arguments;
  const hasResult = event.data?.result;
  const isStaysResult = event.data?.tool === "search_stays" && Array.isArray(event.data?.result?.stays);

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth PaperProps={{ elevation: 8 }}>
      <DialogTitle sx={{ background: color.light, borderBottom: `2px solid ${color.border}`, p: 2, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Chip
            label={agent || "Unknown"}
            size="small"
            sx={{ background: color.border, color: "#fff", fontWeight: 700 }}
          />
          <Typography variant="h6" sx={{ color: color.text, fontWeight: 700 }}>{event.label}</Typography>
        </Box>
        <IconButton onClick={onClose} size="small" sx={{ color: color.text }}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent sx={{ p: 3, maxHeight: "60vh", overflow: "auto" }}>
        {event.detail && (
          <Typography variant="body2" color="textSecondary" gutterBottom>{event.detail}</Typography>
        )}
        {event.timestamp && (
          <Typography variant="caption" color="textSecondary" sx={{ display: "block", mb: 2 }}>{event.timestamp}</Typography>
        )}
        {hasArgs && (
          <Box sx={{ mb: 3 }}>
            <Typography variant="subtitle2" color={color.text} gutterBottom fontWeight={700}>Arguments</Typography>
            <Paper variant="outlined" sx={{ p: 2, background: "#fafafa", maxHeight: "30vh", overflow: "auto" }}>
              <pre style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {formatToolArgs(event.data.arguments)}
              </pre>
            </Paper>
          </Box>
        )}
        {isStaysResult && <StaysSummary result={event.data.result} color={color} />}
        {hasResult && (
          <Box>
            <Typography variant="subtitle2" color={color.text} gutterBottom fontWeight={700}>Result</Typography>
            <Paper variant="outlined" sx={{ p: 2, background: "#fafafa", maxHeight: "30vh", overflow: "auto" }}>
              <pre style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {formatToolResult(event.data.result)}
              </pre>
            </Paper>
          </Box>
        )}
        {!hasArgs && !hasResult && event.data && (
          <Box>
            <Typography variant="subtitle2" color={color.text} gutterBottom fontWeight={700}>Data</Typography>
            <Paper variant="outlined" sx={{ p: 2, background: "#fafafa" }}>
              <pre style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(event.data, null, 2)}
              </pre>
            </Paper>
          </Box>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function Activity({ events }) {
  const itemsRef = useRef(null);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [selectedAgent, setSelectedAgent] = useState(null);

  const scrollToLatest = () => {
    const element = itemsRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  };
  useEffect(scrollToLatest, [events.length]);

  const working = currentAgent(events);

  // One card per tool call: "Calling X" is merged with its matching
  // "X result received" event; everything else passes through as-is.
  const cards = useMemo(() => mergeToolEvents(events), [events]);

  // Compute agent handovers for the timeline
  const rows = useMemo(() => {
    const rows = [];
    let lastAgent = null;
    cards.forEach((event) => {
      const agent = agentForEvent(event);
      const handover = Boolean(agent) && agent !== lastAgent;
      const key = `${event.label}-${event.index}`;
      rows.push({ key, event, agent, handover });
      lastAgent = agent || lastAgent;
    });
    return rows;
  }, [cards]);

  if (!events.length) return null;

  const openEventDetail = (event, agent) => {
    setSelectedEvent(event);
    setSelectedAgent(agent);
  };

  const closeEventDetail = () => {
    setSelectedEvent(null);
    setSelectedAgent(null);
  };

  const renderEvent = ({ key, event, agent, handover }) => {
    const color = agentColor(agent);
    const bg = `linear-gradient(90deg, ${color.border}22 0%, transparent 100%)`;
    const hasDetails = event.data && (event.data.arguments || event.data.result);

    return (
      <div
        key={key}
        className={`event ${event.status}${handover ? " handover" : ""}`}
        style={{ background: bg, borderLeftColor: color.border }}
        onClick={hasDetails ? () => openEventDetail(event, agent) : undefined}
        role={hasDetails ? "button" : undefined}
        tabIndex={hasDetails ? 0 : undefined}
        onKeyDown={hasDetails ? (e) => { if (e.key === "Enter" || e.key === " ") openEventDetail(event, agent); } : undefined}
      >
        <div className="event-main">
          <span className="event-icon">{eventIcon(event)}</span>
          <span className="event-label">
            <strong>{event.toolLabel || event.label}</strong>
            {event.detail && <small className="event-detail">{event.detail}</small>}
            {handover && <small className="event-agent" style={{ color: color.text }}>{agent}</small>}
          </span>
          <span className={`event-dot ${event.status}`} style={{ background: color.border }} />
        </div>
        {hasDetails && (
          <span className="event-expand-hint" style={{ color: color.border, fontSize: 10, marginLeft: 8 }}>
            Click for details
          </span>
        )}
      </div>
    );
  };

  return (
    <>
      <div className="activity-card">
        <div className="activity-heading">
          <span className="activity-icon">◈</span>
          <strong>Live workflow</strong>
          <span className={`agent-chip ${working ? "working" : "idle"}`}>{working ? `▶ ${working}` : "Idle"}</span>
          <small>{cards.length} events</small>
        </div>
        <div className="activity-items" ref={itemsRef}>
          {rows.map(renderEvent)}
        </div>
      </div>
      <EventDetailDialog
        event={selectedEvent}
        agent={selectedAgent}
        open={!!selectedEvent}
        onClose={closeEventDetail}
      />
    </>
  );
}
