import { describe, expect, it } from "vitest";

import { readSseFrames } from "./sse.js";

function streamOf(chunks) {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
}

describe("readSseFrames", () => {
  it("delivers frames split across chunks in order", async () => {
    const seen = [];
    await readSseFrames(
      {
        body: streamOf([
          'data: {"kind":"event","label":"Star',
          'ted"}\n\ndata: {"kind":"content","text":"Hi"}\n\n',
        ]),
      },
      (payload) => seen.push(payload),
    );
    expect(seen).toEqual([
      { kind: "event", label: "Started" },
      { kind: "content", text: "Hi" },
    ]);
  });

  it("delivers a trailing frame without a blank line", async () => {
    const seen = [];
    await readSseFrames(
      { body: streamOf(['data: {"kind":"done","text":"ok"}']) },
      (payload) => seen.push(payload),
    );
    expect(seen).toEqual([{ kind: "done", text: "ok" }]);
  });

  it("ignores frames without a data line", async () => {
    const seen = [];
    await readSseFrames(
      { body: streamOf([": keep-alive\n\ndata: {\"kind\":\"done\"}\n\n"]) },
      (payload) => seen.push(payload),
    );
    expect(seen).toEqual([{ kind: "done" }]);
  });

  it("rejects a response without a body", async () => {
    await expect(readSseFrames({ body: null }, () => {})).rejects.toThrow(
      "Streaming is unavailable.",
    );
  });
});
