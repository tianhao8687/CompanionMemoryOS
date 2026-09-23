"""Local test-only MCP endpoint; never contacts a real account or device."""

import argparse

from mcp.server.fastmcp import FastMCP

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8769)
parser.add_argument("--transport", default="stdio")
args = parser.parse_args()
server = FastMCP("Local test tools", host="127.0.0.1", port=args.port)


@server.tool()
def echo_contact(contact: str, text: str) -> dict[str, str]:
    """Return input without sending it anywhere."""
    return {"status": "succeeded", "contact": contact, "text": text}


@server.tool()
def uncertain() -> dict[str, str]:
    """Simulate an operation whose outcome is unknown."""
    return {"status": "uncertain", "message": "check the destination"}


if __name__ == "__main__":
    server.run(transport=args.transport)
