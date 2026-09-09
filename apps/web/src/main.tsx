import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { HomePage } from "./pages/HomePage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { ProjectDetailPage } from "./pages/ProjectDetailPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { RetentionPage } from "./pages/RetentionPage";
import { RecommendationsPage } from "./pages/RecommendationsPage";
import { LearningPage } from "./pages/LearningPage";
import "./styles.css";

function App() { return <BrowserRouter><div className="app-shell"><nav aria-label="Main navigation"><Link to="/">Overview</Link><Link to="/projects">Projects</Link><Link to="/analytics">Analytics</Link><Link to="/retention">Retention</Link><Link to="/recommendations">Recommendations</Link><Link to="/learning">Learning</Link></nav><Routes><Route path="/" element={<HomePage />} /><Route path="/projects" element={<ProjectsPage />} /><Route path="/projects/:id" element={<ProjectDetailPage />} /><Route path="/analytics" element={<AnalyticsPage />} /><Route path="/retention" element={<RetentionPage />} /><Route path="/recommendations" element={<RecommendationsPage />} /><Route path="/learning" element={<LearningPage />} /></Routes></div></BrowserRouter>; }
const root = document.getElementById("root");
if (!root) throw new Error("Missing root element");
createRoot(root).render(<React.StrictMode><App /></React.StrictMode>);
