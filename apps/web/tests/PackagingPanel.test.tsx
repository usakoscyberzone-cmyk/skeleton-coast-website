import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProjectDetailPage } from "../src/pages/ProjectDetailPage";

const fetchMock = vi.fn();
const revisionA = "a".repeat(64);

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

function json(value: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } }));
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={["/projects/1"]}>
      <Routes><Route path="/projects/:id" element={<ProjectDetailPage />} /></Routes>
    </MemoryRouter>,
  );
}

describe("PackagingPanel", () => {
  it("pairs title and thumbnail and labels every score as advisory", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url === "/projects/1") return json({ id: 1, name: "Coast", path: "I:\\YouTube Projects\\Coast", media_files: [] });
      if (url === "/projects/1/shorts") return json([]);
      return json({ revision: revisionA, candidates: [{
        label: "A", title: "A Skeleton Coast mystery", thumbnail: { aspect: "16:9", file: "Thumbnails/thumbnail-A-16x9.png" },
        hook: "See what the tide revealed", seo_description: "A field report", tags: ["Namibia"],
        pinned_comment: "What do you think?", chapters: "00:00 Opening", playlist: "Field reports",
        next_video_cta: "Watch the expedition", scores: { curiosity: 80, clarity: 90, search_relevance: 70, audience_fit: 85, uniqueness: 75, title_thumbnail_complementarity: 88 },
        rationale: "The image supplies the reveal without repeating the title.",
      }] });
    });

    renderDetail();

    expect(await screen.findByRole("heading", { name: /Candidate A/i })).toBeInTheDocument();
    expect(screen.getByText("A Skeleton Coast mystery")).toBeInTheDocument();
    expect(screen.getByText(/thumbnail-A-16x9\.png/)).toBeInTheDocument();
    expect(screen.getAllByText(/advisory/i).length).toBeGreaterThanOrEqual(6);
    expect(screen.getByText(/not objective truth/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /apply to youtube/i })).not.toBeInTheDocument();
  });

  it("shows empty, loading, and controlled error states", async () => {
    let resolvePackaging!: (response: Response) => void;
    fetchMock.mockImplementation((url: string) => {
      if (url === "/projects/1") return json({ id: 1, name: "Coast", path: "I:\\YouTube Projects\\Coast", media_files: [] });
      if (url === "/projects/1/shorts") return json([]);
      return new Promise<Response>((resolve) => { resolvePackaging = resolve; });
    });
    renderDetail();
    expect(await screen.findByText(/Loading packaging candidates/i)).toBeInTheDocument();
    resolvePackaging(new Response(JSON.stringify({ revision: "missing", candidates: [] })));
    expect(await screen.findByText(/No packaging candidates saved/i)).toBeInTheDocument();
  });

  it("registers an approved PNG and saves its title as one explicit local action", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/projects/1") return json({ id: 1, name: "Coast", path: "I:\\YouTube Projects\\Coast", media_files: [] });
      if (url === "/projects/1/shorts") return json([]);
      if (!init?.method) return json({ revision: "missing", candidates: [] });
      return json({ file: "Metadata/packaging-candidates.json", revision: revisionA }, 201);
    });
    renderDetail();
    await screen.findByText(/No packaging candidates saved/i);

    fireEvent.change(screen.getByLabelText(/Title candidate/i), { target: { value: "The coast changed overnight" } });
    fireEvent.change(screen.getByLabelText(/Approved PNG path/i), { target: { value: "I:\\Approved\\coast.png" } });
    fireEvent.change(screen.getByLabelText(/^Hook$/i), { target: { value: "See what changed" } });
    fireEvent.change(screen.getByLabelText(/SEO description/i), { target: { value: "A Skeleton Coast field report" } });
    fireEvent.change(screen.getByLabelText(/^Tags$/i), { target: { value: "Namibia, Skeleton Coast" } });
    fireEvent.change(screen.getByLabelText(/Pinned comment/i), { target: { value: "What did you see?" } });
    fireEvent.change(screen.getByLabelText(/^Chapters$/i), { target: { value: "00:00 Opening" } });
    fireEvent.change(screen.getByLabelText(/^Playlist$/i), { target: { value: "Field reports" } });
    fireEvent.change(screen.getByLabelText(/Next-video CTA/i), { target: { value: "Watch the full expedition" } });
    fireEvent.change(screen.getByLabelText(/Plain-language rationale/i), { target: { value: "Title gives context and image gives the reveal." } });
    fireEvent.click(screen.getByRole("button", { name: /Save local candidate/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/projects/1/assets/packaging", expect.objectContaining({ method: "PUT" }),
    ));
    expect(fetchMock.mock.calls.some(([url]) => url === "/projects/1/assets/thumbnails")).toBe(false);
    expect(await screen.findByText(/saved inside this project/i)).toBeInTheDocument();
  });

  it("does not silently overwrite packaging changed by another session", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/projects/1") return json({ id: 1, name: "Coast", path: "I:\\YouTube Projects\\Coast", media_files: [] });
      if (url === "/projects/1/shorts") return json([]);
      if (!init?.method) return json({ revision: revisionA, candidates: [{
        label: "A", title: "First title", thumbnail: { aspect: "16:9", file: "Thumbnails/thumbnail-A-16x9.png" }, hook: "Hook", seo_description: "Description", tags: ["Namibia"], pinned_comment: "Comment", chapters: "00:00 Start", playlist: "Reports", next_video_cta: "Watch next", scores: { curiosity: 50, clarity: 50, search_relevance: 50, audience_fit: 50, uniqueness: 50, title_thumbnail_complementarity: 50 }, rationale: "Clear pairing.",
      }] });
      return json({ detail: "Packaging candidates changed; reload before saving" }, 409);
    });
    renderDetail();
    await screen.findByRole("heading", { name: /Candidate A/i });
    fireEvent.change(screen.getByLabelText(/Title candidate/i), { target: { value: "Second title" } });
    fireEvent.change(screen.getByLabelText(/Approved PNG path/i), { target: { value: "I:\\Approved\\b.png" } });
    for (const [label, value] of [[/^Hook$/i, "Hook B"], [/SEO description/i, "Description B"], [/^Tags$/i, "Namibia"], [/Pinned comment/i, "Comment B"], [/^Chapters$/i, "00:00 Start"], [/^Playlist$/i, "Reports"], [/Next-video CTA/i, "Watch next"], [/Plain-language rationale/i, "Different pairing."]] as const) fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: /Save local candidate/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/changed.*reload/i);
    expect(screen.getByRole("button", { name: /Reload packaging candidates/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Candidate B/i })).not.toBeInTheDocument();
    const packagingWrite = fetchMock.mock.calls.find(([url, init]) => url === "/projects/1/assets/packaging" && init?.method === "PUT");
    expect(JSON.parse(packagingWrite?.[1]?.body as string)).toMatchObject({ expected_revision: revisionA, thumbnail_registration: { source_png: "I:\\Approved\\b.png", label: "B" } });
    expect(fetchMock.mock.calls.some(([url]) => url === "/projects/1/assets/thumbnails")).toBe(false);
  });
});
