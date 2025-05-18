import uvicorn
import logging
import os
import sys

# Ensure the project root is in sys.path to allow finding modules in sibling directories
# This is important if this script is run from the root directory.
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    # If run_confluence_service.py is in the root, project_root is correct.
    # If it were nested, we might need os.path.dirname(project_root) for the actual project root.
    sys.path.insert(0, project_root)

# Now that sys.path is adjusted, we can import our modules
try:
    from services.confluence_mcp_api import app
    from configs.confluence_config import API_HOST, API_PORT
    from utilities.confluence_logging_config import setup_app_logging
except ImportError as e:
    print(f"Error importing necessary modules. Ensure your PYTHONPATH is set up correctly or run this script from the project root. Error: {e}", file=sys.stderr)
    sys.exit(1)

# Get a logger for this run script
logger = logging.getLogger(__name__) # Will inherit configuration from setup_app_logging

if __name__ == "__main__":
    # Initialize logging as the first step
    setup_app_logging() 

    logger.info(f"Starting Confluence MCP API service on http://{API_HOST}:{API_PORT}")
    logger.info("Logging is configured. Check console and log file in the configured log directory.")
    
    # More Uvicorn options can be configured here if needed,
    # e.g., log_config from uvicorn.config.LOGGING_CONFIG or a custom one.
    # However, our setup_app_logging() already configures the root logger.
    # To avoid duplicate console logs from Uvicorn's default handlers, 
    # you might pass log_config=None to uvicorn.run if your setup_app_logging
    # adequately covers console logging. For now, we'll let Uvicorn use its defaults
    # which might lead to some overlap on console but ensures Uvicorn's own operational logs appear.
    
    uvicorn.run(app, host=API_HOST, port=API_PORT) 