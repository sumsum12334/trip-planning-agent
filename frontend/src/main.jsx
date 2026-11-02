import { StrictMode, createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Alert,
  Avatar,
  Box,
  Button,
  CssBaseline,
  Divider,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Stack,
  TextField,
  ThemeProvider,
  Tooltip,
  Typography,
  useTheme,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import ChatBubbleOutlinedIcon from "@mui/icons-material/ChatBubbleOutlined";
import DarkModeOutlinedIcon from "@mui/icons-material/DarkModeOutlined";
import DeleteOutlinedIcon from "@mui/icons-material/DeleteOutlined";
import HistoryEduIcon from "@mui/icons-material/HistoryEdu";
import LightModeOutlinedIcon from "@mui/icons-material/LightModeOutlined";
import PlaceIcon from "@mui/icons-material/Place";
import SendIcon from "@mui/icons-material/Send";
import SettingsIcon from "@mui/icons-material/Settings";
import TravelExploreIcon from "@mui/icons-material/TravelExplore";
import { createAppTheme } from "./theme";
import "./styles.css";

const ColorModeContext = createContext({ mode: "light", toggleColorMode: () => {} });
const useColorMode = () => useContext(ColorModeContext);

function Markdown({ children }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>;
}

function MessageBubble({ role, content, reasoning, kicker, footer }) {
  const theme = useTheme();
  const isUser = role === "user";
  const isQuestion = role === "question";
  return (
    <Stack
      direction={isUser ? "row-reverse" : "row"}
      spacing={1.25}
      sx={{ maxWidth: "min(820px, 92%)", alignSelf: isUser ? "flex-end" : "flex-start", width: "fit-content" }}
    >
      <Avatar
        sx={{
          width: 34,
          height: 34,
          fontSize: 12,
          fontWeight: 700,
          bgcolor: isUser ? "action.selected" : "primary.main",
          color: isUser ? "text.primary" : "primary.contrastText",
        }}
      >
        {isUser ? "You" : isQuestion ? "?" : "AI"}
      </Avatar>
      <Paper
        sx={{
          px: 1.75,
          py: 1.35,
          borderRadius: isUser ? "16px 4px 16px 16px" : "4px 16px 16px 16px",
          bgcolor: isUser
            ? (theme.palette.mode === "dark" ? "rgba(139,132,255,0.22)" : "rgba(108,99,255,0.12)")
            : isQuestion
              ? (theme.palette.mode === "dark" ? "rgba(139,132,255,0.16)" : "#f3f1ff")
              : (theme.palette.mode === "dark" ? "rgba(255,255,255,0.04)" : "#f5f7fb"),
          boxShadow: theme.palette.mode === "dark" ? "none" : "0 4px 14px rgba(15,23,42,0.04)",
          lineHeight: 1.55,
          "& p": { m: 0 },
          "& p + p": { mt: 1 },
          "& pre": {
            overflow: "auto",
            p: 1.5,
            borderRadius: 2,
            bgcolor: theme.palette.mode === "dark" ? "#0b1020" : "#18233e",
            color: "#fff",
          },
        }}
      >
        {kicker && (
          <Typography variant="caption" color="primary" fontWeight={800} sx={{ display: "block", mb: 0.5, letterSpacing: 0.6 }}>
            {kicker}
          </Typography>
        )}
        {reasoning ? (
          <Box component="details" sx={{ mb: 1, color: "text.secondary", fontSize: 12 }}>
            <Box component="summary" sx={{ cursor: "pointer" }}>Model reasoning</Box>
            <Markdown>{reasoning}</Markdown>
          </Box>
        ) : null}
        {typeof content === "string" ? (role === "user" ? content : <Markdown>{content}</Markdown>) : content}
        {footer}
      </Paper>
    </Stack>
  );
}


const USER_KEY = "trip-planner-user-id";
const emptyConversation = () => ({ id: null, messages: [], events: [] });
const getUserId = () => {
  const existing = window.localStorage.getItem(USER_KEY);
  if (existing) return existing;
  const id = `local-${crypto.randomUUID()}`;
  window.localStorage.setItem(USER_KEY, id);
  return id;
};

const eventIcon = (event) => {
  if (event.status === "error") return "⚠";
  if (event.label.toLowerCase().includes("history")) return "🧠";
  if (event.type === "model") return "✦";
  if (event.label.toLowerCase().includes("tool")) return "⚙";
  return "✓";
};

function TripPlanCard({ plan }) {
  return <div className="trip-plan-card">
    <div className="trip-plan-header"><div><div className="question-kicker">TRIP PLAN</div><h3>{plan.destination}</h3></div><span>✦</span></div>
    <div className="trip-days">
      {plan.days.map((day) => <article className="trip-day" key={`${day.day}-${day.title}`}>
        <div className="day-number">DAY {day.day}</div><strong>{day.title}</strong>
        <ul>{day.activities.map((activity) => <li key={activity}>{activity}</li>)}</ul>
        {day.notes?.length > 0 && <small>{day.notes.join(" · ")}</small>}
      </article>)}
    </div>
    {plan.budget != null && <div className="trip-budget">Estimated budget: {plan.budget}</div>}
    {plan.notes?.length > 0 && <small className="trip-notes">{plan.notes.join(" · ")}</small>}
  </div>;
}

function Activity({ events }) {
  if (!events.length) return null;
  const activityRef = useRef(null);
  useEffect(() => {
    if (activityRef.current) activityRef.current.scrollTop = activityRef.current.scrollHeight;
  }, [events.length]);
  return (
    <details className="activity-card" open ref={activityRef}>
      <summary className="activity-heading"><span>◈</span><strong>Live workflow</strong><small>{events.length} events</small></summary>
      <div className="activity-items">
        {events.map((event, index) => (
          <div className={`event ${event.status}`} key={`${event.label}-${index}`}>
            <span className="event-icon">{eventIcon(event)}</span>
            <span><strong>{event.label}</strong>{event.detail && <small>{event.detail}</small>}</span>
            <span className={`event-dot ${event.status}`} />
            {event.data?.tool === "display_trip_plan" && event.data?.result && (
              <TripPlanCard plan={event.data.result} />
            )}
          </div>
        ))}
      </div>
    </details>
  );
}

function QuestionBox({ event, onOption, disabled, retryOption, selectedOption }) {
  if (!event?.data?.result?.question) return null;
  const options = event.data.result.options || [];
  const selected = selectedOption || event.data.selected;
  return <section className="question-box">
    <div className="question-box-header"><span className="question-box-icon">?</span><div><div className="question-kicker">YOUR INPUT NEEDED</div><strong>{event.data.result.question}</strong></div></div>
    <p>Choose an option to continue planning.</p>
    <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1} className="question-options" sx={{ mt: 1.5, ml: "39px" }}>
      {options.map((option) => (
        <Button
          key={option}
          type="button"
          size="small"
          variant={selected === option ? "contained" : "outlined"}
          disabled={disabled || Boolean(selected)}
          onClick={() => onOption(option)}
        >
          {selected === option ? "Selected" : option}
        </Button>
      ))}
    </Stack>
    {retryOption && (
      <Button className="question-retry" type="button" size="small" color="error" variant="outlined" onClick={() => onOption(retryOption)} sx={{ mt: 1.5, ml: "39px" }}>
        Retry sending "{retryOption}"
      </Button>
    )}
  </section>;
}

function workflowState(events, pendingQuestion, status) {
  if (pendingQuestion) return { label: "Waiting for your response", className: "waiting", icon: "?" };
  if (status.includes("Sending your choice")) return { label: "Sending your choice to the assistant...", className: "working", icon: "➜" };
  if (status.includes("failed") || events.some((event) => event.status === "error")) return { label: "Needs attention", className: "error", icon: "!" };
  if (status === "Working..." || status.includes("Sending") || events.some((event) => event.status === "running")) return { label: "Agent working", className: "working", icon: "✦" };
  return { label: "Ready", className: "ready", icon: "✓" };
}

function ConversationList({ conversations, activeId, onSelect, onDelete }) {
  return (
    <List dense disablePadding className="conversation-list" sx={{ overflow: "auto", flex: 1 }}>
      {conversations.map((item) => (
        <Box key={item.id} sx={{ display: "flex", alignItems: "center", gap: 0.5, px: 0.5 }}>
          <ListItemButton
            selected={activeId === item.id}
            onClick={() => onSelect(item.id)}
            sx={{ borderRadius: 2, py: 0.75, flex: 1, minWidth: 0 }}
          >
            <ChatBubbleOutlinedIcon sx={{ fontSize: 16, mr: 1, opacity: 0.7 }} />
            <ListItemText
              primary={item.title}
              primaryTypographyProps={{ noWrap: true, fontSize: 13 }}
            />
          </ListItemButton>
          <IconButton size="small" color="error" title="Delete conversation" onClick={() => onDelete(item.id)}>
            <DeleteOutlinedIcon fontSize="small" />
          </IconButton>
        </Box>
      ))}
    </List>
  );
}

function ModelSettings() {
  const [settings, setSettings] = useState({ endpoint_url: "", qwen_model: "" });
  const [apiKey, setApiKey] = useState("");
  const [status, setStatus] = useState("");
  useEffect(() => { fetch("/api/settings").then((response) => response.json()).then(setSettings); }, []);
  async function save() {
    setStatus("Saving...");
    const response = await fetch("/api/settings/model", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint_url: settings.endpoint_url, model: settings.qwen_model, api_key: apiKey || null }),
    });
    if (!response.ok) { setStatus(`Save failed: ${await response.text()}`); return; }
    const result = await response.json();
    setApiKey(""); setSettings({ ...settings, endpoint_url: result.endpoint_url, qwen_model: result.model });
    setStatus(result.api_key_configured ? "Saved; API key configured." : "Saved; API key not configured.");
  }
  return (
    <Paper className="settings panel" variant="outlined" sx={{ mt: 2, p: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <SettingsIcon color="primary" fontSize="small" />
        <Typography fontWeight={700}>Model settings</Typography>
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Settings apply to this running backend. API keys are never displayed.
      </Typography>
      <Stack spacing={2}>
        <TextField
          label="Endpoint URL"
          value={settings.endpoint_url || ""}
          onChange={(event) => setSettings({ ...settings, endpoint_url: event.target.value })}
        />
        <TextField
          label="Model"
          value={settings.qwen_model || ""}
          onChange={(event) => setSettings({ ...settings, qwen_model: event.target.value })}
        />
        <TextField
          label="API key"
          type="password"
          autoComplete="off"
          placeholder="Leave blank to keep current key"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
        />
        <Stack direction="row" spacing={2} alignItems="center">
          <Button variant="contained" color="inherit" onClick={save} sx={{ bgcolor: "#263452", color: "#fff", "&:hover": { bgcolor: "#1b2538" } }}>
            Save settings
          </Button>
          <Typography variant="caption" color="text.secondary">{status}</Typography>
        </Stack>
      </Stack>
    </Paper>
  );
}

function HistoryPage({ userId }) {
  const [entries, setEntries] = useState([]);
  const [form, setForm] = useState({ country: "", city: "", location: "" });
  const [status, setStatus] = useState("");
  async function load() {
    const response = await fetch(`/api/travel-history?user_id=${encodeURIComponent(userId)}`);
    if (response.ok) setEntries(await response.json());
  }
  useEffect(() => { load(); }, [userId]);
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
  return <section className="page">
    <div className="page-title"><div><p className="eyebrow">YOUR MEMORY</p><h1>Travel history</h1><p className="muted">Places you have visited, used to make future plans more personal.</p></div><span className="hero-icon">🧭</span></div>
    <div className="history-layout">
      <Paper className="panel history-form" variant="outlined" sx={{ p: 3 }} component="form" onSubmit={add}>
        <Stack direction="row" spacing={1} alignItems="center" className="section-title" sx={{ mb: 2 }}>
          <PlaceIcon color="primary" />
          <Typography variant="h2" sx={{ fontSize: 18, m: 0 }}>Add a place</Typography>
        </Stack>
        <Stack spacing={2}>
          <TextField label="Country" value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })} placeholder="Hong Kong" />
          <TextField label="City" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} placeholder="Hong Kong" />
          <TextField required label="Location visited" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} placeholder="Victoria Peak" />
          <Button type="submit" variant="contained">Save visit</Button>
          {status && <Alert severity="info">{status}</Alert>}
        </Stack>
      </Paper>
      <div className="panel history-list"><div className="section-title"><span>▣</span><h2>Visited places</h2><b>{entries.length}</b></div>
        {!entries.length && <div className="empty-state"><span>✈</span><p>No places saved yet.</p><small>Add a visit or tell the assistant you have been there before.</small></div>}
        {entries.map((entry) => <div className="history-entry" key={entry.id}><span className="place-pin">●</span><div><strong>{entry.location}</strong><p>{[entry.city, entry.country].filter(Boolean).join(", ") || "Location details not specified"}</p></div><IconButton className="icon-button danger" color="error" title="Remove visit" onClick={() => remove(entry.id)} sx={{ ml: "auto" }}>
            <DeleteOutlinedIcon fontSize="small" />
          </IconButton></div>)}
      </div>
    </div>
  </section>;
}

function ChatPage({ current, setCurrent, conversations, loadConversations, userId }) {
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState("");
  const [retryText, setRetryText] = useState("");
  const [retryOption, setRetryOption] = useState("");
  const [answering, setAnswering] = useState(false);
  const [selectedOption, setSelectedOption] = useState("");
  const answerLockRef = useRef(false);
  const messagesRef = useRef(null);
  useEffect(() => { if (messagesRef.current) messagesRef.current.scrollTop = messagesRef.current.scrollHeight; }, [current.messages, current.events]);
  async function selectConversation(id) {
    const response = await fetch(`/api/conversations/${id}`);
    if (response.ok) { const item = await response.json(); setCurrent({ id: item.id, messages: item.messages, events: item.events || [] }); setStatus(""); setRetryText(""); }
  }
  async function sendMessage(event, retry = false) {
    event?.preventDefault();
    const text = (retry ? retryText : message).trim(); if (!text) return;
    setMessage(""); setRetryText(""); setStatus("Working...");
    const retryBase = retry && current.messages.at(-1)?.role === "assistant" ? current.messages.slice(0, -1) : current.messages;
    const context = retry ? retryBase : current.messages;
    const optimisticMessages = retry ? (retryBase.at(-1)?.role === "user" ? retryBase : [...retryBase, { role: "user", content: text }]) : [...current.messages, { role: "user", content: text }];
    const workingMessages = [...optimisticMessages, { role: "assistant", content: "Working...", reasoning: "" }];
    const optimisticEvents = [...current.events, { type: "agent", label: "Coordinator agent started", status: "running" }, { type: "model", label: "Model request queued", status: "running" }];
    setCurrent({ ...current, messages: workingMessages, events: optimisticEvents });
    const response = await fetch("/api/chat/stream", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text, conversation: context, conversation_id: current.id, user_id: userId }) });
    if (!response.ok) { setRetryText(text); setStatus("Request failed. You can retry the saved message."); return; }
    if (!response.body) { setRetryText(text); setStatus("Streaming is unavailable. Please retry."); return; }
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ""; let streamedText = ""; let streamedReasoning = ""; let result = null; let streamEvents = [...current.events];
    const updateWorking = () => setCurrent((previous) => ({ ...previous, messages: [...workingMessages.slice(0, -1), { role: "assistant", content: streamedText || "Working...", reasoning: streamedReasoning }], events: streamEvents }));
    const processFrame = (frame) => {
      const line = frame.split("\n").find((item) => item.startsWith("data: ")); if (!line) return;
      const payload = JSON.parse(line.slice(6));
      if (payload.kind === "event") { streamEvents = [...streamEvents, payload]; updateWorking(); }
      else if (payload.kind === "reasoning") { streamedReasoning += payload.text; updateWorking(); }
      else if (payload.kind === "content") { streamedText += payload.text; updateWorking(); }
      else if (payload.kind === "done") result = { ...payload, text: payload.text || streamedText, reasoning: payload.reasoning || streamedReasoning };
      else if (payload.kind === "error") setStatus(payload.message);
    };
    while (true) { const { value, done } = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), { stream: !done }); const frames = buffer.split("\n\n"); buffer = frames.pop() || ""; frames.forEach(processFrame); if (done && buffer.trim()) processFrame(buffer); if (done) break; }
    if (result) {
      const completedMessages = result.pending_question
        ? optimisticMessages
        : [...optimisticMessages, { role: "assistant", content: result.text, reasoning: result.reasoning || streamedReasoning }];
      setCurrent({ id: result.conversation_id, messages: completedMessages, events: result.events });
      setStatus(result.pending_question ? "The assistant is waiting for your choice." : (result.stub ? "Local stub response" : `Model: ${result.model}`));
    }
    await loadConversations();
  }
  const questionEvent = [...current.events].reverse().find(
    (event) => event.data?.tool === "ask_user_question" && event.data?.result?.question,
  );
  const pendingEvent = [...current.events].reverse().find(
    (event) => event.data?.tool === "ask_user_question" && event.data?.result?.question && !event.data?.selected,
  );
  const workflow = workflowState(current.events, selectedOption ? null : pendingEvent, status);
  async function answerQuestion(option) {
    if (answerLockRef.current) return;
    answerLockRef.current = true;
    setAnswering(true);
    setSelectedOption(option);
    setStatus("Sending your choice to the assistant...");
    setRetryOption("");
    const optimisticEvents = current.events.map((item) => item === questionEvent
      ? { ...item, data: { ...item.data, selected: option }, detail: `Answer selected: ${option}`, status: "running" }
      : item);
    const optimisticMessages = current.messages.at(-1)?.role === "user" && current.messages.at(-1)?.content === option
      ? current.messages
      : [...current.messages, { role: "user", content: option }];
    setCurrent((previous) => ({ ...previous, messages: optimisticMessages, events: optimisticEvents }));
    const response = await fetch("/api/chat/question", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: option,
        conversation_id: current.id,
        user_id: userId,
      }),
    });
    if (!response.ok) {
      let detail = "The assistant could not continue.";
      try {
        const payload = await response.json();
        detail = typeof payload.detail === "string" ? payload.detail : (payload.detail?.message || detail);
      } catch { /* retain safe fallback */ }
      setRetryOption(option);
      setStatus(`Continuation failed: ${detail}`);
      answerLockRef.current = false;
      setAnswering(false);
      return;
    }
    const result = await response.json();
    const updatedEvents = optimisticEvents.map((item) => item === questionEvent
      ? { ...item, detail: `Answer selected: ${option}`, status: "completed", data: { ...item.data, selected: option } }
      : item);
    setCurrent((previous) => ({
      id: result.conversation_id,
      messages: [...optimisticMessages, {
        role: "assistant",
        content: result.text,
        reasoning: result.reasoning || "",
      }],
      events: [...updatedEvents, ...result.events.filter((event) => event.label !== "Answer recorded")],
    }));
    setStatus(result.stub ? "Local stub response" : `Model: ${result.model}`);
    answerLockRef.current = false;
    setAnswering(false);
    setSelectedOption("");
    await loadConversations();
  }
  return <section className="page chat-page">
    <div className="page-title"><div><p className="eyebrow">AI TRIP COMPANION</p><h1>Plan something memorable.</h1><p className="muted">Your coordinator connects stays, transport, and travel memory in one workflow.</p></div><span className="hero-icon">✦</span></div>
    <div className="chat-workspace"><section className="panel chat-panel"><Box className="messages" ref={messagesRef} sx={{ display: "flex", flexDirection: "column", gap: 0.5 }}>
      {!current.messages.length && <div className="welcome"><span>✦</span><h2>Where will you go next?</h2><p>Ask for an itinerary, compare options, or tell me about somewhere you have visited.</p></div>}
      {(() => {
        const questions = current.events.filter((event) => event.data?.tool === "ask_user_question" && event.data?.result?.question);
        const renderedQuestions = new Set();
        const output = [];
        current.messages.forEach((item, index) => {
          if (item.role === "user") {
            const question = questions.find((event) => event.data?.selected === item.content && !renderedQuestions.has(event));
            if (question) {
              renderedQuestions.add(question);
              output.push(
                <MessageBubble
                  key={`question-${index}`}
                  role="question"
                  kicker="Question"
                  content={<Typography component="span">{question.data.result.question}</Typography>}
                  footer={<Typography variant="caption" color="primary" fontWeight={700} sx={{ display: "block", mt: 1 }}>Answer: {item.content}</Typography>}
                />,
              );
            }
          }
          output.push(
            <MessageBubble
              key={`${item.role}-${index}`}
              role={item.role}
              content={item.content}
              reasoning={item.reasoning}
            />,
          );
        });
        questions.filter((event) => !renderedQuestions.has(event)).forEach((event, index) => output.push(
          <MessageBubble
            key={`pending-question-${index}`}
            role="question"
            kicker="Question"
            content={<Typography component="span">{event.data.result.question}</Typography>}
            footer={event.data.selected ? <Typography variant="caption" color="primary" fontWeight={700} sx={{ display: "block", mt: 1 }}>Answer: {event.data.selected}</Typography> : null}
          />,
        ));
        return (
          <Stack spacing={2} sx={{ width: "100%" }}>
            {output}
          </Stack>
        );
      })()}
    </Box>
      <div className={`workflow-status ${workflow.className}`}><span>{workflow.icon}</span><strong>{workflow.label}</strong><small>{workflow.className === "waiting" ? "Choose an option below." : workflow.className === "working" ? "The assistant is processing your request." : ""}</small></div>
      <QuestionBox event={questionEvent} onOption={answerQuestion} disabled={answering} retryOption={retryOption} selectedOption={selectedOption} />
      <Box className="composer" component="form" onSubmit={sendMessage} sx={{ display: "flex", gap: 1.5, alignItems: "flex-end", p: 2.5, borderTop: "1px solid #edf0f6" }}>
        <TextField
          multiline
          minRows={2}
          maxRows={5}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Plan a 3-day trip to Kyoto for $800..."
          sx={{ flex: 1 }}
        />
        <Button className="send-button" type="submit" variant="contained" endIcon={<SendIcon />}>
          Send
        </Button>
      </Box>
      <div className="composer-footer"><span>{status || "Markdown supported"}</span>{retryText && <Button className="retry" size="small" color="warning" variant="outlined" onClick={(event) => sendMessage(event, true)}>Retry</Button>}</div>
    </section><Activity events={current.events} /></div><ModelSettings />
  </section>;
}

function App() {
  const theme = useTheme();
  const colorMode = useColorMode();
  const isDark = theme.palette.mode === "dark";
  const [page, setPage] = useState("chat");
  const [conversations, setConversations] = useState([]);
  const [current, setCurrent] = useState(emptyConversation);
  const userId = getUserId();
  async function loadConversations() {
    const response = await fetch("/api/conversations");
    if (response.ok) setConversations(await response.json());
  }
  useEffect(() => { loadConversations(); }, []);
  async function deleteConversation(id) {
    if (!window.confirm("Delete this conversation?")) return;
    const response = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
    if (response.ok) {
      if (current.id === id) setCurrent(emptyConversation());
      await loadConversations();
    }
  }
  return (
    <Box
      className="app"
      data-color-mode={theme.palette.mode}
      sx={{
        display: "flex",
        minHeight: "100vh",
        bgcolor: "background.default",
        color: "text.primary",
      }}
    >
      <Box
        component="aside"
        sx={{
          width: 280,
          display: "flex",
          flexDirection: "column",
          p: 2.5,
          bgcolor: isDark ? "#0a0f1c" : "#111b35",
          color: "#dfe6fa",
          borderRight: "1px solid",
          borderColor: isDark ? "rgba(255,255,255,0.06)" : "transparent",
        }}
      >
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mx: 0.5, mb: 3 }}>
          <Box sx={{ width: 36, height: 36, borderRadius: "12px", bgcolor: "primary.main", color: "#fff", display: "grid", placeItems: "center", boxShadow: "0 8px 18px rgba(80,72,190,0.4)" }}>
            <TravelExploreIcon fontSize="small" />
          </Box>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography fontWeight={700} color="#fff" fontSize={18}>Tripwise</Typography>
            <Typography variant="caption" sx={{ color: "#8794b7" }}>AI travel planner</Typography>
          </Box>
          <Tooltip title={isDark ? "Switch to light mode" : "Switch to dark mode"}>
            <IconButton onClick={colorMode.toggleColorMode} size="small" sx={{ color: "#c5ceea", bgcolor: "rgba(255,255,255,0.06)", "&:hover": { bgcolor: "rgba(255,255,255,0.12)" } }}>
              {isDark ? <LightModeOutlinedIcon fontSize="small" /> : <DarkModeOutlinedIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Stack>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => { setCurrent(emptyConversation()); setPage("chat"); }}
          sx={{ mb: 1, py: 1.1 }}
        >
          New conversation
        </Button>
        <Stack component="nav" spacing={0.5} sx={{ my: 2.5 }}>
          <Button
            startIcon={<ChatBubbleOutlinedIcon />}
            onClick={() => setPage("chat")}
            sx={{
              justifyContent: "flex-start",
              color: page === "chat" ? "#fff" : "#9daaca",
              bgcolor: page === "chat" ? "#242f52" : "transparent",
              "&:hover": { bgcolor: "#242f52", color: "#fff" },
            }}
          >
            Chat
          </Button>
          <Button
            startIcon={<HistoryEduIcon />}
            onClick={() => setPage("history")}
            sx={{
              justifyContent: "flex-start",
              color: page === "history" ? "#fff" : "#9daaca",
              bgcolor: page === "history" ? "#242f52" : "transparent",
              "&:hover": { bgcolor: "#242f52", color: "#fff" },
            }}
          >
            Travel history
          </Button>
        </Stack>
        <Typography sx={{ mx: 1, mb: 1, color: "#6e7c9f", fontSize: 10, letterSpacing: 1.5, fontWeight: 700 }}>
          RECENT CHATS
        </Typography>
        <ConversationList
          conversations={conversations}
          activeId={current.id}
          onSelect={(id) => {
            setPage("chat");
            fetch(`/api/conversations/${id}`).then((r) => r.json()).then((item) => setCurrent({ id: item.id, messages: item.messages, events: item.events || [] }));
          }}
          onDelete={deleteConversation}
        />
        <Divider sx={{ borderColor: "#293556", mt: "auto", pt: 2 }} />
        <Typography sx={{ pt: 2, px: 1, color: "#7380a1", fontSize: 12 }}>
          Agent 1–4 <Box component="span" sx={{ float: "right", color: "#5fd39a" }}>online</Box>
        </Typography>
      </Box>
      <Box component="main" sx={{ flex: 1, minWidth: 0 }}>
        {page === "history"
          ? <HistoryPage userId={userId} />
          : <ChatPage current={current} setCurrent={setCurrent} conversations={conversations} loadConversations={loadConversations} userId={userId} />}
      </Box>
    </Box>
  );
}

function Root() {
  const [mode, setMode] = useState(() => {
    try {
      return window.localStorage.getItem("trip-color-mode") || "light";
    } catch {
      return "light";
    }
  });
  const colorMode = useMemo(
    () => ({
      mode,
      toggleColorMode: () => setMode((prev) => {
        const next = prev === "light" ? "dark" : "light";
        try { window.localStorage.setItem("trip-color-mode", next); } catch { /* ignore */ }
        return next;
      }),
    }),
    [mode],
  );
  const theme = useMemo(() => createAppTheme(mode), [mode]);
  return (
    <ColorModeContext.Provider value={colorMode}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <App />
      </ThemeProvider>
    </ColorModeContext.Provider>
  );
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
