export interface Source {
  document_name: string;
  page_number:   number | string;
  doc_type?:     string;
  section_name?: string | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  sources?: Source[];
  confidence?: "high" | "medium" | "low";
}

export interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  createdAt: Date;
  updatedAt: Date;
}

export interface ApiResponse {
  answer:     string;
  sources:    Source[];
  confidence: "high" | "medium" | "low";
}
