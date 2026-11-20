import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Divider,
  IconButton,
  Stack,
  Tooltip,
  Typography,
  useTheme,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import ChatBubbleOutlinedIcon from "@mui/icons-material/ChatBubbleOutlined";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import DarkModeOutlinedIcon from "@mui/icons-material/DarkModeOutlined";
import HistoryEduIcon from "@mui/icons-material/HistoryEdu";
import LightModeOutlinedIcon from "@mui/icons-material/LightModeOutlined";
import SettingsIcon from "@mui/icons-material/Settings";
import TravelExploreIcon from "@mui/icons-material/TravelExplore";
import { useColorMode } from "../lib/colorMode.jsx";
import { emptyConversation, getUserId } from "../lib/session.js";
import { ChatPage } from "./ChatPage.jsx";
import { ConversationList } from "./ConversationList.jsx";
import { HistoryPage } from "./HistoryPage.jsx";
import { SettingsPage } from "./SettingsPage.jsx";

export function App() {
  const theme = useTheme();
  const colorMode = useColorMode();
  const isDark = theme.palette.mode === "dark";
  const [page, setPage] = useState("chat");
  const [conversations, setConversations] = useState([]);
  const [current, setCurrent] = useState(emptyConversation);
  const [collapsed, setCollapsed] = useState(() => {
    try { return window.localStorage.getItem("trip-sidebar-collapsed") === "1"; } catch { return false; }
  });
  const userId = getUserId();
  function toggleSidebar() {
    setCollapsed((previous) => {
      const next = !previous;
      try { window.localStorage.setItem("trip-sidebar-collapsed", next ? "1" : "0"); } catch { /* ignore */ }
      return next;
    });
  }
  const navItems = [
    { key: "chat", label: "Chat", icon: <ChatBubbleOutlinedIcon /> },
    { key: "history", label: "Travel history", icon: <HistoryEduIcon /> },
    { key: "settings", label: "Settings", icon: <SettingsIcon /> },
  ];
  async function loadConversations() {
    const response = await fetch("/api/conversations");
    if (response.ok) setConversations(await response.json());
  }
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const response = await fetch("/api/conversations");
      if (!cancelled && response.ok) setConversations(await response.json());
    })();
    return () => { cancelled = true; };
  }, []);
  async function deleteConversation(id) {
    if (!window.confirm("Delete this conversation?")) return;
    const response = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
    if (response.ok) {
      if (current.id === id) setCurrent(emptyConversation());
      await loadConversations();
    }
  }
  return (
    <Box
      className="app"
      data-color-mode={theme.palette.mode}
      sx={{
        display: "flex",
        minHeight: "100vh",
        bgcolor: "background.default",
        color: "text.primary",
      }}
    >
      <Box
        component="aside"
        sx={{
          width: collapsed ? 78 : 280,
          flex: "0 0 auto",
          display: "flex",
          flexDirection: "column",
          p: collapsed ? 1.25 : 2.5,
          bgcolor: isDark ? "#0a0f1c" : "#111b35",
          color: "#dfe6fa",
          borderRight: "1px solid",
          borderColor: isDark ? "rgba(255,255,255,0.06)" : "transparent",
          transition: "width 160ms ease",
          overflowX: "hidden",
        }}
      >
        <Stack direction={collapsed ? "column" : "row"} spacing={1.5} alignItems="center" sx={{ mx: collapsed ? 0 : 0.5, mb: 3 }}>
          <Tooltip title="Tripwise" placement="right">
            <Box sx={{ width: 36, height: 36, borderRadius: "12px", bgcolor: "primary.main", color: "#fff", display: "grid", placeItems: "center", boxShadow: "0 8px 18px rgba(80,72,190,0.4)", flex: "0 0 auto" }}>
              <TravelExploreIcon fontSize="small" />
            </Box>
          </Tooltip>
          {!collapsed && <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography fontWeight={700} color="#fff" fontSize={18}>Tripwise</Typography>
            <Typography variant="caption" sx={{ color: "#8794b7" }}>AI travel planner</Typography>
          </Box>}
          <Tooltip title={isDark ? "Switch to light mode" : "Switch to dark mode"} placement={collapsed ? "right" : "top"}>
            <IconButton onClick={colorMode.toggleColorMode} size="small" sx={{ color: "#c5ceea", bgcolor: "rgba(255,255,255,0.06)", "&:hover": { bgcolor: "rgba(255,255,255,0.12)" } }}>
              {isDark ? <LightModeOutlinedIcon fontSize="small" /> : <DarkModeOutlinedIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
          <Tooltip title={collapsed ? "Expand sidebar" : "Collapse sidebar"} placement={collapsed ? "right" : "top"}>
            <IconButton onClick={toggleSidebar} size="small" sx={{ color: "#c5ceea", bgcolor: "rgba(255,255,255,0.06)", "&:hover": { bgcolor: "rgba(255,255,255,0.12)" } }}>
              {collapsed ? <ChevronRightIcon fontSize="small" /> : <ChevronLeftIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Stack>
        {collapsed ? (
          <Tooltip title="New conversation" placement="right">
            <IconButton onClick={() => { setCurrent(emptyConversation()); setPage("chat"); }} sx={{ mx: "auto", mb: 1, bgcolor: "primary.main", color: "#fff", borderRadius: "12px", width: 44, height: 44, "&:hover": { bgcolor: "primary.dark" } }}>
              <AddIcon />
            </IconButton>
          </Tooltip>
        ) : (
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => { setCurrent(emptyConversation()); setPage("chat"); }}
            sx={{ mb: 1, py: 1.1 }}
          >
            New conversation
          </Button>
        )}
        <Stack component="nav" spacing={0.5} sx={{ my: 2.5 }}>
          {navItems.map((item) => collapsed ? (
            <Tooltip key={item.key} title={item.label} placement="right">
              <IconButton
                onClick={() => setPage(item.key)}
                sx={{
                  mx: "auto",
                  color: page === item.key ? "#fff" : "#9daaca",
                  bgcolor: page === item.key ? "#242f52" : "transparent",
                  "&:hover": { bgcolor: "#242f52", color: "#fff" },
                }}
              >
                {item.icon}
              </IconButton>
            </Tooltip>
          ) : (
            <Button
              key={item.key}
              startIcon={item.icon}
              onClick={() => setPage(item.key)}
              sx={{
                justifyContent: "flex-start",
                color: page === item.key ? "#fff" : "#9daaca",
                bgcolor: page === item.key ? "#242f52" : "transparent",
                "&:hover": { bgcolor: "#242f52", color: "#fff" },
              }}
            >
              {item.label}
            </Button>
          ))}
        </Stack>
        {!collapsed && <>
          <Typography sx={{ mx: 1, mb: 1, color: "#6e7c9f", fontSize: 10, letterSpacing: 1.5, fontWeight: 700 }}>
            RECENT CHATS
          </Typography>
          <ConversationList
            conversations={conversations}
            activeId={current.id}
            onSelect={(id) => {
              setPage("chat");
              fetch(`/api/conversations/${id}`).then((r) => r.json()).then((item) => setCurrent({ id: item.id, messages: item.messages, events: item.events || [] }));
            }}
            onDelete={deleteConversation}
          />
        </>}
        <Divider sx={{ borderColor: "#293556", mt: "auto", pt: 2 }} />
        {collapsed ? (
          <Tooltip title="Agent 1–4 online" placement="right">
            <Box sx={{ pt: 2, textAlign: "center", color: "#5fd39a", fontSize: 16 }}>●</Box>
          </Tooltip>
        ) : (
          <Typography sx={{ pt: 2, px: 1, color: "#7380a1", fontSize: 12 }}>
            Agent 1–4 <Box component="span" sx={{ float: "right", color: "#5fd39a" }}>online</Box>
          </Typography>
        )}
      </Box>
      <Box component="main" sx={{ flex: 1, minWidth: 0, bgcolor: "background.default", color: "text.primary" }}>
        {page === "history"
          ? <HistoryPage userId={userId} />
          : page === "settings"
            ? <SettingsPage />
            : <ChatPage current={current} setCurrent={setCurrent} loadConversations={loadConversations} userId={userId} />}
      </Box>
    </Box>
  );
}
