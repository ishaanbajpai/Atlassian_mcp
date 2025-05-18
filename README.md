# Confluence Content MCP API

This project provides a Python-based API to interact with an Atlassian Confluence instance (or any MCP-compliant server providing similar functionality) using the Model Context Protocol (MCP). It leverages the `mcp-use` library to manage MCP server connections and the `MCPAgent` to orchestrate interactions with an OpenAI LLM for processing queries and utilizing tools exposed by the MCP server.

The primary interface is a FastAPI application that exposes endpoints to fetch content from Confluence spaces and pages. Fetched content is also saved locally to files.

## Core Components

*   **`services/confluence_mcp_api.py`**: The main FastAPI application. It defines API endpoints, manages the application lifecycle (startup/shutdown of MCP agent), and handles requests.
*   **`agents/atlassian_mcp_agent.py`**: Responsible for initializing the `MCPAgent` and `MCPClient` from the `mcp-use` library. It's called by the API during startup.
*   **`utilities/confluence_mcp_api_tools.py`**: Contains helper functions to generate natural language queries based on API request parameters. These queries are then sent to the `MCPAgent`.
*   **`configs/confluence_config.py`**: Stores general application configurations like the default OpenAI model, the output directory for saved files, and the MCP server connection configuration.
*   **`requirements.txt`**: Lists all Python dependencies.
*   **`.env` (User-created)**: Used to store sensitive information like the `OPENAI_API_KEY`.

## Features

*   Connects to an MCP server (configured for Atlassian's `mcp-remote` by default).
*   Utilizes `mcp-use` for MCP communication and `MCPAgent` for LLM orchestration.
*   Integrates with an OpenAI LLM (e.g., GPT-4o-mini) via `langchain-openai`.
*   Exposes FastAPI endpoints to:
    *   Get HTML content of pages within a specific Confluence space.
    *   Get HTML content of a specific Confluence page by ID or title.
    *   Get HTML content of pages from all accessible Confluence spaces.
*   Saves fetched HTML content to local files in an `output_content` directory, organized by space/page.
*   Asynchronous operations using `asyncio`, `FastAPI`, and `aiofiles`.
*   Configuration managed via Python files and a `.env` file for secrets.

## Prerequisites

*   Python 3.8 or higher.
*   An active MCP server compatible with the configuration in `configs/confluence_config.py`. For the default Atlassian setup, this implies `npx` and `mcp-remote` should be usable by the environment running the API.
*   An OpenAI API key.

## Installation

1.  **Clone the repository or download the files:**
    Ensure all Python files (`.py`) and `requirements.txt` are in your project directory.

2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv .venv
    # On Windows:
    # .venv\Scripts\activate
    # On macOS/Linux:
    # source .venv/bin/activate
    ```

3.  **Install dependencies:**
    Navigate to your project directory and run:
    ```bash
    pip install -r requirements.txt
    ```
    This will install `mcp-use`, `langchain-openai`, `python-dotenv`, `fastapi`, `uvicorn`, `aiofiles`, and their dependencies.

## Configuration

1.  **OpenAI API Key & Model (Environment):**
    Create a file named `.env` in the root of your project directory. Add your OpenAI API key:
    ```env
    OPENAI_API_KEY="your_actual_openai_api_key"
    ```
    You can optionally set the OpenAI model by adding:
    ```env
    OPENAI_MODEL="gpt-4-turbo" # Or any other model you prefer
    ```
    If `OPENAI_MODEL` is not set in `.env` or as an environment variable, it will use the default specified in `configs/confluence_config.py`.

2.  **Application Configuration (`configs/confluence_config.py`):**
    Modify `configs/confluence_config.py` if you need to change:
    *   `OUTPUT_DIR`: The root directory where fetched content will be saved (default: `"output_content"`).
    *   `DEFAULT_OPENAI_MODEL`: The fallback OpenAI model if not set via environment.
    *   `ATLASSIAN_MCP_SERVER_CONFIG`: Defines how to connect to your MCP server. The default is configured for Atlassian's `mcp-remote` tool using `npx`.

```python
# configs/confluence_config.py (example for ATLASSIAN_MCP_SERVER_CONFIG part)
ATLASSIAN_MCP_SERVER_CONFIG = {
    "mcpServers": {
        "atlassian": { # This server name is used by MCPAgent
            "command": "npx",
            "args": ["-y", "mcp-remote", "https://mcp.atlassian.com/v1/sse"]
        }
    }
}
```
    Adjust this configuration if your MCP server setup is different.

## Running the API Server

1.  Ensure your MCP server (e.g., the `npx mcp-remote ...` process for Atlassian) can be started or is already running, and that the client machine can execute the command specified in `configs/confluence_config.py` (within `ATLASSIAN_MCP_SERVER_CONFIG`).
2.  Navigate to your project directory in the terminal.
3.  Activate your virtual environment (if you created one).
4.  Run the API server using Uvicorn (assuming your project root is in PYTHONPATH, or you run from the root):
    ```bash
    python -m services.confluence_mcp_api
    ```
    Or, for development with auto-reload (run from the project root):
    ```bash
    uvicorn services.confluence_mcp_api:app --reload
    ```
    The API server will typically start on `http://localhost:8000` (if `API_HOST` and `API_PORT` in `configs/confluence_config.py` are set to default).

## API Endpoints

You can access the API documentation (Swagger UI) at `http://localhost:8000/docs` or ReDoc at `http://localhost:8000/redoc` when the server is running.

All content-fetching endpoints will attempt to save the retrieved HTML content into the directory specified by `OUTPUT_DIR` in `configs/confluence_config.py`.

### `POST /space/content`
Fetches HTML content for all pages within a specified Confluence space.
*   **Request Body:**
    ```json
    {
        "space_name": "YOUR_SPACE_KEY",
        "start_date": "YYYY-MM-DD", // Optional
        "end_date": "YYYY-MM-DD"    // Optional
    }
    ```
*   **Response:** `ContentResponse` containing the fetched data or an error.
*   **File Saving:** Saves pages into `output_content/spaces/<sanitized_space_name>/page_N.html`.

### `POST /page/content`
Fetches HTML content for a specific Confluence page.
*   **Request Body:**
    ```json
    {
        "page_id": "123456",          // Optional, use if known
        "page_name": "My Page Title", // Optional, use with space_name if ID unknown
        "space_name": "YOUR_SPACE_KEY", // Required if using page_name without page_id
        "start_date": "YYYY-MM-DD",   // Optional, for checking page updates
        "end_date": "YYYY-MM-DD"      // Optional
    }
    ```
*   **Response:** `ContentResponse` containing the fetched data or an error.
*   **File Saving:** Saves the page into `output_content/pages/<sanitized_space_name>/<sanitized_page_identifier>.html`.

### `POST /all/content`
Fetches HTML content for pages from all accessible Confluence spaces.
*   **Request Body:**
    ```json
    {
        "start_date": "YYYY-MM-DD", // Optional
        "end_date": "YYYY-MM-DD"    // Optional
    }
    ```
*   **Response:** `ContentResponse` containing the fetched data or an error.
*   **File Saving:** Saves pages into `output_content/all_content/page_N.html` or a single combined file.

### `POST /process-general-query`
Allows sending a general natural language query to the MCPAgent.
*   **Request Body:**
    ```json
    {
        "query": "Tell me about recent updates in the Engineering space."
    }
    ```
*   **Response:** `GeneralQueryResponse` containing the agent's direct response.
*   **File Saving:** No automatic file saving for this endpoint.

## Troubleshooting

*   **Import Errors (`mcp-use`, `fastapi`, etc.)**: Ensure all dependencies from `requirements.txt` are installed in your active Python virtual environment.
*   **`OPENAI_API_KEY not found`**: Verify your `.env` file is in the project root and correctly formatted, or that the environment variable is set.
*   **API Startup Errors / Agent Initialization Failed**:
    *   Check the console output from `python -m services.confluence_mcp_api` for detailed error messages.
    *   Ensure `agents/atlassian_mcp_agent.py` can successfully import `MCPAgent` and `MCPClient` from `mcp-use`.
    *   Confirm the MCP server configuration in `configs/confluence_config.py` (the `ATLASSIAN_MCP_SERVER_CONFIG` variable) is correct and the server/command (e.g., `npx`) is accessible.
*   **API Endpoint Errors (500, 503)**:
    *   `503 Service Unavailable`: Usually means the `MCPAgent` failed to initialize during API startup. Check startup logs.
    *   `500 Internal Server Error`: An error occurred while processing your request. Check API console logs for details.
*   **Content Not Saving**:
    *   Verify write permissions for the project directory where `output_content` (or your configured `OUTPUT_DIR`) will be created.
    *   Check API console logs for errors from `aiofiles` or the `save_content_to_file` function.
*   **OpenAI API Errors**: Ensure your API key is valid, has funds/credits, and you are adhering to rate limits.

This project is designed for flexibility. You can adapt the MCP server configurations, query generation logic in `utilities/confluence_mcp_api_tools.py`, and even the LLM used by modifying the respective files. 