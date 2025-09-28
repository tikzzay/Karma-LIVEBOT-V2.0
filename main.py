#!/usr/bin/env python3
"""
KARMA-LiveBOT - Discord Bot für Live-Stream Benachrichtigungen
Unterstützt Twitch, YouTube und TikTok mit unterschiedlichen Streamer-Typen
"""

import os
import asyncio
import sqlite3
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import random
import difflib

import discord
from discord.ext import commands, tasks
import aiohttp
from aiohttp import web
import requests
from bs4 import BeautifulSoup
import json
import zipfile
import io

# OpenAI for automatic scraping repair
# the newest OpenAI model is "gpt-5" which was released August 7, 2025. 
# do not change this unless explicitly requested by the user
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    # Note: logger will be defined later, so we don't log here

# Logging Setup - Railway.com compatible
import sys

class RailwayLoggingHandler:
    """Custom logging handler that sends INFO/DEBUG to STDOUT and WARNING/ERROR to STDERR"""
    
    def __init__(self):
        # Create formatters
        self.formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        # Configure root logger (clear existing handlers to prevent duplication)
        root_logger = logging.getLogger()
        root_logger.handlers.clear()  # Prevent duplicate handlers
        root_logger.setLevel(logging.DEBUG)  # Allow DEBUG logs to pass through
        
        # Create STDOUT handler for INFO/DEBUG
        self.stdout_handler = logging.StreamHandler(sys.stdout)
        self.stdout_handler.setLevel(logging.DEBUG)
        self.stdout_handler.setFormatter(self.formatter)
        self.stdout_handler.addFilter(lambda record: record.levelno < logging.WARNING)
        
        # Create STDERR handler for WARNING/ERROR
        self.stderr_handler = logging.StreamHandler(sys.stderr)
        self.stderr_handler.setLevel(logging.WARNING)
        self.stderr_handler.setFormatter(self.formatter)
        
        # Add handlers to root logger
        root_logger.addHandler(self.stdout_handler)
        root_logger.addHandler(self.stderr_handler)

# Initialize Railway-compatible logging
railway_logging = RailwayLoggingHandler()

# SILENCE NOISY HTTP/DEBUG LOGS FOR CLEAN OUTPUT
logging.getLogger('httpcore.http2').setLevel(logging.WARNING)
logging.getLogger('httpcore.http11').setLevel(logging.WARNING)
logging.getLogger('httpcore.connection').setLevel(logging.WARNING)
logging.getLogger('hpack.hpack').setLevel(logging.WARNING)
logging.getLogger('hpack.table').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

# SILENCE DISCORD DEBUG SPAM FOR CLEAN LOGS
logging.getLogger('discord.http').setLevel(logging.WARNING)
logging.getLogger('discord.gateway').setLevel(logging.WARNING)
logging.getLogger('discord.client').setLevel(logging.WARNING)
logging.getLogger('discord.webhook').setLevel(logging.WARNING)  # Reduce webhook debug spam
logging.getLogger('discord.webhook.async_').setLevel(logging.WARNING)  # Reduce webhook debug spam
logging.getLogger('aiohttp.access').setLevel(logging.WARNING)

logger = logging.getLogger('KARMA-LiveBOT')

# Bot Configuration
class Config:
    # Discord IDs aus der Spezifikation
    ADMIN_ROLES = [1388945013735424020, 581139700408909864, 898970074491269170]
    USER_ROLES = [292321283608150016, 276471077402705920]  # Beide normale User-Rollen
    REGULAR_STREAMER_ROLE = 898194971029561344
    KARMA_STREAMER_ROLE = 898971225311838268
    LIVE_ROLE = 899306754549108786
    
    # API Keys aus Environment
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    DISCORD_APP_ID = os.getenv('DISCORD_APP_ID')
    TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
    TWITCH_CLIENT_SECRET = os.getenv('TWITCH_CLIENT_SECRET')
    YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
    TWITTER_BEARER_TOKEN = os.getenv('TWITTER_BEARER_TOKEN')
    INSTAGRAM_SESSION_ID = os.getenv('INSTAGRAM_SESSION_ID')
    
    # OpenAI Auto-Repair System
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    DEV_CHANNEL_ID = int(os.getenv('DEV_CHANNEL_ID')) if os.getenv('DEV_CHANNEL_ID') else None
    
    # Developer/Main Server Configuration
    MAIN_SERVER_ID = int(os.getenv('MAIN_SERVER_ID', '0'))  # Main server where dev logs should be posted
    
    # Platform Colors
    COLORS = {
        'twitch': 0x9146FF,    # Lila
        'youtube': 0xFF0000,   # Rot
        'tiktok': 0x00F2EA,    # Hellblau
        'instagram': 0xE4405F, # Instagram Pink
        'twitter': 0x1DA1F2,   # Twitter Blau
        'x': 0x000000          # X (Twitter) Schwarz
    }
    
    # Check Intervals
    KARMA_CHECK_INTERVAL = 60    # 1 Minute
    REGULAR_CHECK_INTERVAL = 180 # 3 Minuten
    SOCIAL_MEDIA_CHECK_INTERVAL = 1800 # 30 Minuten

# OpenAI Auto-Repair System
class OpenAIAutoRepair:
    """Automatisches Reparatur-System für Scraping-Fehler mit OpenAI-Unterstützung"""
    
    def __init__(self, bot):
        self.bot = bot
        self.openai_client = None
        self.repair_attempts = {}  # Track repair attempts per platform/method
        self.max_repairs_per_hour = 5  # Limit API calls
        self.repair_cooldown = {}  # Cooldown between repairs
        
        if OPENAI_AVAILABLE and Config.OPENAI_API_KEY:
            try:
                self.openai_client = OpenAI(api_key=Config.OPENAI_API_KEY)
                logger.info("🤖 OpenAI Auto-Repair System initialized successfully")
            except Exception as e:
                logger.error(f"🤖 Failed to initialize OpenAI client: {e}")
                self.openai_client = None
        else:
            logger.warning("🤖 OpenAI Auto-Repair System disabled - missing API key or library")
    
    async def send_dev_notification(self, title: str, description: str, error_details: str = None, fix_applied: str = None, color: int = 0xFF6B6B):
        """Sendet Entwickler-Benachrichtigung an DEV_CHANNEL_ID"""
        if not Config.DEV_CHANNEL_ID:
            logger.warning("🤖 DEV_CHANNEL_ID nicht konfiguriert - Benachrichtigung übersprungen")
            return
        
        try:
            channel = self.bot.get_channel(Config.DEV_CHANNEL_ID)
            if not channel:
                logger.error(f"🤖 DEV_CHANNEL_ID {Config.DEV_CHANNEL_ID} nicht gefunden")
                return
            
            embed = discord.Embed(
                title=f"🤖 {title}",
                description=description,
                color=color,
                timestamp=datetime.utcnow()
            )
            
            if error_details:
                embed.add_field(
                    name="❌ Fehler-Details",
                    value=f"```\n{error_details[:1000]}\n```",
                    inline=False
                )
            
            if fix_applied:
                embed.add_field(
                    name="🔧 Angewandte Reparatur",
                    value=f"```\n{fix_applied[:1000]}\n```",
                    inline=False
                )
            
            embed.set_footer(text="KARMA-LiveBOT Auto-Repair System")
            
            await channel.send(embed=embed)
            logger.info(f"🤖 Dev-Benachrichtigung gesendet: {title}")
            
        except Exception as e:
            logger.error(f"🤖 Fehler beim Senden der Dev-Benachrichtigung: {e}")
    
    async def attempt_repair(self, platform: str, method: str, error: str, html_content: str = None, url: str = None) -> dict:
        """Versucht automatische Reparatur mit OpenAI"""
        if not self.openai_client:
            return {"success": False, "reason": "OpenAI nicht verfügbar"}
        
        repair_key = f"{platform}_{method}"
        current_time = datetime.now()
        
        # Check cooldown (1 hour)
        if repair_key in self.repair_cooldown:
            if current_time - self.repair_cooldown[repair_key] < timedelta(hours=1):
                return {"success": False, "reason": "Cooldown aktiv (1 Stunde)"}
        
        # Check hourly limit
        if repair_key not in self.repair_attempts:
            self.repair_attempts[repair_key] = []
        
        # Remove attempts older than 1 hour
        self.repair_attempts[repair_key] = [
            timestamp for timestamp in self.repair_attempts[repair_key]
            if current_time - timestamp < timedelta(hours=1)
        ]
        
        if len(self.repair_attempts[repair_key]) >= self.max_repairs_per_hour:
            return {"success": False, "reason": f"Stündliches Limit erreicht ({self.max_repairs_per_hour})"}
        
        try:
            # Prepare context for OpenAI
            context = f"""
Du bist ein Experte für Web-Scraping und sollst helfen, kaputte Scraping-Selektoren zu reparieren.

PLATFORM: {platform}
METHOD: {method}
ERROR: {error}
URL: {url or 'N/A'}

CURRENT TASK:
- Analysiere den Fehler und den HTML-Content
- Schlage neue CSS-Selektoren oder BeautifulSoup-Pattern vor
- Gib eine JSON-Antwort mit neuen Scraping-Parametern zurück

EXPECTED JSON RESPONSE FORMAT:
{{
    "success": true,
    "selectors": ["selector1", "selector2"],
    "patterns": ["pattern1", "pattern2"],
    "explanation": "Erklärung der Änderungen",
    "confidence": 0.8
}}

HTML CONTENT (erste 2000 Zeichen):
{html_content[:2000] if html_content else 'Nicht verfügbar'}
"""
            
            # Call OpenAI
            response = self.openai_client.chat.completions.create(
                model="gpt-5",  # the newest OpenAI model is "gpt-5" which was released August 7, 2025
                messages=[{"role": "user", "content": context}],
                response_format={"type": "json_object"},
                max_tokens=1000
            )
            
            repair_suggestion = json.loads(response.choices[0].message.content)
            
            # Log attempt
            self.repair_attempts[repair_key].append(current_time)
            self.repair_cooldown[repair_key] = current_time
            
            # Send notification
            await self.send_dev_notification(
                title=f"Auto-Repair Versuch - {platform.title()}",
                description=f"OpenAI-Reparatur für {method} durchgeführt",
                error_details=f"Fehler: {error}\nURL: {url}",
                fix_applied=json.dumps(repair_suggestion, indent=2),
                color=0x57F287  # Green
            )
            
            return repair_suggestion
            
        except Exception as e:
            logger.error(f"🤖 OpenAI Auto-Repair Fehler: {e}")
            await self.send_dev_notification(
                title=f"Auto-Repair Fehler - {platform.title()}",
                description=f"OpenAI-Reparatur fehlgeschlagen für {method}",
                error_details=f"OpenAI Error: {str(e)}\nOriginal Error: {error}",
                color=0xED4245  # Red
            )
            return {"success": False, "reason": f"OpenAI Fehler: {str(e)}"}

# Database Manager with better concurrency handling
class DatabaseManager:
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
        
        # Initialize event status if not exists
        cursor.execute('INSERT OR IGNORE INTO event_status (id, is_active) VALUES (1, FALSE)')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True  # Required for accurate online member counting
# Note: presences intent must also be enabled in Discord Developer Portal

bot = commands.Bot(command_prefix='!', intents=intents)
db = DatabaseManager()

# Instant Gaming Integration
class InstantGamingAPI:
    """Integration for Instant Gaming game searches and affiliate links"""
    
    def __init__(self):
        self.affiliate_tag = "tikzzay"  # Affiliate tag for commission
        self.search_base_url = "https://www.instant-gaming.com/en/search/"
        self.cache = {}  # Cache search results to avoid repeated requests
        self.cache_duration = 1800  # 30 minutes cache
    
    def clear_cache(self):
        """Clear the search cache to force fresh requests"""
        self.cache.clear()
        logger.info("Instant Gaming cache cleared")
    
    def normalize_game_name(self, game: str) -> str:
        """Normalize game name for better matching on Instant Gaming"""
        game = game.lower()
        
        # Handle special cases for better matching
        special_cases = {
            "call of duty": "call of duty black ops 6",  # Default to latest popular version
            "cod": "call of duty black ops 6",
            "warzone": "call of duty warzone",
            "fortnite": "fortnite",
            "minecraft": "minecraft java edition",
            "gta": "grand theft auto v",
            "gta 5": "grand theft auto v",
            "gta v": "grand theft auto v"
        }
        
        # Check for special cases first
        for key, replacement in special_cases.items():
            if game.strip() == key:
                game = replacement
                break
        
        # Remove edition keywords that can interfere with search
        for bad in ["edition", "deluxe", "ultimate", "season", "beta", "early access", "definitive", "complete", "goty", "remastered"]:
            game = game.replace(bad, "")
        
        # Clean up punctuation and extra spaces
        game = game.replace(":", "").replace("-", " ").replace("_", " ")
        return " ".join(game.split())  # Remove extra whitespace

    async def search_game(self, game_name: str) -> Optional[Dict]:
        """Search for a game on Instant Gaming with smart matching and return direct product link"""
        if not game_name or not game_name.strip():
            return None
        
        # Normalize game name for better search results
        normalized_game = self.normalize_game_name(game_name)
        cache_key = f"instant_gaming_{normalized_game}"
        current_time = time.time()
        
        # Check cache first
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if current_time - cached_data['timestamp'] < self.cache_duration:
                logger.info(f"Using cached Instant Gaming data for {game_name}")
                return cached_data['data']
        
        try:
            # Use German URL with normalized game name
            search_url = f"https://www.instant-gaming.com/de/suche/?q={normalized_game.replace(' ', '+')}"
            
            logger.info(f"Searching Instant Gaming for: {game_name} (normalized: {normalized_game})")
            logger.info(f"Using URL: {search_url}")
            
            # Headers to appear like a real browser
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            }
            
            timeout = aiohttp.ClientTimeout(total=15)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, headers=headers, timeout=timeout) as response:
                    if response.status == 200:
                        html = await response.text()
                        
                        # Parse HTML with BeautifulSoup
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Find all products with their titles and links
                        products = []
                        
                        # Try multiple selectors to find product links
                        link_elements = soup.find_all("a", class_="cover") or soup.select('a[href*="/de/"]')
                        
                        for element in link_elements:
                            href = element.get('href', '')
                            if href and '/de/' in href:
                                # Get product title from img alt or nearby text
                                title = ""
                                img = element.find('img')
                                if img and img.get('alt'):
                                    title = img.get('alt').strip()
                                
                                if title and href:
                                    # Convert relative URLs to absolute
                                    if href.startswith('/'):
                                        href = f"https://www.instant-gaming.com{href}"
                                    products.append({'title': title, 'url': href})
                        
                        logger.info(f"Found {len(products)} products for {normalized_game}")
                        
                        if products:
                            # Use difflib to find the best match
                            import difflib
                            product_titles = [p['title'] for p in products]
                            
                            # Try to find close matches
                            best_matches = difflib.get_close_matches(game_name, product_titles, n=1, cutoff=0.4)
                            if not best_matches:
                                # If no close match with original name, try with normalized name
                                best_matches = difflib.get_close_matches(normalized_game, product_titles, n=1, cutoff=0.3)
                            
                            if best_matches:
                                # Find the product with the best matching title
                                best_title = best_matches[0]
                                best_product = next(p for p in products if p['title'] == best_title)
                                product_url = best_product['url']
                                
                                # Add affiliate tag to direct product link
                                separator = '&' if '?' in product_url else '?'
                                affiliate_url = f"{product_url}{separator}igr={self.affiliate_tag}"
                                
                                result = {
                                    'found': True,
                                    'game_name': best_title,
                                    'product_url': product_url,
                                    'affiliate_url': affiliate_url,
                                    'search_url': search_url,
                                    'match_confidence': difflib.SequenceMatcher(None, game_name.lower(), best_title.lower()).ratio()
                                }
                                
                                # Cache the result
                                self.cache[cache_key] = {
                                    'data': result,
                                    'timestamp': current_time
                                }
                                
                                logger.info(f"✅ Found matching product for '{game_name}': {best_title} (confidence: {result['match_confidence']:.2f})")
                                return result
                            else:
                                logger.info(f"❌ No good matches found for '{game_name}' on Instant Gaming")
                        else:
                            logger.info(f"❌ No products found for '{game_name}' on Instant Gaming")
                        
                        # Cache negative result
                        self.cache[cache_key] = {
                            'data': None,
                            'timestamp': current_time
                        }
                        return None
                    else:
                        logger.warning(f"Instant Gaming search failed with status {response.status} for {game_name}")
                        return None
        
        except Exception as e:
            logger.error(f"Error searching Instant Gaming for {game_name}: {e}")
            return None

# Initialize Instant Gaming API
instant_gaming = InstantGamingAPI()

# Social Media APIs Manager
class SocialMediaAPIs:
    """Manager for all social media platform APIs"""
    
    def __init__(self):
        self.twitter_bearer_token = Config.TWITTER_BEARER_TOKEN
        self.instagram_session_id = Config.INSTAGRAM_SESSION_ID
        self.youtube_api_key = Config.YOUTUBE_API_KEY
        self.twitch_client_id = Config.TWITCH_CLIENT_ID
        self.twitch_client_secret = Config.TWITCH_CLIENT_SECRET
        self.cache = {}  # Cache for follower counts
        self.cache_duration = 300  # 5 minutes cache
    
    async def get_follower_count(self, platform: str, username: str) -> Optional[int]:
        """Get follower count for a given platform and username"""
        cache_key = f"{platform}_{username}"
        current_time = time.time()
        
        # Check cache first
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if current_time - cached_data['timestamp'] < self.cache_duration:
                logger.info(f"Using cached follower count for {platform}/{username}: {cached_data['count']}")
                return cached_data['count']
        
        try:
            if platform == 'instagram':
                count = await self._get_instagram_followers(username)
            elif platform in ['x', 'twitter']:
                count = await self._get_twitter_followers(username)
            elif platform == 'youtube':
                count = await self._get_youtube_subscribers(username)
            elif platform == 'tiktok':
                count = await self._get_tiktok_followers(username)
            elif platform == 'twitch':
                count = await self._get_twitch_followers(username)
            else:
                logger.error(f"Unsupported platform: {platform}")
                return None
            
            if count is not None:
                # Cache the result
                self.cache[cache_key] = {
                    'count': count,
                    'timestamp': current_time
                }
                logger.info(f"✅ Retrieved {platform} followers for {username}: {count:,}")
                return count
            else:
                logger.warning(f"❌ Failed to get {platform} followers for {username}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting {platform} followers for {username}: {e}")
            return None
    
    async def _get_instagram_followers(self, username: str) -> Optional[int]:
        """Get Instagram follower count via web scraping"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"'
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                # Try multiple Instagram endpoints
                urls = [
                    f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}",
                    f"https://www.instagram.com/{username}/",
                    f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
                ]
                
                for url in urls:
                    try:
                        async with session.get(url, headers=headers) as response:
                            if response.status == 200:
                                if 'api/v1/users/web_profile_info' in url:
                                    data = await response.json()
                                    # Safe navigation through nested data
                                    if data and isinstance(data, dict):
                                        data_section = data.get('data')
                                        if data_section and isinstance(data_section, dict):
                                            user = data_section.get('user')
                                            if user and isinstance(user, dict):
                                                edge_followed_by = user.get('edge_followed_by')
                                                if edge_followed_by and isinstance(edge_followed_by, dict):
                                                    count = edge_followed_by.get('count')
                                                    if count is not None:
                                                        return int(count)
                                else:
                                    # HTML scraping fallback
                                    text = await response.text()
                                    if 'edge_followed_by' in text:
                                        import re
                                        # Look for follower count in HTML/JS
                                        match = re.search(r'"edge_followed_by":{"count":(\d+)', text)
                                        if match:
                                            return int(match.group(1))
                            else:
                                logger.debug(f"Instagram URL {url} returned status {response.status}")
                    except Exception as e:
                        logger.debug(f"Instagram URL {url} failed: {e}")
                        continue
                
                logger.warning(f"All Instagram methods failed for {username}")
                return None
                
        except Exception as e:
            logger.error(f"Instagram API error for {username}: {e}")
            
            # 🤖 TRIGGER AUTO-REPAIR SYSTEM FOR INSTAGRAM ERRORS
            if auto_repair_system:
                try:
                    logger.info(f"🤖 Triggering auto-repair for Instagram scraping failure (@{username})")
                    repair_result = await auto_repair_system.attempt_repair(
                        platform="instagram",
                        method="follower_scraping",
                        error=f"Instagram scraping error: {str(e)}",
                        url=f"https://www.instagram.com/{username}/"
                    )
                    logger.info(f"🤖 Auto-repair result for Instagram @{username}: {repair_result}")
                except Exception as repair_error:
                    logger.error(f"🤖 Auto-repair system error: {repair_error}")
            
            return None
    
    async def _get_twitter_followers(self, username: str) -> Optional[int]:
        """Get Twitter/X follower count via official API v2"""
        if not self.twitter_bearer_token:
            logger.warning("Twitter Bearer Token not configured")
            return None
            
        try:
            headers = {
                'Authorization': f'Bearer {self.twitter_bearer_token}',
                'User-Agent': 'TwitterBot/1.0'
            }
            
            async with aiohttp.ClientSession() as session:
                url = f"https://api.twitter.com/2/users/by/username/{username}?user.fields=public_metrics"
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        followers = data.get('data', {}).get('public_metrics', {}).get('followers_count')
                        return followers
                    else:
                        logger.warning(f"Twitter API returned status {response.status} for {username}")
                        return None
        except Exception as e:
            logger.error(f"Twitter API error for {username}: {e}")
            return None
    
    async def _get_youtube_subscribers(self, username: str) -> Optional[int]:
        """Get YouTube subscriber count via official API and fallback methods"""
        try:
            # If API key is available, use official API
            if self.youtube_api_key:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                    # Try multiple methods with API key
                    methods = [
                        f"https://www.googleapis.com/youtube/v3/channels?part=statistics&forUsername={username}&key={self.youtube_api_key}",
                        f"https://www.googleapis.com/youtube/v3/channels?part=statistics&id={username}&key={self.youtube_api_key}",
                        f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={username}&type=channel&key={self.youtube_api_key}"
                    ]
                    
                    for i, url in enumerate(methods):
                        try:
                            async with session.get(url) as response:
                                if response.status == 200:
                                    data = await response.json()
                                    if data and data.get('items'):
                                        if i == 2:  # Search API result
                                            # Get channel ID from search and fetch statistics
                                            channel_id = data['items'][0]['snippet']['channelId']
                                            stats_url = f"https://www.googleapis.com/youtube/v3/channels?part=statistics&id={channel_id}&key={self.youtube_api_key}"
                                            async with session.get(stats_url) as stats_response:
                                                if stats_response.status == 200:
                                                    stats_data = await stats_response.json()
                                                    if stats_data and stats_data.get('items'):
                                                        subscribers = stats_data['items'][0].get('statistics', {}).get('subscriberCount')
                                                        if subscribers:
                                                            return int(subscribers)
                                        else:
                                            # Direct statistics result
                                            subscribers = data['items'][0].get('statistics', {}).get('subscriberCount')
                                            if subscribers:
                                                return int(subscribers)
                                else:
                                    logger.debug(f"YouTube API method {i+1} returned status {response.status}")
                        except Exception as e:
                            logger.debug(f"YouTube API method {i+1} failed: {e}")
                            continue
            
            # Fallback: web scraping method
            logger.info(f"Using web scraping fallback for YouTube user: {username}")
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                # Try different YouTube URL formats
                urls = [
                    f"https://www.youtube.com/@{username}/about",
                    f"https://www.youtube.com/c/{username}/about",
                    f"https://www.youtube.com/user/{username}/about",
                    f"https://www.youtube.com/channel/{username}/about"
                ]
                
                for url in urls:
                    try:
                        async with session.get(url, headers=headers) as response:
                            if response.status == 200:
                                text = await response.text()
                                # Look for subscriber count in HTML
                                import re
                                patterns = [
                                    r'"subscriberCountText":{"accessibility":{"accessibilityData":{"label":"([\d,\.]+)\s+subscriber',
                                    r'"subscriberCountText":{"simpleText":"([\d,\.]+)\s+subscriber',
                                    r'([\d,\.]+)\s+subscriber',
                                    r'"subscriberCount":"(\d+)"'
                                ]
                                
                                for pattern in patterns:
                                    match = re.search(pattern, text, re.IGNORECASE)
                                    if match:
                                        subscriber_str = match.group(1).replace(',', '').replace('.', '')
                                        # Handle K/M/B suffixes
                                        if 'K' in subscriber_str.upper():
                                            subscriber_str = subscriber_str.upper().replace('K', '')
                                            return int(float(subscriber_str) * 1000)
                                        elif 'M' in subscriber_str.upper():
                                            subscriber_str = subscriber_str.upper().replace('M', '')
                                            return int(float(subscriber_str) * 1000000)
                                        elif 'B' in subscriber_str.upper():
                                            subscriber_str = subscriber_str.upper().replace('B', '')
                                            return int(float(subscriber_str) * 1000000000)
                                        else:
                                            return int(subscriber_str)
                            else:
                                logger.debug(f"YouTube URL {url} returned status {response.status}")
                    except Exception as e:
                        logger.debug(f"YouTube URL {url} failed: {e}")
                        continue
            
            logger.warning(f"All YouTube methods failed for {username}")
            return None
                
        except Exception as e:
            logger.error(f"YouTube API error for {username}: {e}")
            return None
    
    async def _get_tiktok_followers(self, username: str) -> Optional[int]:
        """Get TikTok follower count via web scraping"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.tiktok.com/',
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"'
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                # Try multiple TikTok endpoints
                urls = [
                    f"https://www.tiktok.com/api/user/detail/?uniqueId={username}",
                    f"https://www.tiktok.com/@{username}"
                ]
                
                for url in urls:
                    try:
                        async with session.get(url, headers=headers) as response:
                            if response.status == 200:
                                if 'api/user/detail' in url:
                                    data = await response.json()
                                    # Safe navigation through nested data
                                    user_info = data.get('userInfo') if data else None
                                    if user_info and isinstance(user_info, dict):
                                        stats = user_info.get('stats')
                                        if stats and isinstance(stats, dict):
                                            followers = stats.get('followerCount')
                                            if followers is not None:
                                                return int(followers)
                                else:
                                    # HTML scraping fallback
                                    text = await response.text()
                                    if 'followerCount' in text:
                                        import re
                                        # Look for follower count in HTML/JS
                                        match = re.search(r'"followerCount":(\d+)', text)
                                        if match:
                                            return int(match.group(1))
                            else:
                                logger.debug(f"TikTok URL {url} returned status {response.status}")
                    except Exception as e:
                        logger.debug(f"TikTok URL {url} failed: {e}")
                        continue
                
                logger.warning(f"All TikTok methods failed for {username}")
                return None
                
        except Exception as e:
            logger.error(f"TikTok API error for {username}: {e}")
            return None
    
    async def _get_twitch_followers(self, username: str) -> Optional[int]:
        """Get Twitch follower count via official API"""
        if not self.twitch_client_id or not self.twitch_client_secret:
            logger.warning("Twitch API credentials not configured")
            return None
            
        try:
            # Get access token first (reuse existing TwitchAPI logic)
            twitch_api = TwitchAPI()
            access_token = await twitch_api.get_access_token()
            if not access_token:
                return None
            
            headers = {
                'Client-ID': self.twitch_client_id,
                'Authorization': f'Bearer {access_token}'
            }
            
            async with aiohttp.ClientSession() as session:
                # Get user ID first
                url = f"https://api.twitch.tv/helix/users?login={username}"
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('data'):
                            user_id = data['data'][0]['id']
                            
                            # Get follower count
                            url = f"https://api.twitch.tv/helix/channels/followers?broadcaster_id={user_id}"
                            async with session.get(url, headers=headers) as response:
                                if response.status == 200:
                                    data = await response.json()
                                    return data.get('total', 0)
                    else:
                        logger.warning(f"Twitch API returned status {response.status} for {username}")
                        return None
        except Exception as e:
            logger.error(f"Twitch API error for {username}: {e}")
            return None
    
    async def validate_username(self, platform: str, username: str) -> bool:
        """Validate if username exists on platform"""
        count = await self.get_follower_count(platform, username)
        return count is not None

# Initialize Social Media APIs
social_media_apis = SocialMediaAPIs()

# Web-Scraping Only APIs for Social Media Stats (no API limits)
class SocialMediaScrapingOnlyAPIs:
    """Social Media APIs that ONLY use web scraping to avoid API limits"""
    
    def __init__(self):
        self.cache = {}  # Cache for follower counts
        self.cache_duration = 300  # 5 minutes cache
    
    async def get_follower_count_scraping_only(self, platform: str, username: str) -> Optional[int]:
        """Get follower count using ONLY web scraping methods (no API calls)"""
        cache_key = f"scraping_{platform}_{username}"
        current_time = time.time()
        
        # Check cache first
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if current_time - cached_data['timestamp'] < self.cache_duration:
                logger.info(f"Using cached scraping follower count for {platform}/{username}: {cached_data['count']:,}")
                return cached_data['count']
        
        try:
            if platform == 'instagram':
                count = await self._scrape_instagram_followers(username)
            elif platform in ['x', 'twitter']:
                count = await self._scrape_twitter_followers(username)
            elif platform == 'youtube':
                count = await self._scrape_youtube_subscribers(username)
            elif platform == 'tiktok':
                count = await self._scrape_tiktok_followers(username)
            elif platform == 'twitch':
                count = await self._scrape_twitch_followers(username)
            else:
                logger.error(f"Unsupported platform for scraping: {platform}")
                return None
            
            if count is not None:
                # Cache the result
                self.cache[cache_key] = {
                    'count': count,
                    'timestamp': current_time
                }
                logger.info(f"🕷️ Scraped {platform} followers for {username}: {count:,}")
                return count
            else:
                logger.warning(f"❌ Failed to scrape {platform} followers for {username}")
                return None
                
        except Exception as e:
            logger.error(f"Error scraping {platform} followers for {username}: {e}")
            return None
    
    async def validate_username_scraping_only(self, platform: str, username: str) -> tuple[bool, str]:
        """Validate if username exists on platform using ONLY scraping
        
        Returns:
            tuple[bool, str]: (is_valid, error_message)
            - (True, ""): User exists
            - (False, "not_found"): User definitely does not exist
            - (False, "scraping_error"): Temporary scraping issue
        """
        try:
            count = await self.get_follower_count_scraping_only(platform, username)
            if count is not None:
                return True, ""
            else:
                # Check if this was a scraping error vs user not found
                # Try a simple connection test
                try:
                    test_result = await self._test_platform_connectivity(platform)
                    if not test_result:
                        return False, "scraping_error"  # Platform issues
                    else:
                        return False, "not_found"  # User likely doesn't exist
                except:
                    return False, "scraping_error"  # Connectivity issues
        except Exception as e:
            logger.error(f"Validation error for {platform}/{username}: {e}")
            return False, "scraping_error"
    
    async def _test_platform_connectivity(self, platform: str) -> bool:
        """Test if we can reach the platform (simple connectivity check)"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            test_urls = {
                'instagram': 'https://www.instagram.com/',
                'youtube': 'https://www.youtube.com/',
                'tiktok': 'https://www.tiktok.com/',
                'twitter': 'https://twitter.com/',
                'x': 'https://x.com/',
                'twitch': 'https://www.twitch.tv/'
            }
            
            url = test_urls.get(platform)
            if not url:
                return False
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url, headers=headers) as response:
                    return response.status < 500  # Accept 4xx but not 5xx
        except:
            return False
    
    async def _scrape_instagram_followers(self, username: str) -> Optional[int]:
        """Instagram follower scraping - web only, no API"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                # Only use web scraping methods for Instagram
                urls = [
                    f"https://www.instagram.com/{username}/",
                    f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
                ]
                
                for url in urls:
                    try:
                        async with session.get(url, headers=headers) as response:
                            if response.status == 200:
                                if 'api/v1/users/web_profile_info' in url:
                                    data = await response.json()
                                    if data and isinstance(data, dict):
                                        data_section = data.get('data')
                                        if data_section and isinstance(data_section, dict):
                                            user = data_section.get('user')
                                            if user and isinstance(user, dict):
                                                edge_followed_by = user.get('edge_followed_by')
                                                if edge_followed_by and isinstance(edge_followed_by, dict):
                                                    count = edge_followed_by.get('count')
                                                    if count is not None:
                                                        return int(count)
                                else:
                                    # HTML scraping
                                    text = await response.text()
                                    if 'edge_followed_by' in text:
                                        import re
                                        match = re.search(r'"edge_followed_by":{"count":(\d+)', text)
                                        if match:
                                            return int(match.group(1))
                            else:
                                logger.debug(f"Instagram scraping URL {url} returned status {response.status}")
                    except Exception as e:
                        logger.debug(f"Instagram scraping URL {url} failed: {e}")
                        continue
                
                logger.warning(f"All Instagram scraping methods failed for {username}")
                return None
                
        except Exception as e:
            logger.error(f"Instagram scraping error for {username}: {e}")
            return None
    
    async def _scrape_twitter_followers(self, username: str) -> Optional[int]:
        """Twitter/X follower scraping - web only, no API"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                # Twitter/X scraping is difficult due to API restrictions
                # We'll try basic methods but this is the least reliable
                urls = [
                    f"https://nitter.net/{username}",  # Nitter alternative frontend
                    f"https://twitter.com/{username}"
                ]
                
                for url in urls:
                    try:
                        async with session.get(url, headers=headers) as response:
                            if response.status == 200:
                                text = await response.text()
                                import re
                                # Look for follower patterns
                                patterns = [
                                    r'([\d,\.]+)\s+[Ff]ollower',
                                    r'"followers_count":(\d+)',
                                    r'follower.*?([\d,\.]+)'
                                ]
                                
                                for pattern in patterns:
                                    match = re.search(pattern, text, re.IGNORECASE)
                                    if match:
                                        follower_str = match.group(1).replace(',', '').replace('.', '')
                                        # Handle K/M/B suffixes
                                        if 'K' in follower_str.upper():
                                            follower_str = follower_str.upper().replace('K', '')
                                            return int(float(follower_str) * 1000)
                                        elif 'M' in follower_str.upper():
                                            follower_str = follower_str.upper().replace('M', '')
                                            return int(float(follower_str) * 1000000)
                                        else:
                                            return int(follower_str)
                            else:
                                logger.debug(f"Twitter scraping URL {url} returned status {response.status}")
                    except Exception as e:
                        logger.debug(f"Twitter scraping URL {url} failed: {e}")
                        continue
                
                logger.warning(f"All Twitter scraping methods failed for {username}")
                return None
                
        except Exception as e:
            logger.error(f"Twitter scraping error for {username}: {e}")
            return None
    
    async def _scrape_youtube_subscribers(self, username: str) -> Optional[int]:
        """YouTube subscriber scraping - web only, no API"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                # Try different YouTube URL formats
                urls = [
                    f"https://www.youtube.com/@{username}/about",
                    f"https://www.youtube.com/c/{username}/about",
                    f"https://www.youtube.com/user/{username}/about",
                    f"https://www.youtube.com/channel/{username}/about"
                ]
                
                for url in urls:
                    try:
                        async with session.get(url, headers=headers) as response:
                            if response.status == 200:
                                text = await response.text()
                                import re
                                patterns = [
                                    r'"subscriberCountText":{"accessibility":{"accessibilityData":{"label":"([\d,\.]+)\s+subscriber',
                                    r'"subscriberCountText":{"simpleText":"([\d,\.]+)\s+subscriber',
                                    r'([\d,\.]+)\s+subscriber',
                                    r'"subscriberCount":"(\d+)"'
                                ]
                                
                                for pattern in patterns:
                                    match = re.search(pattern, text, re.IGNORECASE)
                                    if match:
                                        subscriber_str = match.group(1).replace(',', '').replace('.', '')
                                        # Handle K/M/B suffixes
                                        if 'K' in subscriber_str.upper():
                                            subscriber_str = subscriber_str.upper().replace('K', '')
                                            return int(float(subscriber_str) * 1000)
                                        elif 'M' in subscriber_str.upper():
                                            subscriber_str = subscriber_str.upper().replace('M', '')
                                            return int(float(subscriber_str) * 1000000)
                                        elif 'B' in subscriber_str.upper():
                                            subscriber_str = subscriber_str.upper().replace('B', '')
                                            return int(float(subscriber_str) * 1000000000)
                                        else:
                                            return int(subscriber_str)
                            else:
                                logger.debug(f"YouTube scraping URL {url} returned status {response.status}")
                    except Exception as e:
                        logger.debug(f"YouTube scraping URL {url} failed: {e}")
                        continue
                
                logger.warning(f"All YouTube scraping methods failed for {username}")
                return None
                
        except Exception as e:
            logger.error(f"YouTube scraping error for {username}: {e}")
            return None
    
    async def _scrape_tiktok_followers(self, username: str) -> Optional[int]:
        """TikTok follower scraping - web only, no API"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.tiktok.com/'
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                # Try TikTok web methods
                urls = [
                    f"https://www.tiktok.com/@{username}"
                ]
                
                for url in urls:
                    try:
                        async with session.get(url, headers=headers) as response:
                            if response.status == 200:
                                text = await response.text()
                                if 'followerCount' in text:
                                    import re
                                    # Look for follower count in HTML/JS
                                    match = re.search(r'"followerCount":(\d+)', text)
                                    if match:
                                        return int(match.group(1))
                            else:
                                logger.debug(f"TikTok scraping URL {url} returned status {response.status}")
                    except Exception as e:
                        logger.debug(f"TikTok scraping URL {url} failed: {e}")
                        continue
                
                logger.warning(f"All TikTok scraping methods failed for {username}")
                
                # 🤖 TRIGGER AUTO-REPAIR SYSTEM
                if auto_repair_system:
                    try:
                        logger.info(f"🤖 Triggering auto-repair for TikTok scraping failure (@{username})")
                        repair_result = await auto_repair_system.attempt_repair(
                            platform="tiktok",
                            method="follower_scraping",
                            error=f"All TikTok scraping methods failed for {username} - no followerCount found in HTML",
                            html_content=text if 'text' in locals() else None,
                            url=f"https://www.tiktok.com/@{username}"
                        )
                        logger.info(f"🤖 Auto-repair result for TikTok @{username}: {repair_result}")
                    except Exception as repair_error:
                        logger.error(f"🤖 Auto-repair system error: {repair_error}")
                
                return None
                
        except Exception as e:
            logger.error(f"TikTok scraping error for {username}: {e}")
            
            # 🤖 TRIGGER AUTO-REPAIR SYSTEM FOR EXCEPTIONS
            if auto_repair_system:
                try:
                    logger.info(f"🤖 Triggering auto-repair for TikTok exception (@{username})")
                    repair_result = await auto_repair_system.attempt_repair(
                        platform="tiktok",
                        method="follower_scraping_exception",
                        error=f"TikTok scraping exception: {str(e)}",
                        url=f"https://www.tiktok.com/@{username}"
                    )
                    logger.info(f"🤖 Auto-repair result for TikTok exception @{username}: {repair_result}")
                except Exception as repair_error:
                    logger.error(f"🤖 Auto-repair system error: {repair_error}")
            
            return None
    
    async def _scrape_twitch_followers(self, username: str) -> Optional[int]:
        """Twitch follower scraping - web only, no API"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                url = f"https://www.twitch.tv/{username}"
                
                try:
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            text = await response.text()
                            import re
                            # Look for follower patterns in Twitch HTML
                            patterns = [
                                r'([\d,\.]+)\s+[Ff]ollower',
                                r'"followers":(\d+)',
                                r'follower.*?([\d,\.]+)'
                            ]
                            
                            for pattern in patterns:
                                match = re.search(pattern, text, re.IGNORECASE)
                                if match:
                                    follower_str = match.group(1).replace(',', '').replace('.', '')
                                    # Handle K/M suffixes
                                    if 'K' in follower_str.upper():
                                        follower_str = follower_str.upper().replace('K', '')
                                        return int(float(follower_str) * 1000)
                                    elif 'M' in follower_str.upper():
                                        follower_str = follower_str.upper().replace('M', '')
                                        return int(float(follower_str) * 1000000)
                                    else:
                                        return int(follower_str)
                        else:
                            logger.debug(f"Twitch scraping returned status {response.status}")
                except Exception as e:
                    logger.debug(f"Twitch scraping failed: {e}")
                
                logger.warning(f"Twitch scraping failed for {username}")
                return None
                
        except Exception as e:
            logger.error(f"Twitch scraping error for {username}: {e}")
            return None

# Initialize Social Media Scraping-Only APIs
social_media_scraping_apis = SocialMediaScrapingOnlyAPIs()

# Initialize Auto-Repair System (will be set in on_ready)
auto_repair_system = None

# Platform API Managers
class TwitchAPI:
    def __init__(self):
        self.client_id = Config.TWITCH_CLIENT_ID
        self.client_secret = Config.TWITCH_CLIENT_SECRET
        self.access_token = None
        self.token_expires_at = None
    
    async def get_access_token(self):
        """Get or refresh Twitch access token"""
        if self.access_token and self.token_expires_at and datetime.now() < self.token_expires_at:
            return self.access_token
        
        url = 'https://id.twitch.tv/oauth2/token'
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'client_credentials'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as response:
                if response.status == 200:
                    token_data = await response.json()
                    self.access_token = token_data['access_token']
                    expires_in = token_data['expires_in']
                    self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)
                    return self.access_token
                else:
                    logger.error(f"Failed to get Twitch token: {response.status}")
                    return None
    
    async def get_stream_info(self, username: str) -> Optional[Dict]:
        """Get stream information for a Twitch user"""
        token = await self.get_access_token()
        if not token:
            return None
        
        headers = {
            'Client-ID': self.client_id,
            'Authorization': f'Bearer {token}'
        }
        
        # Get user info first
        user_url = f'https://api.twitch.tv/helix/users?login={username}'
        async with aiohttp.ClientSession() as session:
            async with session.get(user_url, headers=headers) as response:
                if response.status != 200:
                    logger.error(f"Failed to get Twitch user info for {username}")
                    return None
                
                user_data = await response.json()
                if not user_data['data']:
                    return None
                
                user_id = user_data['data'][0]['id']
                profile_image = user_data['data'][0]['profile_image_url']
        
        # Get stream info
        stream_url = f'https://api.twitch.tv/helix/streams?user_id={user_id}'
        async with aiohttp.ClientSession() as session:
            async with session.get(stream_url, headers=headers) as response:
                if response.status == 200:
                    stream_data = await response.json()
                    if stream_data['data']:
                        stream = stream_data['data'][0]
                        
                        # Get follower count
                        follower_count = 0
                        try:
                            follower_url = f'https://api.twitch.tv/helix/channels/followers?broadcaster_id={user_id}'
                            async with session.get(follower_url, headers=headers) as follower_response:
                                if follower_response.status == 200:
                                    follower_data = await follower_response.json()
                                    follower_count = follower_data.get('total', 0)
                        except Exception as e:
                            logger.error(f"Failed to get Twitch follower count for {username}: {e}")
                        
                        return {
                            'is_live': True,
                            'viewer_count': stream['viewer_count'],
                            'game_name': stream['game_name'],
                            'title': stream['title'],
                            'thumbnail_url': stream['thumbnail_url'].replace('{width}', '1920').replace('{height}', '1080'),
                            'profile_image_url': profile_image,
                            'platform_url': f'https://twitch.tv/{username}',
                            'follower_count': follower_count
                        }
                    else:
                        return {'is_live': False}
                return None

class YouTubeAPI:
    def __init__(self):
        self.api_key = Config.YOUTUBE_API_KEY
        self.cache = {}  # Cache für API-Responses
        self.cache_duration = 300  # 5 Minuten Cache
        self.scrape_cache = {}  # Cache für Scraping-Results
        self.scrape_cache_duration = 60  # 1 Minute Cache für Scraping
        self.quota_backoff = {}  # Backoff für Quota-exceeded per user
        self.quota_backoff_duration = 1800  # 30 Minuten Backoff
    
    async def quick_live_check(self, username: str) -> bool:
        """Quick live check via web scraping - saves API quota"""
        import time
        import re
        import json
        
        # Check scraping cache first
        scrape_key = f"youtube_scrape_{username}"
        current_time = time.time()
        
        if scrape_key in self.scrape_cache:
            cached_data = self.scrape_cache[scrape_key]
            if current_time - cached_data['timestamp'] < self.scrape_cache_duration:
                logger.info(f"Using cached scraping data for {username}")
                return cached_data['is_live']
        
        try:
            # Try primary URL format first
            urls_to_check = [
                f'https://www.youtube.com/@{username}',
                f'https://www.youtube.com/c/{username}',
                f'https://www.youtube.com/user/{username}'
            ]
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive',
            }
            
            timeout = aiohttp.ClientTimeout(total=5)  # Reduced timeout
            
            # Use single session for all URL attempts
            async with aiohttp.ClientSession() as session:
                for url in urls_to_check:
                    try:
                        async with session.get(url, headers=headers, timeout=timeout) as response:
                            if response.status == 200:
                                html = await response.text()
                                
                                # Look for ytInitialData first (most reliable)
                                ytdata_pattern = r'ytInitialData"]\s*=\s*({.+?});'
                                ytdata_match = re.search(ytdata_pattern, html)
                                
                                live_indicators_found = 0
                                
                                if ytdata_match:
                                    try:
                                        data = json.loads(ytdata_match.group(1))
                                        # Look for live indicators in JSON
                                        data_str = json.dumps(data)
                                        if '"isLive":true' in data_str or '"liveBroadcastContent":"live"' in data_str:
                                            live_indicators_found += 2  # Strong indicator
                                    except:
                                        pass
                                
                                # Look for additional live indicators (require multiple signals)
                                additional_indicators = [
                                    'watching now',  # More specific than just "watching"
                                    'viewers watching',  # Specific viewer count text
                                    '"isLiveContent":true',  # JSON data
                                    '"liveBroadcastContent":"live"',  # JSON data
                                ]
                                
                                for indicator in additional_indicators:
                                    if indicator in html:
                                        live_indicators_found += 1
                                
                                # Require at least 2 indicators to reduce false positives
                                is_live = live_indicators_found >= 2
                                
                                # Cache the result
                                self.scrape_cache[scrape_key] = {
                                    'is_live': is_live,
                                    'timestamp': current_time
                                }
                                
                                logger.info(f"YouTube scraping for {username}: {'LIVE' if is_live else 'OFFLINE'} (indicators: {live_indicators_found})")
                                return is_live
                    except Exception as e:
                        continue  # Try next URL format
                    
            # If all URLs failed, cache as offline
            self.scrape_cache[scrape_key] = {
                'is_live': False,
                'timestamp': current_time
            }
            return False
            
        except Exception as e:
            logger.error(f"YouTube scraping error for {username}: {e}")
            return False

    async def get_stream_info(self, username: str) -> Optional[Dict]:
        """Smart Polling: Scraping first, API only for details"""
        import time
        
        # PHASE 1: Quick live check via scraping (FREE)
        is_live_basic = await self.quick_live_check(username)
        
        if not is_live_basic:
            # Not live according to scraping - return immediately
            return {'is_live': False, 'method': 'scraping'}
        
        # PHASE 2: Get detailed info via API (EXPENSIVE - only when live)
        logger.info(f"YouTube {username} appears live via scraping, getting detailed info via API")
        
        # Check quota backoff first
        backoff_key = f"youtube_backoff_{username}"
        current_time = time.time()
        
        if backoff_key in self.quota_backoff:
            backoff_data = self.quota_backoff[backoff_key]
            if current_time - backoff_data['timestamp'] < self.quota_backoff_duration:
                logger.info(f"YouTube quota backoff active for {username}, skipping API call")
                return {'is_live': True, 'method': 'scraping_only', 'backoff_remaining': int(self.quota_backoff_duration - (current_time - backoff_data['timestamp']))}
        
        # Check API cache first
        cache_key = f"youtube_api_{username}"
        
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if current_time - cached_data['timestamp'] < self.cache_duration:
                logger.info(f"Using cached YouTube API data for {username}")
                return cached_data['data']
        
        # Handle quota exceeded gracefully
        try:
            # Get channel info by username
            search_url = f'https://www.googleapis.com/youtube/v3/search'
            params = {
                'part': 'snippet',
                'q': f'@{username}',
                'type': 'channel',
                'key': self.api_key,
                'maxResults': 1
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, params=params) as response:
                    if response.status == 403:
                        # Quota exceeded - set backoff and return cached data or scraping result
                        self.quota_backoff[backoff_key] = {'timestamp': current_time}
                        logger.info(f"YouTube quota exceeded for {username}, setting 30min backoff")
                        
                        if cache_key in self.cache:
                            logger.info(f"YouTube quota exceeded, using cached data for {username}")
                            return self.cache[cache_key]['data']
                        else:
                            # Return basic live info based on scraping
                            return {'is_live': True, 'method': 'quota_exceeded_fallback', 'title': 'Live Stream', 'viewer_count': 0}
                    elif response.status != 200:
                        error_data = await response.text()
                        logger.error(f"Failed to search YouTube channel for {username} - Status: {response.status} - Error: {error_data}")
                        return {'is_live': False, 'method': 'api_error'}
                    else:
                        # Fix: Parse JSON inside response context
                        search_data = await response.json()
                        if not search_data.get('items'):
                            result = {'is_live': False, 'method': 'api_no_channel'}
                            self.cache[cache_key] = {'data': result, 'timestamp': current_time}
                            return result
                        
                        # Extract channel ID and profile image
                        channel_id = search_data['items'][0]['id']['channelId']
                        profile_image = search_data['items'][0]['snippet']['thumbnails']['high']['url']
            
            # Check for live streams
            live_url = f'https://www.googleapis.com/youtube/v3/search'
            live_params = {
                'part': 'snippet',
                'channelId': channel_id,
                'eventType': 'live',
                'type': 'video',
                'key': self.api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(live_url, params=live_params) as response:
                    if response.status == 200:
                        live_data = await response.json()
                        if live_data.get('items'):
                            video = live_data['items'][0]
                            video_id = video['id']['videoId']
                            
                            # Get detailed video info
                            video_url = f'https://www.googleapis.com/youtube/v3/videos'
                            video_params = {
                                'part': 'snippet,statistics,liveStreamingDetails',
                                'id': video_id,
                                'key': self.api_key
                            }
                            
                            async with session.get(video_url, params=video_params) as response2:
                                if response2.status == 200:
                                    video_data = await response2.json()
                                    if video_data.get('items'):
                                        video_info = video_data['items'][0]
                                        # Get subscriber count
                                        subscriber_count = 0
                                        try:
                                            # Get channel statistics for subscriber count
                                            channel_url = 'https://www.googleapis.com/youtube/v3/channels'
                                            channel_params = {
                                                'part': 'statistics',
                                                'id': channel_id,
                                                'key': self.api_key
                                            }
                                            
                                            async with session.get(channel_url, params=channel_params) as stats_response:
                                                if stats_response.status == 200:
                                                    stats_data = await stats_response.json()
                                                    if stats_data.get('items'):
                                                        subscriber_count = int(stats_data['items'][0]['statistics'].get('subscriberCount', 0))
                                        except Exception as e:
                                            logger.error(f"Failed to get YouTube subscriber count for {username}: {e}")
                                        
                                        result = {
                                            'is_live': True,
                                            'viewer_count': int(video_info['liveStreamingDetails'].get('concurrentViewers', 0)),
                                            'game_name': 'YouTube Live',
                                            'title': video_info['snippet']['title'],
                                            'thumbnail_url': video_info['snippet']['thumbnails']['maxres']['url'] if 'maxres' in video_info['snippet']['thumbnails'] else video_info['snippet']['thumbnails']['high']['url'],
                                            'profile_image_url': profile_image,
                                            'platform_url': f'https://youtube.com/watch?v={video_id}',
                                            'method': 'api_full',
                                            'follower_count': subscriber_count
                                        }
                                        # Cache the result
                                        self.cache[cache_key] = {'data': result, 'timestamp': current_time}
                                        return result
                        
                        result = {'is_live': False, 'method': 'api_not_live'}
                        self.cache[cache_key] = {'data': result, 'timestamp': current_time}
                        return result
                    else:
                        result = {'is_live': False, 'method': 'api_live_check_failed'}
                        self.cache[cache_key] = {'data': result, 'timestamp': current_time}
                        return result
                        
        except Exception as e:
            logger.error(f"YouTube API error for {username}: {e}")
            # Return cached data if available
            if cache_key in self.cache:
                return self.cache[cache_key]['data']
            # Fallback to scraping result
            return {'is_live': False, 'method': 'api_exception', 'error': str(e)}

class TikTokLiveChecker:
    def __init__(self):
        self.clients = {}  # Store clients per username
        self.httpx_session = None  # HTTP/2 session for advanced WAF bypass
        self.session_cookies = {}  # Store session cookies per domain
        self.waf_backoff = {}  # Track WAF blocks per username {username: {'blocks': count, 'next_check': timestamp}}
    
    async def cleanup(self):
        """Cleanup HTTP sessions to prevent resource leaks"""
        if self.httpx_session:
            try:
                await self.httpx_session.aclose()
                self.httpx_session = None
                logger.info("TikTok: HTTP session cleaned up successfully")
            except Exception as e:
                logger.warning(f"TikTok: Session cleanup error: {e}")
        
    def _implement_waf_backoff(self, username: str):
        """Implement exponential backoff for WAF blocked users"""
        import time
        current_time = time.time()
        
        if username not in self.waf_backoff:
            # First block: 5 minute backoff
            self.waf_backoff[username] = {'blocks': 1, 'next_check': current_time + 300}
            logger.info(f"TikTok {username}: First WAF block - 5 minute backoff implemented")
        else:
            # Exponential backoff: 5, 15, 30, 60 minutes max
            blocks = self.waf_backoff[username]['blocks'] + 1
            if blocks == 2:
                backoff_seconds = 900  # 15 minutes
            elif blocks == 3:
                backoff_seconds = 1800  # 30 minutes
            else:
                backoff_seconds = 3600  # 60 minutes max
                
            self.waf_backoff[username] = {'blocks': blocks, 'next_check': current_time + backoff_seconds}
            logger.warning(f"TikTok {username}: WAF block #{blocks} - {backoff_seconds//60} minute backoff implemented")
        
    async def _init_session(self):
        """Initialize HTTP/2 session with advanced WAF bypass capabilities"""
        if self.httpx_session is None:
            import httpx
            self.httpx_session = httpx.AsyncClient(
                http2=True,
                timeout=30.0,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
                follow_redirects=True
            )
            
    async def _get_session_cookies(self) -> Dict[str, str]:
        """Bootstrap session cookies from TikTok homepage for WAF bypass"""
        if 'tiktok.com' in self.session_cookies:
            return self.session_cookies['tiktok.com']
            
        logger.info("TikTok: Bootstrapping session cookies from homepage...")
        
        try:
            await self._init_session()
            
            # Step 1: Visit homepage to get initial cookies
            homepage_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'en-US,en;q=0.9,de;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'Cache-Control': 'max-age=0'
            }
            
            response = await self.httpx_session.get('https://www.tiktok.com/', headers=homepage_headers, timeout=15.0)
            
            # Extract and store cookies with robust error handling
            cookies = {}
            try:
                for cookie in response.cookies:
                    if hasattr(cookie, 'name') and hasattr(cookie, 'value'):
                        cookies[cookie.name] = cookie.value
                    elif isinstance(cookie, dict):
                        # Handle dict-style cookies
                        cookies[cookie.get('name', '')] = cookie.get('value', '')
                    else:
                        logger.debug(f"TikTok: Skipping malformed cookie: {type(cookie)}")
                        
                logger.info(f"TikTok: Collected {len(cookies)} cookies from homepage")
                self.session_cookies['tiktok.com'] = cookies
                return cookies
                
            except Exception as cookie_error:
                logger.warning(f"TikTok: Cookie extraction failed: {cookie_error}")
                # Return empty dict but don't crash
                self.session_cookies['tiktok.com'] = {}
                return {}
            
        except Exception as e:
            logger.warning(f"TikTok: Failed to bootstrap cookies: {e}")
            return {}
    
    async def _advanced_tiktok_request(self, username: str) -> tuple[str, str, int]:
        """Make advanced HTTP/2 request with full WAF bypass"""
        cookies = await self._get_session_cookies()
        
        # Advanced headers with session context
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9,de;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Cache-Control': 'max-age=0',
            'Referer': 'https://www.tiktok.com/'
        }
        
        url = f'https://www.tiktok.com/@{username}/live'
        
        # Main request with cookies
        response = await self.httpx_session.get(url, headers=headers, cookies=cookies, timeout=15.0)
        html = response.text
        
        return html, str(response.url), len(html)
    
    async def _mobile_api_request(self, username: str) -> tuple[str, str, int]:
        """Advanced TikTok Webcast API with proper JSON endpoints and sec_user_id"""
        logger.info(f"TikTok {username}: Trying Webcast API endpoints...")
        
        try:
            # Step 1: Get user profile JSON to extract sec_user_id
            profile_headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': 'https://www.tiktok.com/',
                'Origin': 'https://www.tiktok.com',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin'
            }
            
            # Try multiple API endpoints for user data
            api_endpoints = [
                f'https://www.tiktok.com/api/user/detail/?uniqueId={username}',
                f'https://www.tiktok.com/node/share/user/@{username}',
                f'https://m.tiktok.com/api/user/detail/?uniqueId={username}'
            ]
            
            sec_user_id = None
            for endpoint in api_endpoints:
                try:
                    response = await self.httpx_session.get(endpoint, headers=profile_headers, timeout=10.0)
                    
                    if response.status_code == 200 and 'application/json' in response.headers.get('content-type', ''):
                        data = response.json()
                        
                        # Extract sec_user_id from various response structures
                        user_detail = None
                        if 'userInfo' in data:
                            user_detail = data['userInfo'].get('user', {})
                        elif 'user' in data:
                            user_detail = data['user']
                        elif 'userDetail' in data:
                            user_detail = data['userDetail']
                            
                        if user_detail and 'secUid' in user_detail:
                            sec_user_id = user_detail['secUid']
                            logger.info(f"TikTok {username}: Got sec_user_id: {sec_user_id[:20]}...")
                            
                            # Check for roomId in user detail
                            room_id = user_detail.get('roomId', '')
                            if room_id and room_id != '0' and room_id != '':
                                logger.info(f"TikTok {username}: ✅ LIVE detected via user API! Room: {room_id}")
                                return 'LIVE_DETECTED_API', str(response.url), len(response.text)
                            break
                            
                except Exception as api_error:
                    logger.debug(f"TikTok {username}: API endpoint {endpoint} failed: {api_error}")
                    continue
            
            # Step 2: If we have sec_user_id, try Webcast room/info endpoint  
            if sec_user_id:
                webcast_headers = profile_headers.copy()
                webcast_headers.update({
                    'Referer': f'https://www.tiktok.com/@{username}/live',
                    'X-Requested-With': 'XMLHttpRequest'
                })
                
                # Try Webcast endpoints for live status
                webcast_endpoints = [
                    f'https://webcast.tiktok.com/webcast/room/info/?aid=1988&room_id_str={sec_user_id}',
                    f'https://www.tiktok.com/api/live/detail/?roomId={sec_user_id}',
                    f'https://m.tiktok.com/api/live/detail/?roomId={sec_user_id}'
                ]
                
                for webcast_url in webcast_endpoints:
                    try:
                        response = await self.httpx_session.get(webcast_url, headers=webcast_headers, timeout=10.0)
                        
                        if response.status_code == 200 and response.text.strip().startswith('{'):
                            data = response.json()
                            
                            # Check various live status indicators
                            if 'data' in data and data['data']:
                                room_data = data['data']
                                status = room_data.get('status', 0)
                                live_room = room_data.get('liveRoom')
                                
                                if status == 2 or (live_room and live_room.get('liveRoomStats')):
                                    logger.info(f"TikTok {username}: ✅ LIVE detected via Webcast API!")
                                    return 'LIVE_DETECTED_WEBCAST', str(response.url), len(response.text)
                                elif status == 4 or status == 0:
                                    logger.info(f"TikTok {username}: Webcast API confirms OFFLINE")
                                    return 'OFFLINE_CONFIRMED_WEBCAST', str(response.url), len(response.text)
                                    
                    except Exception as webcast_error:
                        logger.debug(f"TikTok {username}: Webcast endpoint failed: {webcast_error}")
                        continue
            
            # Step 3: Final fallback to mobile scraping (but classify WAF properly)
            logger.info(f"TikTok {username}: Falling back to mobile web scraping...")
            mobile_url = f'https://m.tiktok.com/@{username}/live'
            
            mobile_web_headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1'
            }
            
            response = await self.httpx_session.get(mobile_url, headers=mobile_web_headers, timeout=10.0)
            html = response.text
            
            # Detect WAF/blocks and return appropriate status
            if len(html) < 5000 and any(block_term in html.lower() for block_term in ['404 not found', 'guru meditation', 'slardar', 'blocked']):
                logger.warning(f"TikTok {username}: Mobile endpoint also blocked - returning UNKNOWN status")
                return 'BLOCKED_UNKNOWN', str(response.url), len(html)
                
            return html, str(response.url), len(html)
            
        except Exception as e:
            logger.error(f"TikTok {username}: All mobile APIs failed: {e}")
            return 'API_ERROR', '', 0
    
    async def _get_tiktok_profile_data(self, username: str) -> Optional[Dict]:
        """Get TikTok profile data including profile image and follower count - works for offline users too"""
        try:
            import aiohttp
            import re
            
            # Try both regular profile page and live page for better data extraction
            urls_to_try = [
                f'https://www.tiktok.com/@{username}',  # Regular profile page
                f'https://www.tiktok.com/@{username}/live'  # Live page (if available)
            ]
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,de;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'no-cache'
            }
            
            timeout = aiohttp.ClientTimeout(total=15)
            
            if not hasattr(self, 'session') or not self.session:
                self.session = aiohttp.ClientSession(timeout=timeout)
            
            for url in urls_to_try:
                try:
                    async with self.session.get(url, headers=headers, timeout=timeout) as response:
                        if response.status == 200:
                            html = await response.text()
                            
                            # Extract profile image with improved patterns
                            profile_image_url = ''
                            avatar_patterns = [
                                r'"avatarLarger":"([^"]+)"',
                                r'"avatarMedium":"([^"]+)"', 
                                r'"avatarThumb":"([^"]+)"',
                                r'"avatar_300x300":\{"uri":"([^"]+)"',
                                r'"avatar_168x168":\{"uri":"([^"]+)"',
                                r'"avatar_larger":\{"uri":"([^"]+)"',
                                r'"avatar_medium":\{"uri":"([^"]+)"',
                                r'avatarLarger.*?"([^"]*\\.jpg[^"]*)"',
                                r'avatarMedium.*?"([^"]*\\.jpg[^"]*)"',
                                r'profile_pic_url_hd":"([^"]+)"'
                            ]
                            
                            for pattern in avatar_patterns:
                                matches = re.findall(pattern, html)
                                if matches:
                                    profile_image_url = matches[0]
                                    # Clean up URL format
                                    if profile_image_url.startswith('//'):
                                        profile_image_url = f"https:{profile_image_url}"
                                    elif not profile_image_url.startswith('http'):
                                        profile_image_url = f"https:{profile_image_url}"
                                    
                                    # Validate URL format
                                    if '.jpg' in profile_image_url or '.png' in profile_image_url or '.webp' in profile_image_url:
                                        break
                            
                            # Extract follower count with improved patterns
                            follower_count = 0
                            follower_patterns = [
                                r'"followerCount":(\d+)',
                                r'"followingCount":(\d+)',
                                r'data-e2e="followers-count">([^<]+)',
                                r'"stats":\{"followerCount":(\d+)',
                                r'"userInfo":\{[^}]*"stats":\{[^}]*"followerCount":(\d+)',
                                r'followersCount.*?(\d+)',
                                r'"follower_count":(\d+)'
                            ]
                            
                            for pattern in follower_patterns:
                                matches = re.findall(pattern, html)
                                if matches:
                                    try:
                                        # Get first numeric value
                                        follower_str = re.sub(r'[^\d]', '', str(matches[0]))
                                        if follower_str:
                                            follower_count = int(follower_str)
                                            break
                                    except (ValueError, IndexError):
                                        continue
                            
                            if profile_image_url or follower_count > 0:
                                logger.info(f"TikTok {username}: Profile data extracted from {url} - Image: {'Yes' if profile_image_url else 'No'}, Followers: {follower_count}")
                                return {
                                    'profile_image_url': profile_image_url,
                                    'follower_count': follower_count
                                }
                
                except Exception as url_error:
                    logger.warning(f"TikTok {username}: Failed to fetch {url}: {url_error}")
                    continue
            
            # If all URLs failed, return None
            logger.warning(f"TikTok {username}: All profile extraction methods failed")
            return None
            
        except Exception as e:
            logger.error(f"TikTok {username}: Profile data extraction error: {e}")
            return None

    async def _extract_sigi_state(self, html: str, username: str) -> Optional[Dict]:
        """Extract and parse SIGI_STATE JSON for robust live detection"""
        import re
        import json
        
        # Look for SIGI_STATE script
        sigi_patterns = [
            r'window\.__SIGI_STATE__\s*=\s*({.*?});',
            r'window\.__SIGI_STATE__=({.*?});',
            r'__SIGI_STATE__\s*=\s*({.*?})',
        ]
        
        for pattern in sigi_patterns:
            matches = re.findall(pattern, html, re.DOTALL)
            if matches:
                try:
                    sigi_data = json.loads(matches[0])
                    logger.info(f"TikTok {username}: SIGI_STATE extracted successfully")
                    
                    # Navigate SIGI structure for live room data
                    user_detail = sigi_data.get('UserDetail', {})
                    live_room = sigi_data.get('LiveRoom', {})
                    user_page = sigi_data.get('UserPage', {})
                    
                    # Check multiple paths for live status - but be more specific about broadcaster vs viewer
                    live_indicators = []
                    
                    # Check if this specific user is the broadcaster (not just viewing someone else's stream)
                    target_user_found = False
                    
                    if user_detail:
                        for user_id, user_data in user_detail.items():
                            if isinstance(user_data, dict):
                                # Check if this is the target user's data
                                user_unique_id = user_data.get('uniqueId', '').lower()
                                if user_unique_id == username.lower():
                                    target_user_found = True
                                    live_status = user_data.get('liveStatus', 0)
                                    if live_status == 1:
                                        live_indicators.append(f"UserDetail_{user_id}_liveStatus_1_BROADCASTER")
                    
                    # Only check LiveRoom if we confirmed this is the target user
                    if target_user_found and live_room:
                        for room_id, room_data in live_room.items():
                            if isinstance(room_data, dict):
                                status = room_data.get('status', 0)
                                owner_id = room_data.get('owner', {}).get('id', '')
                                if status == 2 and owner_id:  # Live status with owner verification
                                    live_indicators.append(f"LiveRoom_{room_id}_status_2_OWNER")
                    
                    # Additional check: UserPage for current user's live status
                    if user_page:
                        for page_id, page_data in user_page.items():
                            if isinstance(page_data, dict):
                                page_unique_id = page_data.get('uniqueId', '').lower()
                                if page_unique_id == username.lower():
                                    live_status = page_data.get('liveStatus', 0)
                                    if live_status == 1:
                                        live_indicators.append(f"UserPage_{page_id}_liveStatus_1_CONFIRMED")
                    
                    logger.info(f"TikTok {username}: SIGI_STATE live indicators: {live_indicators}")
                    
                    if live_indicators:
                        return {'is_live': True, 'method': 'sigi_state', 'indicators': live_indicators}
                    
                except Exception as parse_error:
                    logger.warning(f"TikTok {username}: SIGI_STATE parse error: {parse_error}")
        
        return None

    async def get_stream_info(self, username: str) -> Optional[Dict]:
        """Get stream information for a TikTok user with advanced WAF bypass"""
        try:
            # Initialize session if needed
            await self._init_session()
            
            # Try TikTokLive library first, but fallback to advanced detection if it fails
            try:
                logger.info(f"TikTok {username}: Attempting TikTokLive library import...")
                from TikTokLive.client.client import TikTokLiveClient
                # Define UserOfflineError locally to avoid LSP issues
                class UserOfflineError(Exception):
                    pass
                # Try to import the real one, but use fallback if it fails
                try:
                    from TikTokLive.client.errors import UserOfflineError as TikTokUserOfflineError
                    UserOfflineError = TikTokUserOfflineError
                except ImportError:
                    pass  # Use the fallback defined above
                logger.info(f"TikTok {username}: TikTokLive library imported successfully!")
                
                # Create client and try quick connection
                client = TikTokLiveClient(unique_id=username)
                logger.info(f"TikTok {username}: TikTokLive client created, attempting connection...")
                
                async def quick_connect_test():
                    await client.start()
                    # Check if this user is actually the broadcaster (not just a viewer)
                    room_info = getattr(client, 'room_info', None)
                    if room_info:
                        # If we can get room_info, the user is likely live as broadcaster
                        return True
                    else:
                        # If no room_info, this might just be a viewer connection
                        return False
                
                import asyncio
                result = await asyncio.wait_for(quick_connect_test(), timeout=5.0)
                
                if not result:
                    logger.info(f"TikTok {username}: TikTokLive library confirmed - user offline")
                    raise UserOfflineError("User is not broadcasting")
                
                logger.info(f"TikTok {username}: TikTokLive library confirmed - USER IS LIVE!")
                
                try:
                    # Wrap disconnect in timeout to prevent hanging
                    await asyncio.wait_for(client.disconnect(), timeout=3.0)
                except asyncio.TimeoutError:
                    logger.warning(f"TikTok {username}: Client disconnect timed out")
                except:
                    pass
                
                # Get profile image and follower count via enhanced scraping
                profile_image_url = ''
                follower_count = 0
                
                try:
                    profile_data = await self._get_tiktok_profile_data(username)
                    if profile_data:
                        profile_image_url = profile_data.get('profile_image_url', '')
                        follower_count = profile_data.get('follower_count', 0)
                        logger.info(f"TikTok {username}: Enhanced data - Profile: {'Yes' if profile_image_url else 'No'}, Followers: {follower_count}")
                    else:
                        logger.warning(f"TikTok {username}: Failed to get profile data")
                
                except Exception as profile_error:
                    logger.warning(f"TikTok {username}: Failed to get profile data: {profile_error}")
                
                return {
                    'is_live': True,
                    'viewer_count': 0,
                    'game_name': 'TikTok Live',
                    'title': f'{username} Live Stream',
                    'thumbnail_url': profile_image_url,  # Use profile image as thumbnail
                    'profile_image_url': profile_image_url,
                    'platform_url': f'https://www.tiktok.com/@{username}/live',
                    'follower_count': follower_count
                }
                
            except UserOfflineError:
                logger.info(f"TikTok {username}: TikTokLive library confirmed - user offline")
            except Exception as offline_error:
                if "UserOfflineError" in str(offline_error):
                    logger.info(f"TikTok {username}: TikTokLive library confirmed - user offline")
                else:
                    logger.error(f"TikTok {username}: TikTokLive library error: {offline_error}")
                    raise Exception("TikTokLive failed")
                return {'is_live': False}
            except Exception as e:
                # TikTokLive failed, fall back to URL-based detection
                logger.error(f"TikTok {username}: TikTokLive library failed: {e}")
                raise Exception("TikTokLive failed")
        
        except Exception:
            # Advanced WAF bypass fallback with HTTP/2 and session management
            logger.info(f"TikTok {username}: Starting advanced WAF bypass detection...")
            
            try:
                # Method 1: Advanced HTTP/2 request with session cookies
                html, final_url, html_size = await self._advanced_tiktok_request(username)
                
                logger.info(f"TikTok {username}: Advanced request - URL: {'/live' in final_url}, Size: {html_size} chars")
                
                # Check for SlardarWAF block or 404 errors  
                is_blocked = (html_size < 5000 and any(block_indicator in html.lower() for block_indicator in ['slardar', 'guru meditation', '404 not found', 'tlb']))
                
                if is_blocked:
                    logger.warning(f"TikTok {username}: WAF/Block detected (size: {html_size}), trying mobile API...")
                    # Method 2: Advanced mobile API
                    html, final_url, html_size = await self._mobile_api_request(username)
                    logger.info(f"TikTok {username}: Mobile API result - Size: {html_size} chars")
                    
                    # Handle API responses with proper classification
                    if html in ['LIVE_DETECTED_API', 'LIVE_DETECTED_WEBCAST']:
                        method = 'webcast_api' if 'WEBCAST' in html else 'user_api'
                        return {
                            'is_live': True,
                            'viewer_count': 0,
                            'game_name': 'TikTok Live',
                            'title': f'{username} Live Stream',
                            'thumbnail_url': '',
                            'profile_image_url': '',
                            'platform_url': f'https://www.tiktok.com/@{username}/live',
                            'follower_count': 0,
                            'method': method
                        }
                    elif html in ['OFFLINE_CONFIRMED_API', 'OFFLINE_CONFIRMED_WEBCAST']:
                        method = 'webcast_api' if 'WEBCAST' in html else 'user_api'
                        return {'is_live': False, 'method': method}
                    elif html == 'BLOCKED_UNKNOWN':
                        logger.warning(f"TikTok {username}: All endpoints blocked - status UNKNOWN")
                        return {'is_live': False, 'method': 'blocked_unknown', 'blocked': True}
                    elif html == 'API_ERROR':
                        logger.error(f"TikTok {username}: All API endpoints failed")
                        return {'is_live': False, 'method': 'api_error'}
                    # Continue with HTML analysis if API inconclusive
                
                # Method 3: SIGI_STATE parsing (most reliable)
                sigi_result = await self._extract_sigi_state(html, username)
                if sigi_result:
                    logger.info(f"TikTok {username}: ✅ LIVE detected via SIGI_STATE!")
                    return {
                        'is_live': True,
                        'viewer_count': 0,
                        'game_name': 'TikTok Live',
                        'title': f'{username} Live Stream',
                        'thumbnail_url': '',
                        'profile_image_url': '',
                        'platform_url': f'https://www.tiktok.com/@{username}/live',
                        'follower_count': 0,
                        'method': 'advanced_sigi_state'
                    }
                
                # Method 4: Enhanced pattern matching
                live_indicators = [
                    '"live_status":1',
                    'isLiving":true', 
                    '"liveRoomId":"',
                    '"roomStatus":2',
                    'data-e2e="live-avatar"',
                    'live-indicator',
                    '"status":"live"',
                    'is LIVE - TikTok LIVE'  # Title indicator
                ]
                
                indicator_count = sum(1 for indicator in live_indicators if indicator in html)
                url_has_live = '/live' in final_url
                live_mentions = html.lower().count('live')
                
                # Debug info
                found_indicators = [indicator for indicator in live_indicators if indicator in html]
                logger.info(f"TikTok {username}: Enhanced detection - URL: {url_has_live}, Indicators: {indicator_count}/8, Live mentions: {live_mentions}")
                
                # Enhanced detection logic
                is_likely_live = False
                detection_score = 0
                
                # Scoring system
                if indicator_count >= 2:
                    detection_score += 3
                elif indicator_count >= 1:
                    detection_score += 1
                    
                if live_mentions > 1000:  # Many live mentions suggests full page (higher threshold)
                    detection_score += 2
                elif live_mentions > 500:
                    detection_score += 1
                    
                if url_has_live:
                    detection_score += 1
                    
                if html_size > 50000:  # Large page suggests not blocked
                    detection_score += 1
                
                is_likely_live = detection_score >= 6  # Raised threshold to reduce false positives
                
                logger.info(f"TikTok {username}: Detection score: {detection_score}/8, Live: {is_likely_live}")
                
                if is_likely_live:
                    logger.info(f"TikTok {username}: ✅ LIVE detected via enhanced patterns!")
                    return {
                        'is_live': True,
                        'viewer_count': 0,
                        'game_name': 'TikTok Live',
                        'title': f'{username} Live Stream',
                        'thumbnail_url': '',
                        'profile_image_url': '',
                        'platform_url': f'https://www.tiktok.com/@{username}/live',
                        'follower_count': 0,
                        'method': 'advanced_patterns'
                    }
                
                # Log sample for debugging
                html_sample = html[:500] if len(html) > 500 else html
                logger.info(f"TikTok {username}: HTML sample: {html_sample[:200]}...")
                logger.info(f"TikTok {username}: Page size: {html_size} characters")
                
                # Return offline if no live detection
                return {'is_live': False, 'method': 'advanced_bypass_offline'}
                
            except Exception as e:
                logger.error(f"TikTok {username}: Advanced WAF bypass failed: {e}")
                return {'is_live': False, 'method': 'advanced_bypass_error'}
        
        except Exception as e:
            logger.error(f"TikTok {username}: Complete detection failed: {e}")
            return {'is_live': False, 'method': 'complete_error'}

# Initialize platform APIs
twitch_api = TwitchAPI()
youtube_api = YouTubeAPI()
tiktok_live_checker = TikTokLiveChecker()

# Username Validation Functions
async def validate_username(platform: str, username: str) -> bool:
    """Validate if username exists on specified platform"""
    if not username or not username.strip():
        return True  # Empty usernames are allowed (optional fields)
    
    username = username.strip()
    
    try:
        if platform == 'twitch':
            return await validate_twitch_username(username)
        elif platform == 'youtube':
            return await validate_youtube_username(username)
        elif platform == 'tiktok':
            return await validate_tiktok_username(username)
        else:
            return False
    except Exception as e:
        logger.error(f"Username validation error for {platform}/{username}: {e}")
        return False

async def validate_twitch_username(username: str) -> bool:
    """Check if Twitch username exists"""
    token = await twitch_api.get_access_token()
    if not token:
        return False
    
    headers = {
        'Client-ID': twitch_api.client_id,
        'Authorization': f'Bearer {token}'
    }
    
    user_url = f'https://api.twitch.tv/helix/users?login={username}'
    async with aiohttp.ClientSession() as session:
        async with session.get(user_url, headers=headers) as response:
            if response.status == 200:
                user_data = await response.json()
                return bool(user_data['data'])  # True if user exists
    return False

async def validate_youtube_username(username: str) -> bool:
    """Check if YouTube username/channel exists"""
    # Try both channel ID and custom URL formats
    base_url = 'https://www.googleapis.com/youtube/v3/channels'
    api_key = youtube_api.api_key
    
    # First try as channel handle (@username)
    if username.startswith('@'):
        params = {
            'part': 'id',
            'forHandle': username,
            'key': api_key
        }
    else:
        # Try as custom URL
        params = {
            'part': 'id', 
            'forUsername': username,
            'key': api_key
        }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(base_url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('items'):
                    return True
    
    # If not found with API, try alternate approach (search by name)
    search_url = 'https://www.googleapis.com/youtube/v3/search'
    search_params = {
        'part': 'snippet',
        'q': username,
        'type': 'channel',
        'maxResults': 5,
        'key': api_key
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(search_url, params=search_params) as response:
            if response.status == 200:
                data = await response.json()
                # Check if any result matches exactly
                for item in data.get('items', []):
                    channel_title = item['snippet']['title'].lower()
                    if username.lower() in channel_title or channel_title in username.lower():
                        return True
    
    return False

async def validate_tiktok_username(username: str) -> bool:
    """Check if TikTok username exists"""
    url = f'https://www.tiktok.com/@{username}'
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=timeout) as response:
                if response.status == 200:
                    html = await response.text()
                    # Check for common patterns that indicate profile exists
                    profile_indicators = [
                        '"uniqueId":"',
                        '"nickname":"',
                        f'"uniqueId":"{username}"',
                        'tt-avatar',
                        'profile-header'
                    ]
                    
                    indicator_count = sum(1 for indicator in profile_indicators if indicator in html)
                    return indicator_count >= 2  # Profile exists if multiple indicators found
                elif response.status == 404:
                    return False  # Profile definitely doesn't exist
    except Exception as e:
        logger.error(f"TikTok validation error for {username}: {e}")
    
    return False  # Default to False if validation fails

# Live Checking Task
@tasks.loop(minutes=1)
async def live_checker():
    """Check for live streams based on streamer type intervals"""
    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get current time in minutes since epoch for timing calculations
        current_minute = int(time.time() // 60)
        
        logger.info(f"Live checker running - minute {current_minute}")
        
        # Get all creators
        cursor.execute('SELECT id, discord_user_id, discord_username, streamer_type, notification_channel_id, twitch_username, youtube_username, tiktok_username FROM creators')
        creators = cursor.fetchall()
        
        logger.info(f"Checking {len(creators)} creators")
        
        for creator in creators:
            creator_id, discord_user_id, username, streamer_type, channel_id, twitch_user, youtube_user, tiktok_user = creator
            
            # Check interval based on streamer type
            should_check = False
            if streamer_type == 'karma':
                should_check = True  # Check every minute
            elif streamer_type == 'regular':
                should_check = (current_minute % 3 == 0)  # Check every 3 minutes
            
            if should_check:
                logger.info(f"Checking creator {username} ({streamer_type})")
                await check_creator_platforms(creator_id, discord_user_id, username, streamer_type, channel_id, twitch_user, youtube_user, tiktok_user)
            else:
                logger.debug(f"Skipping {username} ({streamer_type}) - not time to check")
    
    except Exception as e:
        logger.error(f"Error in live_checker: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

async def check_creator_platforms(creator_id, discord_user_id, username, streamer_type, channel_id, twitch_user, youtube_user, tiktok_user):
    """Check all platforms for a specific creator"""
    platforms_to_check = []
    
    if twitch_user:
        platforms_to_check.append(('twitch', twitch_user))
    if youtube_user:
        platforms_to_check.append(('youtube', youtube_user))
    if tiktok_user:
        platforms_to_check.append(('tiktok', tiktok_user))
    
    for platform, platform_username in platforms_to_check:
        try:
            # Get stream info based on platform
            stream_info = None
            if platform == 'twitch':
                stream_info = await twitch_api.get_stream_info(platform_username)
            elif platform == 'youtube':
                stream_info = await youtube_api.get_stream_info(platform_username)
            elif platform == 'tiktok':
                stream_info = await tiktok_live_checker.get_stream_info(platform_username)
            
            if stream_info:
                await handle_stream_status(creator_id, discord_user_id, username, streamer_type, channel_id, platform, platform_username, stream_info)
        
        except Exception as e:
            logger.error(f"Error checking {platform} for {username}: {e}")

async def handle_stream_status(creator_id, discord_user_id, username, streamer_type, channel_id, platform, platform_username, stream_info):
    """Handle stream status and send notifications if needed"""
    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        is_live = stream_info.get('is_live', False)
        today = datetime.now().date()
        
        logger.info(f"Handling stream status for {username} on {platform}: is_live={is_live}")
        
        # Get current live status from database
        cursor.execute(
            'SELECT is_live, last_notification_date FROM live_status WHERE creator_id = ? AND platform = ?',
            (creator_id, platform)
        )
        current_status = cursor.fetchone()
        
        if is_live:
            # Update or insert live status
            if current_status:
                was_live, last_notif_date = current_status
                last_notif_date = datetime.strptime(last_notif_date, '%Y-%m-%d').date() if last_notif_date else None
                
                # Send notification if not live before OR if it's a new day (stream restart)
                should_notify = not was_live or last_notif_date != today
                logger.info(f"Creator {username} on {platform}: was_live={was_live}, last_notif={last_notif_date}, today={today}, should_notify={should_notify}")
            else:
                should_notify = True
                logger.info(f"Creator {username} on {platform}: first time live, should_notify={should_notify}")
            
            if should_notify:
                # Update live status FIRST to prevent repeated notifications
                cursor.execute('''
                    INSERT OR REPLACE INTO live_status 
                    (creator_id, platform, is_live, last_notification_date, stream_start_time)
                    VALUES (?, ?, TRUE, ?, ?)
                ''', (creator_id, platform, today.isoformat(), datetime.now().isoformat()))
                
                conn.commit()  # Commit immediately to prevent repeated notifications
                logger.info(f"Updated live status for {username} on {platform}")
                
                # Send live notification AFTER status is saved (CRASH-RESISTANT)
                try:
                    # Wrap notification sending in timeout to prevent hanging (ChatGPT fix)
                    await asyncio.wait_for(
                        send_live_notification(creator_id, discord_user_id, username, streamer_type, platform, platform_username, stream_info),
                        timeout=30.0
                    )
                except asyncio.TimeoutError:
                    logger.error(f"🚨 CRITICAL: Live notification TIMED OUT for {username} on {platform} after 30s")
                except Exception as notification_error:
                    logger.error(f"🚨 CRITICAL: Live notification failed for {username} on {platform}: {notification_error}")
                    # Continue processing - don't let notification failures stop the live checker
                
                # Update daily streak for Karma streamers (CRASH-RESISTANT)
                if streamer_type == 'karma':
                    try:
                        await update_daily_streak(creator_id, True)
                    except Exception as streak_error:
                        logger.error(f"🚨 CRITICAL: Daily streak update failed for {username}: {streak_error}")
                
                # Assign live role (CRASH-RESISTANT)
                try:
                    # Find guild from all available guilds
                    member = None
                    guild = None
                    for g in bot.guilds:
                        try:
                            member = g.get_member(int(discord_user_id))
                            if member:
                                guild = g
                                break
                        except (ValueError, AttributeError) as guild_error:
                            logger.warning(f"Error accessing guild {g.name}: {guild_error}")
                            continue
                    
                    if guild and member:
                        try:
                            live_role = guild.get_role(Config.LIVE_ROLE)
                            if live_role and live_role not in member.roles:
                                # Add role with timeout (ChatGPT fix)
                                await asyncio.wait_for(member.add_roles(live_role), timeout=10.0)
                                logger.info(f"✅ Added live role to {username}")
                            else:
                                logger.debug(f"Live role already assigned or not found for {username}")
                        except discord.Forbidden:
                            logger.error(f"🚨 CRITICAL: Missing permissions to assign live role to {username}")
                        except discord.HTTPException as discord_error:
                            logger.error(f"🚨 CRITICAL: Discord API error assigning role to {username}: {discord_error}")
                    else:
                        logger.warning(f"Could not find guild member for {username} (Discord ID: {discord_user_id})")
                except Exception as role_error:
                    logger.error(f"🚨 CRITICAL: Live role assignment completely failed for {username}: {role_error}")
                    # Continue processing - don't let role failures stop the live checker
        else:
            # Update live status to offline
            if current_status and current_status[0]:  # Was live before
                # Get message_id and notification_channel_id for deletion
                cursor.execute(
                    'SELECT message_id, notification_channel_id FROM live_status WHERE creator_id = ? AND platform = ?',
                    (creator_id, platform)
                )
                message_data = cursor.fetchone()
                
                # Delete live notification message if it exists
                message_deleted = False
                if message_data and message_data[0] and message_data[1]:
                    message_id, notification_channel_id = message_data
                    try:
                        # Get the channel and delete the message
                        notification_channel = bot.get_channel(int(notification_channel_id))
                        if not notification_channel:
                            # Try to fetch channel as fallback for cache misses
                            try:
                                notification_channel = await asyncio.wait_for(bot.fetch_channel(int(notification_channel_id)), timeout=10.0)
                            except Exception:
                                logger.warning(f"Could not fetch notification channel {notification_channel_id} for {username} on {platform}")
                        
                        if notification_channel:
                            try:
                                message_to_delete = await asyncio.wait_for(
                                    notification_channel.fetch_message(int(message_id)), 
                                    timeout=10.0
                                )
                                await asyncio.wait_for(message_to_delete.delete(), timeout=10.0)
                                logger.info(f"🗑️ Deleted live notification for {username} on {platform} (Message ID: {message_id})")
                                message_deleted = True
                            except discord.NotFound:
                                logger.info(f"Live notification message for {username} on {platform} was already deleted")
                                message_deleted = True  # Message doesn't exist, so consider it "deleted"
                            except asyncio.TimeoutError:
                                logger.warning(f"Timeout while deleting live notification for {username} on {platform} - will retry later")
                            except Exception as delete_error:
                                logger.error(f"Failed to delete live notification for {username} on {platform}: {delete_error} - will retry later")
                        else:
                            logger.warning(f"Notification channel {notification_channel_id} not found for {username} on {platform} - will retry later")
                    except Exception as e:
                        logger.error(f"Error during message deletion for {username} on {platform}: {e} - will retry later")
                
                # Update database: set offline and clear message IDs only if deletion succeeded or message not found
                if message_deleted:
                    cursor.execute(
                        'UPDATE live_status SET is_live = FALSE, message_id = NULL, notification_channel_id = NULL WHERE creator_id = ? AND platform = ?',
                        (creator_id, platform)
                    )
                else:
                    # Only set offline but keep message IDs for retry
                    cursor.execute(
                        'UPDATE live_status SET is_live = FALSE WHERE creator_id = ? AND platform = ?',
                        (creator_id, platform)
                    )
                
                logger.info(f"Updated {username} on {platform} to offline")
                
                # Check if offline on all platforms to remove live role
                cursor.execute(
                    'SELECT COUNT(*) FROM live_status WHERE creator_id = ? AND is_live = TRUE',
                    (creator_id,)
                )
                
                if cursor.fetchone()[0] == 0:  # Not live on any platform
                    # Remove live role
                    try:
                        member = None
                        guild = None
                        for g in bot.guilds:
                            member = g.get_member(int(discord_user_id))
                            if member:
                                guild = g
                                break
                        
                        if guild and member:
                            live_role = guild.get_role(Config.LIVE_ROLE)
                            if live_role and live_role in member.roles:
                                await member.remove_roles(live_role)
                                logger.info(f"Removed live role from {username}")
                    except Exception as e:
                        logger.error(f"Error removing live role from {username}: {e}")
        
        conn.commit()
    
    except Exception as e:
        logger.error(f"Error handling stream status for {username} on {platform}: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

async def send_live_notification(creator_id, discord_user_id, username, streamer_type, platform, platform_username, stream_info):
    """Send live notification to platform-specific channel and subscribers"""
    try:
        # Get platform-specific notification channel
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT channel_id FROM creator_channels 
            WHERE creator_id = ? AND platform = ?
        ''', (creator_id, platform))
        
        channel_result = cursor.fetchone()
        
        if channel_result:
            channel_id = channel_result[0]
        else:
            # Fallback to legacy notification_channel_id
            cursor.execute('SELECT notification_channel_id FROM creators WHERE id = ?', (creator_id,))
            fallback_result = cursor.fetchone()
            if fallback_result:
                channel_id = fallback_result[0]
                logger.warning(f"Using fallback channel for {username} on {platform}")
            else:
                logger.error(f"No notification channel found for {username} on {platform}")
                conn.close()
                return
        
        conn.close()
        
        # Get notification channel with timeout (ChatGPT fix)
        channel = bot.get_channel(int(channel_id))
        if not channel:
            # Try to fetch channel as fallback with timeout
            try:
                channel = await asyncio.wait_for(bot.fetch_channel(int(channel_id)), timeout=10.0)
            except asyncio.TimeoutError:
                logger.error(f"Channel fetch timed out for {channel_id} - {username} on {platform}")
                return
            except:
                logger.error(f"Channel {channel_id} not found for {username} on {platform}")
                return
        
        # Create embed based on streamer type and platform
        embed = await create_live_embed(creator_id, discord_user_id, username, streamer_type, platform, platform_username, stream_info)
        
        # Search for game on Instant Gaming if game_name is available
        instant_gaming_data = None
        game_name = stream_info.get('game_name')
        if game_name and game_name.strip() and platform in ['twitch', 'youtube']:  # Only for Twitch and YouTube
            try:
                instant_gaming_data = await instant_gaming.search_game(game_name)
                if instant_gaming_data:
                    logger.info(f"🎮 Found Instant Gaming link for '{game_name}' - {username} on {platform}")
                else:
                    logger.info(f"🎮 No Instant Gaming results for '{game_name}' - {username} on {platform}")
            except Exception as e:
                logger.error(f"Error searching Instant Gaming for '{game_name}': {e}")
        
        # Send to notification channel with timeout (ChatGPT fix)
        sent_message = None
        if isinstance(channel, (discord.TextChannel, discord.Thread, discord.DMChannel)):
            try:
                sent_message = await asyncio.wait_for(
                    channel.send(embed=embed, view=LiveNotificationView(platform, platform_username, instant_gaming_data)),
                    timeout=15.0
                )
            except asyncio.TimeoutError:
                logger.error(f"Channel send timed out for {username} on {platform}")
                return None
        else:
            logger.error(f"Channel {channel_id} is not a text channel for {username} on {platform}")
            return None
        
        # Store message_id and channel_id in database for later deletion
        if sent_message:
            try:
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE live_status 
                    SET message_id = ?, notification_channel_id = ? 
                    WHERE creator_id = ? AND platform = ?
                ''', (str(sent_message.id), str(channel_id), creator_id, platform))
                conn.commit()
                conn.close()
                logger.info(f"💾 Saved message ID {sent_message.id} for {username} on {platform}")
            except Exception as e:
                logger.error(f"Failed to save message ID for {username} on {platform}: {e}")
                if conn:
                    conn.close()
        
        # Send private notifications to subscribers
        await send_private_notifications(creator_id, username, platform, platform_username, stream_info)
        
        # Log success with safe channel name access
        channel_name = getattr(channel, 'name', f"Channel-{channel_id}")
        logger.info(f"Sent live notification for {username} on {platform} to channel {channel_name}")
    
    except Exception as e:
        logger.error(f"Error sending live notification: {e}")

async def create_live_embed(creator_id, discord_user_id, username, streamer_type, platform, platform_username, stream_info):
    """Create live notification embed based on streamer type"""
    # Initialize description with default value
    description = f"👾 {username} ist LIVE! Schaut vorbei! 🎮"
    
    # Check for custom message first
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT custom_message FROM creators WHERE id = ?', (creator_id,))
        custom_result = cursor.fetchone()
        
        if custom_result and custom_result[0]:
            # Use custom message if available
            description = custom_result[0]
            logger.info(f"Using custom message for {username} on {platform}")
        else:
            # Use standard notification text based on streamer type and platform
            if streamer_type == 'karma':
                if platform == 'twitch':
                    description = f"🚨 Hey Twitch-Runner! 🚨\n{username} ist jetzt LIVE auf Twitch: {platform_username}!\nTaucht ein in die Twitch-Welten, seid aktiv im Chat und verteilt ein bisschen Liebe im Stream! 💜💻"
                elif platform == 'youtube':
                    description = f"⚡ Attention, Net-Runners! ⚡\n{username} streamt jetzt LIVE auf YouTube: {platform_username}!\nCheckt die Action, seid Teil des Chats und boostet die Community! 🔴🤖"
                elif platform == 'tiktok':
                    description = f"💥 Heads up, TikToker! 💥\n{username} ist jetzt LIVE auf TikTok: {platform_username}!\nScrollt nicht vorbei, droppt ein Like und lasst den Stream glühen! 🔵✨"
            else:  # regular streamer
                if platform == 'twitch':
                    description = f"👾 {username} ist LIVE auf Twitch: {platform_username}!\nKommt vorbei und schaut kurz rein! 💜"
                elif platform == 'youtube':
                    description = f"👾 {username} streamt jetzt LIVE auf YouTube: {platform_username}!\nVorbeischauen lohnt sich! 🔴"
                elif platform == 'tiktok':
                    description = f"👾 {username} ist LIVE auf TikTok: {platform_username}!\nLasst ein Like da! 🔵"
    finally:
        conn.close()
    
    embed = discord.Embed(
        description=description,
        color=Config.COLORS[platform]
    )
    
    # Add viewer count and game
    if stream_info.get('viewer_count'):
        embed.add_field(name="👀 Zuschauer", value=f"{stream_info['viewer_count']:,}", inline=True)
    
    if stream_info.get('game_name'):
        embed.add_field(name="🎮 Spiel", value=stream_info['game_name'], inline=True)
    
    # Add follower/subscriber count for all platforms
    if stream_info.get('follower_count'):
        if platform == 'youtube':
            embed.add_field(name="📺 Abonnenten", value=f"{stream_info['follower_count']:,}", inline=True)
        else:  # twitch, tiktok
            embed.add_field(name="💖 Follower", value=f"{stream_info['follower_count']:,}", inline=True)
    
    # Add daily streak for Karma streamers
    if streamer_type == 'karma':
        streak = await get_daily_streak(creator_id)
        embed.add_field(name="🔥 Daily Streak", value=f"{streak} Tage", inline=True)
    
    # Add thumbnail/preview if available
    if stream_info.get('thumbnail_url'):
        embed.set_image(url=stream_info['thumbnail_url'])
    
    # Add profile image for Karma streamers
    if streamer_type == 'karma' and stream_info.get('profile_image_url'):
        embed.set_thumbnail(url=stream_info['profile_image_url'])
    
    embed.timestamp = datetime.utcnow()
    
    return embed

class LiveNotificationView(discord.ui.View):
    def __init__(self, platform: str, username: str, instant_gaming_data: Optional[Dict] = None):
        super().__init__(timeout=None)
        self.platform = platform
        self.username = username
        self.instant_gaming_data = instant_gaming_data
        
        # Platform URLs
        if platform == 'twitch':
            profile_url = f"https://twitch.tv/{username}"
            live_url = f"https://twitch.tv/{username}"
        elif platform == 'youtube':
            profile_url = f"https://youtube.com/@{username}"
            live_url = f"https://youtube.com/@{username}/live"
        elif platform == 'tiktok':
            profile_url = f"https://tiktok.com/@{username}"
            live_url = f"https://tiktok.com/@{username}/live"
        else:
            profile_url = "#"
            live_url = "#"
        
        # Add Watch button (primary action)
        self.add_item(discord.ui.Button(
            label="Anschauen",
            emoji="📺",
            url=live_url,
            style=discord.ButtonStyle.link,
            row=0
        ))
        
        # Add Follow button (secondary action)
        self.add_item(discord.ui.Button(
            label="Folgen",
            emoji="❤️",
            url=profile_url,
            style=discord.ButtonStyle.link,
            row=0
        ))
        
        # Add Instant Gaming button if game found
        if instant_gaming_data and instant_gaming_data.get('found'):
            game_name = instant_gaming_data.get('game_name', 'Game')
            affiliate_url = instant_gaming_data.get('affiliate_url')
            
            # Truncate game name if too long for button
            display_name = game_name if len(game_name) <= 20 else f"{game_name[:17]}..."
            
            self.add_item(discord.ui.Button(
                label=f"Kaufe {display_name} günstiger",
                emoji="🎮",
                url=affiliate_url,
                style=discord.ButtonStyle.link,
                row=1  # Put on second row
            ))

async def send_private_notifications(creator_id, username, platform, platform_username, stream_info):
    """Send private notifications to platform-specific subscribers (CRASH-RESISTANT)"""
    conn = None
    successful_notifications = 0
    failed_notifications = 0
    
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get platform-specific subscribers (including 'all' subscribers) - IMPROVED QUERY
        cursor.execute('''
            SELECT user_id, platform FROM user_subscriptions 
            WHERE creator_id = ? AND (platform = ? OR platform = 'all')
        ''', (creator_id, platform))
        
        subscribers = cursor.fetchall()
        logger.info(f"🔍 Found {len(subscribers)} subscribers for {username} on {platform}: {[sub[1] for sub in subscribers]}")
        
        for user_id, sub_platform in subscribers:
            try:
                user = bot.get_user(int(user_id))
                if not user:
                    # Try to fetch user if not in cache
                    try:
                        user = await bot.fetch_user(int(user_id))
                    except discord.NotFound:
                        logger.warning(f"User {user_id} not found - removing from subscriptions")
                        continue
                    except discord.HTTPException:
                        logger.warning(f"Failed to fetch user {user_id} - skipping DM")
                        failed_notifications += 1
                        continue
                
                if user:
                    try:
                        # Create enhanced embed with platform info
                        embed = discord.Embed(
                            title=f"🔴 Live Benachrichtigung - {platform.title()}",
                            description=f"**{username}** ist jetzt live auf **{platform.title()}**!\n\n📱 Platform: `{platform_username}`",
                            color=Config.COLORS[platform]
                        )
                        
                        # Add platform-specific details
                        if stream_info.get('game_name'):
                            embed.add_field(name="🎮 Spiel", value=stream_info['game_name'], inline=True)
                        
                        if stream_info.get('viewer_count'):
                            embed.add_field(name="👀 Zuschauer", value=f"{stream_info['viewer_count']:,}", inline=True)
                        
                        # Add follower count
                        if stream_info.get('follower_count'):
                            if platform == 'youtube':
                                embed.add_field(name="📺 Abonnenten", value=f"{stream_info['follower_count']:,}", inline=True)
                            else:  # twitch, tiktok
                                embed.add_field(name="💖 Follower", value=f"{stream_info['follower_count']:,}", inline=True)
                        
                        embed.add_field(name="📋 Subscription", value=f"Benachrichtigung für: `{sub_platform}`", inline=False)
                        embed.timestamp = datetime.utcnow()
                        
                        view = LiveNotificationView(platform, platform_username)
                        await user.send(embed=embed, view=view)
                        successful_notifications += 1
                        logger.debug(f"✅ DM sent to {user.name} for {username} on {platform}")
                        
                    except discord.Forbidden:
                        logger.warning(f"🚨 Cannot send DM to {user.name} - DMs disabled")
                        failed_notifications += 1
                    except discord.HTTPException as discord_error:
                        logger.error(f"🚨 Discord API error sending DM to {user.name}: {discord_error}")
                        failed_notifications += 1
                    except Exception as dm_error:
                        logger.error(f"🚨 CRITICAL: DM failed for {user.name}: {dm_error}")
                        failed_notifications += 1
            
            except Exception as user_error:
                logger.error(f"🚨 CRITICAL: User processing failed for {user_id}: {user_error}")
                failed_notifications += 1
        
        logger.info(f"📬 DM Results for {username} on {platform}: ✅ {successful_notifications} successful, ❌ {failed_notifications} failed")
    
    except Exception as notification_error:
        logger.error(f"🚨 CRITICAL: Private notifications completely failed for {username} on {platform}: {notification_error}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

async def update_daily_streak(creator_id, is_live):
    """Update daily streak for creator"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        today = datetime.now().date()
        
        cursor.execute('SELECT current_streak, last_live_date FROM daily_streaks WHERE creator_id = ?', (creator_id,))
        streak_data = cursor.fetchone()
        
        if streak_data:
            current_streak, last_live_date = streak_data
            last_live_date = datetime.strptime(last_live_date, '%Y-%m-%d').date() if last_live_date else None
            
            if is_live:
                if last_live_date != today:  # First stream today
                    if last_live_date == today - timedelta(days=1):
                        # Consecutive day
                        new_streak = current_streak + 1
                    else:
                        # Break in streak
                        new_streak = 1
                    
                    cursor.execute(
                        'UPDATE daily_streaks SET current_streak = ?, last_live_date = ? WHERE creator_id = ?',
                        (new_streak, today.isoformat(), creator_id)
                    )
        else:
            # Initialize streak data
            cursor.execute(
                'INSERT INTO daily_streaks (creator_id, current_streak, last_live_date) VALUES (?, ?, ?)',
                (creator_id, 1 if is_live else 0, today.isoformat() if is_live else None)
            )
        
        conn.commit()
    
    finally:
        conn.close()

async def get_daily_streak(creator_id):
    """Get current daily streak for creator"""
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT current_streak FROM daily_streaks WHERE creator_id = ?', (creator_id,))
        result = cursor.fetchone()
        return result[0] if result else 0
    finally:
        conn.close()

async def get_streamer_counts():
    """Get count of streamers per platform from database"""
    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Count streamers per platform
        cursor.execute('SELECT COUNT(*) FROM creators WHERE twitch_username IS NOT NULL AND twitch_username != ""')
        twitch_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM creators WHERE youtube_username IS NOT NULL AND youtube_username != ""')
        youtube_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM creators WHERE tiktok_username IS NOT NULL AND tiktok_username != ""')
        tiktok_count = cursor.fetchone()[0]
        
        return twitch_count, youtube_count, tiktok_count
        
    except Exception as e:
        logger.error(f"Error getting streamer counts: {e}")
        return 0, 0, 0
    finally:
        if conn:
            conn.close()

async def get_discord_member_count():
    """Get total member count from all guilds"""
    total_members = 0
    try:
        for guild in bot.guilds:
            if guild.member_count:  # Check if member_count is not None
                total_members += guild.member_count
        return total_members
    except Exception as e:
        logger.error(f"Error getting member count: {e}")
        return 0

# Global variable for status rotation
current_status_index = 0

# Keep-Alive Task for Render.com
@tasks.loop(minutes=10)
async def keep_alive_ping():
    """Ping self every 10 minutes to prevent cloud platform from sleeping"""
    try:
        # Get external URL from environment (Render/Railway)
        external_url = os.getenv('RENDER_EXTERNAL_URL') or os.getenv('RAILWAY_PUBLIC_DOMAIN')
        
        if external_url:
            # Use external URL for cloud deployment
            if not external_url.startswith('http'):
                external_url = f"https://{external_url}"
            ping_url = f"{external_url}/health"
        else:
            # Fallback to local - use same PORT as HTTP server (8080)
            ping_url = f"http://localhost:8080/health"
        
        # Ping health endpoint
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(ping_url) as response:
                if response.status == 200:
                    logger.info("✅ Keep-alive ping successful - preventing cloud sleep")
                else:
                    logger.warning(f"⚠️ Keep-alive ping returned status {response.status}")
                    
    except asyncio.TimeoutError:
        logger.warning("⚠️ Keep-alive ping timed out")
    except Exception as e:
        # Don't spam warnings for normal cloud deployment behavior
        logger.debug(f"Keep-alive ping failed (normal for cloud platforms): {e}")

# Status rotation task
@tasks.loop(minutes=3)
async def status_rotator():
    """Rotate bot status every 3 minutes with live data"""
    global current_status_index
    try:
        # Get live data
        twitch_count, youtube_count, tiktok_count = await get_streamer_counts()
        member_count = await get_discord_member_count()
        
        # Define the 4 status messages with emojis for custom status
        statuses = [
            f"🧟‍♂️💜Watching Twitch: {twitch_count}",
            f"🧟‍♀️🩵Watching TikTok: {tiktok_count}",
            f"🧟❤️Watching Youtube: {youtube_count}",
            f"🤖Discord Member: {member_count}"
        ]
        
        # Set custom status (proper format for custom status)
        current_message = statuses[current_status_index]
        await bot.change_presence(activity=discord.CustomActivity(name=current_message))
        
        logger.info(f"🤖 Bot status updated: {current_message}")
        
        # Move to next status (0-3 cycle)
        current_status_index = (current_status_index + 1) % 4
        
    except Exception as e:
        logger.error(f"Error updating bot status: {e}")

# Global variable to track bot start time
bot_start_time = None

# Auto-Restart Task
@tasks.loop(hours=12)
async def auto_restart_task():
    """Automatic restart every 12 hours to prevent memory leaks and refresh connections"""
    try:
        # Check if enough time has passed since bot start (at least 11.5 hours)
        if bot_start_time:
            uptime = datetime.now() - bot_start_time
            if uptime.total_seconds() < 41400:  # 11.5 hours in seconds
                logger.info(f"🔄 AUTO-RESTART: Skipping restart - bot uptime is only {uptime}. Next check in 12 hours.")
                return
        
        logger.info("🔄 AUTO-RESTART: Initiating scheduled 12-hour restart...")
        
        # Send notification to admin channels if possible
        for guild in bot.guilds:
            try:
                # Try to find a suitable channel for admin notifications
                for channel in guild.text_channels:
                    if any(keyword in channel.name.lower() for keyword in ['admin', 'log', 'bot', 'dev']):
                        embed = discord.Embed(
                            title="🔄 Scheduled Restart",
                            description="Bot restarting automatically (12-hour maintenance cycle)",
                            color=0x00FF00,
                            timestamp=datetime.now().replace(tzinfo=datetime.now().astimezone().tzinfo)
                        )
                        await channel.send(embed=embed)
                        break
            except Exception as e:
                logger.warning(f"Could not send restart notification to {guild.name}: {e}")
        
        # Close all connections gracefully
        logger.info("🔄 AUTO-RESTART: Closing connections...")
        await tiktok_live_checker.cleanup()
        
        # Exit - Replit/Railway will automatically restart the bot
        logger.info("🔄 AUTO-RESTART: Exiting for restart...")
        os._exit(0)
        
    except Exception as e:
        logger.error(f"🚨 AUTO-RESTART ERROR: {e}")

async def post_logs_to_dev_channel(log_files_to_delete):
    """Post log files to dev channel before deletion (only on main server)"""
    try:
        # Check if dev channel and main server are configured
        if not Config.DEV_CHANNEL_ID or not Config.MAIN_SERVER_ID:
            logger.info("📁 LOG-BACKUP: Dev channel or main server not configured - skipping log backup")
            return
        
        # Get the main server
        main_guild = bot.get_guild(Config.MAIN_SERVER_ID)
        if not main_guild:
            logger.warning(f"📁 LOG-BACKUP: Main server {Config.MAIN_SERVER_ID} not found")
            return
        
        # Get the dev channel
        dev_channel = main_guild.get_channel(Config.DEV_CHANNEL_ID)
        if not dev_channel:
            logger.warning(f"📁 LOG-BACKUP: Dev channel {Config.DEV_CHANNEL_ID} not found in main server")
            return
        
        if not log_files_to_delete:
            logger.info("📁 LOG-BACKUP: No log files to backup")
            return
        
        logger.info(f"📁 LOG-BACKUP: Backing up {len(log_files_to_delete)} log files to dev channel...")
        
        # Create embed for the log backup
        embed = discord.Embed(
            title="🗑️ Log Cleanup - Archive",
            description=f"Automatische Sicherung von {len(log_files_to_delete)} Log-Dateien vor der 6h-Bereinigung",
            color=0xFFA500,  # Orange
            timestamp=datetime.now().replace(tzinfo=datetime.now().astimezone().tzinfo)
        )
        
        # If there are many files, create a ZIP archive
        if len(log_files_to_delete) > 3:
            # Create ZIP archive in memory
            zip_buffer = io.BytesIO()
            total_size = 0
            files_added = 0
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for file_path, _ in log_files_to_delete:
                    if os.path.exists(file_path):
                        try:
                            file_size = os.path.getsize(file_path)
                            # Skip individual files larger than 50MB to prevent ZIP issues
                            if file_size > 50 * 1024 * 1024:
                                logger.warning(f"📁 LOG-BACKUP: File {file_path} too large ({file_size} bytes) - skipping from ZIP")
                                continue
                            
                            # Use only filename for ZIP entry
                            arcname = os.path.basename(file_path)
                            zip_file.write(file_path, arcname)
                            total_size += file_size
                            files_added += 1
                            logger.debug(f"📁 Added {arcname} to ZIP ({file_size} bytes)")
                        except Exception as e:
                            logger.warning(f"📁 Could not add {file_path} to ZIP: {e}")
            
            zip_buffer.seek(0)
            zip_size = len(zip_buffer.getvalue())
            zip_filename = f"karma_bot_logs_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            
            # Check if ZIP is within Discord limits (8MB default)  
            size_limit = 8 * 1024 * 1024  # Use standard 8MB limit for safety
            if zip_size > size_limit:
                logger.warning(f"📁 LOG-BACKUP: ZIP too large ({zip_size} bytes) - fallback to individual files")
                # Fallback to individual file sending
                await dev_channel.send(embed=discord.Embed(
                    title="🗑️ Log Cleanup - Archive (Fallback)",
                    description=f"ZIP zu groß ({zip_size//1024//1024}MB) - sende Dateien einzeln",
                    color=0xFFA500
                ))
                # Send files individually as fallback
                for file_path, _ in log_files_to_delete:
                    if os.path.exists(file_path):
                        try:
                            file_size = os.path.getsize(file_path)
                            if file_size <= 8 * 1024 * 1024:  # 8MB limit for individual files
                                filename = os.path.basename(file_path)
                                file = discord.File(file_path, filename=filename)
                                await dev_channel.send(file=file)
                                logger.info(f"📁 LOG-BACKUP: Fallback - File {filename} sent individually")
                        except Exception as e:
                            logger.warning(f"📁 Fallback upload failed for {file_path}: {e}")
            else:
                embed.add_field(
                    name="📦 Archive Details", 
                    value=f"**Format:** ZIP-Archiv\n**Dateien:** {files_added}/{len(log_files_to_delete)}\n**Größe:** {zip_size//1024}KB\n**Filename:** `{zip_filename}`", 
                    inline=False
                )
                
                # Send ZIP file
                file = discord.File(zip_buffer, filename=zip_filename)
                await dev_channel.send(embed=embed, file=file)
                logger.info(f"📁 LOG-BACKUP: ZIP archive with {files_added} files ({zip_size//1024}KB) sent to dev channel")
            
        else:
            # Send individual files (≤3 files)
            total_size = sum(os.path.getsize(fp) for fp, _ in log_files_to_delete if os.path.exists(fp))
            
            embed.add_field(
                name="📄 File Details", 
                value=f"**Format:** Einzelne Dateien\n**Anzahl:** {len(log_files_to_delete)}\n**Gesamtgröße:** {total_size//1024}KB", 
                inline=False
            )
            
            await dev_channel.send(embed=embed)
            
            files_sent = 0
            for file_path, _ in log_files_to_delete:
                if os.path.exists(file_path):
                    try:
                        file_size = os.path.getsize(file_path)
                        # Discord file size limit is 8MB (8 * 1024 * 1024 bytes)
                        if file_size > 8 * 1024 * 1024:
                            logger.warning(f"📁 LOG-BACKUP: File {file_path} too large ({file_size//1024//1024}MB) - skipping")
                            continue
                        
                        filename = os.path.basename(file_path)
                        file = discord.File(file_path, filename=filename)
                        await dev_channel.send(file=file)
                        files_sent += 1
                        logger.info(f"📁 LOG-BACKUP: File {filename} sent to dev channel ({file_size//1024}KB)")
                    except FileNotFoundError:
                        logger.warning(f"📁 File {file_path} not found during upload")
                    except discord.HTTPException as e:
                        logger.warning(f"📁 Discord upload failed for {file_path}: {e}")
                    except Exception as e:
                        logger.warning(f"📁 Could not upload {file_path}: {e}")
            
            logger.info(f"📁 LOG-BACKUP: Sent {files_sent}/{len(log_files_to_delete)} individual files")
        
        logger.info("📁 LOG-BACKUP: Log backup to dev channel completed")
        
    except Exception as e:
        logger.error(f"🚨 LOG-BACKUP ERROR: {e}")

# Log Cleanup Task
@tasks.loop(hours=6)
async def log_cleanup_task():
    """Clean old log files every 6 hours, keep only 10 newest files"""
    try:
        logger.info("🗑️ LOG-CLEANUP: Starting log cleanup process...")
        
        # Define log directories to clean
        log_paths = [
            '/tmp/logs/',
            './logs/',
            './',
        ]
        
        for log_path in log_paths:
            try:
                if not os.path.exists(log_path):
                    continue
                    
                # Find all log files
                log_files = []
                for root, dirs, files in os.walk(log_path):
                    for file in files:
                        if file.endswith(('.log', '.txt')) and any(keyword in file.lower() for keyword in ['discord', 'bot', 'karma', 'workflow']):
                            full_path = os.path.join(root, file)
                            try:
                                stat = os.stat(full_path)
                                log_files.append((full_path, stat.st_mtime))
                            except OSError:
                                continue
                
                # Sort by modification time (newest first)
                log_files.sort(key=lambda x: x[1], reverse=True)
                
                # Keep only 10 newest, delete the rest
                if len(log_files) > 10:
                    files_to_delete = log_files[10:]
                    
                    # Post logs to dev channel before deletion (only on first path to avoid duplicates)
                    if log_path == '/tmp/logs/' and files_to_delete:
                        logger.info(f"🗑️ LOG-CLEANUP: Backing up {len(files_to_delete)} files before deletion...")
                        await post_logs_to_dev_channel(files_to_delete)
                        logger.info("🗑️ LOG-CLEANUP: Backup completed, proceeding with deletion...")
                    
                    deleted_count = 0
                    
                    for file_path, _ in files_to_delete:
                        try:
                            os.remove(file_path)
                            deleted_count += 1
                            logger.info(f"🗑️ Deleted old log: {os.path.basename(file_path)}")
                        except OSError as e:
                            logger.warning(f"Could not delete {file_path}: {e}")
                    
                    logger.info(f"🗑️ LOG-CLEANUP: Deleted {deleted_count} old log files in {log_path}")
                else:
                    logger.info(f"🗑️ LOG-CLEANUP: No cleanup needed in {log_path} ({len(log_files)} files)")
                    
            except Exception as path_error:
                logger.warning(f"Error cleaning log path {log_path}: {path_error}")
        
        logger.info("🗑️ LOG-CLEANUP: Process completed")
        
    except Exception as e:
        logger.error(f"🚨 LOG-CLEANUP ERROR: {e}")

# Stats Channels Update Task
@tasks.loop(minutes=5)
async def stats_updater():
    """Update all stats channels with current server statistics"""
    try:
        logger.info("📊 STATS-UPDATE: Starting stats channels update...")
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get all stats channels
        cursor.execute('SELECT guild_id, channel_id, counter_type, role_id, last_count FROM stats_channels')
        stats_channels = cursor.fetchall()
        
        if not stats_channels:
            logger.info("📊 STATS-UPDATE: No stats channels configured")
            conn.close()
            return
        
        # Group by guild to avoid repeated API calls
        guilds_data = {}
        
        for guild_id, channel_id, counter_type, role_id, last_count in stats_channels:
            try:
                guild = bot.get_guild(int(guild_id))
                if not guild:
                    logger.warning(f"📊 Guild {guild_id} not found for channel {channel_id}")
                    continue
                
                # Collect guild data if not already done
                if guild_id not in guilds_data:
                    # Count online members with fallback for missing presences intent
                    online_members = 0
                    for member in guild.members:
                        # Try to count using status, but fallback if presences intent not available
                        if hasattr(member, 'status') and member.status != discord.Status.offline:
                            online_members += 1
                    
                    # If we got 0 online members, likely missing presences intent - fallback to voice channels
                    if online_members == 0:
                        voice_members = set()
                        for voice_channel in guild.voice_channels:
                            voice_members.update(voice_channel.members)
                        online_members = len(voice_members)
                    
                    guilds_data[guild_id] = {
                        'guild': guild,
                        'online_count': online_members,  # Real online members based on status
                        'member_count': guild.member_count,
                        'channel_count': len(guild.channels),
                        'role_count': len(guild.roles) - 1,  # Exclude @everyone
                        'peak_online': 0  # This would need to be tracked separately
                    }
                
                guild_data = guilds_data[guild_id]
                current_count = 0
                
                # Calculate current count based on counter type
                if counter_type == 'online':
                    current_count = guild_data['online_count']
                elif counter_type == 'members':
                    current_count = guild_data['member_count']
                elif counter_type == 'channels':
                    current_count = guild_data['channel_count']
                elif counter_type == 'roles':
                    current_count = guild_data['role_count']
                elif counter_type == 'peak_online':
                    # For peak online, keep the higher value
                    current_count = max(last_count, guild_data['online_count'])
                elif counter_type == 'role_count' and role_id:
                    # Count members with specific role
                    role = guild.get_role(int(role_id))
                    if role:
                        current_count = len(role.members)
                    else:
                        logger.warning(f"📊 Role {role_id} not found in guild {guild_id}")
                        continue
                
                # Update channel name if count changed
                if current_count != last_count:
                    channel = guild.get_channel(int(channel_id))
                    if channel and isinstance(channel, discord.VoiceChannel):
                        # Generate new channel name
                        if counter_type == 'online':
                            new_name = f"🟢ONLINE MEMBER: {current_count}"
                        elif counter_type == 'peak_online':
                            new_name = f"📈DAILY PEAK ONLINE: {current_count}"
                        elif counter_type == 'members':
                            new_name = f"👥DISCORD MEMBER: {current_count}"
                        elif counter_type == 'channels':
                            new_name = f"📝DISCORD CHANNEL: {current_count}"
                        elif counter_type == 'roles':
                            new_name = f"👾DISCORD ROLES: {current_count}"
                        elif counter_type == 'role_count' and role_id:
                            role = guild.get_role(int(role_id))
                            if role:
                                new_name = f"{role.name}: {current_count}"
                            else:
                                continue
                        
                        # Update channel name
                        try:
                            await channel.edit(name=new_name)
                            logger.info(f"📊 Updated {guild.name}: {new_name} (was {last_count})")
                            
                            # Update database with new count
                            cursor.execute(
                                'UPDATE stats_channels SET last_count = ? WHERE channel_id = ?',
                                (current_count, channel_id)
                            )
                            
                        except discord.Forbidden:
                            logger.warning(f"📊 No permission to edit channel {channel.name} in {guild.name}")
                        except discord.HTTPException as e:
                            logger.warning(f"📊 Failed to edit channel {channel.name}: {e}")
                    else:
                        logger.warning(f"📊 Channel {channel_id} not found or not a voice channel - removing from database")
                        # Remove deleted channel from database
                        cursor.execute('DELETE FROM stats_channels WHERE channel_id = ?', (channel_id,))
                        # Commit deletion immediately
                        conn.commit()
                
            except Exception as channel_error:
                logger.error(f"📊 Error updating channel {channel_id}: {channel_error}")
        
        conn.commit()
        conn.close()
        
        updated_count = sum(1 for guild_data in guilds_data.values())
        logger.info(f"📊 STATS-UPDATE: Completed - processed {len(stats_channels)} channels across {updated_count} guilds")
        
        # Also update social media stats channels
        await social_media_stats_updater()
        
    except Exception as e:
        logger.error(f"📊 STATS-UPDATE ERROR: {e}")
        if 'conn' in locals():
            try:
                conn.close()
            except:
                pass


# Social Media Stats Update Task
@tasks.loop(seconds=Config.SOCIAL_MEDIA_CHECK_INTERVAL)
async def social_media_stats_updater_task():
    """Task loop for updating social media stats channels every 30 minutes"""
    await social_media_stats_updater()


async def social_media_stats_updater():
    """Update all social media stats channels with current follower counts"""
    try:
        logger.info("📱 SOCIAL-MEDIA-UPDATE: Starting social media stats channels update...")
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get all social media stats channels
        cursor.execute('SELECT guild_id, channel_id, platform, username, last_follower_count FROM social_media_stats_channels')
        social_channels = cursor.fetchall()
        
        if not social_channels:
            logger.info("📱 SOCIAL-MEDIA-UPDATE: No social media stats channels configured")
            conn.close()
            return
        
        updated_channels = 0
        failed_updates = 0
        
        for guild_id, channel_id, platform, username, last_count in social_channels:
            try:
                guild = bot.get_guild(int(guild_id))
                if not guild:
                    logger.warning(f"📱 Guild {guild_id} not found for social media channel {channel_id}")
                    continue
                
                channel = guild.get_channel(int(channel_id))
                if not channel:
                    logger.warning(f"📱 Channel {channel_id} not found in guild {guild.name}")
                    # Remove from database if channel no longer exists
                    cursor.execute('DELETE FROM social_media_stats_channels WHERE channel_id = ?', (channel_id,))
                    continue
                
                # Get current follower count (using SCRAPING ONLY to save API limits)
                current_count = await social_media_scraping_apis.get_follower_count_scraping_only(platform, username)
                
                if current_count is None:
                    # If we can't get the count, try one more time after a brief delay
                    await asyncio.sleep(2)
                    current_count = await social_media_scraping_apis.get_follower_count_scraping_only(platform, username)
                    
                    if current_count is None:
                        logger.warning(f"📱 Failed to get {platform} follower count for @{username}")
                        failed_updates += 1
                        continue
                
                # Format the channel name
                new_channel_name = f"{platform.title()} Follower: {current_count:,}"
                
                # Only update if the count has changed or name format has changed
                if current_count != last_count or channel.name != new_channel_name:
                    try:
                        await channel.edit(name=new_channel_name, reason="Social Media Follower Update")
                        
                        # Update database with new count and timestamp
                        cursor.execute('''
                            UPDATE social_media_stats_channels 
                            SET last_follower_count = ?, last_update = CURRENT_TIMESTAMP 
                            WHERE channel_id = ?
                        ''', (current_count, channel_id))
                        
                        change_indicator = "➕" if current_count > last_count else ("➖" if current_count < last_count else "➡️")
                        logger.info(f"📱 Updated {guild.name}: {platform.title()} @{username}: {current_count:,} {change_indicator} (was {last_count:,})")
                        updated_channels += 1
                        
                    except discord.HTTPException as http_error:
                        if http_error.status == 429:  # Rate limited
                            logger.warning(f"📱 Rate limited updating {platform} channel for @{username}, will retry next cycle")
                            await asyncio.sleep(1)  # Brief delay before continuing
                        else:
                            logger.error(f"📱 HTTP error updating {platform} channel for @{username}: {http_error}")
                        failed_updates += 1
                    except Exception as update_error:
                        logger.error(f"📱 Error updating {platform} channel for @{username}: {update_error}")
                        failed_updates += 1
                else:
                    logger.debug(f"📱 No change for {platform} @{username}: {current_count:,} followers")
                
                # Small delay to avoid hitting Discord rate limits
                await asyncio.sleep(0.5)
                
            except Exception as channel_error:
                logger.error(f"📱 Error processing social media channel {channel_id}: {channel_error}")
                failed_updates += 1
        
        conn.commit()
        conn.close()
        
        if updated_channels > 0 or failed_updates > 0:
            logger.info(f"📱 SOCIAL-MEDIA-UPDATE: Completed - Updated: {updated_channels}, Failed: {failed_updates}, Total: {len(social_channels)}")
        
    except Exception as e:
        logger.error(f"📱 SOCIAL-MEDIA-UPDATE ERROR: {e}")
        if 'conn' in locals():
            try:
                conn.close()
            except:
                pass

# TikTok Task Recovery
@tasks.loop(minutes=30)
async def tiktok_recovery_task():
    """TikTok task recovery every 30 minutes - restart failed TikTok checks"""
    try:
        logger.info("🔧 TIKTOK-RECOVERY: Starting TikTok task recovery check...")
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get all creators with TikTok usernames
        cursor.execute('SELECT id, discord_username, tiktok_username FROM creators WHERE tiktok_username IS NOT NULL AND tiktok_username != ""')
        tiktok_creators = cursor.fetchall()
        
        if not tiktok_creators:
            logger.info("🔧 TIKTOK-RECOVERY: No TikTok creators found")
            conn.close()
            return
        
        logger.info(f"🔧 TIKTOK-RECOVERY: Checking {len(tiktok_creators)} TikTok creators...")
        
        # Reset any stuck TikTok connections
        try:
            if hasattr(tiktok_live_checker, 'session') and tiktok_live_checker.session:
                await tiktok_live_checker.session.close()
                tiktok_live_checker.session = None
                logger.info("🔧 TIKTOK-RECOVERY: Reset TikTok HTTP session")
        except Exception as session_error:
            logger.warning(f"Error resetting TikTok session: {session_error}")
        
        # Test TikTok connectivity with a quick check
        recovery_success = 0
        recovery_failed = 0
        
        for creator_id, username, tiktok_user in tiktok_creators[:3]:  # Test only first 3 to avoid rate limits
            try:
                logger.info(f"🔧 Testing TikTok connectivity for {username} (@{tiktok_user})...")
                
                # Quick connectivity test with timeout
                test_result = await asyncio.wait_for(
                    tiktok_live_checker.get_stream_info(tiktok_user),
                    timeout=15.0
                )
                
                if test_result is not None:
                    recovery_success += 1
                    logger.info(f"✅ TikTok recovery successful for {username}")
                else:
                    recovery_failed += 1
                    logger.warning(f"⚠️ TikTok recovery failed for {username}")
                    
            except asyncio.TimeoutError:
                recovery_failed += 1
                logger.warning(f"⚠️ TikTok recovery timeout for {username}")
            except Exception as test_error:
                recovery_failed += 1
                logger.warning(f"⚠️ TikTok recovery error for {username}: {test_error}")
        
        # Reset TikTok API caches to prevent stale data
        try:
            if hasattr(tiktok_live_checker, 'cache'):
                tiktok_live_checker.cache.clear()
            if hasattr(tiktok_live_checker, 'scrape_cache'):
                tiktok_live_checker.scrape_cache.clear()
            if hasattr(tiktok_live_checker, 'quota_backoff'):
                # Don't clear quota backoff - it's there for protection
                pass
            logger.info("🔧 TIKTOK-RECOVERY: Cleared TikTok caches")
        except Exception as cache_error:
            logger.warning(f"Error clearing TikTok caches: {cache_error}")
        
        conn.close()
        
        logger.info(f"🔧 TIKTOK-RECOVERY: Completed - Success: {recovery_success}, Failed: {recovery_failed}")
        
    except Exception as e:
        logger.error(f"🚨 TIKTOK-RECOVERY ERROR: {e}")

@bot.event
async def on_ready():
    global bot_start_time
    bot_start_time = datetime.now()
    logger.info(f'{bot.user} has connected to Discord!')
    logger.info(f'Bot is in {len(bot.guilds)} guilds')
    logger.info(f"🔄 Bot started at {bot_start_time} - first auto-restart will be after 12 hours of uptime")
    
    # 🌍 DETAILED SERVER OVERVIEW
    logger.info("🌍 ========== DETAILED SERVER OVERVIEW ==========")
    for guild in bot.guilds:
        try:
            owner = guild.owner
            member_count = guild.member_count
            
            # Find streamer roles and count streamers
            streamer_roles = [r for r in guild.roles if "streamer" in r.name.lower()]
            streamer_count = sum(len(r.members) for r in streamer_roles)
            
            # Format dates
            created_at = guild.created_at.strftime("%d.%m.%Y %H:%M:%S") if guild.created_at else "Unbekannt"
            joined_at = guild.me.joined_at.strftime("%d.%m.%Y %H:%M:%S") if guild.me.joined_at else "Unbekannt"
            
            # Additional server info
            text_channels = len(guild.text_channels)
            voice_channels = len(guild.voice_channels)
            total_roles = len(guild.roles)
            boost_level = guild.premium_tier
            boost_count = guild.premium_subscription_count or 0
            
            # Build server info lines
            info_lines = [
                f"\n🔹 {guild.name}",
                f"   🆔 Server-ID: {guild.id}",
                f"   👑 Besitzer: {owner} (ID: {owner.id})" if owner else "   👑 Besitzer: Unbekannt",
                f"   👥 Mitglieder: {member_count:,}",
                f"   🎥 Streamer: {streamer_count}",
                f"   💬 Text-Kanäle: {text_channels}",
                f"   🔊 Voice-Kanäle: {voice_channels}",
                f"   🏷️ Rollen: {total_roles}",
                f"   ⭐ Boost Level: {boost_level} (Boosts: {boost_count})",
                f"   📅 Erstellt am: {created_at}",
                f"   🤖 Bot beigetreten: {joined_at}",
                f"   ---"
            ]
            
            logger.info("\n".join(info_lines))
            
            # Streamer roles are counted above, no need to log details
            
        except Exception as e:
            logger.error(f"   ❌ Fehler beim Laden der Server-Info für {guild.name}: {e}")
    
    logger.info("🌍 ============ END SERVER OVERVIEW ============\n")
    
    # Start the live check tasks
    live_checker.start()
    
    # Start the status rotation task
    status_rotator.start()
    logger.info("🤖 Status rotation started - cycling every 3 minutes")
    
    # Start keep-alive ping for Render.com
    keep_alive_ping.start()
    logger.info("🔄 Keep-alive ping started - preventing Render.com sleep every 10 minutes")
    
    # Start auto-restart task
    auto_restart_task.start()
    logger.info("🔄 Auto-restart task started - restarting every 12 hours")
    
    # Start log cleanup task
    log_cleanup_task.start()
    logger.info("🗑️ Log cleanup task started - cleaning logs every 6 hours (keep 10 newest)")
    
    # Start stats updater task
    stats_updater.start()
    logger.info("📊 Stats updater started - updating stats channels every 5 minutes")
    
    # Start social media stats updater task
    social_media_stats_updater_task.start()
    logger.info("📱 Social Media stats updater started - updating social media channels every 30 minutes")
    
    # Start TikTok recovery task
    tiktok_recovery_task.start()
    logger.info("🔧 TikTok recovery task started - checking TikTok connectivity every 30 minutes")
    
    # Initialize OpenAI Auto-Repair System
    global auto_repair_system
    auto_repair_system = OpenAIAutoRepair(bot)
    logger.info("🤖 OpenAI Auto-Repair System ready for scraping failures")
    
    # Import and add command cogs (pass DatabaseManager class)
    import commands
    import event_commands
    
    # Set DatabaseManager in modules to avoid class conflicts
    commands.DatabaseManager = DatabaseManager
    event_commands.DatabaseManager = DatabaseManager
    
    from commands import CreatorManagement, UserCommands, ServerManagement
    from event_commands import EventCommands, UtilityCommands
    
    # Add cogs with debug logging
    logger.info("Adding CreatorManagement cog...")
    await bot.add_cog(CreatorManagement(bot, db))
    logger.info("Adding UserCommands cog...")
    await bot.add_cog(UserCommands(bot, db))
    logger.info("Adding ServerManagement cog...")
    await bot.add_cog(ServerManagement(bot, db))
    logger.info("Adding EventCommands cog...")
    await bot.add_cog(EventCommands(bot, db))
    logger.info("Adding UtilityCommands cog...")
    await bot.add_cog(UtilityCommands(bot, db))
    
    logger.info(f"Bot tree has {len(bot.tree.get_commands())} commands")
    
    # Sync slash commands - Simple overwrite approach (fixes old commands)
    try:
        # 1. Global sync first (overwrites old commands globally)
        synced_global = await bot.tree.sync()
        logger.info(f'✅ Global sync successful - {len(synced_global)} command(s) - old commands overwritten')
        
        # 2. Guild sync for immediate visibility (overwrites old guild commands)
        for guild in bot.guilds:
            # Copy global commands to guild for immediate visibility
            bot.tree.copy_global_to(guild=guild)
            synced_guild = await bot.tree.sync(guild=guild)
            logger.info(f'✅ Guild sync successful for {guild.name} - {len(synced_guild)} command(s) - old commands overwritten')
            
    except Exception as e:
        logger.error(f'❌ Command sync failed: {e}')
        # Try basic global sync as last resort
        try:
            synced = await bot.tree.sync()
            logger.info(f'✅ Fallback global sync - {len(synced)} command(s)')
        except Exception as fallback_e:
            logger.error(f'❌ All sync methods failed: {fallback_e}')

async def create_health_server():
    """Create a simple HTTP server for Render.com health checks"""
    async def health_check(request):
        return web.json_response({
            "status": "healthy",
            "bot": "KARMA-LiveBOT",
            "uptime": "running",
            "timestamp": datetime.now().isoformat()
        })
    
    async def root_handler(request):
        return web.json_response({
            "message": "KARMA-LiveBOT is running",
            "status": "online"
        })
    
    # Create web app
    app = web.Application()
    app.router.add_get('/', root_handler)
    app.router.add_get('/health', health_check)
    app.router.add_get('/status', health_check)
    
    # Get port from environment (backend health check server)
    port = int(os.getenv('PORT', 8080))
    
    # Start server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"🌐 HTTP server started on port {port} for Render.com health checks")
    return runner

async def main():
    """Main function to run both Discord bot and HTTP server"""
    if not Config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN not found in environment variables")
        exit(1)
    
    logger.info("Starting KARMA-LiveBOT...")
    
    # Start HTTP server for Render.com
    server_runner = await create_health_server()
    
    try:
        # Start Discord bot (this blocks)
        await bot.start(Config.DISCORD_TOKEN)
    except KeyboardInterrupt:
        logger.info("Bot shutdown requested")
    finally:
        # Cleanup
        if server_runner:
            await server_runner.cleanup()
        # Clean up TikTok session to prevent resource leaks
        await tiktok_live_checker.cleanup()
        await bot.close()

if __name__ == '__main__':
    # Run the async main function
    asyncio.run(main())
