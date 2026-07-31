import axios from "axios";
import { ApiResponse, Source } from "@/types/chat";

// Make this configurable through environment variables
const API_BASE_URL = import.meta.env.VITE_API_URL;

export const chatApi = {
  async sendMessage(query: string): Promise<ApiResponse> {
    try {
      const response = await axios.post<ApiResponse>(
        `${API_BASE_URL}/retrieve/`,
        { query },
        {
          headers: {
            "Content-Type": "application/json",
            "X-API-Key": import.meta.env.VITE_API_KEY || "",
          },
          timeout: 30000, // 30 second timeout
        }
      );
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error)) {
        if (error.code === "ECONNABORTED") {
          throw new Error("Request timeout. Please try again.");
        }
        if (error.response) {
          throw new Error(
            error.response.data?.detail || 
            error.response.data?.message || 
            `Server error: ${error.response.status}`
          );
        }
        if (error.request) {
          throw new Error(
            "Unable to connect to the server. Please check if the backend is running at " + API_BASE_URL
          );
        }
      }
      throw new Error("An unexpected error occurred. Please try again.");
    }
  },

  async streamMessage(
    query: string,
    onChunk: (text: string) => void,
    onComplete: (sources: Source[], confidence: "high" | "medium" | "low") => void
  ): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/stream/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": import.meta.env.VITE_API_KEY || "",
      },
      body: JSON.stringify({ query }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(errorData?.detail || `Server error: ${response.status}`);
    }

    if (!response.body) {
      throw new Error("ReadableStream not supported by the browser.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        
        let boundary = buffer.indexOf("\\n\\n");
        while (boundary !== -1) {
          const chunk = buffer.slice(0, boundary).trim();
          buffer = buffer.slice(boundary + 2);
          
          if (chunk.startsWith("data: ")) {
            const dataStr = chunk.slice(6);
            try {
              const data = JSON.parse(dataStr);
              if (data.type === "text") {
                onChunk(data.text);
              } else if (data.type === "metadata") {
                onComplete(data.sources, data.confidence);
              } else if (data.type === "error") {
                throw new Error(data.error);
              }
            } catch (e) {
              if (e instanceof SyntaxError) {
                console.error("Failed to parse SSE JSON:", dataStr);
              } else {
                throw e; // rethrow API errors
              }
            }
          }
          boundary = buffer.indexOf("\\n\\n");
        }
      }
    } finally {
      reader.releaseLock();
    }
  },
};
