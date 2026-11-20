// Pure helpers that turn persisted messages + tool events into render items.
//
// A user answer to `ask_user_question` is rendered once, as a question card
// with the answer in its footer, instead of repeating the same text as a
// separate user bubble.

const isQuestionEvent = (event) =>
  event?.data?.tool === "ask_user_question" && Boolean(event?.data?.result?.question);

export function buildChatMessages(messages = [], events = []) {
  const questions = (events || []).filter(isQuestionEvent);
  const rendered = new Set();
  const items = [];

  (messages || []).forEach((message, index) => {
    if (message?.role === "user") {
      const question = questions.find(
        (event) => event.data?.selected === message.content && !rendered.has(event),
      );
      if (question) {
        rendered.add(question);
        items.push({
          key: `question-${index}`,
          role: "question",
          question: question.data.result.question,
          answer: message.content,
        });
        return;
      }
    }
    items.push({
      key: `${message?.role || "assistant"}-${index}`,
      role: message?.role || "assistant",
      content: message?.content ?? "",
      reasoning: message?.reasoning,
    });
  });

  questions
    .filter((event) => !rendered.has(event))
    .forEach((event, index) => {
      items.push({
        key: `pending-question-${index}`,
        role: "question",
        question: event.data.result.question,
        answer: event.data.selected || null,
      });
    });

  return items;
}
