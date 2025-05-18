# confluence_config.py

# Directory for saving API output content
OUTPUT_DIR = "output_content"

# Default OpenAI model to be used if not specified in environment variables
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

# Default MCP Server name (can be used if constructing MCP configs dynamically in future)
# For now, the actual server config is in confluence_mcp_server_config.py
DEFAULT_MCP_SERVER_NAME = "atlassian_mcp_server"

# Configuration for the Atlassian MCP server connection.
# This is used by the mcp-use library's MCPClient.from_dict()
# The type hint would be MCPConfigDict from mcp_use.config or mcp_use.types
# but to keep this file simple, we're not importing it here.
ATLASSIAN_MCP_SERVER_CONFIG = {
    "mcpServers": {
        "atlassian": {  # This key 'atlassian' is the server_name used by MCPAgent
            "command": "npx",
            "args": ["-y", "mcp-remote", "https://mcp.atlassian.com/v1/sse"]
        }
    }
}

# API Server Configuration
API_HOST = "localhost"
API_PORT = 8000

# Logging Configuration
LOG_LEVEL = "INFO"  # Recommended levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_OUTPUT_DIR = "logs"
LOG_FILE_NAME = "confluence_mcp_app.log" 