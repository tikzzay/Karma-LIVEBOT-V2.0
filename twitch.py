#!/usr/bin/env python3
"""
Twitch Platform Module for KARMA-LiveBOT
Handles all Twitch API interactions and live stream checking
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import aiohttp

logger = logging.getLogger('KARMA-LiveBOT.Twitch')

class TwitchAPI:
    """Twitch API manager for stream info and authentication"""
    
    def __init__(self):
        self.client_id = os.getenv('TWITCH_CLIENT_ID')
        self.client_secret = os.getenv('TWITCH_CLIENT_SECRET')
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
                            logger.warning(f"Failed to get follower count for {username}: {e}")
                        
                        return {
                            'is_live': True,
                            'viewer_count': stream['viewer_count'],
                            'game_name': stream['game_name'],
                            'title': stream['title'],
                            'thumbnail_url': stream['thumbnail_url'].replace('{width}', '1920').replace('{height}', '1080'),
                            'profile_image_url': profile_image,
                            'platform_url': f'https://www.twitch.tv/{username}',
                            'follower_count': follower_count
                        }
                    else:
                        return {'is_live': False}
                else:
                    logger.error(f"Failed to get Twitch stream info for {username}: {response.status}")
                    return None

    async def get_follower_count(self, username: str) -> Optional[int]:
        """Get follower count for a Twitch user"""
        token = await self.get_access_token()
        if not token:
            return None
        
        headers = {
            'Client-ID': self.client_id,
            'Authorization': f'Bearer {token}'
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

    async def get_profile_image(self, username: str) -> Optional[str]:
        """Get Twitch profile image URL via API"""
        if not self.client_id or not self.client_secret:
            logger.warning(f"Twitch API credentials missing for profile image request: {username}")
            return None
        
        try:
            token = await self.get_access_token()
            if not token:
                return None
            
            headers = {
                'Client-ID': self.client_id,
                'Authorization': f'Bearer {token}'
            }
            
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                user_url = f'https://api.twitch.tv/helix/users?login={username}'
                async with session.get(user_url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"Failed to get Twitch user profile for {username}: {response.status}")
                        return None
                    
                    user_data = await response.json()
                    if not user_data.get('data'):
                        logger.warning(f"No Twitch user data found for username: {username}")
                        return None
                    
                    profile_image_url = user_data['data'][0].get('profile_image_url')
                    if profile_image_url:
                        logger.info(f"✅ Successfully fetched Twitch profile image for {username}")
                        return profile_image_url
                    else:
                        logger.warning(f"No profile image URL in Twitch response for {username}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error fetching Twitch profile image for {username}: {e}")
            return None

# Global instance
twitch_api = TwitchAPI()

# Task function for Twitch platform checking
async def twitch_platform_task(db, bot, creators):
    """Background task for checking Twitch streams"""
    logger.info("🎮 Starting Twitch platform task")
    
    while True:
        try:
            twitch_creators = [c for c in creators if c[5]]  # Has twitch_username
            
            if not twitch_creators:
                await asyncio.sleep(60)  # Wait 1 minute if no Twitch creators
                continue
            
            logger.info(f"🎮 Checking {len(twitch_creators)} Twitch creators")
            
            for creator in twitch_creators:
                creator_id, discord_user_id, username, streamer_type, channel_id, twitch_user, youtube_user, tiktok_user = creator
                
                try:
                    # Check if user is live
                    stream_info = await twitch_api.get_stream_info(twitch_user)
                    
                    if stream_info and stream_info.get('is_live'):
                        logger.info(f"🎮 {twitch_user} is LIVE on Twitch!")
                        # Here you would call handle_stream_status or similar notification logic
                        # This will be handled by the main bot coordination
                    else:
                        logger.debug(f"🎮 {twitch_user} is offline on Twitch")
                    
                except Exception as e:
                    logger.error(f"🎮 Error checking Twitch user {twitch_user}: {e}")
                
                # Small delay between checks to avoid rate limits
                await asyncio.sleep(1)
            
            # Wait based on streamer type intervals
            # For now, use 2 minutes as a reasonable default
            await asyncio.sleep(120)
            
        except Exception as e:
            logger.error(f"🎮 Error in Twitch platform task: {e}")
            await asyncio.sleep(30)  # Wait before retrying on error