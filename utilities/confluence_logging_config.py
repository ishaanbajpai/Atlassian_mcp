import logging
import os
import sys
from configs.confluence_config import LOG_LEVEL, LOG_OUTPUT_DIR, LOG_FILE_NAME

# To prevent multiple handlers being added if setup_app_logging is called multiple times
_logging_configured = False

def setup_app_logging():
    """
    Configures application-wide logging.
    Reads configuration from configs.confluence_config.py.
    Sets up a StreamHandler for console output and a FileHandler for file output.
    """
    global _logging_configured
    if _logging_configured:
        return

    try:
        # Ensure the log directory exists
        if not os.path.exists(LOG_OUTPUT_DIR):
            os.makedirs(LOG_OUTPUT_DIR)
            # Use print here as logger might not be configured yet if this is the first time
            print(f"Created log directory: {LOG_OUTPUT_DIR}") 

        log_file_path = os.path.join(LOG_OUTPUT_DIR, LOG_FILE_NAME)

        app_logger = logging.getLogger() 
        
        numeric_level = getattr(logging, LOG_LEVEL.upper(), None)
        if not isinstance(numeric_level, int):
            # Fallback or error if LOG_LEVEL is invalid
            print(f"Warning: Invalid log level '{LOG_LEVEL}' in config. Defaulting to INFO.", file=sys.stderr)
            numeric_level = logging.INFO
        app_logger.setLevel(numeric_level)

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s'
        )

        # Clear existing handlers from the root logger to prevent duplicates if this function
        # is called multiple times or if other libraries (like Uvicorn) also add handlers.
        # This is a more robust way to prevent duplicate log messages.
        if app_logger.hasHandlers():
            app_logger.handlers.clear()

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        app_logger.addHandler(console_handler)

        file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
        file_handler.setFormatter(formatter)
        app_logger.addHandler(file_handler)
        
        app_logger.info(f"Logging configured: Level={LOG_LEVEL.upper()}, File={log_file_path}")
        _logging_configured = True

    except Exception as e:
        print(f"CRITICAL ERROR during logging setup: {e}. Further logging may be affected.", file=sys.stderr)
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        logging.error(f"Logging setup failed: {e}", exc_info=True) 