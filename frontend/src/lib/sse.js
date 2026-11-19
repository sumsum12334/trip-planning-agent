/**
 * Read a server-sent-events response and invoke `onPayload` for each `data:`
 * JSON frame. Network chunks can split a frame anywhere, so partial text is
 * buffered until a blank line terminates it; a trailing frame without a final
 * blank line is still delivered when the stream ends.
 */
export async function readSseFrames(response, onPayload) {
  if (!response?.body) throw new Error("Streaming is unavailable.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const handle = (frame) => {
    const line = frame.split("\n").find((item) => item.startsWith("data: "));
    if (!line) return;
    onPayload(JSON.parse(line.slice(6)));
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";
      frames.forEach(handle);
      if (done) {
        if (buffer.trim()) handle(buffer);
        break;
      }
    }
  } finally {
    reader.releaseLock?.();
  }
}
