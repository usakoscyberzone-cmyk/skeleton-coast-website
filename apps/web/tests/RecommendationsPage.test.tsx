import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RecommendationsPage } from "../src/pages/RecommendationsPage";

const fetchMock = vi.fn();
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });

describe("RecommendationsPage", () => {
  it("sorts Red, Amber, then Green recommendations and shows their evidence", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify([
      { id: 1, youtube_video_id: "green", state: "green", action: "Leave it", reason: "Healthy", confidence: "high", data_used: { views: 9 } },
      { id: 2, youtube_video_id: "red", state: "red", action: "Change thumbnail", reason: "CTR fell", confidence: "medium", data_used: { ctr: 0.02 } },
      { id: 3, youtube_video_id: "amber", state: "amber", action: "Watch", reason: "Small sample", confidence: "low", data_used: { impressions: 30 } },
    ])));
    render(<RecommendationsPage />);
    expect(await screen.findByRole("heading", { name: /recommendations/i })).toBeInTheDocument();
    expect(screen.getAllByRole("article").map((card) => card.textContent)).toEqual(expect.arrayContaining([expect.stringMatching(/Change thumbnail/), expect.stringMatching(/Watch/), expect.stringMatching(/Leave it/)]));
    const cards = screen.getAllByRole("article");
    expect(cards[0]).toHaveTextContent("Red");
    expect(cards[1]).toHaveTextContent("Amber");
    expect(cards[2]).toHaveTextContent("Green");
    expect(screen.getAllByText(/action/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/reason/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/confidence/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/data used/i).length).toBeGreaterThan(0);
  });
});
