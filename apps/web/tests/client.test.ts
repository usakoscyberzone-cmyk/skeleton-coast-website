import { afterEach, describe, expect, it, vi } from "vitest";
import { getActiveRecommendations, getDashboardSummary, getProject, getProjects, getRetention, getShortPlans, getYouTubeStatus } from "../src/api/client";

describe("dashboard API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reads discovered projects from the projects API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([{ id: 3, name: "Coast", path: "I:\\YouTube Projects\\Coast" }])));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getProjects()).resolves.toEqual([{ id: 3, name: "Coast", path: "I:\\YouTube Projects\\Coast" }]);
    expect(fetchMock).toHaveBeenCalledWith("/projects", expect.objectContaining({ headers: { Accept: "application/json" } }));
  });

  it("reads only runtime-valid short plans from the project funnel API", async () => {
    const plan = { id: 8, project_id: 3, hook_type: "reveal", source_start_seconds: 2.5, source_end_seconds: 22.5, target_duration_seconds: 20, on_screen_text: "The coast changed", cta: "Watch the story", status: "planned", strategic_role: "discovery" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [plan] }));
    await expect(getShortPlans(3)).resolves.toEqual([plan]);
  });

  it.each([
    { source_start_seconds: Number.NaN },
    { source_end_seconds: Infinity },
    { source_end_seconds: 2.5, source_start_seconds: 2.5 },
    { target_duration_seconds: 21 },
  ])("rejects non-finite or impossible short-plan ranges", async (override) => {
    const plan = { id: 8, project_id: 3, hook_type: "reveal", source_start_seconds: 2.5, source_end_seconds: 22.5, target_duration_seconds: 20, on_screen_text: "The coast changed", cta: "Watch the story", status: "planned", strategic_role: "discovery", ...override };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([plan]))));
    await expect(getShortPlans(3)).rejects.toThrow(/Invalid API response/i);
  });

  it("treats an unavailable future recommendations endpoint as no active actions", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })));
    await expect(getActiveRecommendations()).resolves.toEqual([]);
  });

  it.each([
    ["projects", getProjects, { id: 3 }],
    ["project detail", () => getProject(3), { id: 3, name: "Coast", path: "I:\\YouTube Projects\\Coast", media_files: [{}] }],
    ["summary", getDashboardSummary, { video_count: 1, views: {}, watch_minutes: {}, subscribers_gained: {} }],
    ["status", getYouTubeStatus, { channel_title: "Skeleton Coast" }],
    ["recommendations", getActiveRecommendations, [{ id: 1, youtube_video_id: "v", state: "blue" }]],
  ])("rejects malformed %s payloads before components render them", async (_label, client, payload) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))));
    await expect(client()).rejects.toThrow(/Invalid API response/i);
  });

  it("rejects a summary with a non-numeric realtime value", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      video_count: 1,
      views: { value: 2, coverage: 1 },
      watch_minutes: { value: 3, coverage: 1 },
      subscribers_gained: { value: 1, coverage: 1 },
      top_long_form: null,
      top_short: null,
      traffic_sources: {},
      realtime_views: "soon",
    }))));
    await expect(getDashboardSummary()).rejects.toThrow(/Invalid API response/i);
  });

  it.each([
    [{ video_id: "v", retention: [{ elapsed_ratio: 0, audience_retention: 1 }] }],
    [{ video_id: "v", retention: [] }],
  ])("accepts persisted retention point arrays", async (payload) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))));
    await expect(getRetention("v")).resolves.toEqual(payload);
  });

  it.each([
    { video_id: "v", retention: { elapsed_ratio: 0, audience_retention: 1 } },
    { video_id: "v", retention: [{ elapsed_ratio: "start", audience_retention: 1 }] },
    { video_id: "v", retention: [{ elapsed_ratio: 0 }] },
  ])("rejects malformed retention point arrays", async (payload) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))));
    await expect(getRetention("v")).rejects.toThrow(/Invalid API response/i);
  });
});
