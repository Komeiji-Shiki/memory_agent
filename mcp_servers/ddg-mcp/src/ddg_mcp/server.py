import asyncio

from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
from pydantic import AnyUrl
import mcp.server.stdio
from duckduckgo_search import DDGS

server = Server("ddg-mcp")

@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """
    List available resources.
    Currently, no resources are exposed.
    """
    return []

@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    """
    List available prompts.
    Each prompt can have optional arguments to customize its behavior.
    """
    return [
        types.Prompt(
            name="search-results-summary",
            description="Creates a summary of search results",
            arguments=[
                types.PromptArgument(
                    name="query",
                    description="Search query to summarize results for",
                    required=True,
                ),
                types.PromptArgument(
                    name="style",
                    description="Style of the summary (brief/detailed)",
                    required=False,
                )
            ],
        )
    ]

@server.get_prompt()
async def handle_get_prompt(
    name: str, arguments: dict[str, str] | None
) -> types.GetPromptResult:
    """
    Generate a prompt by combining arguments with server state.
    """
    if name == "search-results-summary":
        if not arguments or "query" not in arguments:
            raise ValueError("Missing required 'query' argument")
        
        query = arguments.get("query")
        style = arguments.get("style", "brief")
        detail_prompt = " Give extensive details." if style == "detailed" else ""
        
        # Perform search and get results
        ddgs = DDGS()
        results = ddgs.text(query, max_results=10)
        
        results_text = "\n\n".join([
            f"Title: {result.get('title', 'No title')}\n"
            f"URL: {result.get('href', 'No URL')}\n"
            f"Description: {result.get('body', 'No description')}"
            for result in results
        ])
        
        return types.GetPromptResult(
            description=f"Summarize search results for '{query}'",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(
                        type="text",
                        text=f"Here are the search results for '{query}'. Please summarize them{detail_prompt}:\n\n{results_text}",
                    ),
                )
            ],
        )
    else:
        raise ValueError(f"Unknown prompt: {name}")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """
    List available tools.
    Each tool specifies its arguments using JSON Schema validation.
    """
    return [
        types.Tool(
            name="ddg-text-search",
            description="使用 DuckDuckGo 搜索网页。\n使用建议：\n- 英文中文搜索皆可。\n- 适合搜索正式报告、机构文档、国外新闻。",
            inputSchema={
                "type": "object",
                "properties": {
                    "keywords": {"type": "string", "description": "Search query keywords"},
                    "region": {"type": "string", "description": "Region code (e.g., wt-wt, us-en, uk-en)", "default": "cn"},
                    "safesearch": {"type": "string", "enum": ["on", "moderate", "off"], "description": "Safe search level", "default": "moderate"},
                    "timelimit": {"type": "string", "enum": ["d", "w", "m", "y"], "description": "Time limit (d=day, w=week, m=month, y=year)"},
                    "max_results": {"type": "integer", "description": "Maximum number of results to return", "default": 10},
                },
                "required": ["keywords"],
            },
        ),
        types.Tool(
            name="ddg-news-search",
            description="Search for news articles using DuckDuckGo",
            inputSchema={
                "type": "object",
                "properties": {
                    "keywords": {"type": "string", "description": "Search query keywords"},
                    "region": {"type": "string", "description": "Region code (e.g., wt-wt, us-en, uk-en)", "default": "cn"},
                    "safesearch": {"type": "string", "enum": ["on", "moderate", "off"], "description": "Safe search level", "default": "moderate"},
                    "timelimit": {"type": "string", "enum": ["d", "w", "m"], "description": "Time limit (d=day, w=week, m=month)"},
                    "max_results": {"type": "integer", "description": "Maximum number of results to return", "default": 10},
                },
                "required": ["keywords"],
            },
        ),
        types.Tool(
            name="ddg-video-search",
            description="Search for videos using DuckDuckGo",
            inputSchema={
                "type": "object",
                "properties": {
                    "keywords": {"type": "string", "description": "Search query keywords"},
                    "region": {"type": "string", "description": "Region code (e.g., wt-wt, us-en, uk-en)", "default": "cn"},
                    "safesearch": {"type": "string", "enum": ["on", "moderate", "off"], "description": "Safe search level", "default": "moderate"},
                    "timelimit": {"type": "string", "enum": ["d", "w", "m"], "description": "Time limit (d=day, w=week, m=month)"},
                    "resolution": {"type": "string", "enum": ["high", "standard"], "description": "Video resolution"},
                    "duration": {"type": "string", "enum": ["short", "medium", "long"], "description": "Video duration"},
                    "license_videos": {"type": "string", "enum": ["creativeCommon", "youtube"], "description": "Video license type"},
                    "max_results": {"type": "integer", "description": "Maximum number of results to return", "default": 10},
                },
                "required": ["keywords"],
            },
        ),
    ]

@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """
    Handle tool execution requests.
    """
    if not arguments:
        raise ValueError("Missing arguments")

    if name == "ddg-text-search":
        keywords = arguments.get("keywords")
        if not keywords:
            raise ValueError("Missing keywords")
        
        region = arguments.get("region", "cn")
        safesearch = arguments.get("safesearch", "moderate")
        timelimit = arguments.get("timelimit")
        max_results = arguments.get("max_results", 10)
        
        # Perform search
        ddgs = DDGS()
        results = ddgs.text(
            keywords=keywords,
            region=region,
            safesearch=safesearch,
            timelimit=timelimit,
            max_results=max_results
        )
        
        # Format results
        formatted_results = f"Search results for '{keywords}':\n\n"
        for i, result in enumerate(results, 1):
            formatted_results += (
                f"{i}. {result.get('title', 'No title')}\n"
                f"   URL: {result.get('href', 'No URL')}\n"
                f"   {result.get('body', 'No description')}\n\n"
            )
        
        return [
            types.TextContent(
                type="text",
                text=formatted_results,
            )
        ]
    
    elif name == "ddg-news-search":
        keywords = arguments.get("keywords")
        if not keywords:
            raise ValueError("Missing keywords")
        
        region = arguments.get("region", "cn")
        safesearch = arguments.get("safesearch", "moderate")
        timelimit = arguments.get("timelimit")
        max_results = arguments.get("max_results", 10)
        
        # Perform search
        ddgs = DDGS()
        results = ddgs.news(
            keywords=keywords,
            region=region,
            safesearch=safesearch,
            timelimit=timelimit,
            max_results=max_results
        )
        
        # Format results
        formatted_results = f"News search results for '{keywords}':\n\n"
        for i, result in enumerate(results, 1):
            formatted_results += (
                f"{i}. {result.get('title', 'No title')}\n"
                f"   Source: {result.get('source', 'Unknown')}\n"
                f"   Date: {result.get('date', 'No date')}\n"
                f"   URL: {result.get('url', 'No URL')}\n"
                f"   {result.get('body', 'No description')}\n\n"
            )
        
        return [
            types.TextContent(
                type="text",
                text=formatted_results,
            )
        ]
    
    elif name == "ddg-video-search":
        keywords = arguments.get("keywords")
        if not keywords:
            raise ValueError("Missing keywords")
        
        region = arguments.get("region", "cn")
        safesearch = arguments.get("safesearch", "moderate")
        timelimit = arguments.get("timelimit")
        resolution = arguments.get("resolution")
        duration = arguments.get("duration")
        license_videos = arguments.get("license_videos")
        max_results = arguments.get("max_results", 10)
        
        # Perform search
        ddgs = DDGS()
        results = ddgs.videos(
            keywords=keywords,
            region=region,
            safesearch=safesearch,
            timelimit=timelimit,
            resolution=resolution,
            duration=duration,
            license_videos=license_videos,
            max_results=max_results
        )
        
        # Format results
        formatted_results = f"Video search results for '{keywords}':\n\n"
        for i, result in enumerate(results, 1):
            formatted_results += (
                f"{i}. {result.get('title', 'No title')}\n"
                f"   Publisher: {result.get('publisher', 'Unknown')}\n"
                f"   Duration: {result.get('duration', 'Unknown')}\n"
                f"   URL: {result.get('content', 'No URL')}\n"
                f"   Published: {result.get('published', 'No date')}\n"
                f"   {result.get('description', 'No description')}\n\n"
            )
        
        return [
            types.TextContent(
                type="text",
                text=formatted_results,
            )
        ]
    
    else:
        raise ValueError(f"Unknown tool: {name}")

async def main():
    # Run the server using stdin/stdout streams
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="ddg-mcp",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )