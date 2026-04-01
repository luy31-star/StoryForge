import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  const loc = useLocation();
  if (!token) {
    return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  }
  return <>{children}</>;
}

export function AdminRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  const user = useAuthStore((s) => s.user);
  const loc = useLocation();
  if (!token) {
    return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  }
  if (!user?.is_admin) {
    return <Navigate to="/novels" replace />;
  }
  return <>{children}</>;
}
