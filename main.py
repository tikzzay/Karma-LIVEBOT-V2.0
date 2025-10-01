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

# Import platform modules
from twitch import twitch_api, twitch_platform_task
from youtube import youtube_api, youtube_platform_task
from tiktok import improved_tiktok_checker, tiktok_platform_task
from social import stats_platform_task, social_media_stats_platform_task, social_media_scraping_apis

# Import core modules
from config import Config
from database import DatabaseManager
from autorepair import OpenAIAutoRepair
from instantgaming import InstantGamingAPI
from event import EventManager

# Verbesserte TikTok Live-Erkennung (legacy compatibility)
IMPROVED_TIKTOK_CHECKER_AVAILABLE = True

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

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix='!', intents=intents)
db = DatabaseManager()

# Initialize modules
instant_gaming = InstantGamingAPI(db=db)
event_manager = EventManager(db=db)

# Auto-Repair System (initialized later in on_ready with bot reference)
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
        """Get stream information for a TikTok user with improved double verification"""
        
        # 🚀 PRIORITÄT 1: Neue doppelte Verifikation (TikTokLive + HTML-Parsing)
        if IMPROVED_TIKTOK_CHECKER_AVAILABLE:
            try:
                logger.info(f"TikTok {username}: Verwende verbesserte doppelte Verifikation...")
                result = await improved_tiktok_checker.is_user_live(username)
                
                if result.get('is_live'):
                    logger.info(f"TikTok {username}: ✅ DOPPELT BESTÄTIGT via neue Methode - User ist LIVE!")
                    return result
                else:
                    logger.info(f"TikTok {username}: Doppelte Verifikation bestätigt - User offline")
                    # Bei negativem Ergebnis der doppelten Verifikation ist das sehr sicher
                    return {'is_live': False, 'method': 'double_verification_offline'}
                    
            except Exception as e:
                logger.warning(f"TikTok {username}: Doppelte Verifikation fehlgeschlagen: {e}")
                # Falls die neue Methode fehlschlägt, verwende Fallback
                logger.info(f"TikTok {username}: Fallback auf erweiterte WAF-Umgehung...")
        else:
            logger.warning(f"TikTok {username}: Verbesserte Checker nicht verfügbar, verwende Fallback...")
        
        # 🔄 FALLBACK: Bestehende erweiterte WAF-Umgehungslogik
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
# Old TikTokLiveChecker removed - using improved_tiktok_checker from live_checker.py

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
# ========== NEW MODULAR PLATFORM TASK SYSTEM ==========
# Platform task references
platform_tasks = {}  # Store platform task references
platform_task_heartbeats = {}  # Track platform task health
creators_cache = []  # Cache all creators for platform tasks

# Legacy compatibility (for functions that still expect the old system)
creator_tasks = {}  # Keep for backward compatibility
creator_heartbeats = {}  # Keep for backward compatibility  
creator_data_cache = {}  # Keep for backward compatibility

# ========== NEW PLATFORM COORDINATION SYSTEM ==========

async def refresh_creators_cache():
    """Refresh the creators cache for platform tasks"""
    global creators_cache
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, discord_user_id, discord_username, streamer_type, notification_channel_id, twitch_username, youtube_username, tiktok_username FROM creators')
        creators_cache = cursor.fetchall()
        conn.close()
        logger.info(f"✅ Refreshed creators cache: {len(creators_cache)} creators")
        return creators_cache
    except Exception as e:
        logger.error(f"❌ Error refreshing creators cache: {e}")
        return []

async def platform_notification_coordinator(creator_id, discord_user_id, username, streamer_type, channel_id, platform, platform_username, stream_info):
    """Coordinate notifications from platform tasks to the notification system"""
    try:
        # This is the bridge between new platform tasks and existing notification system
        await handle_stream_status(creator_id, discord_user_id, username, streamer_type, channel_id, platform, platform_username, stream_info)
    except Exception as e:
        logger.error(f"❌ Error in platform notification coordinator for {username} on {platform}: {e}")

async def start_new_platform_tasks():
    """Start the new modular platform tasks"""
    global platform_tasks
    
    try:
        logger.info("🚀 Starting new modular platform task system...")
        
        # Refresh creators cache
        creators = await refresh_creators_cache()
        
        # Start Twitch platform task
        logger.info("🎮 Starting Twitch platform task...")
        platform_tasks['twitch'] = asyncio.create_task(
            enhanced_twitch_platform_task(db, bot, creators)
        )
        
        # Start YouTube platform task
        logger.info("📺 Starting YouTube platform task...")
        platform_tasks['youtube'] = asyncio.create_task(
            enhanced_youtube_platform_task(db, bot, creators)
        )
        
        # Start TikTok platform task
        logger.info("🎵 Starting TikTok platform task...")
        platform_tasks['tiktok'] = asyncio.create_task(
            enhanced_tiktok_platform_task(db, bot, creators)
        )
        
        # Start Stats platform task
        logger.info("📊 Starting Stats platform task...")
        platform_tasks['stats'] = asyncio.create_task(
            stats_platform_task(db, bot)
        )
        
        # Start Social Media Stats platform task
        logger.info("📱 Starting Social Media Stats platform task...")
        platform_tasks['social_media_stats'] = asyncio.create_task(
            social_media_stats_platform_task(db, bot)
        )
        
        logger.info(f"✅ Successfully started {len(platform_tasks)} platform tasks")
        
    except Exception as e:
        logger.error(f"❌ Error starting platform tasks: {e}")

async def enhanced_twitch_platform_task(db, bot, creators):
    """Enhanced Twitch platform task with notification coordination"""
    logger.info("🎮 Enhanced Twitch platform task started")
    
    while True:
        try:
            # Refresh creators periodically
            if random.randint(1, 10) == 1:  # 10% chance each cycle
                creators = await refresh_creators_cache()
            
            twitch_creators = [c for c in creators if c[5]]  # Has twitch_username
            
            if not twitch_creators:
                await asyncio.sleep(120)  # Wait 2 minutes if no Twitch creators
                continue
            
            platform_task_heartbeats['twitch'] = datetime.now()
            logger.debug(f"🎮 Checking {len(twitch_creators)} Twitch creators")
            
            for creator in twitch_creators:
                creator_id, discord_user_id, username, streamer_type, channel_id, twitch_user, youtube_user, tiktok_user = creator
                
                try:
                    # Check if user is live using the imported twitch_api
                    stream_info = await twitch_api.get_stream_info(twitch_user)
                    
                    if stream_info and stream_info.get('is_live'):
                        logger.info(f"🎮 {twitch_user} is LIVE on Twitch!")
                        # Trigger notification through coordinator
                        await platform_notification_coordinator(
                            creator_id, discord_user_id, username, streamer_type, 
                            channel_id, 'twitch', twitch_user, stream_info
                        )
                    else:
                        # Handle offline status too
                        offline_info = {'is_live': False}
                        await platform_notification_coordinator(
                            creator_id, discord_user_id, username, streamer_type, 
                            channel_id, 'twitch', twitch_user, offline_info
                        )
                    
                except Exception as e:
                    logger.error(f"🎮 Error checking Twitch user {twitch_user}: {e}")
                
                # Small delay between checks to avoid rate limits
                await asyncio.sleep(2)
            
            # Determine wait time based on streamer types
            karma_creators = [c for c in twitch_creators if c[3] == 'karma']
            if karma_creators:
                await asyncio.sleep(60)  # 1 minute for karma streamers
            else:
                await asyncio.sleep(180)  # 3 minutes for regular streamers
            
        except Exception as e:
            logger.error(f"🎮 Error in enhanced Twitch platform task: {e}")
            await asyncio.sleep(30)  # Wait before retrying on error

async def enhanced_youtube_platform_task(db, bot, creators):
    """Enhanced YouTube platform task with notification coordination"""
    logger.info("📺 Enhanced YouTube platform task started")
    
    while True:
        try:
            # Refresh creators periodically
            if random.randint(1, 10) == 1:  # 10% chance each cycle
                creators = await refresh_creators_cache()
            
            youtube_creators = [c for c in creators if c[6]]  # Has youtube_username
            
            if not youtube_creators:
                await asyncio.sleep(300)  # Wait 5 minutes if no YouTube creators
                continue
            
            platform_task_heartbeats['youtube'] = datetime.now()
            logger.debug(f"📺 Checking {len(youtube_creators)} YouTube creators")
            
            for creator in youtube_creators:
                creator_id, discord_user_id, username, streamer_type, channel_id, twitch_user, youtube_user, tiktok_user = creator
                
                try:
                    # Check if user is live using the imported youtube_api
                    stream_info = await youtube_api.get_stream_info(youtube_user)
                    
                    if stream_info and stream_info.get('is_live'):
                        logger.info(f"📺 {youtube_user} is LIVE on YouTube!")
                        # Trigger notification through coordinator
                        await platform_notification_coordinator(
                            creator_id, discord_user_id, username, streamer_type, 
                            channel_id, 'youtube', youtube_user, stream_info
                        )
                    else:
                        # Handle offline status too
                        offline_info = {'is_live': False}
                        await platform_notification_coordinator(
                            creator_id, discord_user_id, username, streamer_type, 
                            channel_id, 'youtube', youtube_user, offline_info
                        )
                    
                except Exception as e:
                    logger.error(f"📺 Error checking YouTube user {youtube_user}: {e}")
                
                # Small delay between checks to avoid rate limits
                await asyncio.sleep(3)
            
            # YouTube checks less frequently (5 minutes)
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"📺 Error in enhanced YouTube platform task: {e}")
            await asyncio.sleep(60)  # Wait before retrying on error

async def enhanced_tiktok_platform_task(db, bot, creators):
    """Enhanced TikTok platform task with notification coordination"""
    logger.info("🎵 Enhanced TikTok platform task started")
    
    while True:
        try:
            # Refresh creators periodically
            if random.randint(1, 10) == 1:  # 10% chance each cycle
                creators = await refresh_creators_cache()
            
            tiktok_creators = [c for c in creators if c[7]]  # Has tiktok_username
            
            if not tiktok_creators:
                await asyncio.sleep(180)  # Wait 3 minutes if no TikTok creators
                continue
            
            platform_task_heartbeats['tiktok'] = datetime.now()
            logger.debug(f"🎵 Checking {len(tiktok_creators)} TikTok creators")
            
            for creator in tiktok_creators:
                creator_id, discord_user_id, username, streamer_type, channel_id, twitch_user, youtube_user, tiktok_user = creator
                
                try:
                    # Check if user is live using the imported improved_tiktok_checker
                    stream_info = await improved_tiktok_checker.is_user_live(tiktok_user)
                    
                    if stream_info and stream_info.get('is_live'):
                        logger.info(f"🎵 {tiktok_user} is LIVE on TikTok!")
                        # Trigger notification through coordinator
                        await platform_notification_coordinator(
                            creator_id, discord_user_id, username, streamer_type, 
                            channel_id, 'tiktok', tiktok_user, stream_info
                        )
                    else:
                        # Handle offline status too
                        offline_info = {'is_live': False}
                        await platform_notification_coordinator(
                            creator_id, discord_user_id, username, streamer_type, 
                            channel_id, 'tiktok', tiktok_user, offline_info
                        )
                    
                except Exception as e:
                    logger.error(f"🎵 Error checking TikTok user {tiktok_user}: {e}")
                
                # Small delay between checks to avoid rate limits
                await asyncio.sleep(2)
            
            # TikTok checks every 3 minutes
            await asyncio.sleep(180)
            
        except Exception as e:
            logger.error(f"🎵 Error in enhanced TikTok platform task: {e}")
            await asyncio.sleep(30)  # Wait before retrying on error

# ========== LEGACY SYSTEM (kept for compatibility) ==========

async def individual_creator_task(creator_data):
    """Individual task for monitoring one creator across all platforms"""
    creator_id, discord_user_id, username, streamer_type, channel_id, twitch_user, youtube_user, tiktok_user = creator_data
    
    # Determine check interval based on streamer type
    if streamer_type == 'karma':
        check_interval = Config.KARMA_CHECK_INTERVAL  # 1 minute
    else:
        check_interval = Config.REGULAR_CHECK_INTERVAL  # 3 minutes
    
    logger.info(f"🎯 Starting individual task for {username} ({streamer_type}) - checking every {check_interval}s")
    
    while True:
        try:
            # Update heartbeat BEFORE check starts
            creator_heartbeats[creator_id] = datetime.now()
            
            logger.debug(f"🔍 Checking creator {username} ({streamer_type})")
            
            # Wrap check in timeout to prevent hanging (max 90 seconds)
            timeout_duration = 90  # Maximum time for a complete platform check
            try:
                await asyncio.wait_for(
                    check_creator_platforms(creator_id, discord_user_id, username, streamer_type, channel_id, twitch_user, youtube_user, tiktok_user),
                    timeout=timeout_duration
                )
            except asyncio.TimeoutError:
                logger.error(f"⏱️ TIMEOUT: Creator check for {username} exceeded {timeout_duration}s - skipping this cycle")
            
            # Update heartbeat AFTER successful check
            creator_heartbeats[creator_id] = datetime.now()
            
            # Wait for next check
            await asyncio.sleep(check_interval)
            
        except asyncio.CancelledError:
            logger.info(f"🛑 Task cancelled for creator {username}")
            # Clean up heartbeat on cancellation
            if creator_id in creator_heartbeats:
                del creator_heartbeats[creator_id]
            break
        except Exception as e:
            logger.error(f"❌ Error in individual task for {username}: {e}")
            # Update heartbeat even after error to show task is still alive
            creator_heartbeats[creator_id] = datetime.now()
            # Wait a bit before retrying to avoid spam
            await asyncio.sleep(30)

async def start_individual_creator_tasks():
    """Start individual tasks for all creators"""
    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Get all creators
        cursor.execute('SELECT id, discord_user_id, discord_username, streamer_type, notification_channel_id, twitch_username, youtube_username, tiktok_username FROM creators')
        creators = cursor.fetchall()
        
        logger.info(f"🚀 Starting {len(creators)} individual creator tasks...")
        
        for creator in creators:
            creator_id, discord_user_id, username, streamer_type, channel_id, twitch_user, youtube_user, tiktok_user = creator
            
            # Cache creator data for potential restarts
            creator_data_cache[creator_id] = creator
            
            # Initialize heartbeat
            creator_heartbeats[creator_id] = datetime.now()
            
            # Create individual task for this creator
            task = asyncio.create_task(individual_creator_task(creator))
            creator_tasks[creator_id] = task
            
            # Small delay between starting tasks to prevent thundering herd
            await asyncio.sleep(2)
        
        logger.info(f"✅ Successfully started {len(creator_tasks)} individual creator tasks")
        
    except Exception as e:
        logger.error(f"❌ Error starting individual creator tasks: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

async def restart_creator_task(creator_id, reason="manual"):
    """Restart task for a specific creator (useful when creator data changes)"""
    # Cancel existing task if it exists
    if creator_id in creator_tasks:
        creator_tasks[creator_id].cancel()
        try:
            await asyncio.wait_for(creator_tasks[creator_id], timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        del creator_tasks[creator_id]
        logger.info(f"🔄 Cancelled old task for creator {creator_id} (reason: {reason})")
    
    # Get updated creator data
    conn = None
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, discord_user_id, discord_username, streamer_type, notification_channel_id, twitch_username, youtube_username, tiktok_username FROM creators WHERE id = ?', (creator_id,))
        creator = cursor.fetchone()
        
        if creator:
            # Update cache
            creator_data_cache[creator_id] = creator
            
            # Reset heartbeat
            creator_heartbeats[creator_id] = datetime.now()
            
            # Start new task
            task = asyncio.create_task(individual_creator_task(creator))
            creator_tasks[creator_id] = task
            logger.info(f"✅ Restarted task for creator {creator[2]} (ID: {creator_id})")
        else:
            logger.warning(f"⚠️ Creator {creator_id} not found for restart")
    
    except Exception as e:
        logger.error(f"❌ Error restarting creator task {creator_id}: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

async def watchdog_task():
    """Watchdog task that monitors all creator tasks and restarts hung tasks"""
    logger.info("🐕 Watchdog task started - monitoring all creator tasks for hangs")
    
    # Wait a bit before starting to let tasks initialize
    await asyncio.sleep(60)
    
    while True:
        try:
            current_time = datetime.now()
            hung_tasks = []
            
            # Check each creator task
            for creator_id, last_heartbeat in list(creator_heartbeats.items()):
                # Get creator info for logging
                creator_info = creator_data_cache.get(creator_id)
                if not creator_info:
                    continue
                
                username = creator_info[2]  # discord_username
                streamer_type = creator_info[3]  # streamer_type
                
                # Determine expected check interval
                if streamer_type == 'karma':
                    check_interval = Config.KARMA_CHECK_INTERVAL
                else:
                    check_interval = Config.REGULAR_CHECK_INTERVAL
                
                # Maximum allowed time without heartbeat (3x check interval + 90s buffer for processing)
                max_allowed_time = check_interval * 3 + 90
                time_since_heartbeat = (current_time - last_heartbeat).total_seconds()
                
                # Check if task is hung
                if time_since_heartbeat > max_allowed_time:
                    logger.warning(f"⚠️ WATCHDOG: Task for {username} (ID: {creator_id}) appears hung - last heartbeat {time_since_heartbeat:.0f}s ago (max: {max_allowed_time}s)")
                    hung_tasks.append((creator_id, username, time_since_heartbeat))
                
                # Also check if task is still actually running
                if creator_id in creator_tasks:
                    task = creator_tasks[creator_id]
                    if task.done():
                        logger.warning(f"⚠️ WATCHDOG: Task for {username} (ID: {creator_id}) is unexpectedly done/crashed")
                        hung_tasks.append((creator_id, username, 0))
            
            # Restart hung tasks
            for creator_id, username, time_hung in hung_tasks:
                logger.error(f"🔄 WATCHDOG: Restarting hung task for {username} (ID: {creator_id}) - was hung for {time_hung:.0f}s")
                try:
                    await restart_creator_task(creator_id, reason=f"watchdog_restart_hung_{time_hung:.0f}s")
                except Exception as e:
                    logger.error(f"❌ WATCHDOG: Failed to restart task for {username}: {e}")
            
            if hung_tasks:
                logger.info(f"🐕 WATCHDOG: Restarted {len(hung_tasks)} hung task(s)")
            
            # Run watchdog check every 2 minutes
            await asyncio.sleep(120)
            
        except asyncio.CancelledError:
            logger.info("🐕 Watchdog task cancelled")
            break
        except Exception as e:
            logger.error(f"❌ Error in watchdog task: {e}")
            await asyncio.sleep(60)  # Wait before retrying

# Old central live_checker removed - using individual creator tasks for better stability

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
                # Use improved TikTok checker with image support
                logger.info(f"TikTok {platform_username}: Verwende verbesserte doppelte Verifikation...")
                result = await improved_tiktok_checker.is_user_live(platform_username)
                if result.get('is_live', False):
                    stream_info = result
                else:
                    stream_info = None
            
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
                    logger.info(f"🔍 Attempting to delete message ID {message_id} in channel {notification_channel_id} for {username} on {platform}")
                    try:
                        # Get the channel and delete the message
                        notification_channel = bot.get_channel(int(notification_channel_id))
                        if not notification_channel:
                            # Try to fetch channel as fallback for cache misses
                            try:
                                notification_channel = await asyncio.wait_for(bot.fetch_channel(int(notification_channel_id)), timeout=10.0)
                                logger.info(f"✅ Fetched notification channel {notification_channel_id} for {username} on {platform}")
                            except Exception as fetch_error:
                                logger.warning(f"Could not fetch notification channel {notification_channel_id} for {username} on {platform}: {fetch_error}")
                        
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
                                logger.info(f"Live notification message for {username} on {platform} was already deleted (Message ID: {message_id})")
                                message_deleted = True  # Message doesn't exist, so consider it "deleted"
                            except asyncio.TimeoutError:
                                logger.warning(f"Timeout while deleting live notification for {username} on {platform} (Message ID: {message_id}) - will retry later")
                            except Exception as delete_error:
                                logger.error(f"Failed to delete live notification for {username} on {platform} (Message ID: {message_id}): {delete_error} - will retry later")
                        else:
                            logger.warning(f"Notification channel {notification_channel_id} not found for {username} on {platform} - will retry later")
                    except Exception as e:
                        logger.error(f"Error during message deletion for {username} on {platform}: {e} - will retry later")
                else:
                    logger.info(f"ℹ️ No message to delete for {username} on {platform} (message_id or channel_id missing)")
                
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
                
                live_count = cursor.fetchone()[0]
                logger.info(f"🔍 {username} is live on {live_count} platform(s)")
                
                if live_count == 0:  # Not live on any platform
                    # Remove live role
                    logger.info(f"📍 Attempting to remove live role from {username} (Discord ID: {discord_user_id})")
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
                                logger.info(f"✅ Removed live role from {username}")
                            else:
                                logger.info(f"ℹ️ {username} doesn't have live role or role not found")
                        else:
                            logger.warning(f"⚠️ Could not find guild member for {username} (Discord ID: {discord_user_id})")
                    except Exception as e:
                        logger.error(f"❌ Error removing live role from {username}: {e}")
        
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
    
    # Add stream title if available
    stream_title = stream_info.get('title')
    if stream_title:
        embed.add_field(name="📝 Titel", value=stream_title, inline=False)
    
    # Add viewer count and game (check for None specifically, not truthiness, so 0 is displayed)
    viewer_count = stream_info.get('viewer_count')
    if viewer_count is not None:
        embed.add_field(name="👀 Zuschauer", value=f"{viewer_count:,}", inline=True)
    
    if stream_info.get('game_name'):
        embed.add_field(name="🎮 Spiel", value=stream_info['game_name'], inline=True)
    
    # Add follower/subscriber count for all platforms (check for None specifically, not truthiness)
    follower_count = stream_info.get('follower_count')
    if follower_count is not None and follower_count > 0:
        if platform == 'youtube':
            embed.add_field(name="📺 Abonnenten", value=f"{follower_count:,}", inline=True)
        else:  # twitch, tiktok
            embed.add_field(name="💖 Follower", value=f"{follower_count:,}", inline=True)
    
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

# Keep-Alive Task
@tasks.loop(minutes=10)
async def keep_alive_ping():
    """Ping self every 10 minutes to prevent cloud platform from sleeping"""
    try:
        # Get current port from environment
        port = int(os.getenv('PORT', 5000))
        
        # Use localhost with correct port
        ping_url = f"http://localhost:{port}/health"
        
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
        # Cleanup removed - improved_tiktok_checker handles its own session management
        
        # Exit with code 1 - Railway.com will automatically restart the bot
        # Note: Exit code 0 means "successful exit" and Railway won't restart
        # Exit code 1 means "restart needed" and Railway will restart automatically
        logger.info("🔄 AUTO-RESTART: Exiting with code 1 for automatic Railway restart...")
        os._exit(1)
        
    except Exception as e:
        logger.error(f"🚨 AUTO-RESTART ERROR: {e}")

async def post_logs_to_dev_channel(log_files_to_delete):
    """Post log files to dev channel before deletion - SECURE: Only to configured channels"""
    try:
        # SECURITY: Only upload to specifically configured channels - no fallbacks to other servers
        if not Config.DEV_CHANNEL_ID or not Config.MAIN_SERVER_ID:
            logger.warning("📁 LOG-BACKUP: DEV_CHANNEL_ID or MAIN_SERVER_ID not configured - skipping log backup for security")
            return
        
        # Get the main server (must be configured)
        main_guild = bot.get_guild(Config.MAIN_SERVER_ID)
        if not main_guild:
            logger.warning(f"📁 LOG-BACKUP: Main server {Config.MAIN_SERVER_ID} not found - skipping log backup")
            return
        
        # Get the dev channel (must be configured and exist)
        dev_channel = main_guild.get_channel(Config.DEV_CHANNEL_ID)
        if not dev_channel:
            logger.warning(f"📁 LOG-BACKUP: Dev channel {Config.DEV_CHANNEL_ID} not found in main server - skipping log backup")
            return
        
        # Verify bot has required permissions
        permissions = dev_channel.permissions_for(main_guild.me)
        if not permissions.send_messages or not permissions.attach_files:
            logger.warning(f"📁 LOG-BACKUP: Missing permissions in dev channel {dev_channel.name} - skipping log backup")
            return
        
        logger.info(f"📁 LOG-BACKUP: Using secure dev channel {dev_channel.name} in {main_guild.name}")
        
        if not log_files_to_delete:
            logger.info("📁 LOG-BACKUP: No log files to backup")
            return
        
        logger.info(f"📁 LOG-BACKUP: Backing up {len(log_files_to_delete)} log files to dev channel {dev_channel.name}...")
        
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
@tasks.loop(minutes=10)
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
                            new_name = f"👤DISCORD MEMBER: {current_count}"
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
        
        # Session management now handled by improved_tiktok_checker
        logger.info("🔧 TIKTOK-RECOVERY: Using improved TikTok checker")
        
        # Test TikTok connectivity with a quick check
        recovery_success = 0
        recovery_failed = 0
        
        for creator_id, username, tiktok_user in tiktok_creators[:3]:  # Test only first 3 to avoid rate limits
            try:
                logger.info(f"🔧 Testing TikTok connectivity for {username} (@{tiktok_user})...")
                
                # Quick connectivity test with timeout
                test_result = await asyncio.wait_for(
                    improved_tiktok_checker.is_user_live(tiktok_user),
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
        
        # Cache management now handled by improved_tiktok_checker  
        logger.info("🔧 TIKTOK-RECOVERY: Cache management handled by improved checker")
        
        conn.close()
        
        logger.info(f"🔧 TIKTOK-RECOVERY: Completed - Success: {recovery_success}, Failed: {recovery_failed}")
        
    except Exception as e:
        logger.error(f"🚨 TIKTOK-RECOVERY ERROR: {e}")

# Live Notification Cleanup Task - Check every 15 minutes
@tasks.loop(minutes=15)
async def live_notification_cleanup_task():
    """Check and delete orphaned live notification messages"""
    try:
        logger.info("🧹 NOTIFICATION-CLEANUP: Starting notification cleanup check...")
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Find all live_status entries that are not live but still have message IDs
        cursor.execute('''
            SELECT ls.creator_id, ls.platform, ls.message_id, ls.notification_channel_id, c.discord_username
            FROM live_status ls
            JOIN creators c ON ls.creator_id = c.id
            WHERE ls.is_live = FALSE 
            AND ls.message_id IS NOT NULL 
            AND ls.notification_channel_id IS NOT NULL
        ''')
        
        orphaned_messages = cursor.fetchall()
        
        if not orphaned_messages:
            logger.info("🧹 NOTIFICATION-CLEANUP: No orphaned messages found")
            conn.close()
            return
        
        logger.info(f"🧹 Found {len(orphaned_messages)} orphaned notification messages")
        
        deleted_count = 0
        failed_count = 0
        
        for creator_id, platform, message_id, channel_id, username in orphaned_messages:
            try:
                # Try to fetch and delete the message
                notification_channel = bot.get_channel(int(channel_id))
                if not notification_channel:
                    try:
                        notification_channel = await asyncio.wait_for(
                            bot.fetch_channel(int(channel_id)), 
                            timeout=10.0
                        )
                    except Exception:
                        logger.warning(f"🧹 Channel {channel_id} not found for {username} on {platform}")
                        # Clear the message_id from database even if channel not found
                        cursor.execute('''
                            UPDATE live_status 
                            SET message_id = NULL, notification_channel_id = NULL 
                            WHERE creator_id = ? AND platform = ?
                        ''', (creator_id, platform))
                        conn.commit()
                        continue
                
                if notification_channel:
                    try:
                        message_to_delete = await asyncio.wait_for(
                            notification_channel.fetch_message(int(message_id)), 
                            timeout=10.0
                        )
                        await asyncio.wait_for(message_to_delete.delete(), timeout=10.0)
                        deleted_count += 1
                        logger.info(f"✅ Deleted orphaned notification for {username} on {platform} (Message ID: {message_id})")
                        
                        # Clear message_id from database
                        cursor.execute('''
                            UPDATE live_status 
                            SET message_id = NULL, notification_channel_id = NULL 
                            WHERE creator_id = ? AND platform = ?
                        ''', (creator_id, platform))
                        conn.commit()
                        
                    except discord.NotFound:
                        logger.info(f"🧹 Message already deleted for {username} on {platform}")
                        # Clear message_id from database
                        cursor.execute('''
                            UPDATE live_status 
                            SET message_id = NULL, notification_channel_id = NULL 
                            WHERE creator_id = ? AND platform = ?
                        ''', (creator_id, platform))
                        conn.commit()
                        deleted_count += 1
                        
                    except Exception as delete_error:
                        logger.error(f"❌ Failed to delete notification for {username} on {platform}: {delete_error}")
                        failed_count += 1
            
            except Exception as cleanup_error:
                logger.error(f"❌ Error cleaning up notification for {username} on {platform}: {cleanup_error}")
                failed_count += 1
        
        conn.close()
        
        logger.info(f"🧹 NOTIFICATION-CLEANUP: Completed - Deleted {deleted_count} messages, Failed {failed_count}")
        
    except Exception as e:
        logger.error(f"🚨 NOTIFICATION-CLEANUP ERROR: {e}")

# Live Role Cleanup Task - Check every 10 minutes
@tasks.loop(minutes=10)
async def live_role_cleanup_task():
    """Check and remove live roles from users who are not actually live on any platform"""
    try:
        logger.info("🎭 LIVE-ROLE-CLEANUP: Starting live role cleanup check...")
        
        if not Config.LIVE_ROLE:
            logger.info("🎭 LIVE-ROLE-CLEANUP: No live role configured - skipping")
            return
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        removed_roles = 0
        checked_users = 0
        
        # Check each guild
        for guild in bot.guilds:
            try:
                live_role = guild.get_role(Config.LIVE_ROLE)
                if not live_role:
                    continue
                
                # Get all members with live role
                members_with_role = live_role.members
                logger.info(f"🎭 Found {len(members_with_role)} members with live role in {guild.name}")
                
                for member in members_with_role:
                    checked_users += 1
                    try:
                        # Check if user is actually live on any platform
                        cursor.execute('''
                            SELECT COUNT(*) FROM live_status ls
                            JOIN creators c ON ls.creator_id = c.id
                            WHERE c.discord_user_id = ? AND ls.is_live = TRUE
                        ''', (str(member.id),))
                        
                        live_count = cursor.fetchone()[0]
                        
                        if live_count == 0:
                            # User has role but is not live - remove role
                            await member.remove_roles(live_role)
                            removed_roles += 1
                            logger.info(f"✅ Removed live role from {member.display_name} (not live on any platform)")
                        else:
                            logger.debug(f"✓ {member.display_name} has live role and is live on {live_count} platform(s)")
                    
                    except Exception as member_error:
                        logger.error(f"❌ Error checking member {member.display_name}: {member_error}")
            
            except Exception as guild_error:
                logger.error(f"❌ Error processing guild {guild.name}: {guild_error}")
        
        conn.close()
        
        logger.info(f"🎭 LIVE-ROLE-CLEANUP: Completed - Checked {checked_users} users, removed {removed_roles} stale roles")
        
    except Exception as e:
        logger.error(f"🚨 LIVE-ROLE-CLEANUP ERROR: {e}")

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
    
    # ========== NEW MODULAR PLATFORM TASK SYSTEM ==========
    
    # Start the new modular platform tasks (improved stability and performance)
    logger.info("🚀 Starting NEW modular platform task system...")
    await start_new_platform_tasks()
    
    # Keep legacy system available for comparison (but don't start it)
    # await start_individual_creator_tasks()  # OLD SYSTEM - REPLACED
    
    # Staggered startup to avoid overlaps:
    # Delay each task by 30 seconds to prevent simultaneous execution
    
    async def start_tasks_with_delays():
        """Start background tasks with staggered delays to optimize performance"""
        await asyncio.sleep(30)  # 30s delay
        status_rotator.start()
        logger.info("🤖 Status rotation started - cycling every 3 minutes (30s offset)")
        
        await asyncio.sleep(30)  # 60s total delay  
        stats_updater.start()
        logger.info("📊 Stats updater started - updating stats channels every 10 minutes (60s offset)")
        
        await asyncio.sleep(30)  # 90s total delay
        keep_alive_ping.start()
        logger.info("🔄 Keep-alive ping started - preventing cloud sleep every 10 minutes (90s offset)")
        
        await asyncio.sleep(30)  # 120s total delay
        social_media_stats_updater_task.start() 
        logger.info("📱 Social Media stats updater started - updating social media channels every 60 minutes (120s offset)")
        
        await asyncio.sleep(30)  # 150s total delay
        tiktok_recovery_task.start()
        logger.info("🔧 TikTok recovery task started - checking TikTok connectivity every 30 minutes (150s offset)")
        
        await asyncio.sleep(30)  # 180s total delay
        # Start watchdog task to monitor creator tasks
        asyncio.create_task(watchdog_task())
        logger.info("🐕 Watchdog task started - monitoring creator tasks for hangs every 2 minutes (180s offset)")
        
        await asyncio.sleep(30)  # 210s total delay
        auto_restart_task.start()
        logger.info("🔄 Auto-restart task started - restarting every 12 hours (210s offset)")
        
        await asyncio.sleep(30)  # 240s total delay
        log_cleanup_task.start()
        logger.info("🗑️ Log cleanup task started - cleaning logs every 6 hours (240s offset)")
        
        await asyncio.sleep(30)  # 270s total delay
        live_role_cleanup_task.start()
        logger.info("🎭 Live role cleanup task started - checking roles every 10 minutes (270s offset)")
        
        await asyncio.sleep(30)  # 300s total delay
        live_notification_cleanup_task.start()
        logger.info("🧹 Live notification cleanup task started - checking messages every 15 minutes (300s offset)")
        
        logger.info("⚡ All background tasks started with performance optimization (8 minutes total stagger)")
    
    # Start the staggered task startup in background
    asyncio.create_task(start_tasks_with_delays())
    logger.info("⚡ Performance-optimized task startup initiated - tasks will start over 7 minutes to prevent overlaps")
    
    # Initialize OpenAI Auto-Repair System
    global auto_repair_system
    auto_repair_system = OpenAIAutoRepair(bot, openai_api_key=Config.OPENAI_API_KEY, dev_channel_id=Config.DEV_CHANNEL_ID)
    if auto_repair_system.openai_client:
        logger.info("🤖 OpenAI Auto-Repair System ready for scraping failures")
    else:
        logger.warning("🤖 OpenAI Auto-Repair System disabled - check API key configuration")
    
    # Import and add command cogs (pass DatabaseManager class)
    import commands
    import event_commands
    
    # Set DatabaseManager in modules to avoid class conflicts
    commands.DatabaseManager = DatabaseManager
    event_commands.DatabaseManager = DatabaseManager
    
    from commands import CreatorManagement, UserCommands, ServerManagement
    from event_commands import EventCommands, UtilityCommands
    from custom_commands import CustomCommands
    from giveaway_commands import GiveawayCommands
    from welcome_commands import WelcomeCommands
    
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
    logger.info("Adding CustomCommands cog...")
    await bot.add_cog(CustomCommands(bot, db))
    logger.info("Adding GiveawayCommands cog...")
    await bot.add_cog(GiveawayCommands(bot, db))
    logger.info("Adding WelcomeCommands cog...")
    await bot.add_cog(WelcomeCommands(bot, db))
    
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
            
            # Register custom commands for this guild
            custom_commands_cog = bot.get_cog('CustomCommands')
            if custom_commands_cog:
                await custom_commands_cog.register_guild_commands(guild.id)
            
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
    """Create a simple HTTP server for health checks"""
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
    port = int(os.getenv('PORT', 5000))
    
    # Start server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"🌐 HTTP server started on port {port} for health checks")
    return runner

async def main():
    """Main function to run both Discord bot and HTTP server"""
    if not Config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN not found in environment variables")
        exit(1)
    
    logger.info("Starting KARMA-LiveBOT...")
    
    # Start HTTP server for health checks
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
        # Cleanup removed - improved_tiktok_checker handles its own session management
        await bot.close()

if __name__ == '__main__':
    # Run the async main function
    asyncio.run(main())
