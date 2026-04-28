#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js"
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js"
import { z } from "zod"
import * as path from "path"
import * as os from "os"
import { bingSearch } from "./search.js"
import { CommandOptions } from "./types.js"

const STATE_FILE_PATH = path.join(os.homedir(), ".bing-search-browser-state.json")
const DEFAULT_TIMEOUT = 60000
const DEFAULT_LIMIT = 10
const DEFAULT_LANGUAGE = "zh-CN"
const DEFAULT_REGION = "cn"

const server = new McpServer({
  name: "Bing Search MCP",
  version: "1.0.0"
})

server.tool(
  "search",
  { 
    query: z.string().describe("搜索查询字符串"),
    limit: z.number().optional().describe("返回的搜索结果数量，默认为10。注意：Bing搜索结果有时不太相关，建议酌情增加返回数量（如15-20条）以获得更多可选结果"),
    timeout: z.number().optional().describe("搜索操作的超时时间(毫秒)，默认为60000"),
    language: z.string().optional().describe("搜索结果的语言，例如 zh-CN, en-US 等，默认为 zh-CN"),
    region: z.string().optional().describe("搜索结果的地区，默认为 cn")
  },
  async ({ 
    query, 
    limit = DEFAULT_LIMIT, 
    timeout = DEFAULT_TIMEOUT,
    language = DEFAULT_LANGUAGE,
    region = DEFAULT_REGION
  }: { 
    query: string; 
    limit?: number; 
    timeout?: number;
    language?: string;
    region?: string;
  }) => {
    try {
      const options: CommandOptions = {
        limit,
        timeout,
        stateFile: STATE_FILE_PATH,
        locale: language,
        region
      }
      
      const results = await bingSearch(query, options)
      
      return {
        content: [{ 
          type: "text", 
          text: JSON.stringify(results, null, 2)
        }]
      }
    } catch (error: any) {
      return {
        content: [{ type: "text", text: `执行 Bing 搜索时出错: ${error.message}` }],
        isError: true
      }
    }
  }
)

async function main() {
  try {
    const transport = new StdioServerTransport()
    await server.connect(transport)
    console.error("Bing Search MCP 服务器已启动")
  } catch (error: any) {
    console.error("启动 Bing Search MCP 服务器时出错:", error)
    process.exit(1)
  }
}

main()