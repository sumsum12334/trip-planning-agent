import { Avatar, Box, Paper, Stack, Typography, useTheme } from "@mui/material";
import { Markdown } from "./Markdown.jsx";

export function MessageBubble({ role, content, reasoning, kicker, footer }) {
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
