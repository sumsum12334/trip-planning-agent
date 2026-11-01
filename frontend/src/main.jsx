import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./styles.css";

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
    <div className="question-options">
      {options.map((option) => <button type="button" key={option} disabled={disabled || Boolean(selected)} className={selected === option ? "selected" : ""} onClick={() => onOption(option)}>{selected === option ? "Selected" : option}</button>)}
    </div>
    {retryOption && <button className="question-retry" type="button" onClick={() => onOption(retryOption)}>↻ Retry sending “{retryOption}”</button>}
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
  return <div className="conversation-list">
    {conversations.map((item) => <div className="conversation-row" key={item.id}>
      <button className={`conversation ${activeId === item.id ? "active" : ""}`} onClick={() => onSelect(item.id)}>
        <span>▤</span>{item.title}
      </button>
      <button className="icon-button danger" title="Delete conversation" onClick={() => onDelete(item.id)}>×</button>
    </div>)}
  </div>;
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
  return <details className="settings panel"><summary>⚙ Model settings</summary>
    <p className="muted">Settings apply to this running backend. API keys are never displayed.</p>
    <label>Endpoint URL<input value={settings.endpoint_url || ""} onChange={(event) => setSettings({ ...settings, endpoint_url: event.target.value })} /></label>
    <label>Model<input value={settings.qwen_model || ""} onChange={(event) => setSettings({ ...settings, qwen_model: event.target.value })} /></label>
    <label>API key<input type="password" autoComplete="off" placeholder="Leave blank to keep current key" value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></label>
    <button onClick={save}>Save settings</button> <small className="muted">{status}</small>
  </details>;
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
      <form className="panel history-form" onSubmit={add}><div className="section-title"><span>＋</span><h2>Add a place</h2></div>
        <label>Country<input value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })} placeholder="Hong Kong" /></label>
        <label>City<input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} placeholder="Hong Kong" /></label>
        <label>Location visited<input required value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} placeholder="Victoria Peak" /></label>
        <button type="submit">Save visit</button>{status && <small className="form-status">{status}</small>}
      </form>
      <div className="panel history-list"><div className="section-title"><span>▣</span><h2>Visited places</h2><b>{entries.length}</b></div>
        {!entries.length && <div className="empty-state"><span>✈</span><p>No places saved yet.</p><small>Add a visit or tell the assistant you have been there before.</small></div>}
        {entries.map((entry) => <div className="history-entry" key={entry.id}><span className="place-pin">●</span><div><strong>{entry.location}</strong><p>{[entry.city, entry.country].filter(Boolean).join(", ") || "Location details not specified"}</p></div><button className="icon-button danger" title="Remove visit" onClick={() => remove(entry.id)}>⌫</button></div>)}
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
    <div className="chat-workspace"><section className="panel chat-panel"><div className="messages" ref={messagesRef}>
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
                <div className="message assistant question-message" key={`question-${index}`}>
                  <div className="avatar">?</div>
                  <div className="bubble"><strong>Question</strong><p>{question.data.result.question}</p><small className="question-answer">Answer: {item.content}</small></div>
                </div>,
              );
            }
          }
          output.push(<div className={`message ${item.role}`} key={`${item.role}-${index}`}><div className="avatar">{item.role === "assistant" ? "✦" : "You"}</div><div className="bubble">{item.reasoning && <details className="reasoning"><summary>Model reasoning</summary><ReactMarkdown remarkPlugins={[remarkGfm]}>{item.reasoning}</ReactMarkdown></details>}{item.role === "assistant" ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.content}</ReactMarkdown> : item.content}</div></div>);
        });
        questions.filter((event) => !renderedQuestions.has(event)).forEach((event, index) => output.push(<div className="message assistant question-message" key={`pending-question-${index}`}><div className="avatar">?</div><div className="bubble"><strong>Question</strong><p>{event.data.result.question}</p>{event.data.selected && <small className="question-answer">Answer: {event.data.selected}</small>}</div></div>));
        return output;
      })()}
    </div>
      <div className={`workflow-status ${workflow.className}`}><span>{workflow.icon}</span><strong>{workflow.label}</strong><small>{workflow.className === "waiting" ? "Choose an option below." : workflow.className === "working" ? "The assistant is processing your request." : ""}</small></div>
      <QuestionBox event={questionEvent} onOption={answerQuestion} disabled={answering} retryOption={retryOption} selectedOption={selectedOption} />
      <form className="composer" onSubmit={sendMessage}><textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Plan a 3-day trip to Kyoto for $800..." /><button className="send-button" type="submit">Send <span>➜</span></button></form>
      <div className="composer-footer"><span>{status || "Markdown supported"}</span>{retryText && <button className="retry" onClick={(event) => sendMessage(event, true)}>↻ Retry</button>}</div>
    </section><Activity events={current.events} /></div><ModelSettings />
  </section>;
}

function App() {
  const [page, setPage] = useState("chat"); const [conversations, setConversations] = useState([]); const [current, setCurrent] = useState(emptyConversation); const userId = getUserId();
  async function loadConversations() { const response = await fetch("/api/conversations"); if (response.ok) setConversations(await response.json()); }
  useEffect(() => { loadConversations(); }, []);
  async function deleteConversation(id) { if (!window.confirm("Delete this conversation?")) return; const response = await fetch(`/api/conversations/${id}`, { method: "DELETE" }); if (response.ok) { if (current.id === id) setCurrent(emptyConversation()); await loadConversations(); } }
  return <div className="app"><aside><div className="brand"><span className="brand-mark">✦</span><div><strong>Tripwise</strong><small>AI travel planner</small></div></div>
    <button className="new-button" onClick={() => { setCurrent(emptyConversation()); setPage("chat"); }}>＋ New conversation</button>
    <nav><button className={page === "chat" ? "nav-active" : ""} onClick={() => setPage("chat")}><span>◉</span>Chat</button><button className={page === "history" ? "nav-active" : ""} onClick={() => setPage("history")}><span>⌖</span>Travel history</button></nav>
    <div className="sidebar-label">RECENT CHATS</div><ConversationList conversations={conversations} activeId={current.id} onSelect={(id) => { setPage("chat"); fetch(`/api/conversations/${id}`).then((r) => r.json()).then((item) => setCurrent({ id: item.id, messages: item.messages, events: item.events || [] })); }} onDelete={deleteConversation} />
    <div className="sidebar-footer">Agent 1–4 <span>● online</span></div></aside>
    <main>{page === "history" ? <HistoryPage userId={userId} /> : <ChatPage current={current} setCurrent={setCurrent} conversations={conversations} loadConversations={loadConversations} userId={userId} />}</main>
  </div>;
}

createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);
