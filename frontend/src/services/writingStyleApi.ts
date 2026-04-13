import { apiFetch } from "./api";

export interface WritingStyle {
  id: string;
  name: string;
  reference_author?: string;
  lexicon: {
    tags: string[];
    rules: string[];
    forbidden: string[];
  };
  structure: {
    sentence_length?: number;
    complexity?: string;
    line_break?: string;
    punctuation?: string;
    rules: string[];
  };
  tone: {
    primary: string[];
    description?: string;
    rules: string[];
  };
  rhetoric: {
    types: Record<string, string>;
    rules: string[];
  };
  negative_prompts: string[];
  snippets: string[];
  created_at: string;
  updated_at: string;
}

export async function listWritingStyles(): Promise<WritingStyle[]> {
  const resp = await apiFetch("/api/writing-styles");
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function getWritingStyle(id: string): Promise<WritingStyle> {
  const resp = await apiFetch(`/api/writing-styles/${id}`);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function createWritingStyle(data: Partial<WritingStyle>): Promise<WritingStyle> {
  const resp = await apiFetch("/api/writing-styles", {
    method: "POST",
    body: JSON.stringify(data),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function updateWritingStyle(id: string, data: Partial<WritingStyle>): Promise<WritingStyle> {
  const resp = await apiFetch(`/api/writing-styles/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function deleteWritingStyle(id: string): Promise<void> {
  const resp = await apiFetch(`/api/writing-styles/${id}`, {
    method: "DELETE",
  });
  if (!resp.ok) throw new Error(await resp.text());
}

export async function analyzeSnippet(text: string): Promise<Partial<WritingStyle>> {
  const resp = await apiFetch("/api/writing-styles/analyze-snippet", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export interface AuthorSearchResult {
  name: string;
  works: string[];
  description: string;
}

export async function searchAuthors(author: string): Promise<AuthorSearchResult[]> {
  const resp = await apiFetch("/api/writing-styles/search-authors", {
    method: "POST",
    body: JSON.stringify({ author }),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function fetchSnippets(author: string, works: string[]): Promise<string[]> {
  const resp = await apiFetch("/api/writing-styles/fetch-snippets", {
    method: "POST",
    body: JSON.stringify({ author, works }),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

export async function searchAuthorStyle(author: string): Promise<Partial<WritingStyle>> {
  const resp = await apiFetch("/api/writing-styles/search-author", {
    method: "POST",
    body: JSON.stringify({ author }),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}
