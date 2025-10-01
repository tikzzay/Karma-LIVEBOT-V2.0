#!/usr/bin/env python3
"""
Stats Module for KARMA-LiveBOT
Handles social media follower statistics and server statistics
"""

import os
import asyncio
import logging
import time
import re
from datetime import datetime
from typing import Optional, Dict
import aiohttp
import discord

logger = logging.getLogger('KARMA-LiveBOT.Stats')

class SocialMediaAPIs:
    """Manager for all social media platform APIs"""
    
    def __init__(self):
        self.youtube_api_key = os.getenv('YOUTUBE_API_KEY')
        self.twitch_client_id = os.getenv('TWITCH_CLIENT_ID')
        self.twitch_client_secret = os.getenv('TWITCH_CLIENT_SECRET')
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
            if platform in ['x', 'twitter']:
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
    
    async def _get_twitter_followers(self, username: str) -> Optional[int]:
        """Get Twitter/X follower count via web scraping only"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            # Try both twitter.com and x.com
            urls = [
                f"https://x.com/{username}",
                f"https://twitter.com/{username}"
            ]
            
            async with aiohttp.ClientSession() as session:
                for url in urls:
                    try:
                        async with session.get(url, headers=headers) as response:
                            if response.status == 200:
                                text = await response.text()
                                patterns = [
                                    r'"followers_count":(\d+)',
                                    r'(\d+(?:,\d+)*)\s+Followers',
                                    r'(\d+(?:\.\d+)?[KM]?)\s+Followers'
                                ]
                                
                                for pattern in patterns:
                                    match = re.search(pattern, text, re.IGNORECASE)
                                    if match:
                                        follower_str = match.group(1)
                                        if 'K' in follower_str:
                                            return int(float(follower_str.replace('K', '')) * 1000)
                                        elif 'M' in follower_str:
                                            return int(float(follower_str.replace('M', '')) * 1000000)
                                        else:
                                            return int(follower_str.replace(',', ''))
                    except Exception as e:
                        logger.debug(f"Failed to scrape {url}: {e}")
                        continue
            
            return None
            
        except Exception as e:
            logger.error(f"Twitter web scraping error for {username}: {e}")
            return None
    
    async def _get_youtube_subscribers(self, username: str) -> Optional[int]:
        """Get YouTube subscriber count via API"""
        if not self.youtube_api_key:
            logger.warning("YouTube API key not configured")
            return None
        
        try:
            # Try different methods to get channel info
            base_url = 'https://www.googleapis.com/youtube/v3/channels'
            
            methods = [
                ('forHandle', f'@{username}' if not username.startswith('@') else username),
                ('forUsername', username.replace('@', '')),
                ('id', username)  # In case it's a channel ID
            ]
            
            async with aiohttp.ClientSession() as session:
                for method, search_term in methods:
                    params = {
                        'part': 'statistics',
                        method: search_term,
                        'key': self.youtube_api_key
                    }
                    
                    async with session.get(base_url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get('items'):
                                stats = data['items'][0].get('statistics', {})
                                return int(stats.get('subscriberCount', 0))
            
            return None
            
        except Exception as e:
            logger.error(f"YouTube API error for {username}: {e}")
            return None
    
    async def _get_tiktok_followers(self, username: str) -> Optional[int]:
        """Get TikTok follower count via web scraping"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            async with aiohttp.ClientSession() as session:
                url = f"https://www.tiktok.com/@{username}"
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        text = await response.text()
                        # Look for follower count in TikTok's JSON data
                        patterns = [
                            r'"followerCount":(\d+)',
                            r'"stats":\s*{\s*"followerCount":\s*(\d+)',
                            r'followers.*?(\d+(?:\.\d+)?[KM]?)'
                        ]
                        
                        for pattern in patterns:
                            match = re.search(pattern, text)
                            if match:
                                follower_str = match.group(1)
                                if 'K' in follower_str:
                                    return int(float(follower_str.replace('K', '')) * 1000)
                                elif 'M' in follower_str:
                                    return int(float(follower_str.replace('M', '')) * 1000000)
                                else:
                                    return int(follower_str)
            
            return None
            
        except Exception as e:
            logger.error(f"TikTok scraping error for {username}: {e}")
            return None
    
    async def _get_twitch_followers(self, username: str) -> Optional[int]:
        """Get Twitch follower count via official API"""
        if not self.twitch_client_id or not self.twitch_client_secret:
            logger.warning("Twitch API credentials not configured")
            return None
            
        try:
            # Import TwitchAPI from our twitch module
            from twitch import twitch_api
            return await twitch_api.get_follower_count(username)
            
        except Exception as e:
            logger.error(f"Twitch API error for {username}: {e}")
            return None

class SocialMediaScrapingOnlyAPIs:
    """Scraping-only social media APIs to avoid API rate limits"""
    
    def __init__(self):
        self.cache = {}
        self.cache_duration = 600  # 10 minutes cache for scraping
    
    async def get_follower_count_scraping_only(self, platform: str, username: str) -> Optional[int]:
        """Get follower count using only web scraping methods"""
        cache_key = f"scrape_{platform}_{username}"
        current_time = time.time()
        
        # Check cache first
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if current_time - cached_data['timestamp'] < self.cache_duration:
                logger.info(f"Using cached scraping data for {platform}/{username}: {cached_data['count']}")
                return cached_data['count']
        
        try:
            count = None
            
            if platform in ['x', 'twitter']:
                count = await self._scrape_twitter_followers(username)
            elif platform == 'youtube':
                count = await self._scrape_youtube_subscribers(username)
            elif platform == 'tiktok':
                count = await self._scrape_tiktok_followers(username)
            elif platform == 'twitch':
                count = await self._scrape_twitch_followers(username)
            
            if count is not None:
                # Cache the result
                self.cache[cache_key] = {
                    'count': count,
                    'timestamp': current_time
                }
                logger.info(f"✅ Scraped {platform} followers for {username}: {count:,}")
                return count
            else:
                logger.warning(f"❌ Failed to scrape {platform} followers for {username}")
                return None
                
        except Exception as e:
            logger.error(f"Error scraping {platform} followers for {username}: {e}")
            return None
    
    async def _scrape_twitter_followers(self, username: str) -> Optional[int]:
        """Scrape Twitter/X follower count"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            # Try both twitter.com and x.com
            urls = [
                f"https://x.com/{username}",
                f"https://twitter.com/{username}"
            ]
            
            async with aiohttp.ClientSession() as session:
                for url in urls:
                    try:
                        async with session.get(url, headers=headers) as response:
                            if response.status == 200:
                                text = await response.text()
                                patterns = [
                                    r'"followers_count":(\d+)',
                                    r'(\d+(?:,\d+)*)\s+Followers',
                                    r'(\d+(?:\.\d+)?[KM]?)\s+Followers'
                                ]
                                
                                for pattern in patterns:
                                    match = re.search(pattern, text, re.IGNORECASE)
                                    if match:
                                        follower_str = match.group(1)
                                        if 'K' in follower_str:
                                            return int(float(follower_str.replace('K', '')) * 1000)
                                        elif 'M' in follower_str:
                                            return int(float(follower_str.replace('M', '')) * 1000000)
                                        else:
                                            return int(follower_str.replace(',', ''))
                    except Exception as e:
                        logger.debug(f"Failed to scrape {url}: {e}")
                        continue
            
            return None
            
        except Exception as e:
            logger.error(f"Twitter scraping error for {username}: {e}")
            return None
    
    async def _scrape_youtube_subscribers(self, username: str) -> Optional[int]:
        """Scrape YouTube subscriber count"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            urls = [
                f"https://www.youtube.com/@{username}/about",
                f"https://www.youtube.com/c/{username}/about",
                f"https://www.youtube.com/user/{username}/about",
                f"https://www.youtube.com/channel/{username}/about"
            ]
            
            async with aiohttp.ClientSession() as session:
                for url in urls:
                    try:
                        async with session.get(url, headers=headers) as response:
                            if response.status == 200:
                                text = await response.text()
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
                                        if subscriber_str.isdigit():
                                            return int(subscriber_str)
                    except Exception as e:
                        logger.debug(f"Failed to scrape {url}: {e}")
                        continue
            
            return None
            
        except Exception as e:
            logger.error(f"YouTube scraping error for {username}: {e}")
            return None
    
    async def _scrape_tiktok_followers(self, username: str) -> Optional[int]:
        """Scrape TikTok follower count"""
        try:
            # Import TikTok checker from our tiktok module
            from tiktok import improved_tiktok_checker
            
            # Use the HTML parsing from TikTok module
            result = await improved_tiktok_checker.check_html_parsing(username)
            return result.get("follower_count", 0) or None
            
        except Exception as e:
            logger.error(f"TikTok scraping error for {username}: {e}")
            return None
    
    async def _scrape_twitch_followers(self, username: str) -> Optional[int]:
        """Scrape Twitch follower count"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            async with aiohttp.ClientSession() as session:
                url = f"https://www.twitch.tv/{username}"
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        text = await response.text()
                        patterns = [
                            r'"followers":(\d+)',
                            r'"followerCount":(\d+)',
                            r'(\d+(?:,\d+)*)\s+[Ff]ollowers'
                        ]
                        
                        for pattern in patterns:
                            match = re.search(pattern, text)
                            if match:
                                return int(match.group(1).replace(',', ''))
            
            return None
            
        except Exception as e:
            logger.error(f"Twitch scraping error for {username}: {e}")
            return None

# Global instances
social_media_apis = SocialMediaAPIs()
social_media_scraping_apis = SocialMediaScrapingOnlyAPIs()

# Stats updater functions
async def stats_updater():
    """Update all server stats channels with current counts"""
    try:
        logger.info("📊 STATS-UPDATE: Starting server stats channels update...")
        
        # This function will be called from main.py with the bot and db instances
        # For now, just log that it would update stats
        logger.info("📊 STATS-UPDATE: Stats update function called")
        
    except Exception as e:
        logger.error(f"📊 STATS-UPDATE ERROR: {e}")

async def social_media_stats_updater():
    """Update all social media stats channels with current follower counts"""
    try:
        logger.info("📱 SOCIAL-MEDIA-UPDATE: Starting social media stats channels update...")
        
        # This function will be called from main.py with the bot and db instances
        # For now, just log that it would update social media stats
        logger.info("📱 SOCIAL-MEDIA-UPDATE: Social media stats update function called")
        
    except Exception as e:
        logger.error(f"📱 SOCIAL-MEDIA-UPDATE ERROR: {e}")

# Background task functions
async def stats_platform_task(db, bot):
    """Background task for updating server statistics"""
    logger.info("📊 Starting server stats platform task")
    
    while True:
        try:
            logger.info("📊 Running server stats update...")
            
            # Get stats channels from database
            conn = db.get_connection()
            cursor = conn.cursor()
            
            # Get all stats channels
            cursor.execute('SELECT guild_id, channel_id, counter_type, role_id, last_count FROM stats_channels')
            stats_channels = cursor.fetchall()
            
            if not stats_channels:
                logger.info("📊 No server stats channels configured")
                conn.close()
                await asyncio.sleep(300)  # 5 minutes
                continue
            
            # Group by guild for efficiency
            guilds_data = {}
            for guild_id, channel_id, counter_type, role_id, last_count in stats_channels:
                if guild_id not in guilds_data:
                    guilds_data[guild_id] = []
                guilds_data[guild_id].append({
                    'channel_id': channel_id,
                    'counter_type': counter_type,
                    'role_id': role_id,
                    'last_count': last_count
                })
            
            # Update each guild's stats
            for guild_id, channels in guilds_data.items():
                try:
                    guild = bot.get_guild(int(guild_id))
                    if not guild:
                        logger.warning(f"📊 Guild {guild_id} not found")
                        continue
                    
                    for channel_data in channels:
                        try:
                            channel = guild.get_channel(int(channel_data['channel_id']))
                            if not channel or not isinstance(channel, discord.VoiceChannel):
                                continue
                            
                            # Calculate current count based on counter type
                            current_count = 0
                            new_name = ""
                            
                            if channel_data['counter_type'] == 'members':
                                current_count = guild.member_count
                                new_name = f"👤 𝗗𝗜𝗦𝗖𝗢𝗥𝗗 𝗠𝗘𝗠𝗕𝗘𝗥: {current_count}"
                            elif channel_data['counter_type'] == 'online':
                                online_members = sum(1 for member in guild.members if member.status != discord.Status.offline)
                                current_count = online_members
                                new_name = f"🟢 𝗢𝗡𝗟𝗜𝗡𝗘 𝗠𝗘𝗠𝗕𝗘𝗥: {current_count}"
                            elif channel_data['counter_type'] == 'channels':
                                current_count = len(guild.channels)
                                new_name = f"📺 𝗗𝗜𝗦𝗖𝗢𝗥𝗗 𝗖𝗛𝗔𝗡𝗡𝗘𝗟: {current_count}"
                            elif channel_data['counter_type'] == 'roles':
                                current_count = len(guild.roles)
                                new_name = f"🏷️ 𝗗𝗜𝗦𝗖𝗢𝗥𝗗 𝗥𝗢𝗟𝗘𝗦: {current_count}"
                            elif channel_data['counter_type'] == 'role_count' and channel_data['role_id']:
                                role = guild.get_role(int(channel_data['role_id']))
                                if role:
                                    current_count = len(role.members)
                                    new_name = f"👑 {role.name}: {current_count}"
                            
                            # Update channel if count changed
                            if current_count != channel_data['last_count'] and new_name:
                                try:
                                    await channel.edit(name=new_name)
                                    logger.info(f"📊 Updated {guild.name}: {new_name}")
                                    
                                    # Update database
                                    cursor.execute(
                                        'UPDATE stats_channels SET last_count = ? WHERE channel_id = ?',
                                        (current_count, channel_data['channel_id'])
                                    )
                                    
                                except discord.Forbidden:
                                    logger.warning(f"📊 No permission to edit channel in {guild.name}")
                                except discord.HTTPException as e:
                                    logger.warning(f"📊 Failed to edit channel: {e}")
                        
                        except Exception as channel_error:
                            logger.error(f"📊 Error updating channel {channel_data['channel_id']}: {channel_error}")
                
                except Exception as guild_error:
                    logger.error(f"📊 Error updating guild {guild_id}: {guild_error}")
            
            conn.commit()
            conn.close()
            
            logger.info(f"📊 STATS-UPDATE: Completed - processed {len(stats_channels)} channels")
            
            # Wait 5 minutes before next update
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"📊 Error in stats platform task: {e}")
            await asyncio.sleep(60)  # Wait before retrying on error

async def social_media_stats_platform_task(db, bot):
    """Background task for updating social media statistics"""
    logger.info("📱 Starting social media stats platform task")
    
    while True:
        try:
            logger.info("📱 Running social media stats update...")
            
            conn = db.get_connection()
            cursor = conn.cursor()
            
            # Get all social media stats channels
            cursor.execute('SELECT guild_id, channel_id, platform, username, last_follower_count FROM social_media_stats_channels')
            social_channels = cursor.fetchall()
            
            if not social_channels:
                logger.info("📱 No social media stats channels configured")
                conn.close()
                await asyncio.sleep(1800)  # 30 minutes
                continue
            
            updated_channels = 0
            failed_updates = 0
            
            for guild_id, channel_id, platform, username, last_count in social_channels:
                try:
                    guild = bot.get_guild(int(guild_id))
                    if not guild:
                        logger.warning(f"📱 Guild {guild_id} not found")
                        continue
                    
                    channel = guild.get_channel(int(channel_id))
                    if not channel:
                        logger.warning(f"📱 Channel {channel_id} not found")
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
                    
                    # Update channel if count changed significantly (avoid rate limit issues)
                    if abs(current_count - (last_count or 0)) > max(1, current_count * 0.01):  # 1% change threshold
                        try:
                            await channel.edit(name=new_channel_name)
                            logger.info(f"📱 Updated {guild.name}: {new_channel_name} (was {last_count})")
                            
                            # Update database
                            cursor.execute(
                                'UPDATE social_media_stats_channels SET last_follower_count = ? WHERE channel_id = ?',
                                (current_count, channel_id)
                            )
                            updated_channels += 1
                            
                        except discord.Forbidden:
                            logger.warning(f"📱 No permission to edit channel in {guild.name}")
                        except discord.HTTPException as e:
                            logger.warning(f"📱 Failed to edit channel: {e}")
                    else:
                        logger.debug(f"📱 {platform} count for {username} unchanged: {current_count}")
                
                except Exception as e:
                    logger.error(f"📱 Error updating social media channel {channel_id}: {e}")
                    failed_updates += 1
                
                # Small delay between updates to avoid rate limits
                await asyncio.sleep(1)
            
            conn.commit()
            conn.close()
            
            if updated_channels > 0 or failed_updates > 0:
                logger.info(f"📱 SOCIAL-MEDIA-UPDATE: Completed - Updated: {updated_channels}, Failed: {failed_updates}, Total: {len(social_channels)}")
            
            # Wait 30 minutes before next update
            await asyncio.sleep(1800)
            
        except Exception as e:
            logger.error(f"📱 Error in social media stats platform task: {e}")
            await asyncio.sleep(300)  # Wait before retrying on error