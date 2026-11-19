import { useEffect, useRef, useState, useMemo } from "react";
import {
  Collapse,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Typography,
  Chip,
  Box,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Paper,
  IconButton,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import CloseIcon from "@mui/icons-material/Close";
import { eventIcon } from "../lib/planUtils.js";
import { agentForEvent, currentAgent } from "../lib/workflow.js";

const AGENT_COLORS = {
  "Agent 1 · search_stays": { light: "#e8f5e9", dark: "#1b5e20", border: "#81c784", text: "#2e7d32" },
  "Agent 2 · estimate_transport": { light: "#e3f2fd", dark: "#0d47a1", border: "#64b5f6", text: "#1976d2" },
  "Agent 3 · coordinator": { light: "#f3e5f5", dark: "#4a148c", border: "#ce93d8", text: "#7b1fa2" },
  "Agent 4 · travel_history": { light: "#fff3e0", dark: "#e65100", border: "#ffb74d", text: "#ef6c00" },
  "web_search tool": { light: "#fce4ec", dark: "#880e4f", border: "#f48fb1", text: "#c2185b" },
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
    if (result.destination) return `📍 ${result.destination}`;
    return JSON.stringify(result, null, 2).slice(0, 500);
  }
  return String(result).slice(0, 500);
}

function formatDuration(start, end) {
  if (!start || !end) return "";
  const ms = new Date(end) - new Date(start);
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function EventDetailDialog({ event, agent, open, onClose }) {
  if (!open || !event) return null;
  const color = agentColor(agent);
  const hasArgs = event.data?.arguments;
  const hasResult = event.data?.result;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth PaperProps={{ elevation: 8 }}>
      <DialogTitle sx={{ background: color.light, borderBottom: `2px solid ${color.border}`, p: 2, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Chip
            label={agent || "Unknown"}
            size="small"
            sx={{ background: color.border, color: "#fff", fontWeight: 700 }}
          />
          <Typography variant="h6" sx={{ color: color.text, fontWeight: 700 }}>
            {event.label}
          </Typography>
        </Box>
        <IconButton onClick={onClose} size="small" sx={{ color: color.text }}>
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent sx={{ p: 3, maxHeight: "60vh", overflow: "auto" }}>
        {event.detail && (
          <Typography variant="body2" color="textSecondary" gutterBottom>
            {event.detail}
          </Typography>
        )}
        {event.timestamp && (
          <Typography variant="caption" color="textSecondary" sx={{ display: "block", mb: 2 }}>
            {event.timestamp}
          </Typography>
        )}
        {hasArgs && (
          <Box sx={{ mb: 3 }}>
            <Typography variant="subtitle2" color={color.text} gutterBottom fontWeight={700}>
              Arguments
            </Typography>
            <Paper variant="outlined" sx={{ p: 2, background: "#fafafa", maxHeight: "30vh", overflow: "auto" }}>
              <pre style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {formatToolArgs(event.data.arguments)}
              </pre>
            </Paper>
          </Box>
        )}
        {hasResult && (
          <Box>
            <Typography variant="subtitle2" color={color.text} gutterBottom fontWeight={700}>
              Result
            </Typography>
            <Paper variant="outlined" sx={{ p: 2, background: "#fafafa", maxHeight: "30vh", overflow: "auto" }}>
              <pre style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {formatToolResult(event.data.result)}
              </pre>
            </Paper>
          </Box>
        )}
        {!hasArgs && !hasResult && event.data && (
          <Box>
            <Typography variant="subtitle2" color={color.text} gutterBottom fontWeight={700}>
              Data
            </Typography>
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
  const [viewMode, setViewMode] = useState("timeline"); // "timeline" | "byAgent"

  const scrollToLatest = () => {
    const element = itemsRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  };
  useEffect(scrollToLatest, [events.length]);

  const working = currentAgent(events);

  // Compute agent handovers and group events by agent
  const { rows, byAgent } = useMemo(() => {
    const rows = [];
    const byAgent = {};
    let lastAgent = null;
    events.forEach((event, index) => {
      const agent = agentForEvent(event);
      const handover = Boolean(agent) && agent !== lastAgent;
      const key = `${event.label}-${index}`;
      rows.push({ key, event, agent, handover, index });
      if (agent) {
        if (!byAgent[agent]) byAgent[agent] = [];
        byAgent[agent].push({ key, event, index });
      }
      lastAgent = agent || lastAgent;
    });
    return { rows, byAgent };
  }, [events]);

  const agentStats = useMemo(() => {
    const stats = {};
    Object.entries(byAgent).forEach(([agent, evs]) => {
      const tools = evs.filter(({ event }) => event.type === "tool" || event.label.toLowerCase().includes("tool"));
      const errors = evs.filter(({ event }) => event.status === "error");
      const completed = evs.filter(({ event }) => event.status === "completed");
      const running = evs.filter(({ event }) => event.status === "running");
      const first = evs[0]?.event;
      const last = evs[evs.length - 1]?.event;
      stats[agent] = {
        count: evs.length,
        tools: tools.length,
        errors: errors.length,
        completed: completed.length,
        running: running.length > 0,
        duration: formatDuration(first?.timestamp, last?.timestamp),
        firstEvent: first,
        lastEvent: last,
      };
    });
    return stats;
  }, [byAgent]);

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
            <strong>{event.label}</strong>
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

  const renderTimeline = () => (
    <div className="activity-items" ref={itemsRef}>
      {rows.map(renderEvent)}
    </div>
  );

  const renderByAgent = () => (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {Object.entries(byAgent).map(([agent, evs]) => {
        const stats = agentStats[agent];
        const color = agentColor(agent);
        return (
          <Accordion key={agent} defaultExpanded sx={{ border: `1px solid ${color.border}`, borderRadius: 12, background: color.light }}>
            <AccordionSummary
              expandIcon={<ExpandMoreIcon />}
              sx={{ background: color.light, borderBottom: `1px solid ${color.border}` }}
            >
              <Box sx={{ display: "flex", alignItems: "center", gap: 12, flex: 1, minWidth: 0 }}>
                <Chip
                  label={agent}
                  size="small"
                  sx={{
                    background: color.border,
                    color: "#fff",
                    fontWeight: 700,
                    flex: "0 0 auto",
                    minWidth: 0,
                    textOverflow: "ellipsis",
                    overflow: "hidden",
                  }}
                />
                <Box sx={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 11, color: color.text }}>
                  <span>📋 {stats.count} events</span>
                  <span>⚙ {stats.tools} tools</span>
                  <span>✓ {stats.completed} done</span>
                  {stats.errors > 0 && <span style={{ color: "#c62828" }}>⚠ {stats.errors} errors</span>}
                  {stats.running && <span style={{ color: "#1976d2" }}>▶ running</span>}
                  {stats.duration && <span>⏱ {stats.duration}</span>}
                </Box>
              </Box>
            </AccordionSummary>
            <AccordionDetails sx={{ p: 2, display: "flex", flexDirection: "column", gap: 8 }}>
              {evs.map(({ key, event }) => (
                <div
                  key={key}
                  className={`event ${event.status}`}
                  style={{ borderLeftColor: color.border }}
                  onClick={() => openEventDetail(event, agent)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") openEventDetail(event, agent); }}
                >
                  <div className="event-main">
                    <span className="event-icon">{eventIcon(event)}</span>
                    <span className="event-label">
                      <strong>{event.label}</strong>
                      {event.detail && <small className="event-detail">{event.detail}</small>}
                    </span>
                    <span className={`event-dot ${event.status}`} style={{ background: color.border }} />
                  </div>
                </div>
              ))}
            </AccordionDetails>
          </Accordion>
        );
      })}
    </Box>
  );

  return (
    <>
      <details className="activity-card" onToggle={(e) => { if (e.currentTarget.open) scrollToLatest(); }}>
        <summary className="activity-heading">
          <span>◈</span>
          <strong>Live workflow</strong>
          <span className={`agent-chip ${working ? "working" : "idle"}`}>{working ? `▶ ${working}` : "Idle"}</span>
          <small>{events.length} events</small>
          <Box sx={{ display: "flex", gap: 8, marginLeft: "auto", ml: 2 }}>
            <Button
              size="small"
              variant={viewMode === "timeline" ? "contained" : "outlined"}
              onClick={() => setViewMode("timeline")}
              sx={{ textTransform: "none", fontSize: 11 }}
            >
              Timeline
            </Button>
            <Button
              size="small"
              variant={viewMode === "byAgent" ? "contained" : "outlined"}
              onClick={() => setViewMode("byAgent")}
              sx={{ textTransform: "none", fontSize: 11 }}
            >
              By Agent
            </Button>
          </Box>
        </summary>
        <div className="activity-content">
          {viewMode === "timeline" ? renderTimeline() : renderByAgent()}
        </div>
      </details>
      <EventDetailDialog
        event={selectedEvent}
        agent={selectedAgent}
        open={!!selectedEvent}
        onClose={closeEventDetail}
      />
    </>
  );
}