"""Entry point for Meisengeige program monitoring."""

import asyncio
import sys

from .main import main


if __name__ == "__main__":
    """Run the monitoring script."""
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
