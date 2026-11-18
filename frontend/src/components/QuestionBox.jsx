import { useState } from "react";
import { Button, Stack, TextField } from "@mui/material";

export function QuestionBox({ event, onOption, disabled, retryOption, selectedOption }) {
  const [showCustom, setShowCustom] = useState(false);
  const [customText, setCustomText] = useState("");
  if (!event?.data?.result?.question) return null;
  const options = event.data.result.options || [];
  const selected = selectedOption || event.data.selected;
  const locked = disabled || Boolean(selected);
  return <section className="question-box">
    <div className="question-box-header"><span className="question-box-icon">?</span><div><div className="question-kicker">YOUR INPUT NEEDED</div><strong>{event.data.result.question}</strong></div></div>
    <p>Choose an option to continue planning, or write your own.</p>
    <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1} className="question-options" sx={{ mt: 1.5, ml: "39px" }}>
      {options.map((option) => (
        <Button
          key={option}
          type="button"
          size="small"
          variant={selected === option ? "contained" : "outlined"}
          disabled={locked}
          onClick={() => onOption(option)}
        >
          {selected === option ? "Selected" : option}
        </Button>
      ))}
      {!showCustom && (
        <Button type="button" size="small" variant="outlined" disabled={locked} onClick={() => setShowCustom(true)}>
          Other…
        </Button>
      )}
    </Stack>
    {showCustom && (
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1.5, ml: "39px" }}>
        <TextField
          size="small"
          variant="filled"
          placeholder="Type your own answer"
          value={customText}
          onChange={(e) => setCustomText(e.target.value)}
          sx={{ maxWidth: 360 }}
        />
        <Button type="button" size="small" variant="contained" disabled={locked || !customText.trim()} onClick={() => onOption(customText.trim(), true)}>
          Send
        </Button>
      </Stack>
    )}
    {retryOption && (
      <Button className="question-retry" type="button" size="small" color="error" variant="outlined" onClick={() => onOption(retryOption)} sx={{ mt: 1.5, ml: "39px" }}>
        Retry sending "{retryOption}"
      </Button>
    )}
  </section>;
}
