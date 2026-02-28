"""
Phase 3: SSRF — Vulnerable URL Fetcher Server
This server fetches any URL without checking for internal/private IPs.
"""
from mcp.server.fastmcp import FastMCP
import urllib.request
import socket

mcp = FastMCP("VulnerableURLFetcher")

# Track all requests for the audit log
request_log = []

@mcp.tool()
def fetch_url(url: str) -> str:
    """Fetch the content of a URL and return it. Useful for checking
    the status of web pages, APIs, or services."""
    request_log.append(url)

    # DELIBERATELY VULNERABLE: No deny-list for private IPs
    try:
        # Resolve the hostname to check what IP we'd hit
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        try:
            resolved_ip = socket.gethostbyname(hostname)
        except socket.gaierror:
            resolved_ip = "unresolvable"

        req = urllib.request.Request(url, headers={"User-Agent": "MCP-Fetcher/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read(10000).decode("utf-8", errors="replace")
            return f"[Resolved IP: {resolved_ip}]\n\n{content}"
    except Exception as e:
        return f"[Resolved IP: {resolved_ip if 'resolved_ip' in dir() else 'unknown'}]\nFetch failed: {str(e)}"

@mcp.tool()
def get_request_log() -> str:
    """Return all URLs that have been fetched (audit trail)."""
    return "\n".join(request_log) if request_log else "No requests logged."

if __name__ == "__main__":
    mcp.run(transport="stdio")
