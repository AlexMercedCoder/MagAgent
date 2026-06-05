"""Daemon entry point — launched as a background subprocess by 'magent gateway start'.

Usage: python -m magent.gateway._daemon slack discord telegram
"""

from __future__ import annotations

import asyncio
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main() -> None:
    platforms = sys.argv[1:] or ["slack", "discord", "telegram"]

    from magent.config import get_current_user, load_config
    from magent.gateway import GatewayRunner

    username = get_current_user() or "default"
    config_data = load_config(username)._raw

    runner = GatewayRunner(config_data)

    try:
        asyncio.run(runner.run(platforms))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
