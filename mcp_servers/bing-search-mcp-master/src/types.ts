export interface SearchResult {
  title: string;
  link: string;
  snippet: string;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  language: string;
  region: string;
}

export interface CommandOptions {
  limit?: number;
  timeout?: number;
  stateFile?: string;
  noSaveState?: boolean;
  locale?: string;
  region?: string;
}