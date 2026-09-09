import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AnalyticsPage } from "../src/pages/AnalyticsPage";

const fetchMock = vi.fn();
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });

describe("AnalyticsPage", () => {
  it("shows persisted metrics, coverage, and every required topic without inventing missing values", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      video_count: 2, views: { value: 200, coverage: 2 }, watch_minutes: { value: 60, coverage: 1 }, subscribers_gained: { value: null, coverage: 0 }, impressions: { value: 1000, coverage: 2 }, ctr: { value: null, coverage: 0 }, avg_view_duration_seconds: { value: 23, coverage: 1 }, average_percentage_viewed: { value: 0.5, coverage: 1 }, subscriber_conversion_rate: { value: null, coverage: 0 }, returning_viewers: { value: 12, coverage: 1 }, views_1h: { value: 30, coverage: 1 }, views_24h: { value: null, coverage: 0 }, views_7d: { value: 120, coverage: 1 }, top_long_form: null, top_short: null, traffic_sources: { Browse: .4 }, traffic_source_coverage: { Browse: 2 }, videos: [{ id: "one", title: "One", views: 200 }], topics: { Fishing: { value: 200, coverage: 1 } },
    })));
    render(<AnalyticsPage />);
    expect(await screen.findByRole("heading", { name: /analytics/i })).toBeInTheDocument();
    expect(screen.getByText("1,000")).toBeInTheDocument();
    expect(screen.getAllByText(/Unavailable/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Browse 40%.*2 videos/i)).toBeInTheDocument();
    for (const topic of ["Fishing", "Namibia travel", "Angola", "History", "4x4", "Current events"]) expect(screen.getByText(topic)).toBeInTheDocument();
    expect(screen.getByText(/Namibia travel.*Unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/1 hour/)).toBeInTheDocument();
    expect(screen.getByText(/24 hours/)).toBeInTheDocument();
    expect(screen.getByText(/7 days/)).toBeInTheDocument();
  });
});
