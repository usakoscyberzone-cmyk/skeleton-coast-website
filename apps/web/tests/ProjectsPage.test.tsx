import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProjectDetailPage } from "../src/pages/ProjectDetailPage";
import { ProjectsPage } from "../src/pages/ProjectsPage";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

describe("ProjectsPage", () => {
  it("renders one card for every API-discovered master-folder project", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify([
      { id: 1, name: "Pilchard Mortality", path: "I:\\YouTube Projects\\Pilchard Mortality" },
      { id: 2, name: "Skeleton Coast Sharks", path: "I:\\YouTube Projects\\Skeleton Coast Sharks" },
    ])));

    render(<MemoryRouter><ProjectsPage /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Pilchard Mortality" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Skeleton Coast Sharks" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/projects", expect.anything());
  });

  it("makes an empty discovered-project state clear", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify([])));
    render(<MemoryRouter><ProjectsPage /></MemoryRouter>);
    expect(await screen.findByText(/No projects have been discovered/i)).toBeInTheDocument();
  });
});

describe("ProjectDetailPage", () => {
  function renderDetail(id = "1") {
    return render(
      <MemoryRouter initialEntries={[`/projects/${id}`]}>
        <Routes><Route path="/projects/:id" element={<ProjectDetailPage />} /></Routes>
      </MemoryRouter>,
    );
  }

  it("renders nullable probe metadata as unavailable and makes probe errors visible", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({
      id: 1, name: "Pilchard Mortality", path: "I:\\YouTube Projects\\Pilchard Mortality",
      media_files: [{ id: 11, path: "I:\\YouTube Projects\\Pilchard Mortality\\broken.mp4", kind: "video", duration_seconds: null, width: null, height: null, frame_rate: null, codec: null, probe_error: "ffprobe could not read this file" }],
    })));

    renderDetail();

    expect(await screen.findByRole("heading", { name: "Pilchard Mortality" })).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(screen.getByText(/ffprobe could not read this file/i)).toBeInTheDocument();
  });

  it("shows a loading state and an API error without hiding the project page", async () => {
    let rejectFetch!: (reason: Error) => void;
    fetchMock.mockReturnValue(new Promise((_, reject) => { rejectFetch = reject; }));
    renderDetail();
    expect(screen.getByText(/Loading project/i)).toBeInTheDocument();
    rejectFetch(new Error("Network unavailable"));
    expect(await screen.findByText(/Network unavailable/i)).toBeInTheDocument();
  });

  it("shows an empty media state for a discovered project", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ id: 1, name: "New Project", path: "I:\\YouTube Projects\\New Project", media_files: [] })));
    renderDetail();
    expect(await screen.findByText(/No media files have been indexed/i)).toBeInTheDocument();
  });

  it("keeps long-form context first and shows planned Shorts beneath it", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url === "/projects/1") return Promise.resolve(new Response(JSON.stringify({ id: 1, name: "Pilchard Mortality", path: "I:\\YouTube Projects\\Pilchard Mortality", media_files: [] })));
      return Promise.resolve(new Response(JSON.stringify([{ id: 8, project_id: 1, hook_type: "reveal", source_start_seconds: 2.5, source_end_seconds: 22.5, target_duration_seconds: 20, on_screen_text: "The coast changed", cta: "Watch the story", status: "planned", strategic_role: "discovery" }])));
    });
    renderDetail();
    expect(await screen.findByRole("heading", { name: /Shorts funnel/i })).toBeInTheDocument();
    expect(screen.getByText(/2.5s.*22.5s/i)).toBeInTheDocument();
    expect(screen.getByText(/No metrics have been recorded/i)).toBeInTheDocument();
  });
});
