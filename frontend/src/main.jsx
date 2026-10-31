import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./styles.css";

const emptyConversation = () => ({ id: null, messages: [], events: [] });

function Activity({ events }) {
  if (!events.length) return null;
  return (
    <details className="activity" open={false}>
      <summary>Agent activity ({events.length})</summary>
      <div className="activity-items">
      {events.map((event, index) => (
        <div className={`event ${event.status}`} key={`${event.label}-${index}`}>
          {event.detail ? `${event.label}: ${event.detail}` : event.label}
        </div>
      ))}
      </div>
    </details>
  );
}

function ConversationList({ conversations, activeId, onSelect, onDelete }) {
  return (
    <div className="conversation-list">
      {conversations.map((item) => (
        <div className="conversation-row" key={item.id}>
          <button className={`conversation ${activeId === item.id ? "active" : ""}`} onClick={() => onSelect(item.id)}>
            {item.title}
          </button>
          <button className="delete-conversation" title="Delete conversation" onClick={() => onDelete(item.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

function ModelSettings() {
  const [settings, setSettings] = useState({ endpoint_url: "", qwen_model: "" });
  const [apiKey, setApiKey] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    fetch("/api/settings").then((response) => response.json()).then(setSettings);
  }, []);

  async function save() {
    setStatus("Saving...");
    const response = await fetch("/api/settings/model", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint_url: settings.endpoint_url, model: settings.qwen_model, api_key: apiKey || null }),
    });
    if (!response.ok) {
      setStatus(`Save failed: ${await response.text()}`);
      return;
    }
    const result = await response.json();
    setApiKey("");
    setSettings({ ...settings, endpoint_url: result.endpoint_url, qwen_model: result.model });
    setStatus(result.api_key_configured ? "Saved; API key configured." : "Saved; API key not configured.");
  }

  return (
    <details className="settings panel">
      <summary>Model settings</summary>
      <p className="muted">Settings apply to this running backend process. API keys are never displayed.</p>
      <label>Endpoint URL<input value={settings.endpoint_url || ""} onChange={(event) => setSettings({ ...settings, endpoint_url: event.target.value })} /></label>
      <label>Model<input value={settings.qwen_model || ""} onChange={(event) => setSettings({ ...settings, qwen_model: event.target.value })} /></label>
      <label>API key<input type="password" autoComplete="off" placeholder="Leave blank to keep current key" value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></label>
      <button onClick={save}>Save settings</button> <small className="muted">{status}</small>
    </details>
  );
}

function App() {
  const [conversations, setConversations] = useState([]);
  const [current, setCurrent] = useState(emptyConversation);
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState("");
  const [retryText, setRetryText] = useState("");
  const messagesRef = useRef(null);

  useEffect(() => {
    const messages = messagesRef.current;
    if (messages) messages.scrollTop = messages.scrollHeight;
  }, [current.messages, current.events]);

  async function loadConversations() {
    const response = await fetch("/api/conversations");
    if (response.ok) setConversations(await response.json());
  }

  useEffect(() => { loadConversations(); }, []);

  async function selectConversation(id) {
    const response = await fetch(`/api/conversations/${id}`);
    if (response.ok) {
      const item = await response.json();
      setCurrent({ id: item.id, messages: item.messages, events: item.events || [] });
      const lastMessage = item.messages[item.messages.length - 1];
      const previousMessage = item.messages[item.messages.length - 2];
      if (
        lastMessage?.role === "assistant" &&
        !lastMessage.content &&
        previousMessage?.role === "user"
      ) {
        setRetryText(previousMessage.content);
        setStatus("The previous response was incomplete. You can retry it.");
      } else {
        setRetryText("");
        setStatus("");
      }
    }
  }

  async function deleteConversation(id) {
    if (!window.confirm("Delete this conversation?")) return;
    const response = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
    if (response.ok) {
      if (current.id === id) setCurrent(emptyConversation());
      await loadConversations();
    }
  }

  async function sendMessage(event, retry = false) {
    event?.preventDefault();
    const text = (retry ? retryText : message).trim();
    if (!text) return;
    setMessage("");
    setRetryText("");
    setStatus("Working...");
    const retryBase =
      retry && current.messages.at(-1)?.role === "assistant"
        ? current.messages.slice(0, -1)
        : current.messages;
    const context = retry ? retryBase : current.messages;
    const optimisticMessages = retry
      ? retryBase.at(-1)?.role === "user"
        ? retryBase
        : [...retryBase, { role: "user", content: text }]
      : [...current.messages, { role: "user", content: text }];
    const workingMessages = [...optimisticMessages, { role: "assistant", content: "Working...", reasoning: "" }];
    const optimisticEvents = [
      ...current.events,
      { type: "agent", label: "Coordinator agent started", status: "running" },
      { type: "model", label: "Model is thinking...", status: "running" },
    ];
    setCurrent({
      ...current,
      messages: workingMessages,
      events: optimisticEvents,
    });
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, conversation: context, conversation_id: current.id }),
    });
    if (!response.ok) {
      let detail = {};
      try { detail = (await response.json()).detail || {}; } catch { detail = {}; }
      const savedId = detail.conversation_id || current.id;
      setCurrent({
        ...current,
        id: savedId,
        messages: workingMessages,
        events: [
          ...optimisticEvents,
          { type: "model", label: detail.message || "Model request failed", status: "error" },
        ],
      });
      setRetryText(text);
      setStatus(detail.message || "Request failed. You can retry the saved message.");
      return;
    }
    if (!response.body) {
      setStatus("Streaming is unavailable. Please retry.");
      setRetryText(text);
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let streamedText = "";
    let streamedReasoning = "";
    let result = null;
    let streamEvents = [...optimisticEvents];
    let interrupted = false;
    const updateWorking = (nextEvents = streamEvents) => {
      setCurrent((previous) => ({
        ...previous,
        messages: [
          ...workingMessages.slice(0, -1),
          {
            role: "assistant",
            content: streamedText || (interrupted ? "The model response was interrupted. Please retry." : "Working..."),
            reasoning: streamedReasoning,
          },
        ],
        events: nextEvents,
      }));
    };
    const handleStreamFailure = (error) => {
      interrupted = true;
      const message = `The model stream was interrupted${error ? `: ${error.message}` : "."} You can retry.`;
      const failureEvent = { type: "model", label: "Model stream interrupted", detail: message, status: "error" };
      streamEvents = [...streamEvents, failureEvent];
      updateWorking(streamEvents);
      setRetryText(text);
      setStatus(message);
    };
    const processFrame = (frame) => {
      const line = frame.split("\n").find((item) => item.startsWith("data: "));
      if (!line) return;
      const payload = JSON.parse(line.slice(6));
      if (payload.kind === "event") {
        streamEvents = [...streamEvents, payload];
        updateWorking();
      } else if (payload.kind === "reasoning") {
        streamedReasoning += payload.text;
        updateWorking();
      } else if (payload.kind === "content") {
        streamedText += payload.text;
        updateWorking();
      } else if (payload.kind === "done") {
        result = { ...payload, text: payload.text || streamedText, reasoning: payload.reasoning || streamedReasoning };
      } else if (payload.kind === "error") {
        handleStreamFailure(new Error(payload.message));
      }
    };
    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";
        frames.forEach(processFrame);
        if (done && buffer.trim()) processFrame(buffer);
        if (done) break;
      }
    } catch (error) {
      handleStreamFailure(error);
    }
    if (result) {
      setCurrent({
        id: result.conversation_id,
        messages: [
          ...optimisticMessages,
          { role: "assistant", content: result.text, reasoning: result.reasoning || streamedReasoning },
        ],
        events: result.events,
      });
      setStatus(result.stub ? "Local stub response" : `Model: ${result.model}`);
    }
    await loadConversations();
  }

  return (
    <div className="app">
      <aside>
        <button onClick={() => setCurrent(emptyConversation())}>＋ New conversation</button>
        <h3>Conversations</h3>
        <ConversationList conversations={conversations} activeId={current.id} onSelect={selectConversation} onDelete={deleteConversation} />
      </aside>
      <main>
        <h1>Trip Planner</h1>
        <section className="panel chat-panel">
          <div className="messages" ref={messagesRef}>
            {!current.messages.length && <p className="muted">Ask for destinations, itineraries, budgets, or travel tips.</p>}
            {current.messages.map((item, index) => (
              <div className={`message ${item.role}`} key={`${item.role}-${index}`}>
                {item.reasoning && (
                  <details className="reasoning">
                    <summary>Model reasoning</summary>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.reasoning}</ReactMarkdown>
                  </details>
                )}
                {item.role === "assistant" ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.content}</ReactMarkdown>
                ) : item.content}
              </div>
            ))}
          </div>
          <Activity events={current.events} />
          <form onSubmit={sendMessage}>
            <label>Message<textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Plan a 3-day trip to Kyoto for $800..." /></label>
            <button type="submit">Send</button>{" "}
            {retryText && <button type="button" className="retry" onClick={(event) => sendMessage(event, true)}>Retry</button>}{" "}
            <small>{status}</small>
          </form>
        </section>
        <ModelSettings />
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);
