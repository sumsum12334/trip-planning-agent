import { useEffect, useState } from "react";
import { FormControlLabel, Paper, Stack, Switch, Typography } from "@mui/material";
import AutoFixHighIcon from "@mui/icons-material/AutoFixHigh";
import {
  effectiveReconsiderEnabled,
  fetchReconsiderDefault,
  readReconsiderOverride,
  writeReconsiderOverride,
} from "../lib/reconsider.js";

export function TripAssistanceSettings() {
  const [serverDefault, setServerDefault] = useState(true);
  const [override, setOverride] = useState(() => readReconsiderOverride());
  const [status, setStatus] = useState("");
  useEffect(() => {
    let cancelled = false;
    fetchReconsiderDefault().then((value) => {
      if (!cancelled) setServerDefault(value);
    });
    return () => { cancelled = true; };
  }, []);
  const enabled = effectiveReconsiderEnabled(serverDefault, override);
  function toggle(event) {
    const next = Boolean(event.target.checked);
    writeReconsiderOverride(next);
    setOverride(next);
    setStatus(next ? "On in this browser." : "Off in this browser.");
  }
  return (
    <Paper className="settings panel" variant="outlined" sx={{ mt: 2, p: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <AutoFixHighIcon color="primary" fontSize="small" />
        <Typography fontWeight={700}>Trip assistance</Typography>
      </Stack>
      <FormControlLabel
        control={<Switch checked={enabled} onChange={toggle} />}
        label="Suggest AI reconsideration after plan edits"
      />
      <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
        When on, saving a trip-plan edit offers a one-click "Ask AI to reconsider" prompt.
        Stored in this browser; the default comes from the server.{status ? ` ${status}` : ""}
      </Typography>
    </Paper>
  );
}
