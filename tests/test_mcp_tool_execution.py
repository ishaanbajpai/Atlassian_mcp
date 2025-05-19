import sys
import os
import logging
from pathlib import Path

# Add project root to Python path
project_root = str(Path(__file__).parent.parent)
sys.path.append(project_root)

from mcp_use import MCPClient
from configs.confluence_config import ATLASSIAN_MCP_SERVER_CONFIG
from utilities.confluence_logging_config import setup_app_logging

# Configure logging
setup_app_logging()
logger = logging.getLogger(__name__)

def test_tool_execution(tool_name: str, tool_params: dict):
    """
    Test executing a specific tool with given parameters.
    
    Args:
        tool_name (str): Name of the tool to execute
        tool_params (dict): Parameters for the tool
    """
    try:
        # Initialize MCP client
        logger.info("Initializing MCP client...")
        # MCPClient is expected to be initialized using from_dict
        mcp_client = MCPClient.from_dict(ATLASSIAN_MCP_SERVER_CONFIG)
        
        # Execute the tool
        logger.info(f"Executing tool: {tool_name}")
        logger.info(f"With parameters: {tool_params}")
        
        result = mcp_client.execute_tool(tool_name, tool_params)
        
        logger.info("\nTool Execution Result:")
        logger.info("----------------------")
        logger.info(f"Status: Success")
        logger.info(f"Result: {result}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error executing tool: {str(e)}")
        raise

if __name__ == "__main__":
    # Example: Test getting a page by title
    # You can modify these parameters based on the tools available
    test_tool = "get_page_by_title_and_space"  # Replace with actual tool name
    test_params = {
        "space_key": "MFS",  # Replace with actual space key
        "title": "Test Page"  # Replace with actual page title
    }
    
    try:
        result = test_tool_execution(test_tool, test_params)
        logger.info("\nTest completed successfully!")
    except Exception as e:
        logger.error(f"Test failed: {str(e)}")
        sys.exit(1) 