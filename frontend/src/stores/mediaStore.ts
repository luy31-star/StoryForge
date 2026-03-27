import { create } from "zustand";

interface MediaState {
  audioPreviewUrl: string | null;
  videoPreviewUrl: string | null;
  setAudioPreviewUrl: (url: string | null) => void;
  setVideoPreviewUrl: (url: string | null) => void;
}

export const useMediaStore = create<MediaState>((set) => ({
  audioPreviewUrl: null,
  videoPreviewUrl: null,
  setAudioPreviewUrl: (audioPreviewUrl) => set({ audioPreviewUrl }),
  setVideoPreviewUrl: (videoPreviewUrl) => set({ videoPreviewUrl }),
}));
