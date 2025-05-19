import sys
import os
import logging
from pathlib import Path
import asyncio

# Add project root to Python path
project_root = str(Path(__file__).parent.parent)
sys.path.append(project_root)

from mcp_use import MCPClient
# Assuming MCPSession might be needed for type hinting or direct use if client structure is complex
# from mcp_use.session import MCPSession 
from configs.confluence_config import ATLASSIAN_MCP_SERVER_CONFIG
from utilities.confluence_logging_config import setup_app_logging

# Configure logging
setup_app_logging()
logger = logging.getLogger(__name__)

async def test_mcp_client_connection():
    """
    Test the connection to MCP server and list available tools.
    """
    try:
        # Initialize MCP client
        logger.info("Initializing MCP client...")
        mcp_client = MCPClient.from_dict(ATLASSIAN_MCP_SERVER_CONFIG)
        logger.info("MCPClient initialized.")

        # Determine the server name from the config keys
        # Based on confluence_config.py, ATLASSIAN_MCP_SERVER_CONFIG has {"mcpServers": {"atlassian": ...}}
        server_name = list(ATLASSIAN_MCP_SERVER_CONFIG.get("mcpServers", {}).keys())[0] if ATLASSIAN_MCP_SERVER_CONFIG.get("mcpServers") else None
        
        if not server_name:
            logger.error("Could not determine server name from ATLASSIAN_MCP_SERVER_CONFIG.")
            raise ValueError("Server name not found in configuration.")

        logger.info(f"Attempting to create session for server: {server_name}...")
        # Create and initialize a session
        # MCPClient.create_session is an async method
        session = await mcp_client.create_session(server_name, auto_initialize=True)
        logger.info(f"MCP session created and initialized for server: {server_name}.")
        
        # Get available tools from the session instance
        logger.info(f"Fetching available tools from the MCPSession instance...")
        # Assuming the session object has a 'tools' attribute after initialization
        available_tools = session.tools 
        logger.info("Successfully connected to MCP server and retrieved tool information.")
        
        logger.info(f"Found {len(available_tools)} tools.")

        # Print available tools
        logger.info("\nAvailable Tools:")
        logger.info("----------------")
        if not available_tools:
            logger.info("No tools found.")
        for tool_index, tool in enumerate(available_tools):
            tool_name = getattr(tool, 'name', f'N/A (Tool {tool_index})')
            tool_description = getattr(tool, 'description', 'N/A')
            input_schema = getattr(tool, 'inputSchema', 'N/A')

            logger.info(f"Tool Name: {tool_name}")
            logger.info(f"Description: {tool_description}")
            logger.info(f"Input Schema: {str(input_schema)}")
            if hasattr(tool, 'inputSchema') and tool.inputSchema is not None:
                logger.info(f"Input Schema Type: {type(tool.inputSchema)}")
                logger.info(f"Input Schema Attributes: {dir(tool.inputSchema)}")
            
            # logger.info(f"Tool object type: {type(tool)}")
            # logger.info(f"Tool object attributes: {dir(tool)}")
            logger.info("----------------")
            
        return available_tools
        
    except Exception as e:
        logger.error(f"Error testing MCP client connection: {str(e)}", exc_info=True)
        raise
    finally:
        # Ensure all sessions are closed
        if 'mcp_client' in locals() and mcp_client:
            logger.info("Closing all MCP sessions...")
            await mcp_client.close_all_sessions()
            logger.info("All MCP sessions closed.")

if __name__ == "__main__":
    try:
        # Run the async test function
        tools = asyncio.run(test_mcp_client_connection())
        logger.info(f"\nSuccessfully connected to MCP server and listed tools!")
        logger.info(f"Found {len(tools)} available tools.")
    except Exception as e:
        logger.error(f"Test failed overall: {str(e)}")
        sys.exit(1) 