import { Stack, Typography } from "@mui/material";
import { MessageBubble } from "./MessageBubble.jsx";

/** Render the items produced by `buildChatMessages` as chat bubbles. */
export function ChatMessages({ items }) {
  return (
    <Stack spacing={2} sx={{ width: "100%" }}>
      {items.map((item) => item.role === "question" ? (
        <MessageBubble
          key={item.key}
          role="question"
          kicker="Question"
          content={<Typography component="span">{item.question}</Typography>}
          footer={item.answer ? (
            <Typography variant="caption" color="primary" fontWeight={700} sx={{ display: "block", mt: 1 }}>
              Answer: {item.answer}
            </Typography>
          ) : null}
        />
      ) : (
        <MessageBubble
          key={item.key}
          role={item.role}
          content={item.content}
          reasoning={item.reasoning}
        />
      ))}
    </Stack>
  );
}
