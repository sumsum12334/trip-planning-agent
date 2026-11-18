import { useEffect, useRef } from "react";
import { eventIcon } from "../lib/planUtils.js";
import { agentForEvent, currentAgent } from "../lib/workflow.js";

export function Activity({ events }) {
  const itemsRef = useRef(null);
  const scrollToLatest = () => {
    const element = itemsRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  };
  useEffect(scrollToLatest, [events.length]);
  const working = currentAgent(events);
  // Compute agent handovers in one render-time pass (no mutable render state).
  const { rows } = events.reduce(
    (accumulator, event, index) => {
      const agent = agentForEvent(event);
      const handover = Boolean(agent) && agent !== accumulator.lastAgent;
      return {
        rows: [...accumulator.rows, { key: `${event.label}-${index}`, event, agent, handover }],
        lastAgent: agent || accumulator.lastAgent,
      };
    },
    { rows: [], lastAgent: null },
  );
  if (!events.length) return null;
  return (
    <details className="activity-card" onToggle={(event) => { if (event.currentTarget.open) scrollToLatest(); }}>
      <summary className="activity-heading">
        <span>◈</span>
        <strong>Live workflow</strong>
        <span className={`agent-chip ${working ? "working" : "idle"}`}>{working ? `▶ ${working}` : "Idle"}</span>
        <small>{events.length} events</small>
      </summary>
      <div className="activity-items" ref={itemsRef}>
        {rows.map(({ key, event, agent, handover }) => (
          <div className={`event ${event.status}${handover ? " handover" : ""}`} key={key}>
            <span className="event-icon">{eventIcon(event)}</span>
            <span><strong>{event.label}</strong>{event.detail && <small>{event.detail}</small>}{handover && <small className="event-agent">{agent}</small>}</span>
            <span className={`event-dot ${event.status}`} />
          </div>
        ))}
      </div>
    </details>
  );
}
