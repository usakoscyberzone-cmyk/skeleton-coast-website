import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LearningPage } from "../src/pages/LearningPage";

const fetchMock = vi.fn();
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });

describe("LearningPage", () => {
  it("uses an empty state when the persisted-pattern endpoint is not available", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 }));
    render(<LearningPage />);
    expect(await screen.findByText(/No persisted learning patterns/i)).toBeInTheDocument();
  });

  it("renders only persisted patterns with their evidence counts", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify([{ id: 1, topic: "Fishing", pattern_type: "hook", summary: "Fast opening held viewers", confidence: "high", evidence_count: 8 }])));
    render(<LearningPage />);
    expect(await screen.findByText("Fast opening held viewers")).toBeInTheDocument();
    expect(screen.getByText(/Evidence: 8/i)).toBeInTheDocument();
  });
});
