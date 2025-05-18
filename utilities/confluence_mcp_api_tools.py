# confluence_mcp_api_tools.py

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# These functions generate natural language queries to be sent to the MCPAgent.
# The MCPAgent will then attempt to use the actual tools exposed by the 
# Atlassian MCP server to fulfill these requests.

def format_date_query_suffix(start_date: Optional[str], end_date: Optional[str]) -> str:
    """Helper to create the date part of a query."""
    date_query_parts = []
    if start_date:
        date_query_parts.append(f"from {start_date}")
    if end_date:
        date_query_parts.append(f"to {end_date}")
    
    if date_query_parts:
        return " updated " + " ".join(date_query_parts)
    return ""

def get_pages_in_space_query(space_name: str, start_date: Optional[str], end_date: Optional[str]) -> str:
    """
    Generates a query to get HTML content of pages within a specific space,
    optionally filtered by update dates.
    """
    date_suffix = format_date_query_suffix(start_date, end_date)
    query = f"Get HTML content for all pages in space '{space_name}'{date_suffix}."
    logger.debug(f"Generated query for MCPAgent: {query}")
    return query

def get_page_content_query(
    page_id: Optional[str] = None,
    page_name: Optional[str] = None,
    space_name: Optional[str] = None,
    start_date: Optional[str] = None, # To check if the specific page was updated in this range
    end_date: Optional[str] = None
) -> str:
    """
    Generates a query to get HTML content of a specific page, identified by ID or name/space.
    Date filters might apply to the page's last update if the MCP server supports it.
    """
    date_suffix = format_date_query_suffix(start_date, end_date)
    
    if page_id:
        query = f"Get HTML content for page with ID '{page_id}'{date_suffix}."
    elif page_name and space_name:
        query = f"Get HTML content for page titled '{page_name}' in space '{space_name}'{date_suffix}."
    elif page_name:
        query = f"Get HTML content for page titled '{page_name}'{date_suffix}."
    else:
        # This is an error condition message, so log it as a warning if it's generated.
        # The function returns the error string which is then handled by the API layer.
        error_message = "Error: Insufficient information to identify the page. Provide page_id or page_name (optionally with space_name)."
        logger.warning(f"Generated error message due to insufficient page info: {error_message}")
        return error_message
    
    logger.debug(f"Generated query for MCPAgent: {query}")
    return query

def get_pages_in_all_spaces_query(start_date: Optional[str], end_date: Optional[str]) -> str:
    """
    Generates a query to get HTML content of pages from all accessible spaces,
    optionally filtered by update dates.
    """
    date_suffix = format_date_query_suffix(start_date, end_date)
    query = f"Get HTML content for all pages from all accessible spaces{date_suffix}."
    logger.debug(f"Generated query for MCPAgent: {query}")
    return query 