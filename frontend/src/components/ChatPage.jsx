import { useEffect, useLayoutEffect, useRef, useState, useCallback, useMemo } from "react";
import { Box, Button, Stack, TextField, Typography, IconButton, Tooltip, Fab, Dialog, DialogTitle, DialogContent } from "@mui/material";
import SendIcon from "@mui/icons-material/Send";
import DragIndicatorIcon from "@mui/icons-material/DragIndicator";
import MinimizeIcon from "@mui/icons-material/Minimize";
import MaximizeIcon from "@mui/icons-material/Maximize";
import CloseIcon from "@mui/icons-material/Close";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import { planBudgetItems, planFromEvents } from "../lib/planUtils.js";
import { readSseFrames } from "../lib/sse.js";
import { nextStepSuggestions, workflowState } from "../lib/workflow.js";
import { Activity } from "./Activity.jsx";
import { MessageBubble } from "./MessageBubble.jsx";
import { NextSteps } from "./NextSteps.jsx";
import { QuestionBox } from "./QuestionBox.jsx";
import { TripPlanCard } from "./TripPlanCard.jsx";

export function ChatPage({ current, setCurrent, loadConversations, userId }) {
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState("");
  const [retryText, setRetryText] = useState("");
  const [retryOption, setRetryOption] = useState("");
  const [answering, setAnswering] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [selectedOption, setSelectedOption] = useState("");
  const [planCollapsed] = useState(false);
  // Floating chat panel - always open by default at bottom right
  const [chatPanelOpen, setChatPanelOpen] = useState(true);
  const [chatPanelMinimized, setChatPanelMinimized] = useState(false);
  const [chatPanelPosition, setChatPanelPosition] = useState(() => {
    if (typeof window !== "undefined") {
      return {
        x: Math.max(24, window.innerWidth - 480 - 24),
        y: Math.max(24, window.innerHeight - 600 - 88 - 24),
      };
    }
    return { x: 24, y: 24 };
  });
  const [chatPanelSize, setChatPanelSize] = useState({ width: 480, height: 600 });
  const [isDragging, setIsDragging] = useState(false);

  const answerLockRef = useRef(false);
  const abortRef = useRef(null);
  const requestIdRef = useRef(null);
  const messagesRef = useRef(null);
  const chatPanelRef = useRef(null);
  const dragRef = useRef({ active: false, startX: 0, startY: 0, startLeft: 0, startTop: 0 });

  // Compute latestPlan early
  const latestPlanEvent = useMemo(() => planFromEvents(current.events), [current.events]);
  const latestPlan = latestPlanEvent?.data?.result || null;

  // Check if there's a pending question needing attention
  const pendingQuestionEvent = useMemo(() => {
    return [...current.events].reverse().find(
      (event) => event.data?.tool === "ask_user_question" && event.data?.result?.question && !event.data?.selected,
    );
  }, [current.events]);

  useEffect(() => { if (messagesRef.current) messagesRef.current.scrollTop = messagesRef.current.scrollHeight; }, [current.messages, current.events]);

  // Auto-scroll floating panel messages
  useEffect(() => {
    if (chatPanelRef.current && !chatPanelMinimized && chatPanelOpen) {
      const panel = chatPanelRef.current;
      const items = panel.querySelector('.activity-items') || panel.querySelector('.messages');
      if (items) items.scrollTop = items.scrollHeight;
    }
  }, [current.events, latestPlan, chatPanelMinimized, chatPanelOpen]);

  const handleDragMove = useCallback((e) => {
    if (!dragRef.current.active) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    setChatPanelPosition({
      x: Math.max(0, dragRef.current.startLeft + dx),
      y: Math.max(0, dragRef.current.startTop + dy),
    });
  }, []);

  const handleDragEndRef = useRef(null);

  const handleDragEnd = useCallback(() => {
    if (handleDragEndRef.current) handleDragEndRef.current();
  }, []);

  useLayoutEffect(() => {
    handleDragEndRef.current = () => {
      setIsDragging(false);
      dragRef.current.active = false;
      document.removeEventListener('mousemove', handleDragMove);
      document.removeEventListener('mouseup', handleDragEndRef.current);
    };
  }, [handleDragMove]);

  const handleDragStart = useCallback((e) => {
    if (e.target.closest('button, input, textarea, [role="button"]')) return;
    setIsDragging(true);
    dragRef.current = {
      active: true,
      startX: e.clientX,
      startY: e.clientY,
      startLeft: chatPanelPosition.x,
      startTop: chatPanelPosition.y,
    };
    document.addEventListener('mousemove', handleDragMove);
    document.addEventListener('mouseup', handleDragEnd);
    e.preventDefault();
  }, [chatPanelPosition, handleDragMove, handleDragEnd]);

  const handleResize = useCallback((e, direction) => {
    e.stopPropagation();
    const startX = e.clientX;
    const startY = e.clientY;
    const startWidth = chatPanelSize.width;
    const startHeight = chatPanelSize.height;

    const doResize = (moveEvent) => {
      let newWidth = startWidth;
      let newHeight = startHeight;
      if (direction.includes('e')) newWidth = Math.max(320, startWidth + (moveEvent.clientX - startX));
      if (direction.includes('w')) newWidth = Math.max(320, startWidth - (moveEvent.clientX - startX));
      if (direction.includes('s')) newHeight = Math.max(300, startHeight + (moveEvent.clientY - startY));
      if (direction.includes('n')) newHeight = Math.max(300, startHeight - (moveEvent.clientY - startY));
      setChatPanelSize({ width: newWidth, height: newHeight });
    };

    const stopResize = () => {
      document.removeEventListener('mousemove', doResize);
      document.removeEventListener('mouseup', stopResize);
    };

    document.addEventListener('mousemove', doResize);
    document.addEventListener('mouseup', stopResize);
  }, [chatPanelSize]);

  function planContextFromEvents(events) {
    const event = planFromEvents(events);
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
      const target = planFromEvents(previous.events);
      if (!target) return previous;
      const result = target.data.result;
      let days = (result.days || []).map((day) => ({ ...day }));
      if (Array.isArray(payload.days) && payload.days.length) {
        payload.days.forEach((updatedDay) => {
          const index = days.findIndex((day) => day.day === updatedDay.day);
          if (index >= 0) days[index] = { ...days[index], ...updatedDay };
          else days.push({ ...updatedDay });
        });
        days.sort((a, b) => a.day - b.day);
      } else {
        const dayBudgetMap = new Map((payload.day_budgets || []).map((entry) => [entry.day, entry.amount]));
        const dayItemMap = new Map();
        (payload.day_items || []).forEach((entry) => {
          const list = dayItemMap.get(entry.day) || [];
          list.push({ category: entry.category, amount: entry.amount, currency: payload.currency || result.currency || "" });
          dayItemMap.set(entry.day, list);
        });
        days = days.map((day) => ({
          ...day,
          budget: dayBudgetMap.has(day.day) ? dayBudgetMap.get(day.day) : day.budget,
          budget_items: dayItemMap.has(day.day) ? dayItemMap.get(day.day) : day.budget_items,
        }));
      }
      const merged = { ...result, days };
      if ("budget" in payload) merged.budget = payload.budget;
      if (payload.currency) merged.currency = payload.currency;
      if (payload.mode !== "day" && Array.isArray(payload.budget_items)) merged.budget_items = payload.budget_items;
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
  const planKey = latestPlanEvent ? current.events.indexOf(latestPlanEvent) : -1;
  const workflow = workflowState(current.events, selectedOption ? null : pendingEvent, status);
  const suggestions = nextStepSuggestions(latestPlan, current.messages, Boolean(pendingEvent), streaming || answering);

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

  // Render the floating chat panel - always visible at bottom right
  const renderFloatingChatPanel = () => {
    if (!chatPanelOpen) return null;

    return (
      <section
        className={`panel chat-panel floating ${chatPanelMinimized ? "minimized" : ""} ${isDragging ? "dragging" : ""}`}
        ref={chatPanelRef}
        style={
          isDragging
            ? { left: chatPanelPosition.x, top: chatPanelPosition.y, bottom: "auto", right: "auto", width: chatPanelSize.width, height: chatPanelSize.height }
            : { width: chatPanelSize.width, height: chatPanelSize.height }
        }
      >
        <div className="floating-header" onMouseDown={handleDragStart}>
          <Tooltip title="Drag to move">
            <span className="drag-handle"><DragIndicatorIcon fontSize="small" /></span>
          </Tooltip>
          <div className="floating-title">
            <p className="eyebrow">AI TRIP COMPANION</p>
            <h1 className="chat-title">Plan something memorable.</h1>
          </div>
          <div className="floating-controls">
            <Tooltip title={chatPanelMinimized ? "Expand" : "Minimize"}>
              <IconButton size="small" onClick={() => setChatPanelMinimized(!chatPanelMinimized)} aria-label={chatPanelMinimized ? "Expand chat" : "Minimize chat"}>
                {chatPanelMinimized ? <MaximizeIcon fontSize="small" /> : <MinimizeIcon fontSize="small" />}
              </IconButton>
            </Tooltip>
            <Tooltip title="Close chat">
              <IconButton size="small" onClick={() => { setChatPanelOpen(false); setChatPanelMinimized(false); }} aria-label="Close chat">
                <CloseIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </div>
        </div>
        {!chatPanelMinimized && (
          <>
            <Box className="messages" ref={messagesRef} sx={{ display: "flex", flexDirection: "column", gap: 0.5, maxHeight: "calc(100% - 280px)", overflow: "auto" }}>
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
            {pendingQuestionEvent && (
              <div className="question-alert">
                <span className="question-alert-icon">⚠</span>
                <span className="question-alert-text">The assistant is waiting for your choice.</span>
              </div>
            )}
            <div className={`workflow-status ${workflow.className}`}><span>{workflow.icon}</span><strong>{workflow.label}</strong><small>{workflow.className === "waiting" ? "Choose an option below." : workflow.className === "working" ? "The assistant is processing your request." : ""}</small></div>
            {(pendingEvent || retryOption) && <QuestionBox event={activeQuestionEvent} onOption={answerQuestion} disabled={answering} retryOption={retryOption} selectedOption={selectedOption} />}
            <NextSteps suggestions={suggestions} onSelect={(text) => sendMessage(null, false, text)} disabled={streaming || answering} />
            <Box className="composer" component="form" onSubmit={sendMessage} sx={{ display: "flex", flexDirection: "column", gap: 1.25, alignItems: "stretch", p: 2.5, borderTop: "1px solid #edf0f6" }}>
              <TextField
                multiline
                minRows={2}
                maxRows={5}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Plan a 3-day trip to Kyoto for $800..."
              />
              <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
                {streaming || answering
                  ? <Button className="stop-button" type="button" variant="contained" color="error" onClick={stopStreaming}>Stop</Button>
                  : <Button className="send-button" type="submit" variant="contained" endIcon={<SendIcon />}>Send</Button>}
              </Box>
            </Box>
            <div className="composer-footer"><span>{status || "Markdown supported"}</span>{retryText && <Button className="retry" size="small" color="warning" variant="outlined" disabled={streaming} onClick={(event) => sendMessage(event, true)}>Retry</Button>}</div>
          </>
        )}
        <div className="resize-handles">
          <div className="resize-handle se" onMouseDown={(e) => handleResize(e, 'se')} />
          <div className="resize-handle sw" onMouseDown={(e) => handleResize(e, 'sw')} />
          <div className="resize-handle ne" onMouseDown={(e) => handleResize(e, 'ne')} />
          <div className="resize-handle nw" onMouseDown={(e) => handleResize(e, 'nw')} />
          <div className="resize-handle e" onMouseDown={(e) => handleResize(e, 'e')} />
          <div className="resize-handle w" onMouseDown={(e) => handleResize(e, 'w')} />
          <div className="resize-handle s" onMouseDown={(e) => handleResize(e, 's')} />
          <div className="resize-handle n" onMouseDown={(e) => handleResize(e, 'n')} />
        </div>
      </section>
    );
  };

  return (
    <section className="page chat-page">
      <div className="chat-workspace-new">
        {/* Main content area - Trip Plan takes most space */}
        <main className="main-content">
          {latestPlan && !planCollapsed ? (
            <>
              {/* Trip Plan + Live Workflow side by side */}
              <div className="trip-plan-with-workflow">
                <div className="trip-plan-main">
                  <TripPlanCard key={planKey} plan={latestPlan} onSaveBudget={savePlanBudget} />
                </div>
                <aside className="live-workflow-sidebar">
                  <Activity events={current.events} />
                </aside>
              </div>
            </>
          ) : (
            // No trip plan yet - show inline chat box
            <div className="welcome-chat-area">
              <div className="welcome-content">
                <span className="welcome-icon">✦</span>
                <h2>Where will you go next?</h2>
                <p>Ask me to plan an itinerary, search accommodation, check weather, or estimate transport.</p>
                <NextSteps suggestions={suggestions} onSelect={(text) => sendMessage(null, false, text)} disabled={streaming || answering} />
                {/* Inline chat box for landing page */}
                <div className="inline-chat-box">
                  <Box className="messages" ref={messagesRef} sx={{ display: "flex", flexDirection: "column", gap: 0.5, maxHeight: 400, overflowY: "auto", marginBottom: 16 }}>
                    {!current.messages.length && <div className="welcome-inline"><span>✦</span><p>No messages yet. Send your first message above or click a suggestion.</p></div>}
                    {(() => {
                      const output = [];
                      current.messages.forEach((item, index) => {
                        output.push(
                          <MessageBubble
                            key={`${item.role}-${index}`}
                            role={item.role}
                            content={item.content}
                            reasoning={item.reasoning}
                          />,
                        );
                      });
                      return (
                        <Stack spacing={2} sx={{ width: "100%" }}>
                          {output}
                        </Stack>
                      );
                    })()}
                  </Box>
                  <Box className="composer inline-composer" component="form" onSubmit={sendMessage} sx={{ display: "flex", flexDirection: "column", gap: 1.25, alignItems: "stretch", p: 2.5, borderTop: "1px solid #edf0f6" }}>
                    <TextField
                      multiline
                      minRows={2}
                      maxRows={5}
                      value={message}
                      onChange={(e) => setMessage(e.target.value)}
                      placeholder="Plan a 3-day trip to Kyoto for $800..."
                    />
                    <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
                      {streaming || answering
                        ? <Button className="stop-button" type="button" variant="contained" color="error" onClick={stopStreaming}>Stop</Button>
                        : <Button className="send-button" type="submit" variant="contained" endIcon={<SendIcon />}>Send</Button>}
                    </Box>
                  </Box>
                  <div className="composer-footer"><span>{status || "Markdown supported"}</span>{retryText && <Button className="retry" size="small" color="warning" variant="outlined" disabled={streaming} onClick={(event) => sendMessage(event, true)}>Retry</Button>}</div>
                </div>
              </div>
            </div>
          )}
        </main>

        {/* Floating chat panel - only when trip plan exists */}
        {latestPlan && renderFloatingChatPanel()}

        {/* Bottom-right chat FAB - only when trip plan exists */}
        {latestPlan && (
          <Fab
            className="chat-fab"
            onClick={() => { setChatPanelOpen(true); setChatPanelMinimized(false); }}
            aria-label="Open chat"
            size="large"
          >
            <AutoAwesomeIcon />
          </Fab>
        )}
      </div>
    </section>
  );
}