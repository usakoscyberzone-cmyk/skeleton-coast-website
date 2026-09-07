import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RetentionPage } from "../src/pages/RetentionPage";

const fetchMock = vi.fn();
const summary = { video_count: 1, views: { value: 100, coverage: 1 }, watch_minutes: { value: 20, coverage: 1 }, subscribers_gained: { value: 1, coverage: 1 }, impressions: { value: null, coverage: 0 }, ctr: { value: null, coverage: 0 }, avg_view_duration_seconds: { value: null, coverage: 0 }, average_percentage_viewed: { value: null, coverage: 0 }, subscriber_conversion_rate: { value: null, coverage: 0 }, returning_viewers: { value: null, coverage: 0 }, views_1h: { value: null, coverage: 0 }, views_24h: { value: null, coverage: 0 }, views_7d: { value: null, coverage: 0 }, top_long_form: null, top_short: null, traffic_sources: {}, traffic_source_coverage: {}, videos: [], retention_videos: [{ id: "video-1", title: "Measured video" }], topics: {} };
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });

describe("RetentionPage", () => {
  it("uses persisted retention points for opening and ending without inventing other markers", async () => {
    fetchMock.mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(url.endsWith("/summary") ? summary : { video_id: "video-1", retention: [{ elapsed_ratio: 0, audience_retention: .8 }, { elapsed_ratio: .5, audience_retention: .55 }, { elapsed_ratio: 1, audience_retention: .4 }] }))));
    render(<RetentionPage />);
    fireEvent.change(await screen.findByLabelText(/video/i), { target: { value: "video-1" } });
    expect(await screen.findByText(/Measured retention/i)).toBeInTheDocument();
    expect(screen.getByText(/Opening retention.*80%/i)).toBeInTheDocument();
    expect(screen.getByText(/Ending.*40%/i)).toBeInTheDocument();
    expect(screen.getByText(/First significant drop.*Insufficient/i)).toBeInTheDocument();
  });

  it("shows an unavailable state for a selected video without measured retention", async () => {
    fetchMock.mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(url.endsWith("/summary") ? summary : { video_id: "video-1", retention: null }))));
    render(<RetentionPage />);
    fireEvent.change(await screen.findByLabelText(/video/i), { target: { value: "video-1" } });
    expect(await screen.findByText(/Measured retention is unavailable/i)).toBeInTheDocument();
  });

  it("reports unavailable for an empty measured point array", async () => {
    fetchMock.mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(url.endsWith("/summary") ? summary : { video_id: "video-1", retention: [] }))));
    render(<RetentionPage />);
    fireEvent.change(await screen.findByLabelText(/video/i), { target: { value: "video-1" } });
    expect(await screen.findByText(/Measured retention is unavailable/i)).toBeInTheDocument();
  });

  it("allows a retention video with null views to be selected", async () => {
    const nullViewSummary = { ...summary, retention_videos: [{ id: "retention-only", title: "No view total" }] };
    fetchMock.mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(url.endsWith("/summary") ? nullViewSummary : { video_id: "retention-only", retention: [{ elapsed_ratio: 0, audience_retention: .7 }] }))));
    render(<RetentionPage />);
    fireEvent.change(await screen.findByLabelText(/video/i), { target: { value: "retention-only" } });
    expect(await screen.findByText(/Opening retention.*70%/i)).toBeInTheDocument();
  });
});
