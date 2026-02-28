"""
Phase 1: Indirect Prompt Injection — Vulnerable Filesystem Server
This server provides read_file and write_file tools.
The attack: a file contains hidden instructions that attempt to
make the LLM call write_file to create a "HACKED.txt" file.
"""
from mcp.server.fastmcp import FastMCP
import os

mcp = FastMCP("VulnerableFilesystem")

SANDBOX_DIR = os.path.join(os.path.dirname(__file__), "..", "payloads")

@mcp.tool()
def read_file(filename: str) -> str:
    """Read the contents of a file from the documents directory."""
    path = os.path.join(SANDBOX_DIR, filename)
    if not os.path.exists(path):
        return f"Error: File '{filename}' not found."
    with open(path, "r") as f:
        return f.read()

@mcp.tool()
def write_file(filename: str, content: str) -> str:
    """Write content to a file in the documents directory."""
    path = os.path.join(SANDBOX_DIR, filename)
    with open(path, "w") as f:
        f.write(content)
    return f"Successfully wrote to '{filename}'."

@mcp.tool()
def list_files() -> str:
    """List all files in the documents directory."""
    files = os.listdir(SANDBOX_DIR)
    return "\n".join(files) if files else "No files found."

if __name__ == "__main__":
    mcp.run(transport="stdio")
