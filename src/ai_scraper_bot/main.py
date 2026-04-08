from __future__ import annotations

import logging
import socket

from ai_scraper_bot.bot import ScraperBot
from ai_scraper_bot.config import load_settings
from ai_scraper_bot.utils.runtime_diary import install_runtime_diary_handler


def _check_discord_dns() -> None:
    hosts_to_check = (
        "gateway.discord.gg",
        "discord.com",
    )
    failed_hosts: list[str] = []
    for host in hosts_to_check:
        try:
            socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            failed_hosts.append(host)

    if failed_hosts:
        joined = ", ".join(failed_hosts)
        raise RuntimeError(
            "Discord DNS preflight failed. The current Terminal/network path could not resolve: "
            f"{joined}. This usually means a DNS, VPN, proxy, or network-route problem rather than a bot-code problem."
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    install_runtime_diary_handler()
    settings = load_settings()
    if not settings.discord_bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN is missing from .env")
    if not settings.minimax_api_key or not settings.minimax_api_url:
        logging.getLogger(__name__).warning(
            "MiniMax is not fully configured yet. MINIMAX_API_KEY or MINIMAX_API_URL is missing, so chat and summaries will fail until they are set."
        )
    _check_discord_dns()

    bot = ScraperBot(settings)
    bot.run(settings.discord_bot_token)


if __name__ == "__main__":
    main()
