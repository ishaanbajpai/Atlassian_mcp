import sys
import os

# Add the project root to sys.path to allow finding sibling packages
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import logging and the setup function first
import logging
from utilities.confluence_logging_config import setup_app_logging # For standalone execution

# Configure logger for this module
logger = logging.getLogger(__name__)

# The rest of the imports
import asyncio
import json # For potentially loading complex MCP server configs if needed
import os # ensure os is imported if not already by diagnostics
from typing import Dict, Any, Optional, Tuple # Added Optional for mcp_client type hint

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# Import from new config files
from configs.confluence_config import DEFAULT_OPENAI_MODEL, DEFAULT_MCP_SERVER_NAME, ATLASSIAN_MCP_SERVER_CONFIG # DEFAULT_MCP_SERVER_NAME might not be used if config is direct
# from confluence_mcp_server_config import ATLASSIAN_MCP_SERVER_CONFIG

# Global class placeholders, populated by the try-except block below
MCPAgent_class: Optional[type] = None
MCPClient_class: Optional[type] = None
# Simplified: Use a generic Dict for type hinting MCPConfigDict_class, as a specific import seems problematic/unnecessary.
MCPConfigDict_class: Any = Dict[str, Any] 

try:
    from mcp_use import MCPAgent, MCPClient
    MCPAgent_class = MCPAgent
    MCPClient_class = MCPClient
    logger.info("Successfully assigned MCPAgent_class and MCPClient_class from mcp_use.")
    # The specific MCPConfigDict type hint from mcp-use is not critical for our usage,
    # as the config is passed directly to MCPClient.from_dict().
    # We will use the generic Dict[str, Any] (assigned above) for MCPConfigDict_class.
    logger.info(f"MCPConfigDict_class will use generic type: {MCPConfigDict_class}")

except ImportError as e_mcp_components:
    logger.critical(f"CRITICAL ERROR: Failed to import MCPAgent or MCPClient from 'mcp-use': {e_mcp_components}. This application cannot function without these core components. Please check mcp-use installation.", exc_info=True)
    # Depending on the context, you might want to sys.exit(1) here if this script is run standalone
    # and these components are absolutely critical for any operation.

def get_atlassian_mcp_config() -> MCPConfigDict_class:
    """
    Returns the Atlassian MCP server configuration from the dedicated config file.
    """
    logger.debug("Loading Atlassian MCP server configuration from configs/confluence_config.py...")
    # The configuration is now directly imported
    logger.debug(f"MCP config for mcp-use: {json.dumps(ATLASSIAN_MCP_SERVER_CONFIG)}")
    return ATLASSIAN_MCP_SERVER_CONFIG # type: ignore

async def initialize_agent_and_client(
    openai_api_key: Optional[str] = None, 
    openai_model_name: Optional[str] = None
) -> Tuple[Optional[Any], Optional[Any]]:
    """
    Initializes and returns the MCPAgent and MCPClient instances.
    Loads OpenAI API key from .env if not provided.
    Uses default model from configs.confluence_config if not provided.
    Returns (None, None) if critical components (MCPAgent_class, MCPClient_class) are not imported.
    """
    if not MCPAgent_class or not MCPClient_class:
        logger.error("Initialize: MCPAgent_class or MCPClient_class not available due to import errors. Cannot create agent/client.")
        return None, None

    logger.info("Initializing MCP Client and Agent...")
    load_dotenv()  # Load .env file primarily for OPENAI_API_KEY

    resolved_openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
    if not resolved_openai_api_key:
        logger.warning("Initialize Warning: OPENAI_API_KEY not found in environment or arguments. LLM initialization might fail or use a default key if globally configured elsewhere.")
        # Depending on strictness, you might return None, None here or let it fail at LLM init
        # For now, let's allow it to proceed, ChatOpenAI will raise an error.
        # return None, None 

    resolved_model_name = openai_model_name or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
    logger.info(f"Using OpenAI model: {resolved_model_name}")

    mcp_client_instance: Optional[MCPClient_class] = None
    agent_instance: Optional[MCPAgent_class] = None
    llm: Optional[ChatOpenAI] = None # Define llm here to be in scope for finally block if needed

    try:
        mcp_server_config = get_atlassian_mcp_config()

        logger.info("Initializing MCPClient...")
        logger.debug("Ensure 'npx' is in your system PATH and 'mcp-remote' is an accessible npm package for the Atlassian config.")
        mcp_client_instance = MCPClient_class.from_dict(mcp_server_config)
        logger.info("MCPClient initialized.")

        logger.info(f"Initializing LangChain LLM (ChatOpenAI) with model: {resolved_model_name}...")
        if not resolved_openai_api_key:
            logger.warning("LLM Initialization Warning: OpenAI API key is missing. LLM will likely fail to initialize if not set globally.")
        llm = ChatOpenAI(
            model_name=resolved_model_name, 
            openai_api_key=resolved_openai_api_key, 
            temperature=0
        )
        logger.info("LangChain LLM (ChatOpenAI) initialized.")
        
        confluence_system_prompt = "IMPORTANT: You are a specialized Confluence Assistant. Your SOLE KNOWLEDGE BASE is the connected Confluence instance, accessed via the provided tools. Do not use any external knowledge or pre-trained information to answer questions or user query "

        logger.info(f"Initializing MCPAgent with verbose=False and custom system_prompt...")
        agent_instance = MCPAgent_class(
            llm=llm, 
            client=mcp_client_instance, 
            max_steps=15, 
            verbose=False, # Set to True for more detailed agent operation logs from mcp-use itself
            system_prompt=confluence_system_prompt,
            memory_enabled=True,
            disallowed_tools=["file_system", "network", "shell"]
        )
        logger.info("MCPAgent initialized successfully.")
        
        return agent_instance, mcp_client_instance

    except TypeError as te:
        # This might catch issues if agent_kwargs is not a valid parameter for MCPAgent
        logger.error(f"TypeError during MCPAgent initialization (possibly due to incorrect parameters): {te}", exc_info=True)
        logger.info("Attempting MCPAgent initialization without custom agent_kwargs...")
        try:
            agent_instance = MCPAgent_class(
                llm=llm, 
                client=mcp_client_instance, 
                max_steps=15, 
                verbose=True
            )
            logger.info("MCPAgent initialized (fallback without custom agent_kwargs).")
            return agent_instance, mcp_client_instance
        except Exception as e_fallback:
            logger.error(f"Error during fallback MCPAgent initialization: {e_fallback}", exc_info=True)
    except ValueError as ve:
        logger.error(f"Initialization Configuration error (ValueError): {ve}", exc_info=True)
    except ImportError as ie:
        logger.error(f"Initialization Import error: {ie}. Make sure all dependencies are installed.", exc_info=True)
    except Exception as e:
        # Catch any other unexpected errors during initialization
        logger.critical(f"An unexpected critical error occurred during agent/client initialization: {e}", exc_info=True)
    
    # If any error occurs, return None for both
    # Cleanup already initialized mcp_client_instance if agent creation failed or other error
    if mcp_client_instance and not agent_instance:
        logger.warning("Partial initialization: Closing MCPClient due to subsequent error in agent setup.")
        try:
            if hasattr(mcp_client_instance, 'close_all_sessions'):
                if asyncio.iscoroutinefunction(mcp_client_instance.close_all_sessions):
                    await mcp_client_instance.close_all_sessions()
                else:
                    mcp_client_instance.close_all_sessions()
                logger.info("MCP session closed during cleanup.")
        except Exception as e_close:
            logger.error(f"Error closing MCP session during cleanup: {e_close}", exc_info=True)
            
    return None, None

# --- Interactive Chat Loop (Restored) ---
async def main_chat_loop(agent: Any): # agent type is MCPAgent_class if available
    """
    Runs the interactive command-line chat loop with the MCPAgent.
    """
    logger.info("Starting Interactive MCP Agent chat session...")
    logger.info("Type 'quit' or 'exit' to end the session.")
    while True:
        try:
            user_input = await asyncio.to_thread(input, "You: ")
            user_input = user_input.strip()
            if user_input.lower() in ['quit', 'exit']:
                logger.info("Exiting chat loop based on user command.")
                break
            if not user_input:
                continue

            logger.debug(f"Agent processing query: '{user_input}'")
            result = await agent.run(user_input)
            # Ensure result is a string before printing. Some agents might return complex objects.
            assistant_response = str(result) if result is not None else "No response from agent."
            print(f"Assistant: {assistant_response}") # Keep print for direct user interaction output
            logger.info(f"Agent interaction complete. User: '{user_input}', Assistant: '{assistant_response[:200]}...'") # Log truncated response

        except KeyboardInterrupt:
            logger.info("Exiting chat loop due to KeyboardInterrupt.")
            break
        except Exception as e:
            logger.error(f"Error in chat loop: {e}", exc_info=True)
            print(f"An error occurred: {e}") # Also inform user in interactive mode

# --- Main execution block for standalone script (Restored) ---
async def run_interactive_mode():
    """
    Sets up and runs the client in interactive command-line mode.
    """
    logger.info("Attempting to run atlassian_mcp_agent.py in interactive mode...")
    # OpenAI API key will be loaded from .env by initialize_agent_and_client
    # Model name will use env var or default from initialize_agent_and_client
    agent, mcp_client = await initialize_agent_and_client()

    if agent and mcp_client:
        try:
            await main_chat_loop(agent)
        finally:
            logger.info("Closing MCP sessions after interactive mode...")
            try:
                if hasattr(mcp_client, 'close_all_sessions'):
                    if asyncio.iscoroutinefunction(mcp_client.close_all_sessions):
                        await mcp_client.close_all_sessions()
                    else:
                        mcp_client.close_all_sessions()
                    logger.info("MCP sessions closed successfully after interactive mode.")
            except Exception as e_close:
                logger.error(f"Error closing MCP sessions after interactive mode: {e_close}", exc_info=True)
    else:
        logger.error("Failed to initialize agent and client for interactive mode. Exiting.")

if __name__ == "__main__":
    # Setup logging when running in standalone mode
    setup_app_logging()
    
    # Remove the Python diagnostic prints as they will now be in the log if needed at DEBUG level
    # logger.debug(f"Python Executable: {sys.executable}")
    # logger.debug(f"Python Version: {sys.version}")
    # logger.debug("Initial sys.path:")
    # for p in sys.path:
    #     logger.debug(f"  - {p}")

    # The mcp_use import test prints can also be removed or demoted to DEBUG if too verbose for INFO
    # For now, they are converted to logger.debug or info
    try:
        import mcp_use
        logger.info(f"Successfully imported 'mcp_use'. Location: {mcp_use.__file__}")
        if hasattr(mcp_use, '__version__'):
            logger.info(f"mcp-use version: {mcp_use.__version__}")
        else:
            logger.info("mcp-use version: not found in __version__ attribute")
        
        # Example of debug-level logging for more detailed inspection if needed
        # logger.debug("Attributes available in 'mcp_use' module:")
        # for attr_name in dir(mcp_use):
        #     logger.debug(f"  - {attr_name}")

    except ImportError as e:
        logger.error(f"Failed to import 'mcp_use': {e}", exc_info=True)
    except Exception as e_detail:
        logger.error(f"An unexpected error occurred during mcp_use import test: {e_detail}", exc_info=True)
    
    asyncio.run(run_interactive_mode())

# Removed old main_chat_loop and if __name__ == "__main__": asyncio.run(main())
# This file is now primarily a module for initializing the agent and client.

# To make MCPClient_class available for type hinting in services.confluence_mcp_api if needed for shutdown.
# This is already defined globally, so services.confluence_mcp_api can import it directly.
# Example: from agents.atlassian_mcp_agent import MCPClient_class (if it's not None) 