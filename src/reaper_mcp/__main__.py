#!/usr/bin/env python3
import argparse
import logging
import sys


def main():
    parser = argparse.ArgumentParser(description="REAPER MCP Server")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

    from reaper_mcp.server import mcp
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
