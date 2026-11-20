import { describe, expect, it } from "vitest";

import { buildChatMessages } from "./chatMessages.js";

const questionEvent = (overrides = {}) => ({
  type: "tool",
  label: "ask_user_question result received",
  status: "completed",
  data: {
    tool: "ask_user_question",
    result: { question: "Which month do you want to travel?", options: ["March"] },
    selected: null,
    ...overrides,
  },
});

describe("buildChatMessages", () => {
  it("renders plain user/assistant pairs in order", () => {
    const items = buildChatMessages(
      [
        { role: "user", content: "Plan a trip" },
        { role: "assistant", content: "Here is a plan" },
      ],
      [],
    );
    expect(items).toEqual([
      { key: "user-0", role: "user", content: "Plan a trip", reasoning: undefined },
      {
        key: "assistant-1",
        role: "assistant",
        content: "Here is a plan",
        reasoning: undefined,
      },
    ]);
  });

  it("merges an answered question into a single card with the answer in the footer", () => {
    const event = questionEvent({ selected: "March" });
    const items = buildChatMessages(
      [
        { role: "user", content: "Plan a trip" },
        { role: "user", content: "March" },
        { role: "assistant", content: "Great, March it is." },
      ],
      [event],
    );
    expect(items).toHaveLength(3);
    expect(items[1]).toEqual({
      key: "question-1",
      role: "question",
      question: "Which month do you want to travel?",
      answer: "March",
    });
    // The plain "March" bubble is replaced by the question card.
    expect(items.filter((item) => item.content === "March")).toHaveLength(0);
  });

  it("keeps a pending question visible after the messages", () => {
    const items = buildChatMessages(
      [{ role: "user", content: "Plan a trip" }],
      [questionEvent()],
    );
    expect(items).toHaveLength(2);
    const pending = items[1];
    expect(pending.role).toBe("question");
    expect(pending.answer).toBeNull();
  });

  it("answers each repeated question only once", () => {
    const event = questionEvent({ selected: "March" });
    const items = buildChatMessages(
      [
        { role: "user", content: "March" },
        { role: "user", content: "March" },
      ],
      [event],
    );
    expect(items.filter((item) => item.role === "question")).toHaveLength(1);
    // The second identical bubble still renders as a normal user message.
    expect(items[1].role).toBe("user");
  });

  it("tolerates empty inputs and malformed events", () => {
    expect(buildChatMessages([], [])).toEqual([]);
    expect(buildChatMessages(undefined, undefined)).toEqual([]);
    expect(
      buildChatMessages([{ role: "user", content: "hi" }], [{ data: null }]),
    ).toEqual([
      { key: "user-0", role: "user", content: "hi", reasoning: undefined },
    ]);
  });
});
