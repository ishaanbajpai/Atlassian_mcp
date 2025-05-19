import sys
import os

# Add the project root to sys.path to allow finding sibling packages
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import asyncio
import json
import re # Import regular expressions for stripping prefixes
from typing import Dict, Any, Optional, List # Added List
import aiofiles # For async file operations
import aiofiles.os as aios # For async os operations like makedirs
import logging # Standard logging

# Import the new logging setup function
from utilities.confluence_logging_config import setup_app_logging

# from dotenv import load_dotenv # No longer needed if OpenAI keys are not handled here
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response # Added for favicon dummy handler
from pydantic import BaseModel
from contextlib import asynccontextmanager
import uvicorn

# MCPClient and MCPSession are key
from mcp_use import MCPClient, MCPSession
# Attempt to import ServerManager, assuming its location
try:
    from mcp_use.managers import ServerManager
except ImportError:
    try:
        from mcp_use.managers.server_manager import ServerManager
    except ImportError:
        ServerManager = None # Placeholder if import fails
        logging.getLogger(__name__).error("Failed to import ServerManager. Check mcp_use.managers path.")
from mcp_use.managers.tools.use_tool import UseToolFromServerTool # Corrected import path
from configs.confluence_config import OUTPUT_DIR, API_HOST, API_PORT, ATLASSIAN_MCP_SERVER_CONFIG
# DEFAULT_OPENAI_MODEL is no longer needed from configs.confluence_config

# Import the concrete LangChainAdapter
AdapterClass = None # Placeholder for the specific adapter class
try:
    from mcp_use.adapters.langchain_adapter import LangChainAdapter
    AdapterClass = LangChainAdapter
except ImportError as e_adapter_import:
    logger.error(f"Failed to import LangChainAdapter from mcp_use.adapters.langchain_adapter: {e_adapter_import}. Ensure this is the correct path.")
    # Fallback attempts removed as we now have the specific adapter path

# Get a logger for this module
logger = logging.getLogger(__name__)

# --- Global placeholders for application components ---
mcp_client_instance_api: Optional[MCPClient] = None
adapter_instance_api: Optional[LangChainAdapter] = None # Typed for clarity
server_manager_instance_api: Optional[ServerManager] = None # Typed for clarity
use_tool_executor_instance: Optional[UseToolFromServerTool] = None

# --- FastAPI Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_client_instance_api, adapter_instance_api, server_manager_instance_api, use_tool_executor_instance
    
    setup_app_logging()
    logger.info("FastAPI app starting up...")

    try:
        logger.info("Initializing MCPClient for API...")
        mcp_client_instance_api = MCPClient.from_dict(ATLASSIAN_MCP_SERVER_CONFIG)
        if mcp_client_instance_api:
            logger.info("MCPClient initialized.")
            
            if AdapterClass: # Check if LangChainAdapter class was successfully imported
                try:
                    logger.info(f"Initializing {AdapterClass.__name__}...")
                    adapter_instance_api = AdapterClass() # LangChainAdapter()
                    logger.info(f"{AdapterClass.__name__} initialized.")
                    
                    if ServerManager:
                        try:
                            logger.info("Initializing ServerManager with client and adapter...")
                            server_manager_instance_api = ServerManager(client=mcp_client_instance_api, adapter=adapter_instance_api)
                            logger.info("ServerManager initialized.")
                            
                            try:
                                logger.info("Initializing UseToolFromServerTool with ServerManager...")
                                use_tool_executor_instance = UseToolFromServerTool(server_manager=server_manager_instance_api)
                                logger.info("UseToolFromServerTool initialized and ready for API.")
                            except Exception as e_tool_init:
                                logger.error(f"ERROR: Failed to initialize UseToolFromServerTool: {e_tool_init}", exc_info=True)
                                use_tool_executor_instance = None
                        except Exception as e_sm_init:
                            logger.error(f"ERROR: Failed to initialize ServerManager: {e_sm_init}", exc_info=True)
                            server_manager_instance_api = None
                            use_tool_executor_instance = None
                    else:
                        logger.error("ServerManager class not imported. Cannot initialize UseToolFromServerTool correctly.")
                        use_tool_executor_instance = None
                except Exception as e_adapter_init:
                    logger.error(f"ERROR: Failed to initialize {AdapterClass.__name__ if AdapterClass else 'Adapter'}: {e_adapter_init}", exc_info=True)
                    adapter_instance_api = None
                    server_manager_instance_api = None
                    use_tool_executor_instance = None
            else:
                logger.error("LangChainAdapter class not imported. Cannot initialize ServerManager or UseToolFromServerTool.")
                server_manager_instance_api = None
                use_tool_executor_instance = None
        else:
            logger.error("ERROR: Failed to initialize MCPClient. API will not function correctly.")
            adapter_instance_api = None
            server_manager_instance_api = None
            use_tool_executor_instance = None

    except Exception as e:
        logger.critical(f"CRITICAL ERROR during API startup: {e}", exc_info=True)
        mcp_client_instance_api = None
        adapter_instance_api = None
        server_manager_instance_api = None
        use_tool_executor_instance = None

    yield

    logger.info("FastAPI app shutting down...")
    if mcp_client_instance_api:
        logger.info("Closing all MCP sessions via API's client instance...")
        try:
            if hasattr(mcp_client_instance_api, 'close_all_sessions') and asyncio.iscoroutinefunction(mcp_client_instance_api.close_all_sessions):
                await mcp_client_instance_api.close_all_sessions()
            elif hasattr(mcp_client_instance_api, 'close_all_sessions'):
                 logger.warning("MCPClient.close_all_sessions is not an async function, calling synchronously.")
                 mcp_client_instance_api.close_all_sessions() 
            logger.info("MCP sessions closed via API.")
        except Exception as e_close:
            logger.error(f"Error closing MCP sessions during API shutdown: {e_close}", exc_info=True)
    else:
        logger.info("No active MCP client instance to close.")


app = FastAPI(lifespan=lifespan, title="Confluence Content MCP API")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

# --- Helper Function for Stripping Prefixes and Saving Content ---
COMMON_PREFIXES_REGEX = [
    re.compile(r"^Here is the HTML content for the page with ID '[\w\d-]+':\s*", re.IGNORECASE),
    re.compile(r"^Here's the HTML content for the page titled '[^']+'(?: in space '[^']+')?:\s*", re.IGNORECASE),
    re.compile(r"^The HTML content for page ID '[\w\d-]+' is:\s*", re.IGNORECASE),
    re.compile(r"^Okay, here is the content:\s*", re.IGNORECASE),
    re.compile(r"^Sure, here's the HTML:\s*", re.IGNORECASE)
]

def strip_known_prefixes(content: str) -> str:
    """Strips known conversational prefixes from the content string."""
    for pattern in COMMON_PREFIXES_REGEX:
        content = pattern.sub("", content, count=1) # Remove only the first match at the beginning
    return content.lstrip() # Remove any leading whitespace after stripping

async def save_content_to_file(content: str, file_path: str, raw_page_title: Optional[str] = None, page_id: Optional[str] = None):
    """Asynchronously saves content to a specified file path, creating directories if needed."""
    try:
        # Sanitize title and ID for filename components
        safe_page_title = "".join(c if c.isalnum() else '_' for c in (raw_page_title or "untitled"))
        safe_page_id = "".join(c if c.isalnum() else '_' for c in (page_id or "no_id"))

        # Construct filename if title and ID are provided for page content
        if raw_page_title and page_id: # Specifically for single page content
            # Ensure directory path uses only the base_path, not the full file_path with old name
            base_dir = os.path.dirname(file_path) 
            file_name_to_save = f"{safe_page_title}_{safe_page_id}.md"
            actual_file_path = os.path.join(base_dir, file_name_to_save)
        else:
            actual_file_path = file_path # Use the provided file_path for other cases (space, all)
        
        dir_name = os.path.dirname(actual_file_path)
        if dir_name:
            await aios.makedirs(dir_name, exist_ok=True)
        
        cleaned_content = strip_known_prefixes(content)
        
        async with aiofiles.open(actual_file_path, mode='w', encoding='utf-8') as f:
            await f.write(cleaned_content)
        logger.info(f"Successfully saved cleaned content to {actual_file_path}")
    except Exception as e:
        # Use actual_file_path if available, otherwise fallback to file_path for logging
        log_path = actual_file_path if 'actual_file_path' in locals() else file_path
        logger.error(f"Error saving content to {log_path}: {e}", exc_info=True)

# --- API Request and Response Models ---
# GeneralQueryRequest and GeneralQueryResponse are being removed as the endpoint using them is removed
# class GeneralQueryRequest(BaseModel):
#     query: str

# class GeneralQueryResponse(BaseModel):
#     response: Optional[str] = None
#     error: Optional[str] = None

class SpaceContentRequest(BaseModel):
    space_name: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class PageContentRequest(BaseModel):
    page_id: Optional[str] = None
    page_name: Optional[str] = None
    space_name: Optional[str] = None 
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    recursive: bool = False

class AllContentRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class ContentResponse(BaseModel):
    data: Optional[Any] = None
    message: Optional[str] = None
    error: Optional[str] = None

# --- Helper function to check for MCP authentication errors ---
def is_mcp_auth_error(e: Exception) -> bool:
    error_str = str(e).lower()
    auth_keywords = ["401", "unauthorized", "authentication failed", "token", "credential"]
    connectivity_keywords = ["connection refused", "service unavailable", "503", "proxy error", "mcpclient error", "failed to connect"]

    for keyword in auth_keywords:
        if keyword in error_str:
            return True
    for keyword in connectivity_keywords: 
        if keyword in error_str:
            logger.warning(f"Potential MCP connectivity issue detected: {e}", exc_info=True) 
            return True
    return False

# --- Helper Function to get Atlassian Cloud ID (Uses UseToolFromServerTool) ---
async def _get_cloud_id() -> Optional[str]:
    """Fetches the Atlassian Cloud ID using the getAccessibleAtlassianResources tool via executor."""
    global use_tool_executor_instance
    if not use_tool_executor_instance:
        logger.error("UseToolFromServerTool executor not initialized. Cannot fetch Cloud ID.")
        return None

    tool_name = "getAccessibleAtlassianResources"
    server_name = None
    if ATLASSIAN_MCP_SERVER_CONFIG.get("mcpServers"):
        server_name = list(ATLASSIAN_MCP_SERVER_CONFIG["mcpServers"].keys())[0]
    
    if not server_name:
        logger.error("Could not determine server name for getAccessibleAtlassianResources.")
        return None

    try:
        logger.info(f"Fetching accessible Atlassian resources to get Cloud ID via UseToolFromServerTool (server: {server_name}, tool: {tool_name})")
        
        response_str = await use_tool_executor_instance._arun(
            server_name=server_name,
            tool_name=tool_name,
            tool_input={} # This tool takes no parameters
        )
        
        # UseToolFromServerTool._arun returns a string. We need to parse it if it's JSON.
        # It might also return an error message string.
        try:
            resources_response = json.loads(response_str)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response from {tool_name}: {response_str[:200]}")
            # Check if the response_str itself is an error message from UseToolFromServerTool
            if "not found" in response_str.lower() or "error" in response_str.lower():
                 logger.error(f"Error message from UseToolFromServerTool: {response_str}")
            return None

        if isinstance(resources_response, list) and resources_response:
            first_resource = resources_response[0]
            if isinstance(first_resource, dict) and "id" in first_resource:
                cloud_id = first_resource["id"]
                logger.info(f"Found Cloud ID (from 'id' key): {cloud_id}")
                return cloud_id
            else:
                logger.error(f"Cloud ID (expected in 'id' key) not found in the first resource. Resource structure: {str(first_resource)[:200]}")
                return None
        else:
            logger.error(f"Unexpected response format or empty list from {tool_name} after JSON parsing. Parsed Response: {str(resources_response)[:200]}")
            return None
            
    except Exception as e:
        # This might catch errors from _arun itself or other issues.
        logger.error(f"Error executing {tool_name} via UseToolFromServerTool: {e}", exc_info=True)
        return None

async def _fetch_and_save_page_content(
    server_name: str, 
    cloud_id: str, 
    page_id: str, 
    page_name_hint: Optional[str], 
    base_save_dir: str,
    parent_page_id_for_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Helper function to fetch, parse, and save content for a single page using UseToolFromServerTool."""
    global use_tool_executor_instance
    if not use_tool_executor_instance:
        logger.error(f"UseToolFromServerTool executor not initialized. Cannot fetch page {page_id}.")
        return {"id": page_id, "title": page_name_hint, "saved": False, "error": "Tool executor not initialized"}

    tool_name = "getConfluencePage"
    tool_params = {"cloudId": cloud_id, "pageId": page_id}
    logger.info(f"Fetching content for page ID: {page_id} via executor (server: {server_name}, tool: '{tool_name}', params: {tool_params})")
    
    try:
        response_str = await use_tool_executor_instance._arun(
            server_name=server_name,
            tool_name=tool_name,
            tool_input=tool_params
        )

        try:
            tool_response = json.loads(response_str)
            logger.info(f"For page_id {page_id}, PARSED tool_response from {tool_name}: {tool_response}")
            if isinstance(tool_response, dict):
                logger.info(f"For page_id {page_id}, tool_response keys: {list(tool_response.keys())}")
            html_content = None
            page_title_from_response = tool_response.get("title", page_name_hint or f"page_{page_id}")
            page_id_from_response = tool_response.get("id", page_id)

            if "html" in tool_response and isinstance(tool_response["html"], str):
                html_content = tool_response["html"]
            elif "body" in tool_response:
                if isinstance(tool_response["body"], str):
                    html_content = tool_response["body"]
                elif isinstance(tool_response["body"], dict):
                    if "view" in tool_response["body"] and isinstance(tool_response["body"]["view"], dict) and \
                       "value" in tool_response["body"]["view"] and isinstance(tool_response["body"]["view"]["value"], str):
                        html_content = tool_response["body"]["view"]["value"]
                    elif "storage" in tool_response["body"] and isinstance(tool_response["body"]["storage"], dict) and \
                         "value" in tool_response["body"]["storage"] and isinstance(tool_response["body"]["storage"]["value"], str):
                        html_content = tool_response["body"]["storage"]["value"]
                    elif "raw" in tool_response["body"] and isinstance(tool_response["body"]["raw"], str):
                         html_content = tool_response["body"]["raw"]
            
            if html_content is not None:
                current_page_save_dir = base_save_dir
                if parent_page_id_for_path:
                    current_page_save_dir = os.path.join(base_save_dir, f"page_{parent_page_id_for_path}_descendants")
                
                await save_content_to_file(
                    content=html_content,
                    file_path=os.path.join(current_page_save_dir, f"page_{page_id_from_response}.html"),
                    raw_page_title=page_title_from_response,
                    page_id=page_id_from_response
                )
                return {"id": page_id_from_response, "title": page_title_from_response, "saved": True, "path_segment": f"page_{parent_page_id_for_path}_descendants" if parent_page_id_for_path else ""}
            else:
                logger.warning(f"Could not extract HTML content from tool response for page {page_id_from_response}. Response keys: {list(tool_response.keys())}")
                return {"id": page_id_from_response, "title": page_title_from_response, "saved": False, "error": "No HTML content found"}
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response from {tool_name} for page {page_id}: {response_str[:200]}")
            if "not found" in response_str.lower() or "error" in response_str.lower():
                logger.error(f"Error message from UseToolFromServerTool execution of {tool_name} for page {page_id}: {response_str}")
            return {"id": page_id, "title": page_name_hint, "saved": False, "error": f"Failed to parse response for {tool_name}"}
        except Exception as e_fetch:
            logger.error(f"Error executing/saving page ID {page_id} via executor: {e_fetch}", exc_info=True)
            return {"id": page_id, "title": page_name_hint, "saved": False, "error": str(e_fetch)}
    except Exception as e_fetch:
        logger.error(f"Error executing/saving page ID {page_id} via executor: {e_fetch}", exc_info=True)
        return {"id": page_id, "title": page_name_hint, "saved": False, "error": str(e_fetch)}

# --- API Endpoints ---
@app.post("/space/content", response_model=ContentResponse, tags=["Confluence Content"])
async def get_space_content_api(request: SpaceContentRequest):
    global use_tool_executor_instance
    if not use_tool_executor_instance:
        logger.error("UseToolFromServerTool executor not initialized. Cannot get space content.")
        raise HTTPException(status_code=503, detail="Tool executor not initialized.")

    if not request.space_name:
        raise HTTPException(status_code=400, detail="space_name is required.")

    server_name_for_calls = None
    if ATLASSIAN_MCP_SERVER_CONFIG.get("mcpServers"):
        server_name_for_calls = list(ATLASSIAN_MCP_SERVER_CONFIG["mcpServers"].keys())[0]
    if not server_name_for_calls:
        logger.error("Could not determine server name for space content retrieval operations.")
        raise HTTPException(status_code=500, detail="Server configuration error for tool execution.")

    found_space_id = None
    all_pages_data = []

    try:
        cloud_id = await _get_cloud_id()
        if not cloud_id:
            logger.error(f"Failed to retrieve Cloud ID for space content request (space_name: {request.space_name}).")
            raise HTTPException(status_code=503, detail="Failed to retrieve necessary Cloud ID from Atlassian.")

        spaces_tool_name = "getConfluenceSpaces"
        logger.info(f"Fetching all spaces to find ID for space name: '{request.space_name}' via executor (server: {server_name_for_calls}, tool: {spaces_tool_name})")
        
        spaces_response_str = await use_tool_executor_instance._arun(
            server_name=server_name_for_calls,
            tool_name=spaces_tool_name,
            tool_input={"cloudId": cloud_id}
        )
        
        try:
            spaces_response = json.loads(spaces_response_str)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response from {spaces_tool_name}: {spaces_response_str[:200]}")
            if "not found" in spaces_response_str.lower() or "error" in spaces_response_str.lower():
                logger.error(f"Error message from UseToolFromServerTool execution of {spaces_tool_name}: {spaces_response_str}")
            raise HTTPException(status_code=500, detail=f"Error retrieving space list (parsing failed) for {request.space_name}")
        
        if isinstance(spaces_response, dict) and 'results' in spaces_response and isinstance(spaces_response['results'], list):
            spaces_list = spaces_response['results']
            for space_obj in spaces_list:
                if isinstance(space_obj, dict):
                    s_name = space_obj.get("name")
                    s_key = space_obj.get("key") 
                    s_id = space_obj.get("id")
                    if s_id and ((s_name and s_name.lower() == request.space_name.lower()) or \
                                  (s_key and s_key.lower() == request.space_name.lower())):
                        found_space_id = s_id
                        logger.info(f"Found spaceId: {found_space_id} for spaceName: {request.space_name}")
                        break
            if not found_space_id:
                logger.warning(f"Could not find spaceId for space name: '{request.space_name}'. Available spaces checked: {len(spaces_list)}")
                raise HTTPException(status_code=404, detail=f"Space '{request.space_name}' not found or ID could not be resolved.")
        else:
            logger.error(f"Unexpected response structure from {spaces_tool_name} after parsing. Expected dict with 'results' list. Got: {str(spaces_response)[:200]}")
            raise HTTPException(status_code=500, detail=f"Error retrieving space list for {request.space_name} (unexpected structure).")

        pages_tool_name = "getPagesInConfluenceSpace"
        pages_tool_params = {"cloudId": cloud_id, "spaceId": found_space_id}
        logger.info(f"Fetching pages for spaceId: {found_space_id} via executor (server: {server_name_for_calls}, tool: {pages_tool_name})")
        
        pages_response_str = await use_tool_executor_instance._arun(
            server_name=server_name_for_calls,
            tool_name=pages_tool_name,
            tool_input=pages_tool_params
        )

        try:
            pages_response = json.loads(pages_response_str)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response from {pages_tool_name} for space {found_space_id}: {pages_response_str[:200]}")
            if "not found" in pages_response_str.lower() or "error" in pages_response_str.lower():
                logger.error(f"Error message from UseToolFromServerTool execution of {pages_tool_name} for space {found_space_id}: {pages_response_str}")
            raise HTTPException(status_code=500, detail=f"Error retrieving pages for space ID {found_space_id} (parsing failed).")

        if isinstance(pages_response, dict) and 'results' in pages_response and isinstance(pages_response['results'], list):
            page_summaries_list = pages_response['results']
            logger.info(f"Found {len(page_summaries_list)} page summaries in spaceId: {found_space_id}.")
            
            # TEMPORARY LOGGING: Add this to see the structure
            if page_summaries_list:
                logger.info(f"FIRST PAGE SUMMARY DETAILS: {str(page_summaries_list[0])}") 

            safe_space_name_for_path = "".join(c if c.isalnum() else '_' for c in request.space_name)
            base_save_path = os.path.join(OUTPUT_DIR, "spaces_direct_tool", safe_space_name_for_path)

            for page_data in page_summaries_list:
                if isinstance(page_data, dict):
                    page_id = page_data.get("id")
                    page_title = page_data.get("title", f"page_{page_id}")
                    
                    if page_id:
                        # Fetch full page content for each page ID
                        logger.info(f"Fetching full content for page '{page_title}' (ID: {page_id}) in space '{request.space_name}'")
                        page_content_details = await _fetch_and_save_page_content(
                            server_name=server_name_for_calls,
                            cloud_id=cloud_id,
                            page_id=page_id,
                            page_name_hint=page_title,
                            base_save_dir=base_save_path
                        )
                        if page_content_details and page_content_details.get("saved"):
                            all_pages_data.append(page_content_details)
                        else:
                            logger.warning(f"Could not fetch or save content for page ID {page_id} in space '{request.space_name}'. Details: {page_content_details}")
                            all_pages_data.append({"id": page_id, "title": page_title, "saved": False, "error": page_content_details.get("error") if page_content_details else "Unknown error fetching page"})
                    else:
                        logger.warning(f"Skipping page in space '{request.space_name}' due to missing ID. Page summary data: {str(page_data)[:200]}")
            
            return ContentResponse(
                data={"space_id": found_space_id, "space_name": request.space_name, "pages_processed": len(all_pages_data), "page_details": all_pages_data},
                message=f"Content for space '{request.space_name}' (ID: {found_space_id}) processed. {len(all_pages_data)} pages saved."
            )
        else:
            logger.error(f"Unexpected response structure from {pages_tool_name} for spaceId {found_space_id} after parsing. Expected dict with 'results' list. Got: {str(pages_response)[:200]}")
            raise HTTPException(status_code=500, detail=f"Error retrieving pages for space ID {found_space_id} (unexpected structure).")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /space/content for space_name '{request.space_name}': {e}", exc_info=True)
        if is_mcp_auth_error(e):
            admin_message = "MCP authentication/connectivity error. Administrator action may be required."
            logger.critical(f"{admin_message} Original error: {e}")
            raise HTTPException(status_code=503, detail=admin_message)
        raise HTTPException(status_code=500, detail=f"Error processing space content request: {str(e)}")

@app.post("/page/content", response_model=ContentResponse, tags=["Confluence Content"])
async def get_page_content_api(request: PageContentRequest):
    global use_tool_executor_instance
    if not use_tool_executor_instance:
        logger.error("UseToolFromServerTool executor not initialized. Cannot get page content.")
        raise HTTPException(status_code=503, detail="Tool executor not initialized.")

    if not request.page_id and not request.page_name:
        raise HTTPException(status_code=400, detail="Either page_id or page_name must be provided.")
    
    if request.recursive and not request.page_id:
        raise HTTPException(status_code=400, detail="page_id is required for recursive fetching.")

    server_name_for_calls = None
    if ATLASSIAN_MCP_SERVER_CONFIG.get("mcpServers"):
        server_name_for_calls = list(ATLASSIAN_MCP_SERVER_CONFIG["mcpServers"].keys())[0]
    if not server_name_for_calls:
        logger.error("Could not determine server name for page content retrieval operations.")
        raise HTTPException(status_code=500, detail="Server configuration error for tool execution.")

    processed_pages_data = []

    try:
        cloud_id = await _get_cloud_id()
        if not cloud_id:
            logger.error("Failed to retrieve Cloud ID for page content request.")
            raise HTTPException(status_code=503, detail="Failed to retrieve necessary Cloud ID from Atlassian.")

        target_page_id = request.page_id
        
        if not target_page_id and request.page_name:
            # This is a placeholder. Actual search by name would require a different tool or logic.
            # For now, strictly require page_id if page_name is the only identifier.
            logger.warning("page_name provided without page_id. This endpoint primarily uses page_id for direct fetching.")
            raise HTTPException(status_code=400, detail="page_id is required when page_name is used for this endpoint. Search by name not implemented here.")

        if not target_page_id:
             # Should be caught by above checks, but as a safeguard.
            raise HTTPException(status_code=400, detail="target_page_id could not be determined for fetching.")

        base_save_dir_for_endpoint = os.path.join(OUTPUT_DIR, "pages_direct_tool")
        main_page_data = await _fetch_and_save_page_content(
            server_name=server_name_for_calls, 
            cloud_id=cloud_id, 
            page_id=target_page_id, 
            page_name_hint=request.page_name, 
            base_save_dir=base_save_dir_for_endpoint
        )
        if main_page_data:
            processed_pages_data.append(main_page_data)

        if request.recursive and target_page_id: # Ensure target_page_id is available for recursive calls
            logger.info(f"Recursive fetch requested for page ID: {target_page_id}. Fetching descendants.")
            descendants_tool_name = "getConfluencePageDescendants"
            descendants_params = {"cloudId": cloud_id, "pageId": target_page_id}
            
            descendants_response_str = await use_tool_executor_instance._arun(
                server_name=server_name_for_calls,
                tool_name=descendants_tool_name,
                tool_input=descendants_params
            )

            try:
                descendants_response = json.loads(descendants_response_str)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON response from {descendants_tool_name} for page {target_page_id}: {descendants_response_str[:200]}")
                if "not found" in descendants_response_str.lower() or "error" in descendants_response_str.lower():
                    logger.error(f"Error message from UseToolFromServerTool for {descendants_tool_name} on page {target_page_id}: {descendants_response_str}")
                # Logged error, but continue to return data for main page if fetched
            else:
                if isinstance(descendants_response, list):
                    logger.info(f"Found {len(descendants_response)} descendants for page ID: {target_page_id}.")
                    for descendant_summary in descendants_response:
                        if isinstance(descendant_summary, dict) and "id" in descendant_summary:
                            descendant_id = descendant_summary["id"]
                            descendant_title_hint = descendant_summary.get("title")
                            logger.info(f"Fetching content for descendant page ID: {descendant_id}")
                            descendant_page_data = await _fetch_and_save_page_content(
                                server_name=server_name_for_calls,
                                cloud_id=cloud_id, 
                                page_id=descendant_id, 
                                page_name_hint=descendant_title_hint, 
                                base_save_dir=base_save_dir_for_endpoint, 
                                parent_page_id_for_path=target_page_id 
                            )
                            if descendant_page_data:
                                processed_pages_data.append(descendant_page_data)
                        else:
                            logger.warning(f"Skipping descendant summary due to missing ID or invalid format: {str(descendant_summary)[:100]}")
                else:
                    logger.warning(f"Unexpected response type from {descendants_tool_name} for page ID {target_page_id} after parsing: {type(descendants_response)}. Response: {str(descendants_response)[:200]}")
        
        return ContentResponse(
            data={"pages_processed_details": processed_pages_data, "recursive_request": request.recursive},
            message=f"Page content retrieval complete. Processed {len(processed_pages_data)} page(s)."
        )

    except HTTPException: 
        raise
    except Exception as e:
        logger.error(f"Error in /page/content for page_id '{request.page_id}': {e}", exc_info=True)
        if is_mcp_auth_error(e):
            admin_message = "MCP authentication/connectivity error. Administrator action may be required."
            logger.critical(f"{admin_message} Original error: {e}")
            raise HTTPException(status_code=503, detail=admin_message)
        raise HTTPException(status_code=500, detail=f"Error processing page content request: {str(e)}")

@app.post("/all/content", response_model=ContentResponse, tags=["Confluence Content"])
async def get_all_spaces_content_api(request: AllContentRequest):
    global use_tool_executor_instance
    if not use_tool_executor_instance:
        logger.error("UseToolFromServerTool executor not initialized. Cannot get all content.")
        raise HTTPException(status_code=503, detail="Tool executor not initialized.")

    server_name_for_calls = None
    if ATLASSIAN_MCP_SERVER_CONFIG.get("mcpServers"):
        server_name_for_calls = list(ATLASSIAN_MCP_SERVER_CONFIG["mcpServers"].keys())[0]
    if not server_name_for_calls:
        logger.error("Could not determine server name for all content retrieval operations.")
        raise HTTPException(status_code=500, detail="Server configuration error for tool execution.")

    processed_spaces_summary = []

    try:
        cloud_id = await _get_cloud_id()
        if not cloud_id:
            logger.error("Failed to retrieve Cloud ID for all content request.")
            raise HTTPException(status_code=503, detail="Failed to retrieve necessary Cloud ID from Atlassian.")

        spaces_tool_name = "getConfluenceSpaces"
        logger.info(f"Fetching all spaces for cloudId: {cloud_id} via executor (server: {server_name_for_calls}, tool: {spaces_tool_name})")
        
        spaces_response_str = await use_tool_executor_instance._arun(
            server_name=server_name_for_calls,
            tool_name=spaces_tool_name,
            tool_input={"cloudId": cloud_id}
        )

        try:
            spaces_response = json.loads(spaces_response_str)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON response from {spaces_tool_name} (all content): {spaces_response_str[:200]}")
            if "not found" in spaces_response_str.lower() or "error" in spaces_response_str.lower():
                logger.error(f"Error message from UseToolFromServerTool for {spaces_tool_name} (all content): {spaces_response_str}")
            raise HTTPException(status_code=500, detail="Error retrieving space list for all content (parsing failed).")
        
        if not (isinstance(spaces_response, dict) and 'results' in spaces_response and isinstance(spaces_response['results'], list)):
            logger.error(f"Unexpected response structure from {spaces_tool_name} when fetching all spaces (parsed). Expected dict with 'results' list. Got: {str(spaces_response)[:200]}")
            raise HTTPException(status_code=500, detail="Error retrieving space list for all content (unexpected structure).")

        spaces_list = spaces_response['results']
        logger.info(f"Found {len(spaces_list)} spaces. Processing each...")

        for space_data in spaces_list:
            if not isinstance(space_data, dict):
                logger.warning(f"Skipping non-dict item in spaces_response: {str(space_data)[:100]}")
                continue
            
            current_space_id = space_data.get("id")
            current_space_name = space_data.get("name", f"space_{current_space_id}")
            current_space_key = space_data.get("key")
            pages_in_current_space_count = 0 # Renamed to avoid conflict with pages_response list later
            current_space_page_fetch_details = [] 
            
            if not current_space_id:
                logger.warning(f"Skipping space due to missing ID. Space data: {str(space_data)[:200]}")
                processed_spaces_summary.append({"space_id": None, "space_name": current_space_name, "error": "Missing space ID"})
                continue

            logger.info(f"Fetching pages for space: '{current_space_name}' (ID: {current_space_id}, Key: {current_space_key}) via executor")
            
            pages_tool_name = "getPagesInConfluenceSpace"
            pages_tool_params = {"cloudId": cloud_id, "spaceId": current_space_id}
            try:
                pages_list_response_str = await use_tool_executor_instance._arun(
                    server_name=server_name_for_calls,
                    tool_name=pages_tool_name,
                    tool_input=pages_tool_params
                )

                try:
                    pages_list_response = json.loads(pages_list_response_str) # This is a list of page summaries
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse JSON from {pages_tool_name} for space {current_space_id}: {pages_list_response_str[:200]}")
                    if "not found" in pages_list_response_str.lower() or "error" in pages_list_response_str.lower():
                        logger.error(f"Error message from UseToolFromServerTool for {pages_tool_name}, space {current_space_id}: {pages_list_response_str}")
                    processed_spaces_summary.append({
                        "space_id": current_space_id, 
                        "space_name": current_space_name, 
                        "space_key": current_space_key,
                        "pages_found_and_processed": 0,
                        "error": f"Failed to parse pages list for space {current_space_id}"
                    })
                    continue 

                if isinstance(pages_list_response, dict) and 'results' in pages_list_response and isinstance(pages_list_response['results'], list):
                    page_summary_list_for_space = pages_list_response['results']
                    pages_in_current_space_count = len(page_summary_list_for_space)
                    logger.info(f"Found {pages_in_current_space_count} page summaries in space '{current_space_name}'. Fetching full content for each.")
                    
                    safe_space_name_for_path = "".join(c if c.isalnum() else '_' for c in current_space_name)
                    base_save_path = os.path.join(OUTPUT_DIR, "all_spaces_direct_tool", safe_space_name_for_path)

                    for page_summary_item in page_summary_list_for_space: 
                        if isinstance(page_summary_item, dict):
                            page_id = page_summary_item.get("id")
                            page_title = page_summary_item.get("title", f"page_{page_id}")
                            
                            if page_id:
                                logger.info(f"Fetching full content for page '{page_title}' (ID: {page_id}) in space '{current_space_name}' (all content endpoint)")
                                page_content_details = await _fetch_and_save_page_content(
                                    server_name=server_name_for_calls,
                                    cloud_id=cloud_id,
                                    page_id=page_id,
                                    page_name_hint=page_title,
                                    base_save_dir=base_save_path
                                )
                                if page_content_details:
                                    current_space_page_fetch_details.append(page_content_details)
                                else:
                                    # This case should ideally be handled within _fetch_and_save_page_content which returns a dict
                                    logger.error(f"_fetch_and_save_page_content returned None for page ID {page_id}")
                                    current_space_page_fetch_details.append({"id": page_id, "title": page_title, "saved": False, "error": "Helper function returned None"})
                            else:
                                logger.warning(f"Skipping page in space '{current_space_name}' due to missing ID in summary. Page summary: {str(page_summary_item)[:100]}")
                                current_space_page_fetch_details.append({"id": None, "title": "Unknown (missing ID)", "saved": False, "error": "Missing ID in page summary"})
                        else:
                            logger.warning(f"Unexpected item type in page summary list for space '{current_space_name}': {type(page_summary_item)}")
                else:
                    logger.error(f"Unexpected response from {pages_tool_name} for spaceId {current_space_id} after parsing: {str(pages_list_response)[:200]}")
                
                processed_spaces_summary.append({
                    "space_id": current_space_id, 
                    "space_name": current_space_name, 
                    "space_key": current_space_key,
                    "pages_found_in_summary": pages_in_current_space_count,
                    "page_fetch_details": current_space_page_fetch_details 
                })

            except Exception as e_page_fetch_loop: 
                logger.error(f"Error in page fetching loop for space ID {current_space_id} ('{current_space_name}'): {e_page_fetch_loop}", exc_info=True)
                processed_spaces_summary.append({
                    "space_id": current_space_id, 
                    "space_name": current_space_name, 
                    "space_key": current_space_key,
                    "pages_found_in_summary": 0,
                    "error": str(e_page_fetch_loop)
                })
        
        return ContentResponse(
            data={"total_spaces_scanned": len(spaces_list), "spaces_summary": processed_spaces_summary},
            message=f"Processed all accessible spaces. {len(processed_spaces_summary)} spaces attempted."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in /all/content: {e}", exc_info=True)
        if is_mcp_auth_error(e):
            admin_message = "MCP authentication/connectivity error. Administrator action may be required."
            logger.critical(f"{admin_message} Original error: {e}")
            raise HTTPException(status_code=503, detail=admin_message)
        raise HTTPException(status_code=500, detail=f"Error processing all content request: {str(e)}")

# Ensure uvicorn uses the API_HOST and API_PORT from config when run directly
if __name__ == "__main__":
    setup_app_logging() 
    logger.info(f"Starting Uvicorn server on {API_HOST}:{API_PORT}...")
    uvicorn.run(app, host=API_HOST, port=API_PORT) 