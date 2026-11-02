import { createTheme, alpha } from "@mui/material/styles";

const brand = {
  primary: "#6c63ff",
  primaryDark: "#8b84ff",
};

export function createAppTheme(mode = "light") {
  const isDark = mode === "dark";
  return createTheme({
    palette: {
      mode,
      primary: {
        main: isDark ? brand.primaryDark : brand.primary,
        contrastText: "#ffffff",
      },
      secondary: { main: isDark ? "#6aa8ff" : "#4b83d4" },
      background: {
        default: isDark ? "#0e1322" : "#f3f5fb",
        paper: isDark ? "#171e33" : "#ffffff",
      },
      text: {
        primary: isDark ? "#e8ecf8" : "#17233d",
        secondary: isDark ? "#9aa6c4" : "#6b7793",
      },
      divider: isDark ? alpha("#9aa6c4", 0.16) : alpha("#17233d", 0.08),
      success: { main: "#5fd39a" },
      error: { main: "#e35b71" },
      warning: { main: "#f4b740" },
      action: {
        hover: isDark ? alpha("#8b84ff", 0.12) : alpha("#6c63ff", 0.06),
        selected: isDark ? alpha("#8b84ff", 0.2) : alpha("#6c63ff", 0.12),
      },
    },
    typography: {
      fontFamily: '"Inter", system-ui, -apple-system, sans-serif',
      h1: { fontWeight: 700, letterSpacing: "-0.04em" },
      h2: { fontWeight: 650, letterSpacing: "-0.02em" },
      h3: { fontWeight: 650 },
      button: { textTransform: "none", fontWeight: 700 },
    },
    shape: { borderRadius: 14 },
    shadows: [
      "none",
      "0 1px 2px rgba(15, 23, 42, 0.04)",
      "0 4px 12px rgba(15, 23, 42, 0.06)",
      "0 10px 28px rgba(15, 23, 42, 0.08)",
      "0 16px 40px rgba(15, 23, 42, 0.1)",
      ...Array(20).fill("0 16px 40px rgba(15, 23, 42, 0.1)"),
    ],
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            backgroundImage: isDark
              ? "radial-gradient(circle at 75% -10%, rgba(108,99,255,0.18), transparent 40%)"
              : "radial-gradient(circle at 70% 0, #e9edff 0, transparent 35%)",
            backgroundAttachment: "fixed",
          },
        },
      },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: { borderRadius: 12, px: 1.5 },
          containedPrimary: {
            boxShadow: isDark
              ? "0 8px 20px rgba(108,99,255,0.28)"
              : "0 8px 20px rgba(97,89,230,0.3)",
          },
        },
      },
      MuiPaper: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            backgroundImage: "none",
            border: `1px solid ${isDark ? alpha("#9aa6c4", 0.14) : alpha("#17233d", 0.08)}`,
          },
        },
      },
      MuiTextField: {
        defaultProps: { size: "small", fullWidth: true },
      },
      MuiIconButton: {
        styleOverrides: {
          root: { borderRadius: 10 },
        },
      },
    },
  });
}

export default createAppTheme("light");
