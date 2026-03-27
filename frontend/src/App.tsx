import { Navigate, Route, Routes } from "react-router-dom";
import { Dashboard } from "@/pages/Dashboard";
import { NovelNew } from "@/pages/NovelNew";
import { NovelShelf } from "@/pages/NovelShelf";
import { NovelWorkspace } from "@/pages/NovelWorkspace";
import { NovelMetricsPage } from "@/pages/NovelMetrics";
import { ProjectManagement } from "@/pages/ProjectManagement";
import { SettingsPage } from "@/pages/Settings";
import { WorkflowEditor } from "@/pages/WorkflowEditor";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/editor" element={<WorkflowEditor />} />
      <Route path="/projects" element={<ProjectManagement />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/novels" element={<NovelShelf />} />
      <Route path="/novels/new" element={<NovelNew />} />
      <Route path="/novels/:id" element={<NovelWorkspace />} />
      <Route path="/novels/:id/metrics" element={<NovelMetricsPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
