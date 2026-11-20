import { Box, IconButton, List, ListItemButton, ListItemText } from "@mui/material";
import ChatBubbleOutlinedIcon from "@mui/icons-material/ChatBubbleOutlined";
import DeleteOutlinedIcon from "@mui/icons-material/DeleteOutlined";

export function ConversationList({ conversations, activeId, onSelect, onDelete }) {
  return (
    <List dense disablePadding className="conversation-list" sx={{ overflow: "auto", flex: 1 }}>
      {conversations.map((item) => (
        <Box key={item.id} sx={{ display: "flex", alignItems: "center", gap: 0.5, px: 0.5 }}>
          <ListItemButton
            selected={activeId === item.id}
            onClick={() => onSelect(item.id)}
            sx={{ borderRadius: 2, py: 0.75, flex: 1, minWidth: 0 }}
          >
            <ChatBubbleOutlinedIcon sx={{ fontSize: 16, mr: 1, opacity: 0.7 }} />
            <ListItemText
              primary={item.title}
              primaryTypographyProps={{ noWrap: true, fontSize: 13 }}
            />
          </ListItemButton>
          <IconButton size="small" color="error" title="Delete conversation" onClick={() => onDelete(item.id)}>
            <DeleteOutlinedIcon fontSize="small" />
          </IconButton>
        </Box>
      ))}
    </List>
  );
}
