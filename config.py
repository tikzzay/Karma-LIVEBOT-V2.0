#!/usr/bin/env python3
"""
Configuration Module for KARMA-LiveBOT
Centralized configuration to avoid code duplication
"""

import os

class Config:
    """Centralized configuration for KARMA-LiveBOT"""
    
    # Discord Role IDs
    ADMIN_ROLES = [1388945013735424020, 581139700408909864, 898970074491269170]
    USER_ROLES = [292321283608150016, 276471077402705920]
    REGULAR_STREAMER_ROLE = 898194971029561344
    KARMA_STREAMER_ROLE = 898971225311838268
    LIVE_ROLE = 899306754549108786
    STREAMER_REQUESTS_CHANNEL = 1420132930436595815
    
    # Discord API Keys
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    DISCORD_APP_ID = os.getenv('DISCORD_APP_ID')
    
    # Platform API Keys
    TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
    TWITCH_CLIENT_SECRET = os.getenv('TWITCH_CLIENT_SECRET')
    YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
    
    # OpenAI Auto-Repair System
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    DEV_CHANNEL_ID = int(os.getenv('DEV_CHANNEL_ID', '0'))
    
    # Developer/Main Server Configuration
    MAIN_SERVER_ID = int(os.getenv('MAIN_SERVER_ID', '0'))
    BOT_DEVELOPER_ID = int(os.getenv('BOT_DEVELOPER_ID', '0'))
    
    # Platform Colors
    COLORS = {
        'twitch': 0x9146FF,
        'youtube': 0xFF0000,
        'tiktok': 0x00F2EA,
        'twitter': 0x1DA1F2,
        'x': 0x000000
    }
    
    # Check Intervals (in seconds)
    KARMA_CHECK_INTERVAL = 60           # 1 minute for Karma streamers
    REGULAR_CHECK_INTERVAL = 180        # 3 minutes for regular streamers
    SOCIAL_MEDIA_CHECK_INTERVAL = 3600  # 60 minutes (reduced from 30 to avoid rate limits)
    STATS_UPDATE_INTERVAL = 600         # 10 minutes (increased from 5 to avoid rate limits)
