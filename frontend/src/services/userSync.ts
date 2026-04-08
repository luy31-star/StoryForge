import { fetchMe } from "@/services/authApi";
import { useAuthStore } from "@/stores/authStore";

export async function refreshMeSilently(): Promise<void> {
  const { token } = useAuthStore.getState();
  const { setUser } = useAuthStore.getState();
  if (!token) return;
  try {
    const me = await fetchMe(token);
    setUser(me);
  } catch {
    return;
  }
}

