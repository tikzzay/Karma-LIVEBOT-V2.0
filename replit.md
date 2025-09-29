# KARMA-LiveBOT

## Overview
KARMA-LiveBOT is a Discord bot designed to monitor and notify users about live streams across Twitch, YouTube, and TikTok. It features a tiered notification system: "Karma Streamers" receive enhanced cyberpunk-style notifications with daily streak tracking, while "Regular Streamers" get standard notifications. The bot operates entirely within Discord, offering a seamless user experience without external dashboards. Its core purpose is to keep Discord communities updated on their favorite streamers going live, fostering engagement and providing unique interactions like affiliate product links.

## User Preferences
- Preferred communication style: Simple, everyday language (German)
- /serverinfo command restricted to BOT_DEVELOPER_ID on MAIN_SERVER_ID only
- Stats channels auto-update every 5 minutes - manual renaming will be overwritten

## Recent Changes
- [2025-09-29] Fresh GitHub clone imported to Replit environment
- [2025-09-29] All Python dependencies installed successfully (discord.py, aiohttp, tiktoklive, httpx, openai, etc.)
- [2025-09-29] Fixed config.py type issue with DEV_CHANNEL_ID
- [2025-09-29] Health check HTTP server configured on port 5000 for Replit
- [2025-09-29] Workflow configured to run the Discord bot
- [2025-09-29] .gitignore created for Python project
- [2025-09-29] OpenAI Auto-Repair System fixed - API key and DEV_CHANNEL_ID now correctly passed
- [2025-09-29] Database cleanup - removed 10 non-existent channels from stats_channels table
- [2025-09-29] Improved event_commands.py tests: Instant Gaming (randomized), Log Upload (actual upload), Custom Message (cleaned up)
- [2025-09-29] /help command updated with all new features (/customstreamermessage, /editigreftag, /setupstatschannel, etc.)
- [2025-09-29] Procfile created for Railway deployment

## System Architecture
The bot utilizes a modular, MEE6-style architecture, with specialized modules for each functional area. It is built on `discord.py` and uses `SQLite` for local data persistence.

**Core Components:**
-   **Modular Structure:** Separated into `database`, `autorepair`, `instantgaming`, `event`, `social`, `twitch`, `youtube`, `tiktok`, ` `commands`, `event_commands`, and `main` modules for clean separation of concerns and maintainability.
-   **Asynchronous Operations:** Leverages `asyncio` for concurrent processing of stream monitoring and Discord interactions.
-   **Slash Commands:** Implements modern Discord slash commands (`app_commands`) with role-based permissions for both admin and user functionalities.
-   **Tiered Stream Monitoring:**
    -   **Karma Streamers:** Monitored every 1 minute.
    -   **Regular Streamers:** Monitored every 3 minutes.
    -   **Platform-Specific APIs:** Uses official Twitch API, a smart polling (web scraping + API) system for YouTube to optimize API quota, and universal JSON pattern analysis for TikTok.
-   **Advanced Notification System:**
    -   **Tiered Notifications:** Cyberpunk-style for Karma Streamers (with emojis, profile images, daily streaks) and simple for Regular Streamers.
    -   **Rich Embeds:** Discord embeds with platform-specific colors and dynamic content (viewer counts, game info, thumbnails, follower counts).
    -   **Interactive Elements:** Includes follow buttons and **Instant Gaming affiliate purchase buttons** dynamically based on streamed games.
    -   **Role Management:** Automatic assignment/removal of live roles for streamers.
    -   **Personal Subscriptions:** Private DM notifications for subscribed users.
-   **Data Model:** Manages creator profiles, stream sessions, dual streak systems (daily and event), user subscriptions, and channel configurations within an SQLite database.
-   **Authentication & Permissions:** Role-based access control for Discord commands and environment variable-based API key management for external services.

## Setup Requirements
- Discord bot token and app ID required
- Optional: Twitch, YouTube, TikTok API keys for full functionality
- SQLite database (local storage)
- Python 3.11+ runtime

## External Dependencies
-   **Discord Services:** Discord Bot API, Discord Webhooks.
-   **Streaming Platform APIs:** Twitch API, YouTube Data API v3, TikTok (web scraping).
-   **Python Libraries:** `discord.py`, `aiohttp`, `requests`, `BeautifulSoup4`, `sqlite3`.
-   **Infrastructure:** SQLite Database (`karma_bot.db`), Environment Variables for sensitive data, Python 3.8+.