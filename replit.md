# KARMA-LiveBOT

## Overview
KARMA-LiveBOT is a Discord bot designed to monitor and notify users about live streams across Twitch, YouTube, and TikTok. It features a tiered notification system: "Karma Streamers" receive enhanced cyberpunk-style notifications with daily streak tracking, while "Regular Streamers" get standard notifications. The bot operates entirely within Discord, offering a seamless user experience without external dashboards. Its core purpose is to keep Discord communities updated on their favorite streamers going live, fostering engagement and providing unique interactions like affiliate product links.

## User Preferences
- Preferred communication style: Simple, everyday language (German)
- /serverinfo command restricted to BOT_DEVELOPER_ID on MAIN_SERVER_ID only
- Stats channels auto-update every 5 minutes - manual renaming will be overwritten

## Recent Changes
- [2025-10-01] **Replit Environment Setup Completed:**
  - Fresh GitHub clone successfully configured for Replit environment
  - All Python dependencies installed via packager tool (discord.py, aiohttp, tiktoklive, httpx, openai, PyNaCl, etc.)
  - requirements.txt cleaned up (removed duplicates)
  - .gitignore file created for Python project
  - Workflow configured: "KARMA-LiveBOT" (python main.py) with webview output on port 5000
  - Bot successfully connected to Discord as "Karma LiveBOT#2866" (2 guilds)
  - All platform tasks operational: Twitch, YouTube, TikTok, Stats, Social Media
  - 20 slash commands registered and synced globally
  - HTTP health check server running on 0.0.0.0:5000 with /health and /status endpoints
  - OpenAI Auto-Repair System initialized successfully
  - SQLite database (karma_bot.db) loaded with existing data
  - All environment variables verified and working
  - Python runtime: 3.11.13
- [2025-09-30] **Custom Commands System Implemented:**
  - New `custom_commands` database table with guild-specific command storage
  - `/custom create` - Modal-based command creation with embed and button support
  - `/custom edit` - Edit existing custom commands with pre-filled Modal
  - `/custom delete` - Remove custom commands with confirmation
  - `/custom list` - Display all custom commands for the server
  - Dynamic command registration on bot startup and after creation
  - 50 commands per server limit
  - Admin-only access via role-based permissions
  - Button support with Label|URL format and URL validation
  - Architect review: Pass with minor improvement suggestions
- [2025-09-30] **Railway.com Compatibility & Enhancements:**
  - **Auto-Restart:** Re-enabled 12-hour auto-restart (os._exit) - Railway.com will automatically restart bot
  - **Live-Rollen-Cleanup:** New background task (10min) checks all members with live role and removes if not live on any platform
  - **Stream-Titel:** Live notifications now display stream title for Twitch, YouTube, and TikTok
  - **Nachrichten-Cleanup:** New background task (15min) finds and deletes orphaned live notification messages
  - **TikTok Fixes:** Now displays viewer count (even 0), thumbnail, profile image, and follower count
  - **Enhanced Logging:** Detailed diagnostics for message deletion and role removal
  - **Embed Logic Fix:** Changed from truthiness to `is not None` so zero viewer counts display
  - Architect review: PASS - All fixes verified without regressions
- [2025-09-30] **Giveaway-System Implementiert:**
  - Neue Datei `giveaway_commands.py` mit komplettem Giveaway-Management
  - `/startgiveaway` - Channel-Auswahl + Modal für Beschreibung, Keys, Timer, Gewinner-Anzahl, Bild
  - Teilnahme-Button mit automatischer Gewinner-Prüfung (past_winners Datenbank)
  - Timer-System mit automatischer Gewinner-Auswahl nach Ablauf
  - `/resetgewinner` - Löscht alle gespeicherten Gewinner für neue Giveaways
  - Live Teilnehmer-Zähler im Embed
  - Giveaway-Wiederherstellung nach Bot-Neustart (Timer + Buttons)
  - 3 neue Datenbank-Tabellen: giveaways, giveaway_participants, past_winners
  - 20 Commands total (vorher 18) - 2 neue Giveaway-Commands
  - Architect review: PASS - Vollständige Implementierung aller Features

## System Architecture
The bot utilizes a modular, MEE6-style architecture, with specialized modules for each functional area. It is built on `discord.py` and uses `SQLite` for local data persistence.

**Core Components:**
-   **Modular Structure:** Separated into `database`, `autorepair`, `instantgaming`, `event`, `social`, `twitch`, `youtube`, `tiktok`, `commands`, `event_commands`, `custom_commands`, `giveaway_commands`, and `main` modules for clean separation of concerns and maintainability.
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

## Replit Setup
**Environment:** Fully configured and running on Replit
- **Workflow:** KARMA-LiveBOT (python main.py) on port 5000
- **Health Check:** HTTP server on 0.0.0.0:5000 with /health and /status endpoints
- **Runtime:** Python 3.11.13
- **Database:** SQLite (karma_bot.db) - local persistent storage
- **Dependencies:** Managed via pyproject.toml and requirements.txt

## Required Environment Variables
All secrets are configured in Replit Secrets:
- `DISCORD_TOKEN` - Discord bot authentication (required)
- `DISCORD_APP_ID` - Discord application ID (required)
- `TWITCH_CLIENT_ID` - Twitch API credentials (optional)
- `TWITCH_CLIENT_SECRET` - Twitch API credentials (optional)
- `YOUTUBE_API_KEY` - YouTube Data API v3 key (optional)
- `OPENAI_API_KEY` - For auto-repair system (optional)
- `DEV_CHANNEL_ID` - Developer notification channel (optional)
- `MAIN_SERVER_ID` - Main Discord server ID (optional)
- `BOT_DEVELOPER_ID` - Bot developer user ID (optional)
- `TWITTER_BEARER_TOKEN` - Twitter API (optional)
- `INSTAGRAM_SESSION_ID` - Instagram scraping (optional)

## External Dependencies
-   **Discord Services:** Discord Bot API, Discord Webhooks.
-   **Streaming Platform APIs:** Twitch API, YouTube Data API v3, TikTok (web scraping).
-   **Python Libraries:** `discord.py`, `aiohttp`, `requests`, `BeautifulSoup4`, `sqlite3`.
-   **Infrastructure:** SQLite Database (`karma_bot.db`), Environment Variables for sensitive data, Python 3.8+.