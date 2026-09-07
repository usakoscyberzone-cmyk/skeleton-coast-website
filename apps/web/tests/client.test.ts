import { afterEach, describe, expect, it, vi } from "vitest";
import { getActiveRecommendations, getProjects } from "../src/api/client";

describe("dashboard API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reads discovered projects from the projects API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([{ id: 3, name: "Coast", path: "I:\\YouTube Projects\\Coast" }])));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getProjects()).resolves.toEqual([{ id: 3, name: "Coast", path: "I:\\YouTube Projects\\Coast" }]);
    expect(fetchMock).toHaveBeenCalledWith("/projects", expect.objectContaining({ headers: { Accept: "application/json" } }));
  });

  it("treats an unavailable future recommendations endpoint as no active actions", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })));
    await expect(getActiveRecommendations()).resolves.toEqual([]);
  });
});
