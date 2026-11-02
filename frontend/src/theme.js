import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#6c63ff", contrastText: "#ffffff" },
    secondary: { main: "#4b83d4" },
    background: { default: "#f5f7fb", paper: "#ffffff" },
    text: { primary: "#17233d", secondary: "#74809b" },
    success: { main: "#5fd39a" },
    error: { main: "#e35b71" },
    warning: { main: "#f4b740" },
  },
  typography: {
    fontFamily: '"Inter", system-ui, -apple-system, sans-serif',
    h1: { fontFamily: '"Inter", system-ui, -apple-system, sans-serif', fontWeight: 700, letterSpacing: "-0.04em" },
    h2: { fontFamily: '"Inter", system-ui, -apple-system, sans-serif', fontWeight: 600 },
    h3: { fontFamily: '"Inter", system-ui, -apple-system, sans-serif', fontWeight: 600 },
    button: { textTransform: "none", fontWeight: 700 },
  },
  shape: { borderRadius: 12 },
  components: {
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 12 },
        containedPrimary: { boxShadow: "0 8px 20px #6159e64d" },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: { backgroundImage: "none" },
      },
    },
    MuiTextField: {
      defaultProps: { size: "small", fullWidth: true },
    },
  },
});

export default theme;
