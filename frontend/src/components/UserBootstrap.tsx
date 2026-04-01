import { useEffect } from "react";
import { fetchMe } from "@/services/authApi";
import { useAuthStore } from "@/stores/authStore";

/** 有 token 时刷新 /me，同步积分与管理员标记 */
export function UserBootstrap() {
  const token = useAuthStore((s) => s.token);
  const setUser = useAuthStore((s) => s.setUser);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    fetchMe(token)
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch(() => {
        /* 忽略：token 失效时由各 API 返回 401 */
      });
    return () => {
      cancelled = true;
    };
  }, [token, setUser]);

  return null;
}
