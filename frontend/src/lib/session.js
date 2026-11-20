export const USER_KEY = "trip-planner-user-id";
export const emptyConversation = () => ({ id: null, messages: [], events: [] });
export const getUserId = () => {
  const existing = window.localStorage.getItem(USER_KEY);
  if (existing) return existing;
  const id = `local-${crypto.randomUUID()}`;
  window.localStorage.setItem(USER_KEY, id);
  return id;
};
