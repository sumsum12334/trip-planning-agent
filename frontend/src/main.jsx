import { StrictMode, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { CssBaseline, ThemeProvider } from "@mui/material";
import { createAppTheme } from "./theme";
import { ColorModeContext } from "./lib/colorMode.jsx";
import { App } from "./components/App.jsx";
import "leaflet/dist/leaflet.css";
import "./styles.css";

function Root() {
  const [mode, setMode] = useState(() => {
    try {
      return window.localStorage.getItem("trip-color-mode") || "light";
    } catch {
      return "light";
    }
  });
  const colorMode = useMemo(
    () => ({
      mode,
      toggleColorMode: () => setMode((prev) => {
        const next = prev === "light" ? "dark" : "light";
        try { window.localStorage.setItem("trip-color-mode", next); } catch { /* ignore */ }
        return next;
      }),
    }),
    [mode],
  );
  const theme = useMemo(() => createAppTheme(mode), [mode]);
  return (
    <ColorModeContext.Provider value={colorMode}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <App />
      </ThemeProvider>
    </ColorModeContext.Provider>
  );
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
