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

logger = logging.getLogger('KARMA-LiveBOT.events')

# Configuration
class Config:
    ADMIN_ROLES = [1388945013735424020, 581139700408909864, 898970074491269170]
    USER_ROLES = [292321283608150016, 276471077402705920]  # Beide normale User-Rollen
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

class EventCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db

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
                    "`/testbot` - Bot-Tests durchführen"
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

    @app_commands.command(name="testbot", description="Bot-Funktionen testen")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    async def test_bot(self, interaction: discord.Interaction):
        """Test bot functions"""
        try:
            view = TestBotView(self.db)
            
            embed = discord.Embed(
                title="🧪 Bot Test-Menü",
                description="Wählen Sie einen Test aus:",
                color=discord.Color.purple()
            )
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            logger.info(f"✅ TestBot command executed successfully for {interaction.user}")
            
        except discord.errors.NotFound:
            # Interaction timeout or already responded
            logger.warning(f"❌ TestBot interaction timeout/expired for {interaction.user}")
            try:
                # Try followup if response already sent
                await interaction.followup.send("⚠️ Bot Test konnte nicht geladen werden. Versuchen Sie es erneut.", ephemeral=True)
            except:
                pass
        except Exception as e:
            logger.error(f"❌ TestBot command error for {interaction.user}: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Fehler beim Laden des Test-Menüs.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Fehler beim Laden des Test-Menüs.", ephemeral=True)
            except:
                pass

class TestBotView(discord.ui.View):
    def __init__(self, db):
        super().__init__(timeout=300)
        self.db = db

    @discord.ui.select(
        placeholder="Test auswählen...",
        options=[
            discord.SelectOption(label="API-Test", value="api_test", emoji="🔌"),
            discord.SelectOption(label="Live-Benachrichtigung", value="live_demo", emoji="📺"),
            discord.SelectOption(label="Event-Test", value="event_test", emoji="🎮")
        ]
    )
    async def select_test(self, interaction: discord.Interaction, select: discord.ui.Select):
        test_type = select.values[0]
        
        if test_type == "api_test":
            await self.run_api_test(interaction)
        elif test_type == "live_demo":
            await self.run_live_demo(interaction)
        elif test_type == "event_test":
            await self.run_event_test(interaction)

    async def run_api_test(self, interaction: discord.Interaction):
        """Test API connections"""
        embed = discord.Embed(
            title="🔌 API Test Ergebnisse",
            color=discord.Color.blue()
        )
        
        # Test Twitch API
        import os
        twitch_status = "✅ OK" if os.getenv('TWITCH_CLIENT_ID') and os.getenv('TWITCH_CLIENT_SECRET') else "❌ Fehlt"
        embed.add_field(name="Twitch API", value=twitch_status, inline=True)
        
        # Test YouTube API
        youtube_status = "✅ OK" if os.getenv('YOUTUBE_API_KEY') else "❌ Fehlt"
        embed.add_field(name="YouTube API", value=youtube_status, inline=True)
        
        # Test TikTok (Web Scraping)
        tiktok_status = "✅ OK (Web Scraping)" 
        embed.add_field(name="TikTok Detection", value=tiktok_status, inline=True)
        
        # Test Discord connection
        discord_status = "✅ OK" if interaction.guild else "❌ Fehler"
        embed.add_field(name="Discord Connection", value=discord_status, inline=True)
        
        # Database test
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM creators')
            creator_count = cursor.fetchone()[0]
            conn.close()
            db_status = f"✅ OK ({creator_count} Creators)"
        except Exception as e:
            db_status = f"❌ Fehler: {str(e)[:50]}"
        
        embed.add_field(name="Datenbank", value=db_status, inline=False)
        
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