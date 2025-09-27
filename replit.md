# KARMA-LiveBOT

## Overview

KARMA-LiveBOT is a fully functional Discord bot that monitors and notifies about live streams across multiple platforms (Twitch, YouTube, and TikTok). The bot differentiates between two types of streamers - "Karma Streamers" (premium tier with enhanced cyberpunk-style notifications and daily streak tracking) and "Regular Streamers" (standard simple notifications). The bot operates entirely within Discord with no external dashboard, using different monitoring frequencies and notification styles based on streamer tier.

**Status**: ✅ **READY TO RUN** - Setup completed in Replit environment
**Last Updated**: September 27, 2025

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Bot Framework
- **Discord.py**: Core bot framework using `discord.ext.commands` for command handling and slash commands
- **SQLite Database**: Local data persistence for creator configurations, stream tracking, and daily streaks
- **Asynchronous Operations**: Built on asyncio for concurrent stream monitoring and Discord interactions

### Command Structure
- **Slash Commands**: Modern Discord application commands using `app_commands` (12 commands total)
  - Admin Commands: `/addcreator`, `/deletecreator`, `/streakevent`, `/reset`, `/testbot`
  - User Commands: `/request`, `/requeststatus`, `/subcreator`, `/unsub`, `/live`, `/ranking`, `/help`
- **Role-Based Permissions**: 
  - Admin commands require admin roles (IDs: 1388945013735424020, 581139700408909864, 898970074491269170)
  - User commands require user role (ID: 292321283608150016)
- **Modular Cog System**: Separate command modules (`commands.py`, `event_commands.py`) for different functionalities
- **Interactive UI**: Modal forms and dropdown selects for complex configuration

### Stream Monitoring Architecture
- **Tiered Monitoring**: Different check intervals based on streamer type
  - Karma Streamers: Every 1 minute
  - Regular Streamers: Every 3 minutes
- **Platform-Specific APIs**:
  - Twitch: Official Twitch API with OAuth2 authentication
  - YouTube: Smart Polling System - Web scraping for live detection, API only for details (95% quota reduction)
  - TikTok: Universal JSON pattern analysis with ≥2 pattern threshold (eliminates false positives)
- **Smart Polling (YouTube)**: Two-phase approach to optimize API quota usage
  - Phase 1: Web scraping for basic live detection (free)
  - Phase 2: YouTube API calls only when live detected (expensive but necessary)
- **Duplicate Prevention**: Daily tracking system prevents multiple notifications for the same stream session

### Notification System
- **Tiered Notification Styles**: 
  - Karma Streamers: Cyberpunk-style notifications with emojis (🚨 Hey Cyber-Runner! 🚨)
  - Regular Streamers: Simple notifications (👾 [User] ist LIVE!)
- **Embed-Based Messages**: Rich Discord embeds with platform-specific colors
  - Twitch: Purple (0x9146FF), YouTube: Red (0xFF0000), TikTok: Light Blue (0x00F2EA)
- **Dynamic Content**: Real-time viewer counts, game/category information, stream thumbnails, follower/subscriber counts
- **Follower/Subscriber Display**: All platforms show follower counts (Twitch followers, YouTube subscribers, TikTok followers)
- **Different Embed Contents**: Karma gets profile images + daily streaks, Regular gets basic info
- **Interactive Elements**: Follow buttons linking to platform profiles
- **Role Management**: Automatic assignment/removal of live roles when streamers go online/offline
- **Personal Subscriptions**: Private DM notifications for subscribed users

### Data Model
- **Creator Profiles**: Discord user mapping to platform accounts (Twitch, YouTube, TikTok)
- **Stream Sessions**: Tracking of daily streams to prevent duplicate notifications
- **Dual Streak System**: 
  - Daily Streaks: Only for Karma Streamers (persistent tracking)
  - Event Streaks: For both types during active events (with point multipliers)
- **Event System**: Points based on stream duration + streak multipliers
- **User Subscriptions**: Personal notification preferences per creator
- **Channel Configuration**: Per-creator notification channel assignments
- **Live Status Tracking**: Per-platform live status to prevent duplicate notifications

### Authentication & Permissions
- **Discord Permissions**: Role-based access control using specific Discord role IDs
- **Admin Commands**: Restricted to admin roles (IDs: 1388945013735424020, 581139700408909864, 898970074491269170)
- **User Commands**: Require user role (ID: 292321283608150016) for normal user access
- **API Authentication**: Environment variable-based API key management
- **Secure Token Handling**: OAuth2 flows for platform API access

## External Dependencies

### Discord Services
- **Discord Bot API**: Core bot functionality and slash command system
- **Discord Webhooks**: Message delivery and embed creation

### Streaming Platform APIs
- **Twitch API**: Stream status, viewer counts, game information, and user data
- **YouTube Data API v3**: Live stream detection and channel information
- **TikTok**: Web scraping for live status (no official API)

### Development Dependencies
- **discord.py**: Python Discord API wrapper
- **aiohttp**: Asynchronous HTTP client for API requests
- **requests**: Synchronous HTTP requests for certain operations
- **BeautifulSoup4**: HTML parsing for TikTok web scraping
- **sqlite3**: Local database operations

### Infrastructure Requirements
- **SQLite Database**: Local file-based database (`karma_bot.db`)
- **Environment Variables**: Secure storage for API tokens and bot credentials
- **Python 3.8+**: Runtime environment with asyncio support

### API Rate Limits & Monitoring
- **Twitch API**: Standard rate limits with OAuth2 token refresh
- **YouTube API**: Quota-based limits requiring efficient usage patterns
- **TikTok Scraping**: Custom rate limiting to avoid detection and blocking

## Replit Environment Setup

### Project Structure
- **Main Entry Point**: `main.py` - Discord bot application
- **Command Modules**: `commands.py`, `event_commands.py` - Discord slash commands
- **Database**: `karma_bot.db` - SQLite database for persistent storage
- **Dependencies**: Managed via Python package installer with packages from `pyproject.toml` and `requirements.txt`

### Workflow Configuration
- **Discord Bot Workflow**: Configured to run `python main.py` as a console application
- **Process Type**: Long-running backend service (Discord bot)
- **Output**: Console logs for monitoring bot activity and debugging

### Required Environment Variables
**CRITICAL**: The following environment variables must be configured in Replit Secrets for the bot to function:

1. **Discord Bot Configuration**:
   - `DISCORD_TOKEN` - Your Discord bot token (from Discord Developer Portal)
   - `DISCORD_APP_ID` - Your Discord application ID

2. **Streaming Platform APIs** (optional but recommended for full functionality):
   - `TWITCH_CLIENT_ID` - Twitch API client ID
   - `TWITCH_CLIENT_SECRET` - Twitch API client secret
   - `YOUTUBE_API_KEY` - YouTube Data API v3 key

### Setup Instructions
1. **Configure Discord Bot**:
   - Create bot application at https://discord.com/developers/applications
   - Generate bot token and copy to `DISCORD_TOKEN` secret
   - Copy application ID to `DISCORD_APP_ID` secret

2. **Optional API Configuration**:
   - Setup Twitch API credentials for Twitch stream monitoring
   - Setup YouTube API key for YouTube stream monitoring
   - TikTok monitoring works without API keys (uses web scraping)

3. **Start the Bot**:
   - The workflow will automatically start when environment variables are configured
   - Monitor console logs for startup status and errors
   - Bot status will show as online in Discord when successfully connected

### Database Management
- **Automatic Initialization**: Database tables are created automatically on first run
- **Persistent Storage**: SQLite database persists between restarts
- **Cloud Storage**: Database location optimized for cloud deployment (Railway/Render compatible)