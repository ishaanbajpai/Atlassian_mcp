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

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
import uvicorn

# Functions to be imported from other modules
from utilities.confluence_mcp_api_tools import (
    get_pages_in_space_query,
    get_page_content_query,
    get_pages_in_all_spaces_query
)
# This function will be created in atlassian_mcp_agent.py
from agents.atlassian_mcp_agent import initialize_agent_and_client, MCPClient_class as GlobalMCPClient_class 
from configs.confluence_config import OUTPUT_DIR, DEFAULT_OPENAI_MODEL, API_HOST, API_PORT # Import new configs

# Get a logger for this module
logger = logging.getLogger(__name__)

# --- Global placeholders for application components ---
# These will be populated by the lifespan manager
agent_instance: Optional[Any] = None 
mcp_client_instance_api: Optional[Any] = None # Renamed to avoid potential confusion

# --- FastAPI Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_instance, mcp_client_instance_api
    
    # Call the logging setup at the beginning of the lifespan
    setup_app_logging()
    
    logger.info("FastAPI app starting up...")
    load_dotenv() # Load .env for OPENAI_API_KEY etc.
    
    openai_api_key = os.getenv("OPENAI_API_KEY")
    # Use DEFAULT_OPENAI_MODEL from config as fallback
    openai_model_name = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL) 

    if not openai_api_key:
        logger.critical("CRITICAL ERROR: OPENAI_API_KEY not found. API cannot fully initialize agent.")
    else:
        logger.info(f"OpenAI API Key found. Using model: {openai_model_name}")

    try:
        logger.info("Initializing MCP Agent and Client for API...")
        agent, mcp_client_ref = await initialize_agent_and_client(
            openai_api_key=openai_api_key, 
            openai_model_name=openai_model_name
        )
        if agent and mcp_client_ref:
            agent_instance = agent
            mcp_client_instance_api = mcp_client_ref
            logger.info("MCPAgent and MCPClient initialized and ready for API.")
        else:
            logger.error("ERROR: Failed to initialize MCPAgent or MCPClient. API endpoints relying on agent will not work.")

    except Exception as e:
        logger.critical(f"CRITICAL ERROR during API startup and agent initialization: {e}", exc_info=True)

    yield # API is ready and serving requests

    logger.info("FastAPI app shutting down...")
    if mcp_client_instance_api and GlobalMCPClient_class: 
        logger.info("Closing all MCP sessions via API's client instance...")
        try:
            if hasattr(mcp_client_instance_api, 'close_all_sessions') and asyncio.iscoroutinefunction(mcp_client_instance_api.close_all_sessions):
                await mcp_client_instance_api.close_all_sessions()
            elif hasattr(mcp_client_instance_api, 'close_all_sessions'):
                 mcp_client_instance_api.close_all_sessions() 
            logger.info("MCP sessions closed via API.")
        except Exception as e_close:
            logger.error(f"Error closing MCP sessions during API shutdown: {e_close}", exc_info=True)
    else:
        logger.info("No active MCP client instance to close or MCPClient_class not available.")


app = FastAPI(lifespan=lifespan, title="Confluence Content MCP API")

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
            file_name_to_save = f"{safe_page_title}_{safe_page_id}.html"
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
class GeneralQueryRequest(BaseModel):
    query: str

class GeneralQueryResponse(BaseModel):
    response: Optional[str] = None
    error: Optional[str] = None

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

# --- API Endpoints ---
@app.post("/process-general-query", response_model=GeneralQueryResponse, tags=["General"])
async def handle_general_query(request: GeneralQueryRequest):
    global agent_instance
    if not agent_instance:
        logger.error("MCPAgent not initialized. Cannot process general query.")
        raise HTTPException(status_code=503, detail="MCPAgent not initialized or initialization failed.")
    
    logger.info(f"Received general query: '{request.query}'")
    try:
        agent_response = await agent_instance.run(request.query)
        return GeneralQueryResponse(response=agent_response)
    except Exception as e:
        logger.error(f"Error processing general query '{request.query}': {e}", exc_info=True)
        if is_mcp_auth_error(e):
            admin_message = "MCP authentication/connectivity error. Administrator action required to check mcp-remote and refresh Atlassian authentication if necessary."
            logger.critical(f"{admin_message} Original error for query '{request.query}': {e}")
            raise HTTPException(status_code=503, detail=f"Service temporarily unavailable due to Atlassian MCP connection issue. {admin_message}")
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")

@app.post("/space/content", response_model=ContentResponse, tags=["Confluence Content"])
async def get_space_content_api(request: SpaceContentRequest):
    global agent_instance
    if not agent_instance:
        logger.error("MCPAgent not initialized. Cannot get space content.")
        raise HTTPException(status_code=503, detail="MCPAgent not initialized or initialization failed.")
    
    query = get_pages_in_space_query(
        space_name=request.space_name,
        start_date=request.start_date,
        end_date=request.end_date
    )
    logger.info(f"Processing space content query for space: {request.space_name}, Start: {request.start_date}, End: {request.end_date}")
    try:
        agent_response = await agent_instance.run(query)
        if agent_response:
            safe_space_name = "".join(c if c.isalnum() else '_' for c in request.space_name)
            base_save_path = os.path.join(OUTPUT_DIR, "spaces", safe_space_name)
            
            if isinstance(agent_response, list):
                logger.debug(f"Agent response is a list with {len(agent_response)} items for space '{request.space_name}'.")
                for i, page_content_item in enumerate(agent_response):
                    if isinstance(page_content_item, dict) and 'html' in page_content_item:
                        html_content = page_content_item['html']
                        page_title = page_content_item.get('title')
                        page_id_val = page_content_item.get('id')
                        file_name_placeholder = f"page_{page_id_val or i+1}.html" 
                        await save_content_to_file(html_content, os.path.join(base_save_path, file_name_placeholder), raw_page_title=page_title, page_id=page_id_val)
                    elif isinstance(page_content_item, str):
                        file_name_placeholder = f"page_{i+1}.html" 
                        await save_content_to_file(page_content_item, os.path.join(base_save_path, file_name_placeholder)) 
                    else:
                        logger.warning(f"Unexpected item type in agent response list for space '{request.space_name}': {type(page_content_item)}. Item: {str(page_content_item)[:200]}")
            elif isinstance(agent_response, str):
                logger.debug(f"Agent response is a string for space '{request.space_name}'. Saving as single file.")
                await save_content_to_file(agent_response, os.path.join(base_save_path, "full_space_content.html"))
            else:
                logger.warning(f"Agent response for space content '{request.space_name}' is not a list or string: {type(agent_response)}. Response: {str(agent_response)[:200]}")

        return ContentResponse(data=agent_response, message="Query processed. Content saving attempted.")
    except Exception as e:
        logger.error(f"Error in /space/content for space '{request.space_name}': {e}", exc_info=True)
        if is_mcp_auth_error(e):
            admin_message = "MCP authentication/connectivity error. Administrator action required to check mcp-remote and refresh Atlassian authentication if necessary."
            logger.critical(f"{admin_message} Original error for space '{request.space_name}': {e}")
            raise HTTPException(status_code=503, detail=f"Service temporarily unavailable due to Atlassian MCP connection issue. {admin_message}")
        raise HTTPException(status_code=500, detail=f"Error processing space content query: {str(e)}")

@app.post("/page/content", response_model=ContentResponse, tags=["Confluence Content"])
async def get_page_content_api(request: PageContentRequest):
    global agent_instance
    if not agent_instance:
        logger.error("MCPAgent not initialized. Cannot get page content.")
        raise HTTPException(status_code=503, detail="MCPAgent not initialized or initialization failed.")

    query = get_page_content_query(
        page_id=request.page_id,
        page_name=request.page_name,
        space_name=request.space_name,
        start_date=request.start_date,
        end_date=request.end_date
    )
    if query.startswith("Error:"): 
        logger.warning(f"Invalid page content request: {query}. Parameters: ID={request.page_id}, Name={request.page_name}, Space={request.space_name}")
        raise HTTPException(status_code=400, detail=query)
    
    logger.info(f"Processing page content query. Page ID: {request.page_id}, Name: {request.page_name}, Space: {request.space_name}, Start: {request.start_date}, End: {request.end_date}")
    try:
        agent_response = await agent_instance.run(query)
        if agent_response and isinstance(agent_response, str):
            space_folder_name = "unknown_space"
            if request.space_name:
                space_folder_name = "".join(c if c.isalnum() else '_' for c in request.space_name)
            
            base_save_dir = os.path.join(OUTPUT_DIR, "pages", space_folder_name)
            dummy_filename = f"{(request.page_name or request.page_id or 'temp')}.html" 
            full_path_for_save_func = os.path.join(base_save_dir, dummy_filename)

            await save_content_to_file(agent_response, full_path_for_save_func, raw_page_title=request.page_name, page_id=request.page_id)
        elif not agent_response:
            logger.info(f"Agent returned no response for page query. Page ID: {request.page_id}, Name: {request.page_name}")
        elif not isinstance(agent_response, str):
            logger.warning(f"Agent response for page query was not a string. Type: {type(agent_response)}. Page ID: {request.page_id}, Name: {request.page_name}. Response: {str(agent_response)[:200]}")
            
        return ContentResponse(data=agent_response, message="Query processed. Content saving attempted.")
    except Exception as e:
        logger.error(f"Error in /page/content. Page ID: {request.page_id}, Name: {request.page_name}: {e}", exc_info=True)
        if is_mcp_auth_error(e):
            admin_message = "MCP authentication/connectivity error. Administrator action required to check mcp-remote and refresh Atlassian authentication if necessary."
            logger.critical(f"{admin_message} Original error for page ID '{request.page_id}', Name '{request.page_name}': {e}")
            raise HTTPException(status_code=503, detail=f"Service temporarily unavailable due to Atlassian MCP connection issue. {admin_message}")
        raise HTTPException(status_code=500, detail=f"Error processing page content query: {str(e)}")

@app.post("/all/content", response_model=ContentResponse, tags=["Confluence Content"])
async def get_all_spaces_content_api(request: AllContentRequest):
    global agent_instance
    if not agent_instance:
        logger.error("MCPAgent not initialized. Cannot get all content.")
        raise HTTPException(status_code=503, detail="MCPAgent not initialized or initialization failed.")

    query = get_pages_in_all_spaces_query(
        start_date=request.start_date,
        end_date=request.end_date
    )
    logger.info(f"Processing query for content from all spaces. Start: {request.start_date}, End: {request.end_date}")
    try:
        agent_response = await agent_instance.run(query) 
        
        if agent_response:
            logger.info(f"Received response for all content. Type: {type(agent_response)}. Consider how to best save or process this.")
            # Further processing/saving logic might be needed here depending on expected response structure
        else:
            logger.info("Agent returned no response for all content query.")

        return ContentResponse(data=agent_response, message="Query processed for all spaces. Review logs for details on response type and saving.")
    except Exception as e:
        logger.error(f"Error in /all/content: {e}", exc_info=True)
        if is_mcp_auth_error(e):
            admin_message = "MCP authentication/connectivity error. Administrator action required to check mcp-remote and refresh Atlassian authentication if necessary."
            logger.critical(f"{admin_message} Original error for all content query: {e}")
            raise HTTPException(status_code=503, detail=f"Service temporarily unavailable due to Atlassian MCP connection issue. {admin_message}")
        raise HTTPException(status_code=500, detail=f"Error processing query for all spaces: {str(e)}")

# Ensure uvicorn uses the API_HOST and API_PORT from config when run directly
if __name__ == "__main__":
    # Note: setup_app_logging() is called within the lifespan manager when app starts
    uvicorn.run(app, host=API_HOST, port=API_PORT) 