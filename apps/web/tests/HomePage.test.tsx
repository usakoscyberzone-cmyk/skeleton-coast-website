import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "../src/pages/HomePage";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

describe("HomePage", () => {
  it("prioritizes the next actions panel above performance metrics", async () => {
    fetchMock.mockImplementation((url: string) => {
      const payload = url.endsWith("/recommendations/active")
        ? [{ id: 7, youtube_video_id: "video-1", state: "amber", action: "Review the opening hook", reason: "Retention softened", confidence: "medium", data_used: { impressions: 2000 } }]
        : url.endsWith("/analytics/summary")
          ? { video_count: 2, views: { value: 14200, coverage: 2 }, watch_minutes: { value: 7200, coverage: 2 }, subscribers_gained: { value: 84, coverage: 2 }, realtime_views: 318, top_long_form: { title: "Desert Kob", views: 9000 }, top_short: { title: "Shark release", views: 5200 }, traffic_sources: { Browse: 0.46, Suggested: 0.24, Search: 0.18, External: 0.12 }, video_states: [{ title: "Desert Kob", state: "green" }, { title: "Shark release", state: "red" }] }
          : { status: "authorized", channel_title: "Skeleton Coast" };
      return Promise.resolve(new Response(JSON.stringify(payload)));
    });

    render(<HomePage />);

    expect(await screen.findByRole("heading", { name: /what should i do next/i })).toBeInTheDocument();
    expect(screen.getByText("Review the opening hook")).toBeInTheDocument();
    expect(screen.getByText("14,200")).toBeInTheDocument();
    expect(screen.getByText("120.0 h")).toBeInTheDocument();
    expect(screen.getByText("84")).toBeInTheDocument();
    expect(screen.getByText("318")).toBeInTheDocument();
    expect(screen.getAllByText("Desert Kob").length).toBeGreaterThan(0);
    expect(screen.getByText("Shark release")).toBeInTheDocument();
    expect(screen.getByText(/Browse 46%/)).toBeInTheDocument();
    expect(screen.getByText("Green")).toBeInTheDocument();
    expect(screen.getByText("Amber")).toBeInTheDocument();
    expect(screen.getByText("Red")).toBeInTheDocument();
  });

  it("shows an unavailable state instead of inventing realtime views", async () => {
    fetchMock.mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(
      url.endsWith("/analytics/summary")
        ? { video_count: 0, views: { value: null, coverage: 0 }, watch_minutes: { value: null, coverage: 0 }, subscribers_gained: { value: null, coverage: 0 } }
        : url.endsWith("/recommendations/active") ? [] : { status: "configuration_required" },
    ))));

    render(<HomePage />);
    expect(await screen.findByText(/Realtime views unavailable/i)).toBeInTheDocument();
  });
});
