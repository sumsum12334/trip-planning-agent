import { useEffect, useState } from "react";
import { Button, Paper, Stack, TextField, Typography } from "@mui/material";
import SettingsIcon from "@mui/icons-material/Settings";

export function ModelSettings() {
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
  return (
    <Paper className="settings panel" variant="outlined" sx={{ mt: 2, p: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <SettingsIcon color="primary" fontSize="small" />
        <Typography fontWeight={700}>Model settings</Typography>
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Settings apply to this running backend. API keys are never displayed.
      </Typography>
      <Stack spacing={2}>
        <TextField
          variant="filled"
          label="Endpoint URL"
          value={settings.endpoint_url || ""}
          onChange={(event) => setSettings({ ...settings, endpoint_url: event.target.value })}
        />
        <TextField
          variant="filled"
          label="Model"
          value={settings.qwen_model || ""}
          onChange={(event) => setSettings({ ...settings, qwen_model: event.target.value })}
        />
        <TextField
          variant="filled"
          label="API key"
          type="password"
          autoComplete="off"
          placeholder="Leave blank to keep current key"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
        />
        <Stack direction="row" spacing={2} alignItems="center">
          <Button variant="contained" color="inherit" onClick={save} sx={{ bgcolor: "#263452", color: "#fff", "&:hover": { bgcolor: "#1b2538" } }}>
            Save settings
          </Button>
          <Typography variant="caption" color="text.secondary">{status}</Typography>
        </Stack>
      </Stack>
    </Paper>
  );
}
