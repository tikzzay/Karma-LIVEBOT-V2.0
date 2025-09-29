#!/usr/bin/env python3
"""
YouTube Platform Module for KARMA-LiveBOT
Handles all YouTube API interactions and live stream checking
"""

import os
import asyncio
import logging
import time
import re
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import aiohttp

logger = logging.getLogger('KARMA-LiveBOT.YouTube')

class YouTubeAPI:
    """YouTube API manager for stream info and subscriber data"""
    
    def __init__(self):
        self.api_key = os.getenv('YOUTUBE_API_KEY')
        self.cache = {}  # Cache für API-Responses
        self.cache_duration = 300  # 5 Minuten Cache
        self.scrape_cache = {}  # Cache für Scraping-Results
        self.scrape_cache_duration = 60  # 1 Minute Cache für Scraping
        self.quota_backoff = {}  # Backoff für Quota-exceeded per user
        self.quota_backoff_duration = 1800  # 30 Minuten Backoff
    
    async def quick_live_check(self, username: str) -> bool:
        """Quick live check via web scraping - saves API quota"""
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
                                        yt_data = json.loads(ytdata_match.group(1))
                                        # Search for live indicators in the data
                                        yt_data_str = json.dumps(yt_data).lower()
                                        
                                        live_patterns = [
                                            '"isbadgelive":true',
                                            '"style":"LIVE"',
                                            '"liveBadge"',
                                            '"isLive":true',
                                            '"liveBroadcastContent":"live"'
                                        ]
                                        
                                        for pattern in live_patterns:
                                            if pattern in yt_data_str:
                                                live_indicators_found += 1
                                                logger.debug(f"YouTube {username}: Found live indicator: {pattern}")
                                    except json.JSONDecodeError:
                                        logger.debug(f"YouTube {username}: Failed to parse ytInitialData")
                                
                                # Fallback: direct HTML pattern matching
                                if live_indicators_found == 0:
                                    html_lower = html.lower()
                                    fallback_patterns = [
                                        r'"style":\s*"live"',
                                        r'"isbadgelive":\s*true',
                                        r'"liveBroadcastContent":\s*"live"',
                                        r'watching now',
                                        r'started streaming'
                                    ]
                                    
                                    for pattern in fallback_patterns:
                                        if re.search(pattern, html_lower):
                                            live_indicators_found += 1
                                            logger.debug(f"YouTube {username}: Found fallback live indicator")
                                
                                is_live = live_indicators_found >= 2  # Require 2+ indicators for confidence
                                
                                # Cache the result
                                self.scrape_cache[scrape_key] = {
                                    'is_live': is_live,
                                    'timestamp': current_time
                                }
                                
                                if is_live:
                                    logger.info(f"YouTube {username}: Quick check indicates LIVE (indicators: {live_indicators_found})")
                                else:
                                    logger.info(f"YouTube {username}: Quick check indicates offline (indicators: {live_indicators_found})")
                                
                                return is_live
                                
                    except asyncio.TimeoutError:
                        logger.debug(f"YouTube {username}: Timeout for URL {url}")
                        continue
                    except Exception as e:
                        logger.debug(f"YouTube {username}: Error for URL {url}: {e}")
                        continue
            
            # If all URLs failed, cache negative result
            self.scrape_cache[scrape_key] = {
                'is_live': False,
                'timestamp': current_time
            }
            logger.info(f"YouTube {username}: Quick check failed - assuming offline")
            return False
            
        except Exception as e:
            logger.error(f"YouTube {username}: Quick live check error: {e}")
            return False

    async def get_stream_info(self, username: str) -> Optional[Dict]:
        """Get stream information for a YouTube user using smart polling"""
        # Check quota backoff first
        if username in self.quota_backoff:
            backoff_until = self.quota_backoff[username]
            if time.time() < backoff_until:
                logger.info(f"YouTube {username}: In quota backoff until {datetime.fromtimestamp(backoff_until)}")
                return {'is_live': False, 'method': 'quota_backoff'}
        
        # Phase 1: Quick live check via scraping
        is_live_scraping = await self.quick_live_check(username)
        
        if not is_live_scraping:
            # If scraping says offline, trust it and save API quota
            return {'is_live': False, 'method': 'scraping_offline'}
        
        # Phase 2: User appears live via scraping, use API for details
        if not self.api_key:
            logger.warning(f"YouTube API key missing for {username} - using scraping result only")
            return {
                'is_live': True,
                'method': 'scraping_only',
                'viewer_count': 0,
                'title': f'{username} Live Stream',
                'thumbnail_url': '',
                'profile_image_url': '',
                'platform_url': f'https://www.youtube.com/@{username}/live'
            }
        
        # Check cache
        cache_key = f"youtube_api_{username}"
        current_time = time.time()
        
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if current_time - cached_data['timestamp'] < self.cache_duration:
                logger.info(f"Using cached YouTube API data for {username}")
                return cached_data['data']
        
        try:
            # API call to get detailed stream info
            search_url = 'https://www.googleapis.com/youtube/v3/search'
            params = {
                'part': 'snippet',
                'channelId': '',  # We'll need to resolve this
                'eventType': 'live',
                'type': 'video',
                'key': self.api_key
            }
            
            # First resolve channel ID from username
            channel_id = await self._resolve_channel_id(username)
            if not channel_id:
                logger.warning(f"Could not resolve channel ID for {username}")
                return {'is_live': False, 'method': 'channel_not_found'}
            
            params['channelId'] = channel_id
            
            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, params=params) as response:
                    if response.status == 403:
                        # Quota exceeded
                        logger.warning(f"YouTube API quota exceeded for {username}")
                        self.quota_backoff[username] = time.time() + self.quota_backoff_duration
                        return {'is_live': True, 'method': 'quota_exceeded_fallback'}
                    
                    if response.status == 200:
                        data = await response.json()
                        if data.get('items'):
                            # Live stream found
                            video = data['items'][0]
                            video_id = video['id']['videoId']
                            
                            # Get additional details
                            video_details = await self._get_video_details(video_id)
                            
                            result = {
                                'is_live': True,
                                'viewer_count': video_details.get('concurrent_viewers', 0),
                                'title': video['snippet']['title'],
                                'thumbnail_url': video['snippet']['thumbnails'].get('high', {}).get('url', ''),
                                'profile_image_url': video['snippet']['thumbnails'].get('default', {}).get('url', ''),
                                'platform_url': f'https://www.youtube.com/watch?v={video_id}',
                                'method': 'api_confirmed'
                            }
                            
                            # Cache the result
                            self.cache[cache_key] = {
                                'data': result,
                                'timestamp': current_time
                            }
                            
                            return result
                        else:
                            # No live stream found via API (but scraping said live)
                            return {'is_live': False, 'method': 'api_no_live_found'}
                    else:
                        logger.error(f"YouTube API error for {username}: {response.status}")
                        return {'is_live': False, 'method': 'api_error'}
        
        except Exception as e:
            logger.error(f"YouTube API error for {username}: {e}")
            # Return cached data if available
            if cache_key in self.cache:
                return self.cache[cache_key]['data']
            # Fallback to scraping result
            return {'is_live': False, 'method': 'api_exception', 'error': str(e)}

    async def _resolve_channel_id(self, username: str) -> Optional[str]:
        """Resolve YouTube channel ID from username"""
        if not self.api_key:
            return None
        
        try:
            # Try different methods to resolve channel ID
            methods = [
                ('forHandle', f'@{username}' if not username.startswith('@') else username),
                ('forUsername', username.replace('@', '')),
            ]
            
            async with aiohttp.ClientSession() as session:
                for method_name, search_term in methods:
                    url = 'https://www.googleapis.com/youtube/v3/channels'
                    params = {
                        'part': 'id',
                        method_name: search_term,
                        'key': self.api_key
                    }
                    
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get('items'):
                                return data['items'][0]['id']
            
            return None
            
        except Exception as e:
            logger.error(f"Error resolving channel ID for {username}: {e}")
            return None

    async def _get_video_details(self, video_id: str) -> Dict:
        """Get detailed video information"""
        if not self.api_key:
            return {}
        
        try:
            url = 'https://www.googleapis.com/youtube/v3/videos'
            params = {
                'part': 'statistics,liveStreamingDetails',
                'id': video_id,
                'key': self.api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('items'):
                            video = data['items'][0]
                            live_details = video.get('liveStreamingDetails', {})
                            
                            return {
                                'concurrent_viewers': int(live_details.get('concurrentViewers', 0))
                            }
            
            return {}
            
        except Exception as e:
            logger.error(f"Error getting video details for {video_id}: {e}")
            return {}

async def validate_youtube_username(username: str) -> bool:
    """Validate if a YouTube username exists"""
    youtube_api = YouTubeAPI()
    
    if not youtube_api.api_key:
        logger.warning("YouTube API key not available for validation")
        return True  # Assume valid if we can't check
    
    try:
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
        
    except Exception as e:
        logger.error(f"Error validating YouTube username {username}: {e}")
        return True  # Assume valid on error

# Global instance
youtube_api = YouTubeAPI()

# Task function for YouTube platform checking
async def youtube_platform_task(db, bot, creators):
    """Background task for checking YouTube streams"""
    logger.info("📺 Starting YouTube platform task")
    
    while True:
        try:
            youtube_creators = [c for c in creators if c[6]]  # Has youtube_username
            
            if not youtube_creators:
                await asyncio.sleep(60)  # Wait 1 minute if no YouTube creators
                continue
            
            logger.info(f"📺 Checking {len(youtube_creators)} YouTube creators")
            
            for creator in youtube_creators:
                creator_id, discord_user_id, username, streamer_type, channel_id, twitch_user, youtube_user, tiktok_user = creator
                
                try:
                    # Check if user is live
                    stream_info = await youtube_api.get_stream_info(youtube_user)
                    
                    if stream_info and stream_info.get('is_live'):
                        logger.info(f"📺 {youtube_user} is LIVE on YouTube!")
                        # Here you would call handle_stream_status or similar notification logic
                        # This will be handled by the main bot coordination
                    else:
                        logger.debug(f"📺 {youtube_user} is offline on YouTube")
                    
                except Exception as e:
                    logger.error(f"📺 Error checking YouTube user {youtube_user}: {e}")
                
                # Small delay between checks to avoid rate limits
                await asyncio.sleep(2)
            
            # Wait based on streamer type intervals
            # For now, use 5 minutes as a reasonable default (YouTube changes less frequently)
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"📺 Error in YouTube platform task: {e}")
            await asyncio.sleep(30)  # Wait before retrying on error