#!/usr/bin/env python3
"""
NEXUS CLI Entry Point

Usage:
    nexus think "brainstorm ideas for a new project"
    nexus status
    nexus learn "the deployment failed"
    nexus memory
"""

import sys
import asyncio
from pathlib import Path

# Add work to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cli import main

if __name__ == "__main__":
    asyncio.run(main())
