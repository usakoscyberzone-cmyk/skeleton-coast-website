import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RetentionPage } from "../src/pages/RetentionPage";

const fetchMock = vi.fn();
const summary = { video_count: 1, views: { value: 100, coverage: 1 }, watch_minutes: { value: 20, coverage: 1 }, subscribers_gained: { value: 1, coverage: 1 }, impressions: { value: null, coverage: 0 }, ctr: { value: null, coverage: 0 }, avg_view_duration_seconds: { value: null, coverage: 0 }, average_percentage_viewed: { value: null, coverage: 0 }, subscriber_conversion_rate: { value: null, coverage: 0 }, returning_viewers: { value: null, coverage: 0 }, views_1h: { value: null, coverage: 0 }, views_24h: { value: null, coverage: 0 }, views_7d: { value: null, coverage: 0 }, top_long_form: null, top_short: null, traffic_sources: {}, traffic_source_coverage: {}, videos: [{ id: "video-1", title: "Measured video", views: 100 }], topics: {} };
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });

describe("RetentionPage", () => {
  it("lets a viewer select an exposed video and labels supported retention signals as measured", async () => {
    fetchMock.mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(url.endsWith("/summary") ? summary : { video_id: "video-1", retention: { opening_retention: .8, first_significant_drop_seconds: 12, replay_sections: [{ start_seconds: 30, end_seconds: 42 }], slow_sections: [{ start_seconds: 50, end_seconds: 62 }], strong_ending: true, short_candidates: [{ start_seconds: 30, end_seconds: 42 }] } }))));
    render(<RetentionPage />);
    fireEvent.change(await screen.findByLabelText(/video/i), { target: { value: "video-1" } });
    expect(await screen.findByText(/Measured retention/i)).toBeInTheDocument();
    expect(screen.getByText(/Opening retention.*80%/i)).toBeInTheDocument();
    expect(screen.getByText(/First significant drop.*12/i)).toBeInTheDocument();
    expect(screen.getByText(/Replay or high-interest/i)).toBeInTheDocument();
  });

  it("shows an unavailable state for a selected video without measured retention", async () => {
    fetchMock.mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(url.endsWith("/summary") ? summary : { video_id: "video-1", retention: null }))));
    render(<RetentionPage />);
    fireEvent.change(await screen.findByLabelText(/video/i), { target: { value: "video-1" } });
    expect(await screen.findByText(/Measured retention is unavailable/i)).toBeInTheDocument();
  });
});
