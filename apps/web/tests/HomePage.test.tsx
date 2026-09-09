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
          ? [{ id: 7, youtube_video_id: "video-1", state: "amber", action: "Review the opening hook", reason: "Retention softened", confidence: "medium", data_used: { impressions: 2000 } }, { id: 8, youtube_video_id: "video-2", state: "green", action: "Leave it alone", reason: "Distribution is healthy", confidence: "high", data_used: { views: 9000 } }, { id: 9, youtube_video_id: "video-3", state: "red", action: "Test a thumbnail", reason: "Distribution stalled", confidence: "high", data_used: { ctr: .02 } }]
        : url.endsWith("/analytics/summary")
          ? { video_count: 2, views: { value: 14200, coverage: 2 }, watch_minutes: { value: 7200, coverage: 2 }, subscribers_gained: { value: 84, coverage: 2 }, realtime_views: 318, top_long_form: { id: "video-2", title: "Desert Kob", views: 9000 }, top_short: { id: "video-3", title: "Shark release", views: 5200 }, traffic_sources: { Browse: 0.46, Suggested: 0.24, Search: 0.18, External: 0.12 } }
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
    expect(screen.getAllByText("Shark release").length).toBeGreaterThan(0);
    expect(screen.getByText(/Browse 46%/)).toBeInTheDocument();
    expect(screen.getAllByText("Green").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Amber").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Red").length).toBeGreaterThan(0);
    expect(screen.getByText("video-2")).toBeInTheDocument();
  });

  it("keeps dashboard analytics available when YouTube authorization requires attention", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.endsWith("/youtube/status")) return Promise.resolve(new Response(JSON.stringify({ detail: "YouTube authorization is required." }), { status: 401 }));
      if (url.endsWith("/recommendations/active")) return Promise.resolve(new Response(JSON.stringify([])));
      return Promise.resolve(new Response(JSON.stringify({ video_count: 1, views: { value: 14, coverage: 1 }, watch_minutes: { value: 60, coverage: 1 }, subscribers_gained: { value: 1, coverage: 1 }, top_long_form: null, top_short: null, traffic_sources: {} })));
    });
    render(<HomePage />);
    expect(await screen.findByText("14")).toBeInTheDocument();
    expect(screen.getByText(/YouTube authorization is required/i)).toBeInTheDocument();
  });

  it("shows an unavailable state instead of inventing realtime views", async () => {
    fetchMock.mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(
      url.endsWith("/analytics/summary")
        ? { video_count: 0, views: { value: null, coverage: 0 }, watch_minutes: { value: null, coverage: 0 }, subscribers_gained: { value: null, coverage: 0 }, top_long_form: null, top_short: null, traffic_sources: {} }
        : url.endsWith("/recommendations/active") ? [] : { status: "configuration_required" },
    ))));

    render(<HomePage />);
    expect(await screen.findByText(/Realtime views unavailable/i)).toBeInTheDocument();
  });
});
