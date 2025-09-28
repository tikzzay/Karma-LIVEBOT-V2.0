"""
Event Management und weitere Commands für KARMA-LiveBOT
"""

import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
from typing import List, Optional
import logging
from datetime import datetime, timedelta
import os
import asyncio
import glob
import time
import aiohttp

logger = logging.getLogger('KARMA-LiveBOT.events')

# Configuration
class Config:
    ADMIN_ROLES = [1388945013735424020, 581139700408909864, 898970074491269170]
    USER_ROLES = [292321283608150016, 276471077402705920]  # Beide normale User-Rollen
    
    # Developer/Main Server Configuration (from secrets)
    MAIN_SERVER_ID = int(os.getenv('MAIN_SERVER_ID', '0'))  # Main server where serverinfo command is available
    BOT_DEVELOPER_ID = int(os.getenv('BOT_DEVELOPER_ID', '0'))  # Developer user ID
    
    # API Keys from Environment (avoid circular import)
    TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
    TWITCH_CLIENT_SECRET = os.getenv('TWITCH_CLIENT_SECRET')
    YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
    
    COLORS = {
        'twitch': 0x9146FF,    # Lila
        'youtube': 0xFF0000,   # Rot
        'tiktok': 0x00F2EA     # Hellblau
    }

# DatabaseManager placeholder (will be set at runtime)
DatabaseManager = None

def has_admin_role():
    """Check if user has admin permissions"""
    def predicate(interaction: discord.Interaction) -> bool:
        # Check if user is a Member (not just User) to access roles
        if not hasattr(interaction, 'guild') or not interaction.guild:
            return False
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.roles:
            return False
        user_roles = [role.id for role in member.roles]
        return any(role_id in Config.ADMIN_ROLES for role_id in user_roles)
    return app_commands.check(predicate)

def has_user_role():
    """Check if user has user permissions (for normal user commands)"""
    def predicate(interaction: discord.Interaction) -> bool:
        # Check if user is a Member (not just User) to access roles
        if not hasattr(interaction, 'guild') or not interaction.guild:
            return False
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.roles:
            return False
        user_roles = [role.id for role in member.roles]
        # Allow both admin roles and user role
        return (any(role_id in Config.ADMIN_ROLES for role_id in user_roles) or 
                any(user_role in Config.USER_ROLES for user_role in user_roles))
    return app_commands.check(predicate)

def is_developer_on_main_server():
    """Check if user is developer on main server (for serverinfo command)"""
    # IDs that are explicitly NOT allowed to use serverinfo
    FORBIDDEN_IDS = [581139700408909864, 898970074491269170]
    
    def predicate(interaction: discord.Interaction) -> bool:
        # Must be on main server
        if not interaction.guild or interaction.guild.id != Config.MAIN_SERVER_ID:
            return False
        # Must be the developer and NOT one of the forbidden IDs
        if interaction.user.id in FORBIDDEN_IDS:
            return False
        return interaction.user.id == Config.BOT_DEVELOPER_ID
    return app_commands.check(predicate)

class EventCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db
    
    async def get_twitch_profile_image(self, username: str) -> Optional[str]:
        """Get Twitch profile image URL via API - dedicated method to avoid circular imports"""
        if not Config.TWITCH_CLIENT_ID or not Config.TWITCH_CLIENT_SECRET:
            logger.warning(f"Twitch API credentials missing for profile image request: {username}")
            return None
        
        try:
            # Get OAuth token
            token_url = 'https://id.twitch.tv/oauth2/token'
            token_data = {
                'client_id': Config.TWITCH_CLIENT_ID,
                'client_secret': Config.TWITCH_CLIENT_SECRET,
                'grant_type': 'client_credentials'
            }
            
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Get access token
                async with session.post(token_url, data=token_data) as token_response:
                    if token_response.status != 200:
                        logger.error(f"Failed to get Twitch token for profile image: {token_response.status}")
                        return None
                    
                    token_json = await token_response.json()
                    access_token = token_json.get('access_token')
                    
                    if not access_token:
                        logger.error("No access token received from Twitch API")
                        return None
                
                # Get user profile
                headers = {
                    'Client-ID': Config.TWITCH_CLIENT_ID,
                    'Authorization': f'Bearer {access_token}'
                }
                
                user_url = f'https://api.twitch.tv/helix/users?login={username}'
                async with session.get(user_url, headers=headers) as user_response:
                    if user_response.status != 200:
                        logger.error(f"Failed to get Twitch user profile for {username}: {user_response.status}")
                        return None
                    
                    user_data = await user_response.json()
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
    
    async def get_youtube_profile_image(self, username: str) -> Optional[str]:
        """Get YouTube profile image URL via API - dedicated method to avoid circular imports"""
        if not Config.YOUTUBE_API_KEY:
            logger.warning(f"YouTube API key missing for profile image request: {username}")
            return None
        
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Search for channel by username
                search_url = 'https://www.googleapis.com/youtube/v3/search'
                params = {
                    'part': 'snippet',
                    'q': f'@{username}',
                    'type': 'channel',
                    'key': Config.YOUTUBE_API_KEY,
                    'maxResults': 1
                }
                
                async with session.get(search_url, params=params) as search_response:
                    if search_response.status == 403:
                        logger.warning(f"YouTube API quota exceeded for profile image request: {username}")
                        return None
                    elif search_response.status != 200:
                        logger.error(f"YouTube search API error for {username}: {search_response.status}")
                        return None
                    
                    search_data = await search_response.json()
                    if not search_data.get('items'):
                        logger.warning(f"No YouTube channel found for username: {username}")
                        return None
                    
                    # Fix: Use correct channel ID extraction for search results
                    channel_id = search_data['items'][0]['id']['channelId']
                
                # Get channel details for profile image
                channels_url = 'https://www.googleapis.com/youtube/v3/channels'
                params = {
                    'part': 'snippet',
                    'id': channel_id,
                    'key': Config.YOUTUBE_API_KEY
                }
                
                async with session.get(channels_url, params=params) as channel_response:
                    if channel_response.status != 200:
                        logger.error(f"YouTube channels API error for {username}: {channel_response.status}")
                        return None
                    
                    channel_data = await channel_response.json()
                    if not channel_data.get('items'):
                        logger.warning(f"No YouTube channel details found for {username}")
                        return None
                    
                    thumbnails = channel_data['items'][0]['snippet'].get('thumbnails', {})
                    # Try different thumbnail sizes, prioritizing higher quality
                    for size in ['high', 'medium', 'default']:
                        if size in thumbnails:
                            profile_url = thumbnails[size]['url']
                            logger.info(f"✅ Successfully fetched YouTube profile image for {username} (size: {size})")
                            return profile_url
                    
                    logger.warning(f"No thumbnail URLs found in YouTube response for {username}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error fetching YouTube profile image for {username}: {e}")
            return None

    @app_commands.command(name="streakevent", description="Event-Management: on/off")
    @app_commands.describe(action="Event aktivieren oder deaktivieren")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    async def streak_event(self, interaction: discord.Interaction, action: str):
        """Manage streak events"""
        if action.lower() not in ['on', 'off']:
            await interaction.response.send_message(
                "❌ Ungültige Aktion. Verwenden Sie 'on' oder 'off'.",
                ephemeral=True
            )
            return

        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            if action.lower() == 'on':
                cursor.execute(
                    'UPDATE event_status SET is_active = TRUE, started_at = ? WHERE id = 1',
                    (datetime.now().isoformat(),)
                )
                
                embed = discord.Embed(
                    title="🎉 Event gestartet!",
                    description="Das Streak-Event wurde aktiviert. Alle Streamer können jetzt Event-Punkte sammeln!",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="📊 Punkteberechnung",
                    value="• 2h → 20 Punkte\n• 4h → 40 Punkte\n• 6h → 60 Punkte\n• 8h → 80 Punkte\n• 10h → 100 Punkte",
                    inline=True
                )
                embed.add_field(
                    name="🔥 Streak Multiplikatoren",
                    value="• 3 Tage → x2\n• 6 Tage → x3\n• 9 Tage → x4",
                    inline=True
                )
                
            else:  # off
                cursor.execute(
                    'UPDATE event_status SET is_active = FALSE, ended_at = ? WHERE id = 1',
                    (datetime.now().isoformat(),)
                )
                
                embed = discord.Embed(
                    title="🏁 Event beendet!",
                    description="Das Streak-Event wurde deaktiviert. Alle Event-Streaks und Punkte wurden zurückgesetzt.",
                    color=discord.Color.orange()
                )
            
            conn.commit()
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error managing event: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Event-Management.",
                ephemeral=True
            )
        finally:
            conn.close()

    @app_commands.command(name="reset", description="Event-Daten zurücksetzen")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    async def reset_event(self, interaction: discord.Interaction):
        """Reset event data"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Reset event streaks and points
            cursor.execute('UPDATE event_streaks SET current_event_streak = 0, event_points = 0')
            
            # Set event as inactive
            cursor.execute('UPDATE event_status SET is_active = FALSE, ended_at = ?', (datetime.now().isoformat(),))
            
            conn.commit()
            
            embed = discord.Embed(
                title="🔄 Event-Daten zurückgesetzt",
                description="Alle Event-Streaks und Punkte wurden auf 0 zurückgesetzt.",
                color=discord.Color.blue()
            )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error resetting event: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Zurücksetzen der Event-Daten.",
                ephemeral=True
            )
        finally:
            conn.close()

    @app_commands.command(name="ranking", description="Top 10 Creator Rangliste anzeigen")
    @has_user_role()
    async def show_ranking(self, interaction: discord.Interaction):
        """Show top 10 creators ranking"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # First check if event is active
            cursor.execute('SELECT is_active FROM event_status WHERE id = 1')
            event_status = cursor.fetchone()
            is_active = event_status[0] if event_status else False
            
            if not is_active:
                await interaction.response.send_message(
                    "❌ Event ist derzeit nicht aktiv. Rangliste ist nur während aktiven Events verfügbar.",
                    ephemeral=True
                )
                return
            
            # Get rankings with platform information
            cursor.execute('''
                SELECT c.discord_username, c.streamer_type, es.event_points, es.current_event_streak,
                       c.twitch_username, c.youtube_username, c.tiktok_username
                FROM creators c
                JOIN event_streaks es ON c.id = es.creator_id
                WHERE es.event_points > 0
                ORDER BY es.event_points DESC
                LIMIT 10
            ''')
            
            rankings = cursor.fetchall()
            
            if not rankings:
                await interaction.response.send_message(
                    "❌ Keine Event-Daten gefunden.",
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title="🏆 Top 10 Creator Rangliste",
                color=discord.Color.gold()
            )
            
            ranking_text = ""
            for i, (username, streamer_type, points, streak, twitch_user, youtube_user, tiktok_user) in enumerate(rankings, 1):
                type_emoji = "⭐" if streamer_type == "karma" else "👾"
                
                # Determine primary platform (prefer the one with most activity or first available)
                platform = "Unbekannt"
                if twitch_user:
                    platform = "Twitch"
                elif youtube_user:
                    platform = "YouTube"  
                elif tiktok_user:
                    platform = "TikTok"
                
                ranking_text += f"{i}.{type_emoji} **{username}** - {platform} - {points:,} Punkte (🔥{streak})\n"
            
            embed.add_field(
                name="🏆 Event Rangliste",
                value=ranking_text,
                inline=False
            )
            
            embed.set_footer(text="🟢 Event Aktiv")
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            logger.error(f"Error showing ranking: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Abrufen der Rangliste.",
                ephemeral=True
            )
        finally:
            conn.close()

class UtilityCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db
    

    @app_commands.command(name="live", description="Alle aktuellen Live-Streams anzeigen")
    @has_user_role()
    async def show_live_streams(self, interaction: discord.Interaction):
        """Show all current live streams"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT c.discord_username, c.streamer_type, ls.platform, c.twitch_username, c.youtube_username, c.tiktok_username
                FROM creators c
                JOIN live_status ls ON c.id = ls.creator_id
                WHERE ls.is_live = TRUE
                ORDER BY ls.platform, c.streamer_type DESC
            ''')
            
            live_streams = cursor.fetchall()
            
            # Group by platform with usernames
            platforms = {'twitch': [], 'youtube': [], 'tiktok': []}
            stream_data = []
            
            for username, streamer_type, platform, twitch_user, youtube_user, tiktok_user in live_streams:
                type_emoji = "⭐" if streamer_type == "karma" else "👾"
                platforms[platform].append(f"{type_emoji} **{username}**")
                
                # Store stream data for buttons
                if platform == 'twitch' and twitch_user:
                    stream_data.append({'platform': 'twitch', 'username': twitch_user, 'display_name': username})
                elif platform == 'youtube' and youtube_user:
                    stream_data.append({'platform': 'youtube', 'username': youtube_user, 'display_name': username})
                elif platform == 'tiktok' and tiktok_user:
                    stream_data.append({'platform': 'tiktok', 'username': tiktok_user, 'display_name': username})
            
            embeds = []
            
            # Twitch embed
            if platforms['twitch']:
                twitch_embed = discord.Embed(
                    title="🟣 Twitch Live Streams",
                    description="\n".join(platforms['twitch']),
                    color=Config.COLORS['twitch']
                )
                embeds.append(twitch_embed)
            
            # YouTube embed
            if platforms['youtube']:
                youtube_embed = discord.Embed(
                    title="🔴 YouTube Live Streams",
                    description="\n".join(platforms['youtube']),
                    color=Config.COLORS['youtube']
                )
                embeds.append(youtube_embed)
            
            # TikTok embed
            if platforms['tiktok']:
                tiktok_embed = discord.Embed(
                    title="🔵 TikTok Live Streams",
                    description="\n".join(platforms['tiktok']),
                    color=Config.COLORS['tiktok']
                )
                embeds.append(tiktok_embed)
            
            if not embeds:
                embed = discord.Embed(
                    title="📺 Live Streams",
                    description="❌ Momentan ist niemand live.",
                    color=discord.Color.greyple()
                )
                await interaction.response.send_message(embed=embed)
            else:
                # Create view with watch buttons if there are live streams
                view = LiveStreamView(stream_data) if stream_data else None
                await interaction.response.send_message(embeds=embeds[:10], view=view)  # Discord limit
            
        except Exception as e:
            logger.error(f"Error showing live streams: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Abrufen der Live-Streams.",
                ephemeral=True
            )
        finally:
            conn.close()

    @app_commands.command(name="help", description="Alle verfügbaren Befehle anzeigen")
    @has_user_role()
    async def show_help(self, interaction: discord.Interaction):
        """Show help with all commands"""
        embed = discord.Embed(
            title="🤖 KARMA-LiveBOT Hilfe",
            description="Hier sind alle verfügbaren Befehle:",
            color=discord.Color.blue()
        )
        
        # Check if user is admin (only works if user is a Member in a guild)
        is_admin = False
        if interaction.guild and hasattr(interaction.user, 'roles'):
            # User is a Member in a guild context
            user_roles = [role.id for role in interaction.user.roles]
            is_admin = any(role_id in Config.ADMIN_ROLES for role_id in user_roles)
        elif interaction.guild:
            # Get member from guild if user is not already a member object
            member = interaction.guild.get_member(interaction.user.id)
            if member and member.roles:
                user_roles = [role.id for role in member.roles]
                is_admin = any(role_id in Config.ADMIN_ROLES for role_id in user_roles)
        
        if is_admin:
            embed.add_field(
                name="👑 Admin Befehle",
                value=(
                    "`/addcreator` - Creator hinzufügen\n"
                    "`/deletecreator` - Creator entfernen\n"
                    "`/streakevent on/off` - Event starten/stoppen\n"
                    "`/reset` - Event-Daten zurücksetzen\n"
                    "`/serverinfo` - Server-Übersicht & Bot-Tests"
                ),
                inline=False
            )
        
        embed.add_field(
            name="👥 Nutzer Befehle",
            value=(
                "`/request` - Anfrage stellen um als Streamer hinzugefügt zu werden\n"
                "`/requeststatus` - Status der Streamer-Anfrage prüfen\n"
                "`/subcreator` - Creator für private Benachrichtigungen abonnieren\n"
                "`/unsub` - Abonnements verwalten\n"
                "`/live` - Alle aktuellen Live-Streams anzeigen\n"
                "`/ranking` - Top 10 Creator Rangliste\n"
                "`/help` - Diese Hilfe anzeigen"
            ),
            inline=False
        )
        
        embed.add_field(
            name="ℹ️ Informationen",
            value=(
                "• **Karma Streamer**: Cyberpunk-Style Benachrichtigungen, Daily Streaks\n"
                "• **Regular Streamer**: Einfache Benachrichtigungen\n"
                "• **Live-Rolle**: Wird automatisch bei Live-Status vergeben\n"
                "• **Private Benachrichtigungen**: Über `/subcreator` abonnierbar"
            ),
            inline=False
        )
        
        embed.set_footer(text="KARMA-LiveBOT | Unterstützt Twitch, YouTube & TikTok")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="serverinfo", description="Developer Server-Informationen und Bot-Tests")
    @app_commands.guilds(discord.Object(Config.MAIN_SERVER_ID))  # Only on main server
    @is_developer_on_main_server()
    async def server_info(self, interaction: discord.Interaction):
        """Show server information and test bot functions - Developer only"""
        try:
            view = ServerInfoView(self.db, interaction.client)
            
            embed = discord.Embed(
                title="🌍 Developer Server-Info & Test-Menü",
                description="Wählen Sie eine Option aus:",
                color=discord.Color.blue()
            )
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            logger.info(f"✅ ServerInfo command executed successfully for developer {interaction.user}")
            
        except discord.errors.NotFound:
            # Interaction timeout or already responded
            logger.warning(f"❌ ServerInfo interaction timeout/expired for {interaction.user}")
            try:
                # Try followup if response already sent
                await interaction.followup.send("⚠️ Server-Info konnte nicht geladen werden. Versuchen Sie es erneut.", ephemeral=True)
            except:
                pass
        except Exception as e:
            logger.error(f"❌ ServerInfo command error for {interaction.user}: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Fehler beim Laden der Server-Info.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Fehler beim Laden der Server-Info.", ephemeral=True)
            except:
                pass

class ServerInfoView(discord.ui.View):
    def __init__(self, db, bot):
        super().__init__(timeout=300)
        self.db = db
        self.bot = bot

    @discord.ui.select(
        placeholder="Option auswählen...",
        options=[
            discord.SelectOption(label="Server-Übersicht", value="server_overview", emoji="🌍"),
            discord.SelectOption(label="Bot-API-Test", value="bot_api_test", emoji="🔌"),
            discord.SelectOption(label="Live-Benachrichtigung", value="live_demo", emoji="📺"),
            discord.SelectOption(label="Auto-Löschung Test", value="deletion_test", emoji="🗑️"),
            discord.SelectOption(label="Event-Test", value="event_test", emoji="🎮"),
            discord.SelectOption(label="Instant Gaming Test", value="instant_gaming_test", emoji="🎮"),
            discord.SelectOption(label="Leave-Server", value="leave_server", emoji="🚪"),
            discord.SelectOption(label="Server-Unban", value="server_unban", emoji="🔓")
        ]
    )
    async def select_option(self, interaction: discord.Interaction, select: discord.ui.Select):
        option_type = select.values[0]
        logger.info(f"🔄 ServerInfo dropdown selection: '{option_type}' by user {interaction.user}")
        
        if option_type == "server_overview":
            logger.info(f"📋 Calling show_server_overview for user {interaction.user}")
            await self.show_server_overview(interaction)
        elif option_type == "bot_api_test":
            logger.info(f"🔌 Calling run_bot_api_test for user {interaction.user}")
            await self.run_bot_api_test(interaction)
        elif option_type == "live_demo":
            logger.info(f"📺 Calling run_live_demo for user {interaction.user}")
            await self.run_live_demo(interaction)
        elif option_type == "deletion_test":
            logger.info(f"🗑️ Calling run_deletion_test for user {interaction.user}")
            await self.run_deletion_test(interaction)
        elif option_type == "event_test":
            logger.info(f"🎮 Calling run_event_test for user {interaction.user}")
            await self.run_event_test(interaction)
        elif option_type == "instant_gaming_test":
            logger.info(f"🎮 Calling run_instant_gaming_test for user {interaction.user}")
            await self.run_instant_gaming_test(interaction)
        elif option_type == "leave_server":
            logger.info(f"🚪 Calling show_leave_server_modal for user {interaction.user}")
            await self.show_leave_server_modal(interaction)
        elif option_type == "server_unban":
            logger.info(f"🔓 Calling show_server_unban_modal for user {interaction.user}")
            await self.show_server_unban_modal(interaction)
        else:
            logger.warning(f"❌ Unknown option selected: '{option_type}' by user {interaction.user}")

    async def show_server_overview(self, interaction: discord.Interaction):
        """Show detailed server overview with specified format - ALL servers"""
        logger.info(f"🌍 STARTING show_server_overview for user {interaction.user}")
        
        try:
            # Defer to get more time for invite operations
            await interaction.response.defer()
            logger.info(f"✅ Deferred interaction for show_server_overview")
        except Exception as defer_error:
            logger.error(f"❌ Failed to defer interaction: {defer_error}")
            # Try to respond directly if defer failed
            try:
                embed = discord.Embed(
                    title="❌ Server-Übersicht Fehler",
                    description="⚠️ Server-Info konnte nicht geladen werden. Versuchen Sie es erneut.",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            except:
                return
        
        embed = discord.Embed(
            title="🌍 Server-Übersicht (Alle Server)",
            description=f"Bot ist auf **{len(self.bot.guilds)}** Server(n)",
            color=discord.Color.blue()
        )
        
        # Count total streamers from database
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM creators')
            total_streamers = cursor.fetchone()[0]
            conn.close()
        except:
            total_streamers = 0
        
        # Show up to 10 servers (Discord embed limits)
        servers_shown = 0
        for guild in self.bot.guilds:
            if servers_shown >= 10:  # Discord embed field limit
                remaining = len(self.bot.guilds) - servers_shown
                embed.add_field(
                    name="➕ Weitere Server",
                    value=f"Und **{remaining}** weitere Server...",
                    inline=False
                )
                break
                
            try:
                owner = guild.owner
                member_count = guild.member_count
                
                # Count streamers on this specific server (streamer roles)
                streamer_roles = [r for r in guild.roles if "streamer" in r.name.lower()]
                server_streamers = sum(len(r.members) for r in streamer_roles)
                
                # Format dates
                created_at = guild.created_at.strftime("%d.%m.%Y") if guild.created_at else "Unbekannt"
                joined_at = guild.me.joined_at.strftime("%d.%m.%Y") if guild.me.joined_at else "Unbekannt"
                
                # Create fresh single-use invite (delete old bot invites first)
                invite_link = "Keine Berechtigung"
                try:
                    # Step 1: Delete old bot-created invites if we have permission
                    if guild.me.guild_permissions.manage_guild:
                        try:
                            invites = await guild.invites()
                            deleted_count = 0
                            for invite in invites:
                                # Only delete invites created by THIS BOT
                                if invite.inviter and invite.inviter.id == self.bot.user.id:
                                    try:
                                        await invite.delete(reason="ServerInfo - replacing with new invite")
                                        deleted_count += 1
                                        logger.info(f"Deleted old bot invite: {invite.url}")
                                    except Exception as delete_error:
                                        logger.warning(f"Failed to delete bot invite {invite.url}: {delete_error}")
                            
                            if deleted_count > 0:
                                logger.info(f"Deleted {deleted_count} old bot invites from {guild.name}")
                        except Exception as cleanup_error:
                            logger.warning(f"Failed to cleanup old invites in {guild.name}: {cleanup_error}")
                    
                    # Step 2: Create new single-use invite
                    for channel in guild.text_channels:
                        if channel.permissions_for(guild.me).create_instant_invite:
                            try:
                                invite = await channel.create_invite(
                                    max_age=3600, max_uses=1, unique=True,
                                    reason="ServerInfo - fresh single-use invite"
                                )
                                invite_link = invite.url
                                logger.info(f"Created fresh single-use invite for {guild.name}: {invite_link}")
                                break
                            except Exception as invite_error:
                                logger.warning(f"Failed to create invite in {channel.name}: {invite_error}")
                                continue
                    
                    if invite_link == "Keine Berechtigung":
                        invite_link = "Kann keinen Invite erstellen"
                        
                except Exception as e:
                    invite_link = f"Fehler: {str(e)[:30]}"
                    logger.error(f"Error managing invites for {guild.name}: {e}")
                
                # Build server info according to specification
                server_info = (
                    f"🔹 **Server-Name:** {guild.name}\n"
                    f"🆔 **Server-ID:** {guild.id}\n"
                    f"👑 **Besitzer:** {owner}\n"
                    f"👑 **BesitzerID:** {owner.id}\n"
                    f"👥 **Mitglieder:** {member_count:,}\n"
                    f"🎥 **Streamer:** {server_streamers}\n"
                    f"📅 **Erstellt am:** {created_at}\n"
                    f"🤖 **Bot beigetreten:** {joined_at}\n"
                    f"🔗 **Invite:** {invite_link}"
                )
                
                embed.add_field(
                    name=f"🔹 {guild.name}",
                    value=server_info,
                    inline=False
                )
                
                servers_shown += 1
                
            except Exception as e:
                embed.add_field(
                    name=f"❌ {guild.name}",
                    value=f"**Fehler beim Laden:** {str(e)[:100]}",
                    inline=False
                )
                servers_shown += 1
        
        # Add summary footer
        embed.set_footer(text=f"Angezeigt: {servers_shown}/{len(self.bot.guilds)} Server | 🎥 Total DB-Streamer: {total_streamers} | KARMA-LiveBOT")
        await interaction.edit_original_response(embed=embed, view=None)

    async def run_bot_api_test(self, interaction: discord.Interaction):
        """Comprehensive Bot API Test according to specification"""
        embed = discord.Embed(
            title="🔌 Bot-API-Test Ergebnisse",
            color=discord.Color.blue()
        )
        
        # Bot-Status
        bot_uptime = time.time() - getattr(self.bot, '_startup_time', time.time())
        uptime_hours = int(bot_uptime // 3600)
        uptime_minutes = int((bot_uptime % 3600) // 60)
        
        bot_status = (
            f"✅ **Online**\n"
            f"📊 **Server:** {len(self.bot.guilds)}\n"
            f"⏰ **Uptime:** {uptime_hours}h {uptime_minutes}m"
        )
        embed.add_field(name="🤖 Bot-Status", value=bot_status, inline=True)
        
        # Discord API Test
        latency_ms = round(self.bot.latency * 1000, 2)
        discord_status = f"✅ **Latenz:** {latency_ms}ms"
        embed.add_field(name="📡 Discord API Test", value=discord_status, inline=True)
        
        # Database Test
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM creators')
            creator_count = cursor.fetchone()[0]
            
            # Count live creators
            cursor.execute('SELECT COUNT(DISTINCT creator_id) FROM live_status WHERE is_live = 1')
            live_count = cursor.fetchone()[0]
            conn.close()
            
            db_status = f"✅ **Verbindung OK**\n📊 **Creators:** {creator_count}\n🔴 **Live:** {live_count}"
        except Exception as e:
            db_status = f"❌ **Fehler:** {str(e)[:30]}"
        
        embed.add_field(name="🗄️ Database Test", value=db_status, inline=True)
        
        # API-Keys Check
        twitch_status = "✅ Gesetzt" if os.getenv('TWITCH_CLIENT_ID') and os.getenv('TWITCH_CLIENT_SECRET') else "❌ Fehlt"
        youtube_status = "✅ Gesetzt" if os.getenv('YOUTUBE_API_KEY') else "❌ Fehlt"
        
        # TikTok Tasks Status (simplified - count background tasks)
        try:
            current_tasks = len([task for task in asyncio.all_tasks() if not task.done()])
            tiktok_status = f"✅ Tasks: {current_tasks}"
        except:
            tiktok_status = "❌ Fehler"
        
        api_keys_status = f"🟣 **Twitch:** {twitch_status}\n🔴 **YouTube:** {youtube_status}\n🔵 **TikTok:** {tiktok_status}"
        embed.add_field(name="🔑 API-Keys Check", value=api_keys_status, inline=True)
        
        # Logfile-Check
        try:
            # Find latest log file
            log_files = glob.glob('/tmp/logs/*.log')
            if log_files:
                latest_log = max(log_files, key=os.path.getmtime)
                with open(latest_log, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    recent_lines = lines[-50:] if len(lines) >= 50 else lines
                    
                    # Count errors (excluding UserOfflineError)
                    error_count = 0
                    for line in recent_lines:
                        if 'ERROR' in line and 'UserOfflineError' not in line:
                            error_count += 1
                    
                    log_status = f"✅ **Letzte 50 Zeilen**\n⚠️ **Errors:** {error_count}"
            else:
                log_status = "❌ Keine Logs gefunden"
        except Exception as e:
            log_status = f"❌ Fehler: {str(e)[:30]}"
        
        embed.add_field(name="📋 Logfile-Check", value=log_status, inline=True)
        
        # Environment Check
        discord_token_set = "✅" if os.getenv('DISCORD_TOKEN') else "❌"
        bot_dev_id_set = "✅" if os.getenv('BOT_DEVELOPER_ID') else "❌"
        
        env_status = f"🔑 **DISCORD_TOKEN:** {discord_token_set}\n👤 **BOT_DEVELOPER_ID:** {bot_dev_id_set}"
        embed.add_field(name="🌍 Environment Check", value=env_status, inline=True)
        
        # Live Role Test (new)
        try:
            # Use environment variable or hardcoded value to avoid importing main
            live_role_id = int(os.getenv('LIVE_ROLE_ID', '899306754549108786'))
            
            # Test live role accessibility across all guilds
            live_role_tests = []
            role_found_count = 0
            
            for guild in self.bot.guilds:
                live_role = guild.get_role(live_role_id)
                if live_role:
                    role_found_count += 1
                    # Check if bot can manage this role
                    can_manage = guild.me.guild_permissions.manage_roles and live_role < guild.me.top_role
                    status = "✅" if can_manage else "⚠️ Keine Berechtigung"
                    live_role_tests.append(f"{guild.name[:20]}: {status}")
                else:
                    live_role_tests.append(f"{guild.name[:20]}: ❌ Nicht gefunden")
            
            if role_found_count > 0:
                live_role_status = f"✅ **Status:** {role_found_count}/{len(self.bot.guilds)} Server gefunden"
                live_role_status += f"\n🔧 **Role ID:** {live_role_id}"
                # Show details for first 3 servers
                if live_role_tests[:3]:
                    live_role_status += "\n\n**Server-Status:**"
                    for test in live_role_tests[:3]:
                        live_role_status += f"\n{test}"
                    if len(live_role_tests) > 3:
                        live_role_status += f"\n...und {len(live_role_tests) - 3} weitere"
            else:
                live_role_status = f"❌ **Live-Rolle nicht gefunden**\n🔧 **Role ID:** {live_role_id}"
                
        except Exception as e:
            live_role_status = f"❌ **Fehler:** {str(e)[:50]}"
        
        embed.add_field(name="🔴 Live-Rolle Test", value=live_role_status, inline=True)
        
        embed.set_footer(text="Test abgeschlossen - Alle Systeme geprüft")
        await interaction.response.edit_message(embed=embed, view=None)

    async def run_live_demo(self, interaction: discord.Interaction):
        """Demo live notifications for all platforms and streamer types"""
        await interaction.response.edit_message(content="📺 Sende Live-Benachrichtigung Tests...", embed=None, view=None)
        
        # Get the channel where interaction was sent
        channel = interaction.channel
        
        # Test 1: Twitch Karma Streamer
        twitch_karma_embed = discord.Embed(
            description="🚨 Hey Cyber-Runner! 🚨\nTestUser ist jetzt LIVE auf Twitch: testchannel!\nTaucht ein in die Neon-Welten, seid aktiv im Chat und verteilt ein bisschen Liebe im Grid! 💜💻",
            color=Config.COLORS['twitch']
        )
        twitch_karma_embed.set_thumbnail(url="https://static-cdn.jtvnw.net/user-default-pictures-uv/de130ab0-def7-11e9-b668-784f43822e80-profile_image-300x300.png")
        twitch_karma_embed.set_image(url="https://static-cdn.jtvnw.net/previews-ttv/live_user_testchannel-1920x1080.jpg")
        twitch_karma_embed.add_field(name="👀 Zuschauer", value="1,234", inline=True)
        twitch_karma_embed.add_field(name="🎮 Spiel", value="Cyberpunk 2077", inline=True)
        twitch_karma_embed.add_field(name="💖 Follower", value="15,678", inline=True)
        twitch_karma_embed.add_field(name="🔥 Daily Streak", value="5 Tage", inline=True)
        twitch_karma_embed.set_footer(text="🟣 Twitch • Karma Streamer Test")
        twitch_karma_embed.timestamp = datetime.now()
        
        # Create simple test view (avoiding circular imports)
        class TestNotificationView(discord.ui.View):
            def __init__(self, platform: str, username: str):
                super().__init__(timeout=None)
                
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
                
                # Add buttons
                self.add_item(discord.ui.Button(label="Anschauen", emoji="📺", url=live_url, style=discord.ButtonStyle.link, row=0))
                self.add_item(discord.ui.Button(label="Folgen", emoji="❤️", url=profile_url, style=discord.ButtonStyle.link, row=0))
        
        view = TestNotificationView('twitch', 'testchannel')
        
        await channel.send("**🚨 TEST: Twitch Karma Streamer**", embed=twitch_karma_embed, view=view)
        
        # Test 2: YouTube Karma Streamer  
        youtube_karma_embed = discord.Embed(
            description="🚨 Hey Cyber-Runner! 🚨\nTestUser ist jetzt LIVE auf YouTube!\nTaucht ein in die Neon-Welten, seid aktiv im Chat und verteilt ein bisschen Liebe im Grid! ❤️💻",
            color=Config.COLORS['youtube']
        )
        youtube_karma_embed.set_thumbnail(url="https://cdn.discordapp.com/embed/avatars/1.png")
        youtube_karma_embed.set_image(url="https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg")
        youtube_karma_embed.add_field(name="👀 Zuschauer", value="2,567", inline=True)
        youtube_karma_embed.add_field(name="🎮 Kategorie", value="Gaming", inline=True)
        youtube_karma_embed.add_field(name="📺 Abonnenten", value="89,234", inline=True)
        youtube_karma_embed.add_field(name="🔥 Daily Streak", value="3 Tage", inline=True)
        youtube_karma_embed.set_footer(text="🔴 YouTube • Karma Streamer Test")
        youtube_karma_embed.timestamp = datetime.now()
        
        view = TestNotificationView('youtube', 'testuser')
        
        await channel.send("**🚨 TEST: YouTube Karma Streamer**", embed=youtube_karma_embed, view=view)
        
        # Test 3: TikTok Karma Streamer
        tiktok_karma_embed = discord.Embed(
            description="🚨 Hey Cyber-Runner! 🚨\nTestUser ist jetzt LIVE auf TikTok!\nTaucht ein in die Neon-Welten, seid aktiv im Chat und verteilt ein bisschen Liebe im Grid! 🌊💻",
            color=Config.COLORS['tiktok']
        )
        tiktok_karma_embed.set_thumbnail(url="https://cdn.discordapp.com/embed/avatars/2.png")
        tiktok_karma_embed.set_image(url="https://picsum.photos/1920/1080?random=3")
        tiktok_karma_embed.add_field(name="👀 Zuschauer", value="890", inline=True)
        tiktok_karma_embed.add_field(name="🎮 Kategorie", value="TikTok Live", inline=True)
        tiktok_karma_embed.add_field(name="💖 Follower", value="43,512", inline=True)
        tiktok_karma_embed.add_field(name="🔥 Daily Streak", value="7 Tage", inline=True)
        tiktok_karma_embed.set_footer(text="🔵 TikTok • Karma Streamer Test")
        tiktok_karma_embed.timestamp = datetime.now()
        
        view = TestNotificationView('tiktok', 'testuser')
        
        await channel.send("**🚨 TEST: TikTok Karma Streamer**", embed=tiktok_karma_embed, view=view)
        
        # Test 4: Twitch Regular Streamer (NO profile image, HAS stream thumbnail)
        twitch_regular_embed = discord.Embed(
            description="👾 RegularUser ist LIVE!\nSchaut vorbei und habt Spaß! 🎮",
            color=Config.COLORS['twitch']
        )
        twitch_regular_embed.set_image(url="https://static-cdn.jtvnw.net/previews-ttv/live_user_regularuser-1920x1080.jpg")
        twitch_regular_embed.add_field(name="👀 Zuschauer", value="456", inline=True)
        twitch_regular_embed.add_field(name="🎮 Spiel", value="Minecraft", inline=True)
        twitch_regular_embed.add_field(name="💖 Follower", value="8,291", inline=True)
        twitch_regular_embed.set_footer(text="🟣 Twitch • Regular Streamer Test")
        twitch_regular_embed.timestamp = datetime.now()
        
        view = TestNotificationView('twitch', 'regularuser')
        
        await channel.send("**👾 TEST: Twitch Regular Streamer**", embed=twitch_regular_embed, view=view)
        
        # Test 5: YouTube Regular Streamer (NO profile image, HAS stream thumbnail)
        youtube_regular_embed = discord.Embed(
            description="👾 RegularUser ist LIVE!\nSchaut vorbei und habt Spaß! 📺",
            color=Config.COLORS['youtube']
        )
        youtube_regular_embed.set_image(url="https://i.ytimg.com/vi/9bZkp7q19f0/maxresdefault.jpg")
        youtube_regular_embed.add_field(name="👀 Zuschauer", value="789", inline=True)
        youtube_regular_embed.add_field(name="🎮 Kategorie", value="Just Chatting", inline=True)
        youtube_regular_embed.add_field(name="📺 Abonnenten", value="23,456", inline=True)
        youtube_regular_embed.set_footer(text="🔴 YouTube • Regular Streamer Test")
        youtube_regular_embed.timestamp = datetime.now()
        
        view = TestNotificationView('youtube', 'regularuser')
        
        await channel.send("**👾 TEST: YouTube Regular Streamer**", embed=youtube_regular_embed, view=view)
        
        # Test 6: TikTok Regular Streamer (NO profile image, HAS stream thumbnail)
        tiktok_regular_embed = discord.Embed(
            description="👾 RegularUser ist LIVE!\nSchaut vorbei und habt Spaß! 🌊",
            color=Config.COLORS['tiktok']
        )
        tiktok_regular_embed.set_image(url="https://picsum.photos/1920/1080?random=6")
        tiktok_regular_embed.add_field(name="👀 Zuschauer", value="321", inline=True)
        tiktok_regular_embed.add_field(name="🎮 Kategorie", value="TikTok Live", inline=True)
        tiktok_regular_embed.add_field(name="💖 Follower", value="12,789", inline=True)
        tiktok_regular_embed.set_footer(text="🔵 TikTok • Regular Streamer Test")
        tiktok_regular_embed.timestamp = datetime.now()
        
        view = TestNotificationView('tiktok', 'regularuser')
        
        await channel.send("**👾 TEST: TikTok Regular Streamer**", embed=tiktok_regular_embed, view=view)
        
        # Final summary
        summary_embed = discord.Embed(
            title="✅ Live-Benachrichtigung Tests abgeschlossen",
            description="Alle 6 Test-Nachrichten wurden gesendet:\n\n"
                       "🚨 **Karma Streamer** (Cyberpunk-Style + Profile + Buttons):\n"
                       "• 🟣 Twitch: Profilbild + Stream-Vorschau + Watch/Follow\n"
                       "• 🔴 YouTube: Profilbild + Stream-Vorschau + Watch/Follow\n" 
                       "• 🔵 TikTok: Profilbild + Stream-Vorschau + Watch/Follow\n\n"
                       "👾 **Regular Streamer** (Einfacher Style + Buttons):\n"
                       "• 🟣 Twitch: Stream-Vorschau + Watch/Follow (kein Profilbild)\n"
                       "• 🔴 YouTube: Stream-Vorschau + Watch/Follow (kein Profilbild)\n"
                       "• 🔵 TikTok: Stream-Vorschau + Watch/Follow (kein Profilbild)\n\n"
                       "**Neue Features:**\n"
                       "📺 **Watch-Button**: Direkt zum Live-Stream\n"
                       "❤️ **Follow-Button**: Zum Profil folgen\n"
                       "🖼️ **Live-Vorschau**: Stream-Thumbnails für alle\n"
                       "👤 **Profilbilder**: Nur für Karma Streamer",
            color=discord.Color.green()
        )
        
        await channel.send(embed=summary_embed)

    async def run_deletion_test(self, interaction: discord.Interaction):
        """Demo automatic message deletion functionality"""
        await interaction.response.edit_message(content="🗑️ Teste automatische Nachrichtenlöschung...", embed=None, view=None)
        
        # Get the channel where interaction was sent
        channel = interaction.channel
        
        # Send initial info
        info_embed = discord.Embed(
            title="🗑️ Auto-Löschung Test",
            description="**Demonstration der automatischen Nachrichtenlöschung**\n\n"
                       "📺 Schritt 1: Sende Test-Live-Benachrichtigung\n"
                       "⏱️ Schritt 2: Warte 5 Sekunden\n"
                       "🗑️ Schritt 3: Lösche Nachricht automatisch\n"
                       "✅ Schritt 4: Bestätigung",
            color=discord.Color.orange()
        )
        await channel.send(embed=info_embed)
        
        # Create a realistic test live notification
        test_live_embed = discord.Embed(
            description="🚨 Hey Cyber-Runner! 🚨\nTikZ aka. Zay ist jetzt LIVE auf Twitch: tikzzay!\n**Spielt gerade: Among Us** 🎮\n\n**⚠️ DIES IST EINE TEST-NACHRICHT DIE GLEICH GELÖSCHT WIRD ⚠️**",
            color=Config.COLORS['twitch']
        )
        
        # Get real Twitch profile image via dedicated API call
        real_profile_url = await self.get_twitch_profile_image("tikzzay")
        
        # Add realistic streamer branding and thumbnail with REAL profile image
        test_live_embed.set_thumbnail(url="https://static-cdn.jtvnw.net/previews-ttv/live_user_tikzzay-320x180.jpg")
        test_live_embed.set_author(
            name="TikZ aka. Zay", 
            icon_url=real_profile_url or "https://static-cdn.jtvnw.net/user-default-pictures-uv/de130ab0-def7-11e9-b668-784f43822e80-profile_image-300x300.png"
        )
        
        if not real_profile_url:
            logger.warning("⚠️ Auto-deletion test using placeholder Twitch profile image (API failed)")
        
        # Enhanced live stream data
        test_live_embed.add_field(name="👀 Zuschauer", value="892", inline=True)
        test_live_embed.add_field(name="🎮 Spiel", value="Among Us", inline=True)
        test_live_embed.add_field(name="💖 Follower", value="3,156", inline=True)
        test_live_embed.add_field(name="🔥 Daily Streak", value="7 Tage", inline=True)
        test_live_embed.add_field(name="⭐ Karma Streamer", value="Premium", inline=True)
        test_live_embed.add_field(name="🕐 Live seit", value="< 1 Min", inline=True)
        
        test_live_embed.set_footer(text="🟣 Twitch • 🧪 TEST: Auto-Löschung (wird in 5s gelöscht)")
        test_live_embed.timestamp = datetime.now()
        
        # Create test view with realistic buttons
        class TestNotificationView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=None)
                self.add_item(discord.ui.Button(label="Anschauen", emoji="📺", url="https://twitch.tv/tikzzay", style=discord.ButtonStyle.link, row=0))
                self.add_item(discord.ui.Button(label="Folgen", emoji="❤️", url="https://twitch.tv/tikzzay", style=discord.ButtonStyle.link, row=0))
        
        view = TestNotificationView()
        
        # Send the test notification and store the message
        test_message = await channel.send("**🧪 TEST-LIVE-BENACHRICHTIGUNG**", embed=test_live_embed, view=view)
        
        # Send countdown status
        countdown_embed = discord.Embed(
            title="⏱️ Countdown läuft...",
            description=f"**Test-Nachricht ID:** `{test_message.id}`\n"
                       f"**Channel ID:** `{channel.id}`\n\n"
                       "Die Nachricht wird in **5 Sekunden** automatisch gelöscht...",
            color=discord.Color.yellow()
        )
        await channel.send(embed=countdown_embed)
        
        # Wait 5 seconds
        await asyncio.sleep(5)
        
        # Delete the test message (demonstrating the auto-deletion feature)
        try:
            await test_message.delete()
            
            # Send success confirmation
            success_embed = discord.Embed(
                title="✅ Auto-Löschung erfolgreich!",
                description="**Die Test-Live-Benachrichtigung wurde automatisch gelöscht!**\n\n"
                           "🎯 **Das passiert jetzt automatisch:**\n"
                           "• Wenn ein Stream startet → Live-Benachrichtigung wird gesendet\n"
                           "• Message-ID wird in der Datenbank gespeichert\n"
                           "• Wenn der Stream endet → Nachricht wird automatisch gelöscht\n"
                           "• Keine alten Benachrichtigungen bleiben hängen!\n\n"
                           "🛡️ **Robuste Implementierung:**\n"
                           "• Bei Fehlern wird es später erneut versucht\n"
                           "• Message-IDs werden nur bei erfolgreicher Löschung entfernt\n"
                           "• Fallback zu fetch_channel() bei Cache-Problemen",
                color=discord.Color.green()
            )
            success_embed.add_field(
                name="🔧 Technische Details",
                value=f"**Gelöschte Message-ID:** `{test_message.id}`\n"
                     f"**Deletion-Zeit:** {datetime.now().strftime('%H:%M:%S')}\n"
                     f"**Status:** Erfolgreich gelöscht",
                inline=False
            )
            await channel.send(embed=success_embed)
            
        except discord.NotFound:
            # Message was already deleted
            already_deleted_embed = discord.Embed(
                title="ℹ️ Nachricht bereits gelöscht",
                description="Die Test-Nachricht war bereits gelöscht (vermutlich manuell).\n"
                           "Dies wird auch korrekt von der Auto-Löschung behandelt.",
                color=discord.Color.blue()
            )
            await channel.send(embed=already_deleted_embed)
            
        except Exception as e:
            # Error occurred
            error_embed = discord.Embed(
                title="⚠️ Löschung fehlgeschlagen",
                description=f"**Fehler:** {str(e)}\n\n"
                           "In der echten Implementierung würde:\n"
                           "• Die Message-ID gespeichert bleiben\n"
                           "• Beim nächsten Offline-Check erneut versucht werden\n"
                           "• Retry-Mechanismus aktiviert werden",
                color=discord.Color.red()
            )
            await channel.send(embed=error_embed)

    async def run_event_test(self, interaction: discord.Interaction):
        """Demo event system"""
        embed = discord.Embed(
            title="🎮 Event-Test Demo",
            description="Event-System Demonstration",
            color=discord.Color.gold()
        )
        
        embed.add_field(
            name="📊 Beispiel-Berechnung",
            value="Creator: TestUser\n⏱️ Stream-Dauer: 6h → 60 Punkte\n🔥 Event Streak: 6 Tage → x3 Multiplikator\n🏆 Gesamt: 180 Punkte",
            inline=False
        )
        
        # Create Top 10 demo ranking with all details
        demo_rankings = [
            ("KarmaGamer99", "Twitch", "Karma", 850, 12),
            ("StreamQueen", "YouTube", "Regular", 720, 8),
            ("CyberNinja", "TikTok", "Karma", 680, 10),
            ("GamingLord", "Twitch", "Regular", 550, 6),
            ("LiveMaster", "YouTube", "Karma", 480, 9),
            ("TikTokStar", "TikTok", "Regular", 420, 5),
            ("ProStreamer", "Twitch", "Karma", 380, 7),
            ("ContentKing", "YouTube", "Regular", 320, 4),
            ("ViralGamer", "TikTok", "Karma", 280, 6),
            ("StreamRookie", "Twitch", "Regular", 180, 3)
        ]
        
        ranking_text = ""
        for i, (username, platform, streamer_type, points, streak) in enumerate(demo_rankings, 1):
            type_emoji = "⭐" if streamer_type == "Karma" else "👾"
            ranking_text += f"{i}.{type_emoji} **{username}** - {platform} - {points:,} Punkte (🔥{streak})\n"
        
        embed.add_field(
            name="🏆 Top 10 Demo Rangliste",
            value=ranking_text,
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=None)

    async def run_instant_gaming_test(self, interaction: discord.Interaction):
        """Test Instant Gaming integration mit Live-Demo Embeds für Twitch und YouTube"""
        # Import instant_gaming from main module
        try:
            from main import instant_gaming
        except ImportError:
            embed = discord.Embed(
                title="❌ Instant Gaming Integration Fehler",
                description="Integration konnte nicht geladen werden.",
                color=discord.Color.red()
            )
            await interaction.response.edit_message(embed=embed, view=None)
            return

        # Status Embed
        status_embed = discord.Embed(
            title="🎮 Instant Gaming Integration Test",
            description="**Live-Demo mit Twitch und YouTube Vorschauen**\n"
                       "🔍 Teste direkte Produktlinks mit Affiliate-Tag\n"
                       "📺 Zeige realistische Live-Benachrichtigungen",
            color=discord.Color.purple()
        )
        status_embed.add_field(name="🔌 Integration Status", value="✅ **Geladen und bereit**", inline=False)
        status_embed.set_footer(text="🎮 Teste Spiele-Suche und generiere Live-Demos...")
        
        await interaction.response.edit_message(embed=status_embed, view=None)
        
        # Test Spiele für direkte Produktlinks mit Error Handling
        test_games = ["Cyberpunk 2077", "Call of Duty Black Ops 6"]
        
        try:
            logger.info(f"🎮 Testing Instant Gaming search for: {test_games[0]}")
            cyberpunk_result = await instant_gaming.search_game(test_games[0])
            if cyberpunk_result:
                logger.info(f"✅ Found {test_games[0]} on Instant Gaming")
            else:
                logger.warning(f"❌ {test_games[0]} not found on Instant Gaming")
        except Exception as e:
            logger.error(f"❌ Error searching for {test_games[0]}: {e}")
            cyberpunk_result = None
        
        try:
            logger.info(f"🎮 Testing Instant Gaming search for: {test_games[1]}")
            cod_result = await instant_gaming.search_game(test_games[1])
            if cod_result:
                logger.info(f"✅ Found {test_games[1]} on Instant Gaming")
            else:
                logger.warning(f"❌ {test_games[1]} not found on Instant Gaming")
        except Exception as e:
            logger.error(f"❌ Error searching for {test_games[1]}: {e}")
            cod_result = None
        
        # Erstelle TWITCH Live-Demo Embed
        twitch_demo = discord.Embed(
            description="🚨 Hey Cyber-Runner! 🚨\n**TikZ aka. Zay** ist jetzt LIVE auf Twitch!\n**Spielt gerade: Cyberpunk 2077** 🎮",
            color=Config.COLORS['twitch']
        )
        
        # Get REAL Twitch profile image via dedicated API call
        tikz_profile_url = await self.get_twitch_profile_image("tikzzay")
        
        # Twitch Profilbild mit ECHTEM API-Aufruf
        twitch_demo.set_author(
            name="TikZ aka. Zay", 
            icon_url=tikz_profile_url or "https://static-cdn.jtvnw.net/user-default-pictures-uv/13e5fa74-defa-11e9-8543-784f43822e80-profile_image-300x300.png"
        )
        
        if not tikz_profile_url:
            logger.warning("⚠️ Instant Gaming test using placeholder Twitch profile (API failed)")
        twitch_demo.set_image(url="https://static-cdn.jtvnw.net/ttv-boxart/1091500-285x380.jpg")  # Cyberpunk 2077 game art
        
        # Stream Details (ohne unwanted text)
        twitch_demo.add_field(name="👀 Zuschauer", value="1,347", inline=True)
        twitch_demo.add_field(name="🎮 Spiel", value="Cyberpunk 2077", inline=True)
        twitch_demo.add_field(name="💖 Follower", value="3,256", inline=True)
        twitch_demo.add_field(name="🔥 Daily Streak", value="7 Tage", inline=True)
        
        twitch_demo.set_footer(text="🟣 Twitch • LIVE-DEMO mit Instant Gaming")
        twitch_demo.timestamp = datetime.now()
        
        # Erstelle YOUTUBE Live-Demo Embed
        youtube_demo = discord.Embed(
            description="🚨 Hey Cyber-Runner! 🚨\n**Sturmpelz** ist jetzt LIVE auf YouTube!\n**Spielt gerade: Call of Duty Black Ops 6** 🎮",
            color=Config.COLORS['youtube']
        )
        
        # Get REAL YouTube profile image via dedicated API call
        sturmpelz_profile_url = await self.get_youtube_profile_image("sturmpelz11")
        
        # YouTube Profilbild mit ECHTEM API-Aufruf
        youtube_demo.set_author(
            name="✨Sturmpelz✨", 
            icon_url=sturmpelz_profile_url or "https://yt3.ggpht.com/a/default-user=s240-c-k-c0x00ffffff-no-rj"
        )
        
        if not sturmpelz_profile_url:
            logger.warning("⚠️ Instant Gaming test using placeholder YouTube profile (API failed)")
        youtube_demo.set_image(url="https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg")  # Call of Duty gameplay thumbnail
        
        # Stream Details (ohne unwanted text)
        youtube_demo.add_field(name="👀 Zuschauer", value="892", inline=True)
        youtube_demo.add_field(name="🎮 Spiel", value="Call of Duty Black Ops 6", inline=True)
        youtube_demo.add_field(name="📺 Abonnenten", value="2,184", inline=True)
        youtube_demo.add_field(name="🔥 Daily Streak", value="4 Tage", inline=True)
        
        youtube_demo.set_footer(text="🔴 YouTube • LIVE-DEMO mit Instant Gaming")
        youtube_demo.timestamp = datetime.now()
        
        # Twitch View mit direktem Produktlink
        class TwitchInstantGamingView(discord.ui.View):
            def __init__(self, cyberpunk_link):
                super().__init__(timeout=None)
                # Standard Twitch Buttons
                self.add_item(discord.ui.Button(
                    label="Anschauen", emoji="📺", 
                    url="https://twitch.tv/tikzzay", 
                    style=discord.ButtonStyle.link, row=0
                ))
                self.add_item(discord.ui.Button(
                    label="Folgen", emoji="❤️", 
                    url="https://twitch.tv/tikzzay", 
                    style=discord.ButtonStyle.link, row=0
                ))
                # Instant Gaming Button mit direktem Produktlink
                if cyberpunk_link:
                    self.add_item(discord.ui.Button(
                        label="🎮 Cyberpunk 2077 kaufen (-65%)", emoji="💰",
                        url=cyberpunk_link,
                        style=discord.ButtonStyle.link, row=1
                    ))
        
        # YouTube View mit direktem Produktlink
        class YouTubeInstantGamingView(discord.ui.View):
            def __init__(self, cod_link):
                super().__init__(timeout=None)
                # Standard YouTube Buttons
                self.add_item(discord.ui.Button(
                    label="Anschauen", emoji="📺", 
                    url="https://youtube.com/@sturmpelz", 
                    style=discord.ButtonStyle.link, row=0
                ))
                self.add_item(discord.ui.Button(
                    label="Abonnieren", emoji="❤️", 
                    url="https://youtube.com/@sturmpelz", 
                    style=discord.ButtonStyle.link, row=0
                ))
                # Instant Gaming Button mit direktem Produktlink
                if cod_link:
                    self.add_item(discord.ui.Button(
                        label="🎮 COD Black Ops 6 kaufen (-50%)", emoji="💰",
                        url=cod_link,
                        style=discord.ButtonStyle.link, row=1
                    ))
        
        # Erstelle Views mit direkten Links (Safe Access)
        cyberpunk_link = cyberpunk_result.get('affiliate_url') if cyberpunk_result and isinstance(cyberpunk_result, dict) else None
        cod_link = cod_result.get('affiliate_url') if cod_result and isinstance(cod_result, dict) else None
        
        twitch_view = TwitchInstantGamingView(cyberpunk_link)
        youtube_view = YouTubeInstantGamingView(cod_link)
        
        # Sende die Live-Demos
        demo_header = (
            "**💰 LIVE-DEMO: Instant Gaming Integration**\n"
            "*So würden echte Live-Benachrichtigungen mit direkten Produktlinks aussehen:*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        # Update Status und sende Demos
        await interaction.edit_original_response(embed=status_embed, view=None)
        
        # Sende Twitch Demo
        await interaction.followup.send(
            content=f"{demo_header}\n\n**🟣 TWITCH LIVE-DEMO:**", 
            embed=twitch_demo, 
            view=twitch_view, 
            ephemeral=True
        )
        
        # Sende YouTube Demo
        await interaction.followup.send(
            content="**🔴 YOUTUBE LIVE-DEMO:**", 
            embed=youtube_demo, 
            view=youtube_view, 
            ephemeral=True
        )
        
        # Abschließender Status mit detaillierten Ergebnissen
        success_count = sum([1 for link in [cyberpunk_link, cod_link] if link])
        total_count = 2
        
        status_color = discord.Color.green() if success_count > 0 else discord.Color.orange()
        status_title = "✅ Instant Gaming Test Abgeschlossen" if success_count > 0 else "⚠️ Instant Gaming Test mit Warnungen"
        
        final_status = discord.Embed(
            title=status_title,
            description="**Zwei Live-Demos gesendet!**\n\n"
                       f"🔗 Cyberpunk 2077: {'✅ Direkter Link gefunden' if cyberpunk_link else '❌ Nicht gefunden/Fehler'}\n"
                       f"🔗 Call of Duty: {'✅ Direkter Link gefunden' if cod_link else '❌ Nicht gefunden/Fehler'}\n\n"
                       f"📊 **Erfolgsrate:** {success_count}/{total_count} Spiele\n"
                       f"🏷️ **Affiliate Tag:** `{instant_gaming.affiliate_tag}`\n\n"
                       f"💡 **Demo-Status:** Live-Embeds wurden gesendet {'mit Kaufbuttons' if success_count > 0 else 'ohne Kaufbuttons (Fallback)'}",
            color=status_color
        )
        
        if success_count == 0:
            final_status.add_field(
                name="🔧 Troubleshooting",
                value="Keine direkten Produktlinks gefunden. Mögliche Ursachen:\n"
                      "• Temporäre Netzwerkprobleme\n"
                      "• Instant Gaming Website-Änderungen\n"
                      "• Spiel momentan nicht verfügbar\n"
                      "➜ Demo-Embeds funktionieren trotzdem!",
                inline=False
            )
        
        final_status.set_footer(text="🎮 Integration getestet - Demo vollständig")
        final_status.timestamp = datetime.now()
        
        await interaction.followup.send(embed=final_status, ephemeral=True)

    async def show_leave_server_modal(self, interaction: discord.Interaction):
        """Show modal for Leave-Server function"""
        modal = LeaveServerModal(self.bot)
        await interaction.response.send_modal(modal)

    async def show_server_unban_modal(self, interaction: discord.Interaction):
        """Show modal for Server-Unban function"""  
        modal = ServerUnbanModal(self.bot)
        await interaction.response.send_modal(modal)


class LeaveServerModal(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title='Bot Server verlassen')
        self.bot = bot

    server_id = discord.ui.TextInput(
        label='Server ID',
        placeholder='Geben Sie die Server ID ein...',
        required=True,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            guild_id = int(self.server_id.value)
            guild = self.bot.get_guild(guild_id)
            
            if not guild:
                await interaction.response.send_message(
                    f"❌ Server mit ID `{guild_id}` nicht gefunden oder Bot ist nicht Mitglied.",
                    ephemeral=True
                )
                return
            
            # Create confirmation view
            view = LeaveServerConfirmView(self.bot, guild)
            
            embed = discord.Embed(
                title="⚠️ Server verlassen - Bestätigung",
                description="**Sind Sie sicher, dass der Bot folgenden Server verlassen soll?**",
                color=discord.Color.orange()
            )
            
            # Server-Informationen als separate Felder für bessere Übersichtlichkeit
            embed.add_field(
                name="📋 Server-Details",
                value=f"🔹 **Name:** {guild.name}\n"
                     f"🆔 **ID:** {guild.id}\n"
                     f"👥 **Mitglieder:** {guild.member_count:,}\n"
                     f"👑 **Besitzer:** {guild.owner.display_name if guild.owner else 'Unbekannt'}",
                inline=False
            )
            
            embed.add_field(
                name="⚠️ Warnung",
                value="**Diese Aktion kann nicht rückgängig gemacht werden!**",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message(
                "❌ Ungültige Server ID. Bitte geben Sie eine gültige Zahl ein.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Fehler beim Verarbeiten der Anfrage: {str(e)[:100]}",
                ephemeral=True
            )


class LeaveServerConfirmView(discord.ui.View):
    def __init__(self, bot, guild):
        super().__init__(timeout=60)
        self.bot = bot
        self.guild = guild

    @discord.ui.button(label='✅ Bestätigen', style=discord.ButtonStyle.danger)
    async def confirm_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            guild_name = self.guild.name
            await self.guild.leave()
            
            embed = discord.Embed(
                title="✅ Server verlassen",
                description=f"Bot hat erfolgreich den Server **{guild_name}** (ID: {self.guild.id}) verlassen.",
                color=discord.Color.green()
            )
            
            await interaction.response.edit_message(embed=embed, view=None)
            
        except Exception as e:
            embed = discord.Embed(
                title="❌ Fehler beim Verlassen",
                description=f"Fehler beim Verlassen des Servers: {str(e)[:200]}",
                color=discord.Color.red()
            )
            await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label='❌ Abbrechen', style=discord.ButtonStyle.secondary)
    async def cancel_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="❌ Abgebrochen",
            description="Server-Verlassen wurde abgebrochen.",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=None)


class ServerUnbanModal(discord.ui.Modal):
    def __init__(self, bot):
        super().__init__(title='Server Unban')
        self.bot = bot

    server_id = discord.ui.TextInput(
        label='Server ID',
        placeholder='Geben Sie die Server ID ein...',
        required=True,
        max_length=20
    )
    
    user_id = discord.ui.TextInput(
        label='User ID',
        placeholder='Geben Sie die User ID ein...',
        required=True,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            guild_id = int(self.server_id.value)
            user_id = int(self.user_id.value)
            
            guild = self.bot.get_guild(guild_id)
            if not guild:
                await interaction.response.send_message(
                    f"❌ Server mit ID `{guild_id}` nicht gefunden oder Bot ist nicht Mitglied.",
                    ephemeral=True
                )
                return
            
            # Check if bot has ban permissions
            if not guild.me.guild_permissions.ban_members:
                await interaction.response.send_message(
                    f"❌ Bot hat keine Berechtigung zum Entbannen auf Server **{guild.name}**.",
                    ephemeral=True
                )
                return
            
            # Try to get user info
            try:
                user = await self.bot.fetch_user(user_id)
                user_name = f"{user.name} ({user.id})"
            except:
                user_name = f"User ID: {user_id}"
            
            # Try to unban
            try:
                await guild.unban(discord.Object(id=user_id), reason="Unban via Bot Developer Command")
                
                embed = discord.Embed(
                    title="✅ Erfolgreich entbannt",
                    description="User wurde erfolgreich entbannt.",
                    color=discord.Color.green()
                )
                
                # Details als separate Felder für bessere Übersichtlichkeit
                embed.add_field(
                    name="👤 User-Details",
                    value=f"**Name:** {user_name}",
                    inline=False
                )
                
                embed.add_field(
                    name="🏠 Server-Details",
                    value=f"**Name:** {guild.name}\n**ID:** {guild.id}",
                    inline=False
                )
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
            except discord.NotFound:
                await interaction.response.send_message(
                    f"❌ User `{user_name}` ist nicht auf Server **{guild.name}** gebannt.",
                    ephemeral=True
                )
            except discord.Forbidden:
                await interaction.response.send_message(
                    f"❌ Keine Berechtigung zum Entbannen auf Server **{guild.name}**.",
                    ephemeral=True
                )
            except Exception as e:
                await interaction.response.send_message(
                    f"❌ Fehler beim Entbannen: {str(e)[:100]}",
                    ephemeral=True
                )
                
        except ValueError:
            await interaction.response.send_message(
                "❌ Ungültige ID. Bitte geben Sie gültige Zahlen ein.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Fehler beim Verarbeiten der Anfrage: {str(e)[:100]}",
                ephemeral=True
            )


class LiveStreamView(discord.ui.View):
    def __init__(self, stream_data):
        super().__init__(timeout=None)
        self.stream_data = stream_data
        
        # Add watch buttons for each live stream (max 25 buttons)
        for i, stream in enumerate(stream_data[:25]):
            platform = stream['platform']
            username = stream['username']
            display_name = stream['display_name']
            
            # Platform-specific URLs
            if platform == 'twitch':
                url = f"https://twitch.tv/{username}"
                emoji = "🟣"
            elif platform == 'youtube':
                url = f"https://youtube.com/@{username}/live"
                emoji = "🔴"
            elif platform == 'tiktok':
                url = f"https://tiktok.com/@{username}/live"
                emoji = "🔵"
            else:
                continue
            
            # Create button with emoji and short name
            button_label = f"{display_name[:15]}"  # Truncate long names
            button = discord.ui.Button(
                label=button_label,
                emoji=emoji,
                url=url,
                style=discord.ButtonStyle.link,
                row=i // 5  # 5 buttons per row
            )
            
            self.add_item(button)