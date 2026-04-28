#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import axios from "axios";

const API_KEY = process.env.BING_API_KEY;
if (!API_KEY) {
  console.error("Error: BING_API_KEY environment variable is required");
  process.exit(1);
}

const server = new McpServer({
  name: "bing-search",
  version: "1.0.0",
});

const bingApi = axios.create({
  baseURL: "https://api.bing.microsoft.com/v7.0",
  headers: { "Ocp-Apim-Subscription-Key": API_KEY },
});

server.tool(
  "search",
  {
    query: z.string().describe("The search query"),
    count: z.number().min(1).max(50).optional().default(10).describe("Number of results to return"),
  },
  async ({ query, count }) => {
    try {
      const response = await bingApi.get("/search", {
        params: {
          q: query,
          count: count,
          responseFilter: "Webpages",
          safeSearch: "Strict",
        },
      });

      const results = response.data.webPages?.value || [];
      
      if (results.length === 0) {
        return {
          content: [{ type: "text", text: "No results found." }],
        };
      }

      const formattedResults = results.map((result, index) => {
        return `[${index + 1}] ${result.name}\nURL: ${result.url}\nSnippet: ${result.snippet}\n`;
      }).join("\n---\n\n");

      return {
        content: [{ type: "text", text: formattedResults }],
      };
    } catch (error) {
      if (axios.isAxiosError(error)) {
        return {
          content: [
            {
              type: "text",
              text: `Bing API error: ${
                error.response?.data?.error?.message || error.message
              }`,
            },
          ],
          isError: true,
        };
      }
      throw error;
    }
  }
);

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Bing Search MCP server running on stdio");
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});