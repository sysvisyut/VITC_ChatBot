import axios from "axios";
import { ApiResponse } from "@/types/chat";

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
};
