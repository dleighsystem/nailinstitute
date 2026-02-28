"""
Phase 4: Resource Exhaustion (DoS) — Malicious Server
This server returns progressively massive payloads to test
whether the host/client can handle or reject them.
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("MaliciousDoSServer")

@mcp.tool()
def get_small_data() -> str:
    """Returns a small, normal-sized dataset (1KB). Safe baseline."""
    return "A" * 1024

@mcp.tool()
def get_medium_data() -> str:
    """Returns a medium dataset (1MB). Tests basic limits."""
    return "B" * (1024 * 1024)

@mcp.tool()
def get_large_data() -> str:
    """Returns a large dataset (10MB). Tests memory handling."""
    return "C" * (10 * 1024 * 1024)

@mcp.tool()
def get_huge_data() -> str:
    """Returns a massive dataset (100MB). Tests crash resistance."""
    return "D" * (100 * 1024 * 1024)

@mcp.tool()
def get_nested_json() -> str:
    """Returns deeply nested JSON that may cause parsing issues."""
    import json
    data = {"value": "leaf"}
    for i in range(500):
        data = {"level": i, "child": data}
    return json.dumps(data)

if __name__ == "__main__":
    mcp.run(transport="stdio")
