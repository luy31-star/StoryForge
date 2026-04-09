import { Navigate, Route, Routes, Outlet } from "react-router-dom";
import { AppLayout } from "@/components/AppLayout";
import { AdminRoute, ProtectedRoute } from "@/components/ProtectedRoute";
import { UserBootstrap } from "@/components/UserBootstrap";
import { useAuthStore } from "@/stores/authStore";
import { Admin } from "@/pages/Admin";
import { Dashboard } from "@/pages/Dashboard";
import { Landing } from "@/pages/Landing";
import { Login } from "@/pages/Login";
import { NovelNew } from "@/pages/NovelNew";
import { NovelShelf } from "@/pages/NovelShelf";
import { NovelWorkspace } from "@/pages/NovelWorkspace";
import { NovelMetricsPage } from "@/pages/NovelMetrics";
import { ProjectManagement } from "@/pages/ProjectManagement";
import { WorkflowEditor } from "@/pages/WorkflowEditor";
import { Register } from "@/pages/Register";
import { Recharge } from "@/pages/Recharge";
import { MyTasks } from "@/pages/MyTasks";

export default function App() {
  const user = useAuthStore((s) => s.user);

  return (
    <>
      <UserBootstrap />
      <Routes>
        <Route element={user ? <AppLayout /> : <Outlet />}>
          <Route path="/" element={<Landing />} />
        </Route>
        <Route path="/legacy-home" element={<Dashboard />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />

        <Route
          element={
            <ProtectedRoute>
              <AppLayout />
            </ProtectedRoute>
          }
        >
          <Route path="/novels" element={<NovelShelf />} />
          <Route path="/tasks" element={<MyTasks />} />
          <Route path="/novels/new" element={<NovelNew />} />
          <Route path="/novels/:id" element={<NovelWorkspace />} />
          <Route path="/novels/:id/metrics" element={<NovelMetricsPage />} />
          <Route path="/recharge" element={<Recharge />} />
          <Route
            path="/editor"
            element={
              <AdminRoute>
                <WorkflowEditor />
              </AdminRoute>
            }
          />
          <Route
            path="/projects"
            element={
              <AdminRoute>
                <ProjectManagement />
              </AdminRoute>
            }
          />
          <Route
            path="/admin"
            element={
              <AdminRoute>
                <Admin />
              </AdminRoute>
            }
          />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
