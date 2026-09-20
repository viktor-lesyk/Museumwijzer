from .fetch_page import FETCH_PAGE_TOOL_SPEC, execute_fetch_page
from .web_search import WEB_SEARCH_TOOL_SPEC, execute_web_search

AGENT_TOOLS = [FETCH_PAGE_TOOL_SPEC, WEB_SEARCH_TOOL_SPEC]

__all__ = [
    "AGENT_TOOLS",
    "FETCH_PAGE_TOOL_SPEC",
    "WEB_SEARCH_TOOL_SPEC",
    "execute_fetch_page",
    "execute_web_search",
]
