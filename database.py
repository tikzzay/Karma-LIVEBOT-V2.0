#!/usr/bin/env python3
"""
Database Module for KARMA-LiveBOT
Handles all database operations and SQLite management
"""

import os
import sqlite3
import logging
import time

logger = logging.getLogger('KARMA-LiveBOT.Database')

class DatabaseManager:
    """Database manager with better concurrency handling"""
    
    def __init__(self, db_path='karma_bot.db'):
        # Use persistent storage paths for cloud deployment
        if os.path.exists('/data'):  # Railway.com volume
            db_path = '/data/karma_bot.db'
        elif os.path.exists('/var/data'):  # Render.com disk  
            db_path = '/var/data/karma_bot.db'
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self, timeout=30, max_retries=2):
        """Get database connection with retry logic for locked database"""
        for attempt in range(max_retries):
            try:
                conn = sqlite3.connect(self.db_path, timeout=timeout)
                conn.execute('PRAGMA journal_mode=WAL')  # Enable WAL mode for better concurrency
                conn.execute('PRAGMA synchronous=NORMAL')  # Balance between safety and speed
                conn.execute('PRAGMA cache_size=10000')  # Increase cache size
                conn.execute('PRAGMA temp_store=memory')  # Store temp tables in memory
                conn.execute('PRAGMA busy_timeout=10000')  # Wait up to 10s for locks
                return conn
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    wait_time = 0.1 * (attempt + 1)  # Simple linear backoff: 0.1s, 0.2s
                    logger.warning(f"Database locked, retrying in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)  # Short sleep shouldn't block heartbeat
                else:
                    raise e
        raise sqlite3.OperationalError("Failed to get database connection after all retries")
    
    def init_database(self):
        """Initialize database with all required tables"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Creator table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS creators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_user_id TEXT NOT NULL,
                discord_username TEXT NOT NULL,
                streamer_type TEXT NOT NULL CHECK (streamer_type IN ('karma', 'regular')),
                notification_channel_id TEXT NOT NULL,
                twitch_username TEXT,
                youtube_username TEXT,
                tiktok_username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(discord_user_id)
            )
        ''')
        
        # Daily Streaks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_streaks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                current_streak INTEGER DEFAULT 0,
                last_live_date DATE,
                FOREIGN KEY (creator_id) REFERENCES creators (id),
                UNIQUE(creator_id)
            )
        ''')
        
        # Event Streaks table (für Events)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS event_streaks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                current_event_streak INTEGER DEFAULT 0,
                event_points INTEGER DEFAULT 0,
                last_event_stream_date DATE,
                FOREIGN KEY (creator_id) REFERENCES creators (id),
                UNIQUE(creator_id)
            )
        ''')
        
        # Event Status table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS event_status (
                id INTEGER PRIMARY KEY,
                is_active BOOLEAN DEFAULT FALSE,
                started_at TIMESTAMP,
                ended_at TIMESTAMP
            )
        ''')
        
        # Creator Channels table (for platform-specific notification channels)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS creator_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                platform TEXT NOT NULL CHECK (platform IN ('twitch', 'youtube', 'tiktok')),
                channel_id TEXT NOT NULL,
                FOREIGN KEY (creator_id) REFERENCES creators (id),
                UNIQUE(creator_id, platform)
            )
        ''')
        
        # User Subscriptions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                creator_id INTEGER NOT NULL,
                platform TEXT NOT NULL DEFAULT 'all',
                subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (creator_id) REFERENCES creators (id),
                UNIQUE(user_id, creator_id, platform)
            )
        ''')
        
        # Live Status Tracking (prevents double notifications)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS live_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                is_live BOOLEAN DEFAULT FALSE,
                last_notification_date DATE,
                stream_start_time TIMESTAMP,
                FOREIGN KEY (creator_id) REFERENCES creators (id),
                UNIQUE(creator_id, platform)
            )
        ''')
        
        # Migration: Check if user_subscriptions needs platform column migration
        cursor.execute("PRAGMA table_info(user_subscriptions)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'platform' not in columns:
            # Safe migration: Create new table and migrate data
            cursor.execute('''
                CREATE TABLE user_subscriptions_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    creator_id INTEGER NOT NULL,
                    platform TEXT NOT NULL DEFAULT 'all',
                    subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (creator_id) REFERENCES creators (id),
                    UNIQUE(user_id, creator_id, platform)
                )
            ''')
            
            # Copy existing data with default 'all' platform
            cursor.execute('''
                INSERT INTO user_subscriptions_new (id, user_id, creator_id, platform, subscribed_at)
                SELECT id, user_id, creator_id, 'all', subscribed_at FROM user_subscriptions
            ''')
            
            # Replace old table
            cursor.execute('DROP TABLE user_subscriptions')
            cursor.execute('ALTER TABLE user_subscriptions_new RENAME TO user_subscriptions')
        
        # Migration: Backfill creator_channels from existing creators
        cursor.execute('SELECT id, notification_channel_id, twitch_username, youtube_username, tiktok_username FROM creators')
        existing_creators = cursor.fetchall()
        
        for creator_id, channel_id, twitch, youtube, tiktok in existing_creators:
            # Add channel entries for each platform that has a username
            if twitch:
                cursor.execute('''
                    INSERT OR IGNORE INTO creator_channels (creator_id, platform, channel_id)
                    VALUES (?, ?, ?)
                ''', (creator_id, 'twitch', channel_id))
            if youtube:
                cursor.execute('''
                    INSERT OR IGNORE INTO creator_channels (creator_id, platform, channel_id)
                    VALUES (?, ?, ?)
                ''', (creator_id, 'youtube', channel_id))
            if tiktok:
                cursor.execute('''
                    INSERT OR IGNORE INTO creator_channels (creator_id, platform, channel_id)
                    VALUES (?, ?, ?)
                ''', (creator_id, 'tiktok', channel_id))
        
        # Migration: Add message_id and notification_channel_id to live_status table for auto-deletion
        cursor.execute("PRAGMA table_info(live_status)")
        live_status_columns = [column[1] for column in cursor.fetchall()]
        if 'message_id' not in live_status_columns:
            cursor.execute('ALTER TABLE live_status ADD COLUMN message_id TEXT')
            logger.info("Added message_id column to live_status table")
        if 'notification_channel_id' not in live_status_columns:
            cursor.execute('ALTER TABLE live_status ADD COLUMN notification_channel_id TEXT')
            logger.info("Added notification_channel_id column to live_status table")
        
        # Migration: Add custom_message column to creators table for custom notifications
        cursor.execute("PRAGMA table_info(creators)")
        creators_columns = [column[1] for column in cursor.fetchall()]
        if 'custom_message' not in creators_columns:
            cursor.execute('ALTER TABLE creators ADD COLUMN custom_message TEXT DEFAULT NULL')
            logger.info("Added custom_message column to creators table")
        
        # Stats Channels table (für Voice Channel Statistiken)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stats_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                counter_type TEXT NOT NULL CHECK (counter_type IN ('online', 'peak_online', 'members', 'channels', 'roles', 'role_count')),
                role_id TEXT,
                last_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_id)
            )
        ''')
        
        # Social Media Stats Channels table (für Social Media Follower Statistiken)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS social_media_stats_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                platform TEXT NOT NULL CHECK (platform IN ('instagram', 'x', 'twitter', 'twitch', 'youtube', 'tiktok')),
                username TEXT NOT NULL,
                last_follower_count INTEGER DEFAULT 0,
                last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_id),
                UNIQUE(guild_id, platform, username)
            )
        ''')
        
        # Instant Gaming Configuration table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS instant_gaming_config (
                id INTEGER PRIMARY KEY,
                affiliate_tag TEXT NOT NULL DEFAULT 'tikzzay'
            )
        ''')
        
        # Custom Commands table (für Custom Slash Commands pro Server)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS custom_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                name TEXT NOT NULL,
                response TEXT,
                embed_title TEXT,
                embed_description TEXT,
                embed_color TEXT,
                button_label TEXT,
                button_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, name)
            )
        ''')
        
        # Giveaways table (für Giveaway-Verwaltung)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                message_id TEXT,
                description TEXT NOT NULL,
                keys TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                winner_count INTEGER NOT NULL,
                image_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ends_at TIMESTAMP NOT NULL,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')
        
        # Giveaway Participants table (Teilnehmer pro Giveaway)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS giveaway_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                giveaway_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (giveaway_id) REFERENCES giveaways (id),
                UNIQUE(giveaway_id, user_id)
            )
        ''')
        
        # Past Winners table (Globale Gewinner-Historie)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS past_winners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                giveaway_id INTEGER NOT NULL,
                won_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (giveaway_id) REFERENCES giveaways (id),
                UNIQUE(user_id, giveaway_id)
            )
        ''')
        
        # Initialize event status if not exists
        cursor.execute('INSERT OR IGNORE INTO event_status (id, is_active) VALUES (1, FALSE)')
        
        # Initialize Instant Gaming config if not exists
        cursor.execute('INSERT OR IGNORE INTO instant_gaming_config (id, affiliate_tag) VALUES (1, "tikzzay")')
        
        conn.commit()
        conn.close()
        logger.info("✅ Database initialized successfully")
