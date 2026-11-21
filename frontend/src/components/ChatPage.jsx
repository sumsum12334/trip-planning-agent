import { useEffect, useRef, useState, useMemo } from "react";
import { Box, Button, TextField } from "@mui/material";
import ChatIcon from "@mui/icons-material/Chat";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import SendIcon from "@mui/icons-material/Send";
import { buildChatMessages } from "../lib/chatMessages.js";
import { planBudgetItems, planFromEvents } from "../lib/planUtils.js";
import {
  effectiveReconsiderEnabled,
  fetchReconsiderDefault,
  readReconsiderOverride,
} from "../lib/reconsider.js";
import { readSseFrames } from "../lib/sse.js";
import { nextStepSuggestions, workflowState } from "../lib/workflow.js";
import { Activity } from "./Activity.jsx";
import { ChatMessages } from "./ChatMessages.jsx";
import { NextSteps } from "./NextSteps.jsx";
import { QuestionBox } from "./QuestionBox.jsx";
import { TripPlanCard, TripPlanPending } from "./TripPlanCard.jsx";

export function ChatPage({ current, setCurrent, loadConversations, userId }) {
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState("");
  const [retryText, setRetryText] = useState("");
  const [retryOption, setRetryOption] = useState("");
  const [answering, setAnswering] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [selectedOption, setSelectedOption] = useState("");
  const [chatMinimized, setChatMinimized] = useState(false);
  const [reconsiderServerDefault, setReconsiderServerDefault] = useState(true);
  const [reconsiderOverride] = useState(() => readReconsiderOverride());

  // Server default for the reconsider-after-edit prompt; a failed fetch
  // resolves to enabled without breaking the page.
  useEffect(() => {
    let cancelled = false;
    fetchReconsiderDefault().then((value) => {
      if (!cancelled) setReconsiderServerDefault(value);
    });
    return () => { cancelled = true; };
  }, []);

  const answerLockRef = useRef(false);
  const abortRef = useRef(null);
  const requestIdRef = useRef(null);
  const messagesRef = useRef(null);

  const latestPlanEvent = useMemo(
    () => planFromEvents(current.events, (plan) => Boolean(plan?.destination)),
    [current.events],
  );
  const latestPlan = latestPlanEvent?.data?.result || null;

  const pendingQuestionEvent = useMemo(() => {
    return [...current.events].reverse().find(
      (event) => event.data?.tool === "ask_user_question" && event.data?.result?.question && !event.data?.selected,
    );
  }, [current.events]);

  const messageItems = useMemo(
    () => buildChatMessages(current.messages, current.events),
    [current.messages, current.events],
  );

  const hasConversation = current.messages.length > 0;

  useEffect(() => { if (messagesRef.current) messagesRef.current.scrollTop = messagesRef.current.scrollHeight; }, [current.messages, current.events, latestPlan, chatMinimized]);

  function planContextFromEvents(events) {
    const event = planFromEvents(events, (plan) => Boolean(plan?.destination));
    if (!event) return null;
    const result = event.data.result;
    return {
      destination: result.destination,
      currency: result.currency,
      budget: result.budget ?? null,
      budget_items: planBudgetItems(result),
      days: result.days || [],
    };
  }

  async function sendMessage(event, retry = false, overrideText = null) {
    event?.preventDefault();
    if (streaming || answerLockRef.current) return;
    const text = (overrideText != null ? overrideText : retry ? retryText : message).trim();
    if (!text) return;
    setMessage(""); setRetryText(""); setRetryOption(""); setStatus("Working...");
    setChatMinimized(false);
    const controller = new AbortController();
    abortRef.current = controller;
    const requestId = `req-${crypto.randomUUID()}`;
    requestIdRef.current = requestId;
    setStreaming(true);
    const retryBase = retry && current.messages.at(-1)?.role === "assistant" ? current.messages.slice(0, -1) : current.messages;
    const context = retry ? retryBase : current.messages;
    const optimisticMessages = retry ? (retryBase.at(-1)?.role === "user" ? retryBase : [...retryBase, { role: "user", content: text }]) : [...current.messages, { role: "user", content: text }];
    const workingMessages = [...optimisticMessages, { role: "assistant", content: "Working...", reasoning: "" }];
    const optimisticEvents = [...current.events, { type: "agent", label: "Coordinator agent started", status: "running" }, { type: "model", label: "Model request queued", status: "running" }];
    setCurrent({ ...current, messages: workingMessages, events: optimisticEvents });
    let streamedText = "";
    let streamedReasoning = "";
    let streamEvents = [...current.events];
    let result = null;
    const renderPartial = () => setCurrent((previous) => ({ ...previous, messages: [...workingMessages.slice(0, -1), { role: "assistant", content: streamedText || "Working...", reasoning: streamedReasoning }], events: streamEvents }));
    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({ message: text, conversation: context, conversation_id: current.id, user_id: userId, request_id: requestId, plan_context: planContextFromEvents(current.events) }),
      });
      if (!response.ok) { setRetryText(text); setStatus("Request failed. You can retry the saved message."); return; }
      if (!response.body) { setRetryText(text); setStatus("Streaming is unavailable. Please retry."); return; }
      await readSseFrames(response, (payload) => {
        if (payload.kind === "event") { streamEvents = [...streamEvents, payload]; renderPartial(); }
        else if (payload.kind === "reasoning") { streamedReasoning += payload.text; renderPartial(); }
        else if (payload.kind === "content") { streamedText += payload.text; renderPartial(); }
        else if (payload.kind === "done") result = { ...payload, text: payload.text || streamedText, reasoning: payload.reasoning || streamedReasoning };
        else if (payload.kind === "error") setStatus(payload.message);
      });
      if (result) {
        const completedMessages = result.pending_question
          ? optimisticMessages
          : [...optimisticMessages, { role: "assistant", content: result.text, reasoning: result.reasoning || streamedReasoning }];
        const mergedEvents = [...current.events, ...(result.events || [])];
        setCurrent({ id: result.conversation_id || current.id, messages: completedMessages, events: mergedEvents });
        setStatus(
          result.pending_question
            ? "The assistant is waiting for your choice."
            : result.stopped
              ? "Stopped. Edit your message or ask something else."
              : result.stub ? "Local stub response" : `Model: ${result.model}`
        );
      } else {
        setRetryText(text);
        setStatus("The model stream ended without a response. You can retry.");
        setCurrent((previous) => ({
          ...previous,
          messages: [...workingMessages.slice(0, -1), { role: "assistant", content: streamedText || "[No response received. Please retry.]", reasoning: streamedReasoning }],
          events: streamEvents,
        }));
      }
    } catch (error) {
      if (error?.name === "AbortError") {
        setRetryText(text);
        setStatus("Stopped. Edit your message or ask something else.");
        setCurrent((previous) => ({
          ...previous,
          messages: [...workingMessages.slice(0, -1), { role: "assistant", content: streamedText || "[Stopped] Response stopped.", reasoning: streamedReasoning }],
          events: [...streamEvents, { type: "agent", label: "Stopped by user", status: "completed" }],
        }));
      } else {
        setRetryText(text);
        setStatus("Request failed. You can retry the saved message.");
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
      requestIdRef.current = null;
      await loadConversations();
    }
  }

  async function stopStreaming() {
    const requestId = requestIdRef.current;
    setStatus("Stopping...");
    if (requestId) {
      try {
        await fetch("/api/chat/stop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ request_id: requestId }),
        });
      } catch {
        /* The abort below still stops the local stream. */
      }
    }
    abortRef.current?.abort();
  }

  async function savePlanBudget(payload) {
    setCurrent((previous) => {
      const target = planFromEvents(previous.events, (plan) => Boolean(plan?.destination));
      if (!target) return previous;
      const result = target.data.result;
      const merged = { ...result };
      if (Array.isArray(payload.days) && payload.days.length) {
        const days = (result.days || []).map((day) => ({ ...day }));
        payload.days.forEach((updatedDay) => {
          const index = days.findIndex((day) => day.day === updatedDay.day);
          if (index >= 0) days[index] = { ...days[index], ...updatedDay };
          else days.push({ ...updatedDay });
        });
        merged.days = days.sort((a, b) => a.day - b.day);
      }
      if (Array.isArray(payload.budget_items)) merged.budget_items = payload.budget_items;
      if ("budget" in payload) merged.budget = payload.budget;
      if (payload.currency) merged.currency = payload.currency;
      if ("start_date" in payload) merged.start_date = payload.start_date || null;
      return {
        ...previous,
        events: previous.events.map((event) => event === target
          ? { ...event, data: { ...event.data, result: merged } }
          : event),
      };
    });
    if (!current.id) return;
    try {
      await fetch(`/api/conversations/${current.id}/trip-plan`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch {
      /* The local edit still applies for the current session. */
    }
  }

  const questionEvent = [...current.events].reverse().find(
    (event) => event.data?.tool === "ask_user_question" && event.data?.result?.question,
  );
  const pendingEvent = [...current.events].reverse().find(
    (event) => event.data?.tool === "ask_user_question" && event.data?.result?.question && !event.data?.selected,
  );
  const activeQuestionEvent = pendingEvent || questionEvent;
  // Keep the card mounted across incremental `set_trip_day` plan events so the
  // plan renders part by part instead of remounting on every tool call.
  const planKey = current.id || "trip-plan";
  const workflow = workflowState(current.events, selectedOption ? null : pendingEvent, status);
  const suggestions = nextStepSuggestions(latestPlan, current.messages, Boolean(pendingEvent), streaming || answering);
  const busy = streaming || answering;
  // The wide plan layout is used whenever a plan exists or a turn is running
  // (so the blank plan shell appears the moment a message is sent).
  const showPlanArea = Boolean(latestPlan) || busy;
  const reconsiderEnabled = effectiveReconsiderEnabled(reconsiderServerDefault, reconsiderOverride);

  // Sends the reconsideration request through the normal chat flow, including
  // the concrete plan changes (actual values) so the agent knows what to review.
  function handleReconsider(changes) {
    const details = (Array.isArray(changes) ? changes : [])
      .filter(Boolean)
      .map((change) => `- ${change}`)
      .join("\n");
    if (!details) return;
    sendMessage(
      null,
      false,
      `I adjusted the trip plan directly. The changes were:\n${details}\nPlease reconsider the plan and update it if needed.`,
    );
  }

  async function answerQuestion(option, custom = false) {
    if (answerLockRef.current || streaming) return;
    answerLockRef.current = true;
    setAnswering(true);
    setSelectedOption(option);
    setStatus("Sending your choice to the assistant...");
    setRetryOption("");
    const controller = new AbortController();
    abortRef.current = controller;
    const requestId = `req-${crypto.randomUUID()}`;
    requestIdRef.current = requestId;
    const questionIndex = current.events.indexOf(activeQuestionEvent);
    const markSelected = (list, eventStatus) => list.map((item, index) => index === questionIndex
      ? { ...item, data: { ...item.data, selected: option }, detail: `Answer selected: ${option}`, status: eventStatus }
      : item);
    const optimisticEvents = markSelected(current.events, "running");
    const optimisticMessages = current.messages.at(-1)?.role === "user" && current.messages.at(-1)?.content === option
      ? current.messages
      : [...current.messages, { role: "user", content: option }];
    const workingMessages = [...optimisticMessages, { role: "assistant", content: "Working...", reasoning: "" }];
    setCurrent((previous) => ({ ...previous, messages: workingMessages, events: optimisticEvents }));
    let streamedText = "";
    let streamedReasoning = "";
    let streamEvents = optimisticEvents;
    let result = null;
    const renderPartial = () => setCurrent((previous) => ({
      ...previous,
      messages: [...optimisticMessages, { role: "assistant", content: streamedText || "Working...", reasoning: streamedReasoning }],
      events: streamEvents,
    }));
    try {
      const response = await fetch("/api/chat/question/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          message: option,
          conversation_id: current.id,
          user_id: userId,
          custom,
          request_id: requestId,
          plan_context: planContextFromEvents(current.events),
        }),
      });
      if (!response.ok) {
        let detail = "The assistant could not continue.";
        try {
          const payload = await response.json();
          detail = typeof payload.detail === "string" ? payload.detail : (payload.detail?.message || detail);
        } catch { /* retain safe fallback */ }
        throw new Error(detail);
      }
      await readSseFrames(response, (payload) => {
        if (payload.kind === "event") { streamEvents = [...streamEvents, payload]; renderPartial(); }
        else if (payload.kind === "reasoning") { streamedReasoning += payload.text; renderPartial(); }
        else if (payload.kind === "content") { streamedText += payload.text; renderPartial(); }
        else if (payload.kind === "done") result = { ...payload, text: payload.text || streamedText, reasoning: payload.reasoning || streamedReasoning };
        else if (payload.kind === "error") setStatus(payload.message);
      });
      if (!result) throw new Error("The continuation ended without a response. You can retry.");
      const answeredEvents = markSelected(optimisticEvents, "completed");
      const continuedEvents = (result.events || []).filter((event) => event.label !== "Answer recorded");
      const completedMessages = result.pending_question
        ? optimisticMessages
        : [...optimisticMessages, { role: "assistant", content: result.text, reasoning: result.reasoning || "" }];
      setCurrent({
        id: result.conversation_id || current.id,
        messages: completedMessages,
        events: [...answeredEvents, ...continuedEvents],
      });
      setStatus(
        result.pending_question
          ? "The assistant is waiting for your choice."
          : result.stopped
            ? "Stopped. Edit your choice or ask something else."
            : result.stub ? "Local stub response" : `Model: ${result.model}`
      );
      setSelectedOption("");
    } catch (error) {
      if (error?.name === "AbortError") {
        setStatus("Stopped. Edit your choice or ask something else.");
        setCurrent((previous) => ({
          ...previous,
          messages: [...optimisticMessages, { role: "assistant", content: streamedText || "[Stopped] Response stopped.", reasoning: streamedReasoning }],
          events: [...streamEvents, { type: "agent", label: "Stopped by user", status: "completed" }],
        }));
      } else {
        setRetryOption({ value: option, custom });
        setStatus(`Continuation failed: ${error?.message || "The assistant could not continue."}`);
        setCurrent((previous) => ({ ...previous, messages: optimisticMessages, events: streamEvents }));
      }
    } finally {
      answerLockRef.current = false;
      setAnswering(false);
      abortRef.current = null;
      requestIdRef.current = null;
      await loadConversations();
    }
  }

  function renderComposer(inline = false) {
    return (
      <Box className={`composer${inline ? " inline-composer" : ""}`} component="form" onSubmit={sendMessage} sx={{ display: "flex", flexDirection: "column", gap: 1.25, alignItems: "stretch", p: 2.5, borderTop: "1px solid #edf0f6" }}>
        <TextField
          multiline
          minRows={2}
          maxRows={5}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Plan a 3-day trip to Kyoto for $800..."
        />
        <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
          {busy
            ? <Button className="stop-button" type="button" variant="contained" color="error" onClick={stopStreaming}>Stop</Button>
            : <Button className="send-button" type="submit" variant="contained" endIcon={<SendIcon />}>Send</Button>}
        </Box>
      </Box>
    );
  }

  function renderComposerFooter() {
    return (
      <div className="composer-footer">
        <span>{status || "Markdown supported"}</span>
        {retryText && <Button className="retry" size="small" color="warning" variant="outlined" disabled={streaming} onClick={(event) => sendMessage(event, true)}>Retry</Button>}
      </div>
    );
  }

  // The chat lives in a fixed floating box in the bottom-right corner once the
  // conversation has started; the landing page keeps its centered composer.
  const chatPanel = hasConversation ? (
    <aside
      className={`chat-panel floating${chatMinimized ? " minimized" : ""}`}
      aria-label="Trip assistant"
    >
      <div
        className="chat-panel-header"
        onClick={chatMinimized ? () => setChatMinimized(false) : undefined}
      >
        <div className="chat-panel-title">
          <p className="eyebrow">AI TRIP COMPANION</p>
          <h2 className="chat-title">Plan something memorable.</h2>
        </div>
        <button
          type="button"
          className="chat-panel-toggle"
          onClick={() => setChatMinimized((value) => !value)}
          aria-expanded={!chatMinimized}
          aria-label={chatMinimized ? "Open chat panel" : "Minimize chat panel"}
        >
          {chatMinimized ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
        </button>
      </div>
      {!chatMinimized ? (
        <>
          <Box className="messages chat-panel-messages" ref={messagesRef} sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 0.5, overflow: "auto", padding: "16px 18px 8px" }}>
            <ChatMessages items={messageItems} />
          </Box>
          {pendingQuestionEvent && (
            <div className="question-alert">
              <span className="question-alert-icon">⚠</span>
              <span className="question-alert-text">The assistant is waiting for your choice.</span>
            </div>
          )}
          <div className={`workflow-status ${workflow.className}`} aria-live="polite" aria-busy={workflow.className === "working"}><span>{workflow.icon}</span><strong>{workflow.label}</strong>{workflow.detail ? <small>{workflow.detail}</small> : null}</div>
          {(pendingEvent || retryOption) && <QuestionBox event={activeQuestionEvent} onOption={answerQuestion} disabled={answering || streaming} retryOption={retryOption} selectedOption={selectedOption} />}
          <NextSteps suggestions={suggestions} onSelect={(text) => sendMessage(null, false, text)} disabled={busy} />
          {renderComposer()}
          {renderComposerFooter()}
        </>
      ) : (
        <div className={`chat-panel-collapsed-status ${workflow.className}`}>
          <span className="chat-panel-collapsed-icon">
            {pendingEvent ? "!" : <ChatIcon fontSize="small" />}
          </span>
          <small>
            {pendingEvent
              ? `Waiting for your choice: ${activeQuestionEvent?.data?.result?.question || ""}`
              : streaming
                ? (status || workflow.label)
                : workflow.label}
          </small>
          {pendingEvent && <span className="chat-panel-collapsed-badge" aria-hidden="true" />}
        </div>
      )}
    </aside>
  ) : null;

  return (
    <section className="page chat-page">
      <div className={`chat-workspace-new${showPlanArea ? " has-plan" : ""}`}>
        <main className="main-content">
          {latestPlan ? (
            <TripPlanCard
              key={planKey}
              plan={latestPlan}
              onSaveBudget={savePlanBudget}
              onReconsider={handleReconsider}
              reconsiderEnabled={reconsiderEnabled}
              busy={busy}
            />
          ) : busy ? (
            <TripPlanPending />
          ) : hasConversation ? (
            <div className="working-area">
              <Activity events={current.events} />
            </div>
          ) : (
            <div className="welcome-chat-area">
              <div className="welcome-content">
                <span className="welcome-icon">✦</span>
                <h2>Where will you go next?</h2>
                <p>Ask me to plan an itinerary, search accommodation, check weather, or estimate transport.</p>
                <NextSteps suggestions={suggestions} onSelect={(text) => sendMessage(null, false, text)} disabled={busy} />
                <div className="inline-chat-box">
                  {renderComposer(true)}
                  {renderComposerFooter()}
                </div>
              </div>
            </div>
          )}
        </main>

        {showPlanArea && current.events.length > 0 && (
          <aside className="live-workflow-sidebar" aria-label="Live workflow">
            <Activity events={current.events} />
          </aside>
        )}
      </div>
      {chatPanel}
    </section>
  );
}
