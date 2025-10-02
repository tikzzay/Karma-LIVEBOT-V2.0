# KARMA-LiveBOT

## Overview
KARMA-LiveBOT is a Discord bot designed to monitor and notify users about live streams across Twitch, YouTube, and TikTok. It features a tiered notification system: "Karma Streamers" receive enhanced cyberpunk-style notifications with daily streak tracking, while "Regular Streamers" get standard notifications. The bot operates entirely within Discord, offering a seamless user experience, keeping communities updated on their favorite streamers, fostering engagement, and providing unique interactions like affiliate product links.

## User Preferences
- Preferred communication style: Simple, everyday language (German)
- /serverinfo command restricted to BOT_DEVELOPER_ID on MAIN_SERVER_ID only
- Stats channels auto-update every 5 minutes - manual renaming will be overwritten

## System Architecture
The bot utilizes a modular, MEE6-style architecture built on `discord.py` and uses `SQLite` for local data persistence.

**Core Components:**
-   **Modular Structure:** Organized into specialized modules for `database`, `autorepair`, `instantgaming`, `event`, `social`, `twitch`, `youtube`, `tiktok`, `commands`, `event_commands`, `custom_commands`, `giveaway_commands`, and `main` for maintainability.
-   **Asynchronous Operations:** Leverages `asyncio` for concurrent processing.
-   **Slash Commands:** Implements modern Discord slash commands (`app_commands`) with role-based permissions.
-   **Tiered Stream Monitoring:**
    -   Karma Streamers: Monitored every 1 minute with enhanced notifications.
    -   Regular Streamers: Monitored every 3 minutes with standard notifications.
    -   Platform-Specific APIs: Uses Twitch API, optimized YouTube polling (web scraping + API), and universal JSON pattern analysis for TikTok.
-   **Advanced Notification System:**
    -   Rich Embeds: Discord embeds with platform-specific colors, dynamic content (viewer counts, game info, thumbnails, follower counts), and interactive elements (follow buttons, Instant Gaming affiliate links).
    -   Role Management: Automatic assignment/removal of live roles.
    -   Personal Subscriptions: Private DM notifications.
-   **Data Model:** Manages creator profiles, stream sessions, dual streak systems (daily and event), user subscriptions, and channel configurations within an SQLite database.
-   **Authentication & Permissions:** Role-based access control for Discord commands and environment variable-based API key management.
-   **Welcome System:** Configurable welcome messages with custom banners, profile picture overlays, username display, and auto-role assignment, including SSRF protection for banner URLs.
-   **Custom Commands System:** Allows creation, editing, deletion, and listing of guild-specific custom commands with embed and button support, limited to 50 commands per server with admin-only access.
-   **Giveaway System:** Comprehensive giveaway management including starting giveaways with channel selection, description, keys, timer, winner count, image, participation buttons, and automatic winner selection.

## External Dependencies
-   **Discord Services:** Discord Bot API, Discord Webhooks.
-   **Streaming Platform APIs:** Twitch API, YouTube Data API v3, TikTok (web scraping).
-   **Python Libraries:** `discord.py`, `aiohttp`, `requests`, `BeautifulSoup4`, `sqlite3`, `tiktoklive`, `httpx`, `openai`, `PyNaCl`, `brotli`, `schedule`, `Pillow`.
-   **Infrastructure:** SQLite Database (`karma_bot.db`), Environment Variables.

## Replit Setup (October 1, 2025)
- **Environment:** Python 3.11 on Replit NixOS
- **Workflow:** "Discord Bot" running `python main.py` (console output)
- **Required Secrets:** All environment variables are configured in Replit Secrets:
  - DISCORD_TOKEN - Discord bot authentication token
  - DISCORD_APP_ID - Discord application ID
  - TWITCH_CLIENT_ID - Twitch API client ID
  - TWITCH_CLIENT_SECRET - Twitch API client secret
  - YOUTUBE_API_KEY - YouTube Data API v3 key
  - OPENAI_API_KEY - OpenAI API key for auto-repair system
  - DEV_CHANNEL_ID - Discord channel for developer notifications and log posting
  - MAIN_SERVER_ID - Main Discord server ID
  - BOT_DEVELOPER_ID - Bot developer's Discord user ID
- **Status:** Bot successfully running and connected to Discord, monitoring 2 guilds with all platform tasks (Twitch, YouTube, TikTok) operational
- **Log Posting:** Automatic log posting to DEV_CHANNEL_ID every 6 hours (configured Oct 1, 2025)