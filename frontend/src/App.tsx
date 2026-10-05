import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { TopNavigation } from "./components/TopNavigation";
import { useSession } from "./hooks/useSession";
import { api } from "./services/api";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { CandidatesPage } from "./pages/CandidatesPage";
import { CasesPage } from "./pages/CasesPage";
import { DashboardPage } from "./pages/DashboardPage";
import { EmergingPage } from "./pages/EmergingPage";
import { InboxPage } from "./pages/InboxPage";
import { IntentsPage } from "./pages/IntentsPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { SettingsPage } from "./pages/SettingsPage";
import { SupportPage } from "./pages/SupportPage";
import { ArticlePage } from "./site/ArticlePage";
import { HomePage } from "./site/HomePage";
import { NotFoundPage } from "./site/NotFoundPage";
import { SiteLayout } from "./site/SiteLayout";
import { TopicPage } from "./site/TopicPage";
import "./site/site.css";
/** Admin portal: everything except the customer chat. */
function AdminApp() {
  const { sessionId, reset } = useSession();
  const [menuOpen, setMenuOpen] = useState(false);
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30000, retry: 1 });
  const analytics = useQuery({ queryKey: ["analytics"], queryFn: api.analytics, refetchInterval: 30000, retry: 1 });
  const inbox = useQuery({ queryKey: ["inbox", "badge"], queryFn: () => api.inbox({ handoff_status: "needs_agent" }), refetchInterval: 5000, retry: 1 });
  const badges = {
    candidates: analytics.data?.stats.pending_candidates ?? 0,
    emerging: analytics.data?.stats.emerging_open ?? 0,
    inbox: inbox.data?.counts.needs_agent ?? 0,
  };
  return (
    <div className="app-shell">
      <a href="#main" className="sr-only">Skip to content</a>
      <Sidebar open={menuOpen} onNavigate={() => setMenuOpen(false)} badges={badges} />
      <div className={`scrim ${menuOpen ? "open" : ""}`} onClick={() => setMenuOpen(false)} aria-hidden="true" />
      <div className="main">
        <TopNavigation health={health.data} healthError={health.isError} onMenu={() => setMenuOpen(true)} waiting={badges.inbox} />
        <main id="main" className="content">
          <Routes>
            <Route index element={<DashboardPage />} />
            <Route path="inbox" element={<InboxPage />} />
            <Route path="support" element={<SupportPage key={sessionId} sessionId={sessionId} onNewSession={reset} />} />
            <Route path="cases" element={<CasesPage />} />
            <Route path="cases/:caseId" element={<CasesPage />} />
            <Route path="knowledge" element={<KnowledgePage />} />
            <Route path="candidates" element={<CandidatesPage />} />
            <Route path="emerging" element={<EmergingPage />} />
            <Route path="intents" element={<IntentsPage />} />
            <Route path="analytics" element={<AnalyticsPage />} />
            <Route path="settings" element={<SettingsPage sessionId={sessionId} onNewSession={reset} />} />
            <Route path="*" element={<Navigate to="/admin" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/admin/*" element={<AdminApp />} />
      <Route element={<SiteLayout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/user" element={<HomePage />} />
        <Route path="/help/topic/:topic" element={<TopicPage />} />
        <Route path="/help/article/:articleId" element={<ArticlePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
