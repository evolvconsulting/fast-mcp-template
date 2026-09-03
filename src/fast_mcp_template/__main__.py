"""Console entry point: `fast-mcp-template` runs the server on stdio."""

from __future__ import annotations

from fast_mcp_template.server import build_server


def main() -> None:
    """Run the server over stdio."""
    build_server().run()


if __name__ == "__main__":
    main()
