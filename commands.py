"""
Slash Commands für den KARMA-LiveBOT
"""

import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
from typing import List, Optional
import logging
from datetime import datetime, timedelta

logger = logging.getLogger('KARMA-LiveBOT.commands')

# Configuration class (copied from main to avoid circular imports)
class Config:
    # Discord IDs aus der Spezifikation
    ADMIN_ROLES = [1388945013735424020, 581139700408909864, 898970074491269170]
    USER_ROLES = [292321283608150016, 276471077402705920]  # Beide normale User-Rollen
    REGULAR_STREAMER_ROLE = 898194971029561344
    KARMA_STREAMER_ROLE = 898971225311838268
    LIVE_ROLE = 899306754549108786
    STREAMER_REQUESTS_CHANNEL = 1420132930436595815  # Channel für Streamer-Anfragen
    
    # Platform Colors
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

class CreatorManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db

    @app_commands.command(name="addcreator", description="Creator hinzufügen und konfigurieren")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    async def add_creator(self, interaction: discord.Interaction):
        """Add creator command - shows modal for input"""
        modal = AddCreatorModal(self.db)
        await interaction.response.send_modal(modal)
    
    @app_commands.command(name="request", description="Anfrage stellen um als Streamer hinzugefügt zu werden")
    @has_user_role()
    async def request_creator(self, interaction: discord.Interaction):
        """Request to be added as creator - shows modal for input"""
        modal = RequestCreatorModal(self.bot, self.db)
        await interaction.response.send_modal(modal)
    
    @app_commands.command(name="requeststatus", description="Status der Streamer-Anfrage prüfen")
    @has_user_role()
    @app_commands.describe(user="Discord User (optional - standardmäßig du selbst)")
    async def request_status(self, interaction: discord.Interaction, user: discord.Member = None):
        """Check if a Discord user is already added as creator"""
        # Use provided user or default to command user
        target_user = user if user else interaction.user
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Search by user ID (unique and reliable)
            cursor.execute('SELECT discord_username, streamer_type FROM creators WHERE discord_user_id = ?', 
                          (str(target_user.id),))
            creator = cursor.fetchone()
            
            if creator:
                embed = discord.Embed(
                    title="✅ Streamer Status",
                    description=f"**{target_user.display_name}** ist bereits als **{creator[1].title()}** Streamer hinzugefügt!",
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title="❌ Streamer Status", 
                    description=f"**{target_user.display_name}** ist noch nicht als Streamer hinzugefügt.\n\nVerwende `/request` um eine Anfrage zu stellen!",
                    color=discord.Color.red()
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error checking request status: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Prüfen des Status.",
                ephemeral=True
            )
        finally:
            conn.close()

    @app_commands.command(name="deletecreator", description="Creator entfernen")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    async def delete_creator(self, interaction: discord.Interaction, discord_user: discord.Member):
        """Delete creator command"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Check if creator exists
        cursor.execute('SELECT id FROM creators WHERE discord_user_id = ?', (str(discord_user.id),))
        creator = cursor.fetchone()
        
        if not creator:
            await interaction.response.send_message(
                f"❌ Creator {discord_user.mention} ist nicht in der Datenbank registriert.",
                ephemeral=True
            )
            conn.close()
            return
        
        creator_id = creator[0]
        
        # Delete all related data
        cursor.execute('DELETE FROM user_subscriptions WHERE creator_id = ?', (creator_id,))
        cursor.execute('DELETE FROM live_status WHERE creator_id = ?', (creator_id,))
        cursor.execute('DELETE FROM event_streaks WHERE creator_id = ?', (creator_id,))
        cursor.execute('DELETE FROM daily_streaks WHERE creator_id = ?', (creator_id,))
        cursor.execute('DELETE FROM creator_channels WHERE creator_id = ?', (creator_id,))
        cursor.execute('DELETE FROM creators WHERE id = ?', (creator_id,))
        
        conn.commit()
        conn.close()
        
        embed = discord.Embed(
            title="✅ Creator entfernt",
            description=f"Creator {discord_user.mention} und alle zugehörigen Daten wurden erfolgreich entfernt.",
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed)

class AddCreatorModal(discord.ui.Modal):
    def __init__(self, db):
        super().__init__(title='Creator hinzufügen')
        self.db = db

    discord_user = discord.ui.TextInput(
        label='Discord Username',
        placeholder='@username oder User ID eingeben',
        required=True
    )
    
    twitch_username = discord.ui.TextInput(
        label='Twitch Username',
        placeholder='Twitch Username (optional)',
        required=False
    )
    
    youtube_username = discord.ui.TextInput(
        label='YouTube Username',
        placeholder='YouTube @username (optional)',
        required=False
    )
    
    tiktok_username = discord.ui.TextInput(
        label='TikTok Username',
        placeholder='TikTok Username (optional)',
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        # First, validate all provided usernames
        await interaction.response.defer(ephemeral=True)
        
        validation_errors = []
        
        # Import validation functions from main
        from main import validate_username
        
        # Validate each platform username if provided
        if self.twitch_username.value and self.twitch_username.value.strip():
            twitch_valid = await validate_username('twitch', self.twitch_username.value.strip())
            if not twitch_valid:
                validation_errors.append(f"🟣 Twitch: Username '{self.twitch_username.value}' existiert nicht")
        
        if self.youtube_username.value and self.youtube_username.value.strip():
            youtube_valid = await validate_username('youtube', self.youtube_username.value.strip())
            if not youtube_valid:
                validation_errors.append(f"🔴 YouTube: Username/Channel '{self.youtube_username.value}' existiert nicht")
        
        if self.tiktok_username.value and self.tiktok_username.value.strip():
            tiktok_valid = await validate_username('tiktok', self.tiktok_username.value.strip())
            if not tiktok_valid:
                validation_errors.append(f"🔵 TikTok: Username '{self.tiktok_username.value}' existiert nicht")
        
        # If validation errors, show them and stop
        if validation_errors:
            error_embed = discord.Embed(
                title="❌ Username-Validierung fehlgeschlagen",
                description="Die folgenden Benutzernamen konnten nicht gefunden werden:",
                color=discord.Color.red()
            )
            error_embed.add_field(
                name="Fehler:",
                value="\n".join(validation_errors),
                inline=False
            )
            error_embed.add_field(
                name="💡 Hinweis:",
                value="Bitte überprüfen Sie die Schreibweise und versuchen Sie es erneut.",
                inline=False
            )
            
            await interaction.followup.send(embed=error_embed, ephemeral=True)
            return
        
        # All validations passed, create config view
        view = CreatorConfigView(self.db, {
            'discord_user': self.discord_user.value,
            'twitch_username': self.twitch_username.value or None,
            'youtube_username': self.youtube_username.value or None,
            'tiktok_username': self.tiktok_username.value or None
        })
        
        embed = discord.Embed(
            title="✅ Validierung erfolgreich",
            description="Bitte wählen Sie den Streamer-Typ und den Benachrichtigungs-Channel:",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Discord User", 
            value=self.discord_user.value, 
            inline=False
        )
        
        platforms = []
        if self.twitch_username.value:
            platforms.append(f"🟣 Twitch: {self.twitch_username.value} ✅")
        if self.youtube_username.value:
            platforms.append(f"🔴 YouTube: {self.youtube_username.value} ✅")
        if self.tiktok_username.value:
            platforms.append(f"🔵 TikTok: {self.tiktok_username.value} ✅")
        
        if platforms:
            embed.add_field(
                name="Validierte Plattformen",
                value="\n".join(platforms),
                inline=False
            )
        
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

class RequestCreatorModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, db):
        super().__init__(title='Streamer-Anfrage stellen')
        self.bot = bot
        self.db = db

    # Remove discord_user field - we'll use interaction.user automatically
    
    twitch_username = discord.ui.TextInput(
        label='Twitch Username',
        placeholder='Dein Twitch Username (optional)',
        required=False
    )
    
    youtube_username = discord.ui.TextInput(
        label='YouTube Username',
        placeholder='Dein YouTube @username (optional)',
        required=False
    )
    
    tiktok_username = discord.ui.TextInput(
        label='TikTok Username',
        placeholder='Dein TikTok Username (optional)',
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Check if user already exists
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT discord_username FROM creators WHERE discord_user_id = ?', 
                          (str(interaction.user.id),))
            existing = cursor.fetchone()
            
            if existing:
                await interaction.response.send_message(
                    f"❌ Du bist bereits als Streamer registriert: **{existing[0]}**",
                    ephemeral=True
                )
                return
                
            # Create embed for the request
            embed = discord.Embed(
                title="📝 Neue Streamer-Anfrage",
                description=f"**{interaction.user.mention}** möchte als Streamer hinzugefügt werden:",
                color=discord.Color.orange()
            )
            
            embed.add_field(
                name="Discord User", 
                value=f"{interaction.user.display_name} ({interaction.user.mention})\nUser ID: {interaction.user.id}", 
                inline=False
            )
            
            platforms = []
            if self.twitch_username.value:
                platforms.append(f"🟣 **Twitch:** {self.twitch_username.value}")
            if self.youtube_username.value:
                platforms.append(f"🔴 **YouTube:** {self.youtube_username.value}")
            if self.tiktok_username.value:
                platforms.append(f"🔵 **TikTok:** {self.tiktok_username.value}")
            
            if platforms:
                embed.add_field(
                    name="Plattformen",
                    value="\n".join(platforms),
                    inline=False
                )
            else:
                embed.add_field(
                    name="Plattformen",
                    value="❌ Keine Plattformen angegeben",
                    inline=False
                )
            
            embed.add_field(
                name="💡 Nächste Schritte", 
                value=f"Verwende `/addcreator` und gib folgende Daten ein:\n**Discord User:** {interaction.user.mention} (ID: {interaction.user.id})\n**Usernames:** Wie oben angegeben", 
                inline=False
            )
            embed.set_footer(text=f"Angefragt am {datetime.now().strftime('%d.%m.%Y um %H:%M')} Uhr")
            
            # Send to requests channel
            try:
                requests_channel = self.bot.get_channel(Config.STREAMER_REQUESTS_CHANNEL)
                if requests_channel:
                    await requests_channel.send(embed=embed)
                    
                    # Confirm to user
                    await interaction.response.send_message(
                        "✅ **Anfrage erfolgreich eingereicht!**\n\nDeine Anfrage wurde an die Moderatoren weitergeleitet. Du erhältst eine Benachrichtigung, sobald du als Streamer hinzugefügt wurdest.\n\nPrüfe deinen Status mit `/requeststatus`!",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "❌ Fehler: Requests-Channel nicht gefunden. Bitte kontaktiere einen Admin.",
                        ephemeral=True
                    )
            except Exception as e:
                logger.error(f"Error sending request to channel: {e}")
                await interaction.response.send_message(
                    "❌ Fehler beim Senden der Anfrage. Bitte versuche es später erneut.",
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Error processing creator request: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Verarbeiten der Anfrage.",
                ephemeral=True
            )
        finally:
            conn.close()

class CreatorConfigView(discord.ui.View):
    def __init__(self, db, creator_data: dict):
        super().__init__(timeout=300)
        self.db = db
        self.creator_data = creator_data
        self.selected_streamer_type = None
        self.selected_channels = {}  # Platform-specific channels: {'twitch': channel, 'youtube': channel, 'tiktok': channel}
        
        # Identify available platforms
        self.platforms_with_usernames = []
        if creator_data.get('twitch_username'):
            self.platforms_with_usernames.append('twitch')
        if creator_data.get('youtube_username'):
            self.platforms_with_usernames.append('youtube')
        if creator_data.get('tiktok_username'):
            self.platforms_with_usernames.append('tiktok')

    @discord.ui.select(
        placeholder="Streamer-Typ auswählen...",
        options=[
            discord.SelectOption(label="Karma Streamer", value="karma", emoji="⭐"),
            discord.SelectOption(label="Regular Streamer", value="regular", emoji="👾")
        ]
    )
    async def select_streamer_type(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.selected_streamer_type = select.values[0]
        
        # Update embed
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(
            title="Creator Konfiguration", color=discord.Color.blue()
        )
        
        # Add streamer type field
        embed.add_field(
            name="✅ Streamer-Typ",
            value=f"{'⭐ Karma Streamer' if self.selected_streamer_type == 'karma' else '👾 Regular Streamer'}",
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="➡️ Channels konfigurieren", style=discord.ButtonStyle.primary, row=1)
    async def configure_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_streamer_type:
            await interaction.response.send_message("❌ Bitte wählen Sie zuerst einen Streamer-Typ!", ephemeral=True)
            return
        
        # Show multi-platform channel selection
        channel_view = MultiChannelView(self.db, self.creator_data, self.selected_streamer_type, self.platforms_with_usernames)
        
        embed = discord.Embed(
            title=f"📺 Channel-Konfiguration für {self.creator_data['discord_user']}",
            description="Wählen Sie für jede Plattform einen eigenen Benachrichtigungs-Channel:",
            color=discord.Color.blue()
        )
        
        # Show platforms to configure
        platforms_text = []
        emojis = {'twitch': '🟣', 'youtube': '🔴', 'tiktok': '🔵'}
        for platform in self.platforms_with_usernames:
            username = self.creator_data.get(f'{platform}_username')
            platforms_text.append(f"{emojis[platform]} {platform.title()}: {username}")
        
        embed.add_field(name="Plattformen", value="\n".join(platforms_text), inline=False)
        embed.add_field(
            name="Typ", 
            value=f"{'⭐ Karma Streamer' if self.selected_streamer_type == 'karma' else '👾 Regular Streamer'}",
            inline=True
        )
        
        await interaction.response.edit_message(embed=embed, view=channel_view)


class MultiChannelView(discord.ui.View):
    def __init__(self, db, creator_data: dict, streamer_type: str, platforms: list):
        super().__init__(timeout=300)
        self.db = db
        self.creator_data = creator_data
        self.streamer_type = streamer_type
        self.platforms = platforms
        self.selected_channels = {}
        
        # Add channel selectors based on available platforms
        if 'twitch' in platforms:
            self.add_item(TwitchChannelSelect())
        if 'youtube' in platforms:
            self.add_item(YouTubeChannelSelect())
        if 'tiktok' in platforms:
            self.add_item(TikTokChannelSelect())
        
        # Add save button
        save_btn = discord.ui.Button(label="💾 Speichern", style=discord.ButtonStyle.success, row=4)
        save_btn.callback = self.save_creator
        self.add_item(save_btn)

    async def save_creator(self, interaction: discord.Interaction):
        """Save creator with platform-specific channels"""
        if not self.selected_channels:
            await interaction.response.send_message(
                "❌ Bitte wählen Sie mindestens einen Channel aus!",
                ephemeral=True
            )
            return
        
        # Parse Discord user
        discord_user_str = self.creator_data['discord_user']
        discord_user = None
        
        # Try to get user by mention or ID
        if discord_user_str.startswith('<@') and discord_user_str.endswith('>'):
            user_id = discord_user_str[2:-1].replace('!', '')
            try:
                discord_user = interaction.guild.get_member(int(user_id))
            except:
                pass
        else:
            # Try to find by username or ID
            try:
                user_id = int(discord_user_str)
                if interaction.guild:
                    discord_user = interaction.guild.get_member(user_id)
            except:
                # Search by username
                if interaction.guild and interaction.guild.members:
                    for member in interaction.guild.members:
                        if member.name.lower() == discord_user_str.lower() or member.display_name.lower() == discord_user_str.lower():
                            discord_user = member
                            break
        
        if not discord_user:
            await interaction.response.send_message(
                f"❌ Discord User '{discord_user_str}' konnte nicht gefunden werden.",
                ephemeral=True
            )
            return
        
        # Save to database
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Get first selected channel for legacy notification_channel_id (backward compatibility)
            first_channel_id = list(self.selected_channels.values())[0].id if self.selected_channels else "0"
            
            # Insert or update creator
            cursor.execute('''
                INSERT OR IGNORE INTO creators 
                (discord_user_id, discord_username, streamer_type, notification_channel_id, 
                 twitch_username, youtube_username, tiktok_username)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(discord_user.id),
                discord_user.display_name,
                self.streamer_type,
                str(first_channel_id),
                self.creator_data['twitch_username'],
                self.creator_data['youtube_username'],
                self.creator_data['tiktok_username']
            ))
            
            # Get creator ID
            cursor.execute('SELECT id FROM creators WHERE discord_user_id = ?', (str(discord_user.id),))
            creator_result = cursor.fetchone()
            if not creator_result:
                raise Exception("Failed to get creator ID")
            creator_id = creator_result[0]
            
            # Update existing creator if needed
            cursor.execute('''
                UPDATE creators 
                SET discord_username = ?, streamer_type = ?, notification_channel_id = ?,
                    twitch_username = ?, youtube_username = ?, tiktok_username = ?
                WHERE discord_user_id = ?
            ''', (
                discord_user.display_name,
                self.streamer_type,
                str(first_channel_id),
                self.creator_data['twitch_username'],
                self.creator_data['youtube_username'],
                self.creator_data['tiktok_username'],
                str(discord_user.id)
            ))
            
            # Clear existing platform channels for this creator
            cursor.execute('DELETE FROM creator_channels WHERE creator_id = ?', (creator_id,))
            
            # Insert platform-specific channels
            for platform, channel in self.selected_channels.items():
                cursor.execute('''
                    INSERT INTO creator_channels (creator_id, platform, channel_id)
                    VALUES (?, ?, ?)
                ''', (creator_id, platform, str(channel.id)))
            
            # Initialize streak data for Karma streamers
            if self.streamer_type == 'karma':
                cursor.execute('''
                    INSERT OR REPLACE INTO daily_streaks (creator_id, current_streak)
                    VALUES (?, 0)
                ''', (creator_id,))
            
            # Initialize event streak data for both types
            cursor.execute('''
                INSERT OR REPLACE INTO event_streaks (creator_id, current_event_streak, event_points)
                VALUES (?, 0, 0)
            ''', (creator_id,))
            
            conn.commit()
            
            # Success message
            embed = discord.Embed(
                title="✅ Creator erfolgreich hinzugefügt!",
                description=f"**{discord_user.display_name}** wurde als {'⭐ Karma' if self.streamer_type == 'karma' else '👾 Regular'} Streamer hinzugefügt.",
                color=discord.Color.green()
            )
            
            # Show configured channels
            channel_info = []
            emojis = {'twitch': '🟣', 'youtube': '🔴', 'tiktok': '🔵'}
            for platform, channel in self.selected_channels.items():
                channel_info.append(f"{emojis[platform]} {platform.title()}: {channel.mention}")
            
            embed.add_field(name="Konfigurierte Channels", value="\n".join(channel_info), inline=False)
            embed.add_field(name="Plattformen", value=f"{len(self.platforms)} Plattform{'en' if len(self.platforms) > 1 else ''}", inline=True)
            
            await interaction.response.edit_message(embed=embed, view=None)
            
        except Exception as e:
            logger.error(f"Error saving creator: {e}")
            await interaction.response.send_message(
                f"❌ Fehler beim Speichern des Creators: {str(e)}",
                ephemeral=True
            )
        finally:
            conn.close()

# Simple channel selectors for each platform
class TwitchChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="🟣 Twitch Channel auswählen...",
            channel_types=[discord.ChannelType.text],
            row=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        # Store selection in parent view
        self.view.selected_channels['twitch'] = self.values[0]
        await interaction.response.send_message(f"✅ Twitch Channel: {self.values[0].mention}", ephemeral=True)

class YouTubeChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="🔴 YouTube Channel auswählen...",
            channel_types=[discord.ChannelType.text],
            row=2
        )
    
    async def callback(self, interaction: discord.Interaction):
        # Store selection in parent view
        self.view.selected_channels['youtube'] = self.values[0]
        await interaction.response.send_message(f"✅ YouTube Channel: {self.values[0].mention}", ephemeral=True)

class TikTokChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="🔵 TikTok Channel auswählen...",
            channel_types=[discord.ChannelType.text],
            row=3
        )
    
    async def callback(self, interaction: discord.Interaction):
        # Store selection in parent view
        self.view.selected_channels['tiktok'] = self.values[0]
        await interaction.response.send_message(f"✅ TikTok Channel: {self.values[0].mention}", ephemeral=True)


# End of channel selectors


class ChannelSelectionView(discord.ui.View):
    def __init__(self, db, creator_data: dict, streamer_type: str, platforms: list):
        super().__init__(timeout=300)
        self.db = db
        self.creator_data = creator_data
        self.streamer_type = streamer_type
        self.platforms = platforms
        self.selected_channels = {}
        self.current_platform_index = 0
        
        self._setup_current_platform()
    
    def _setup_current_platform(self):
        """Setup UI for current platform selection"""
        self.clear_items()
        
        if self.current_platform_index >= len(self.platforms):
            self._setup_final_view()
            return
        
        platform = self.platforms[self.current_platform_index]
        emojis = {'twitch': '🟣', 'youtube': '🔴', 'tiktok': '🔵'}
        
        # Add channel selector for current platform
        channel_select = discord.ui.ChannelSelect(
            placeholder=f"{emojis[platform]} {platform.title()} Channel auswählen...",
            channel_types=[discord.ChannelType.text]
        )
        channel_select.callback = self._channel_selected
        self.add_item(channel_select)
        
        # Add skip button if more than one platform
        if len(self.platforms) > 1:
            skip_btn = discord.ui.Button(
                label=f"{platform.title()} überspringen",
                style=discord.ButtonStyle.secondary,
                emoji="⏭️"
            )
            skip_btn.callback = self._skip_platform
            self.add_item(skip_btn)
    
    async def _channel_selected(self, interaction: discord.Interaction):
        """Handle channel selection for current platform"""
        platform = self.platforms[self.current_platform_index]
        self.selected_channels[platform] = interaction.data['values'][0]
        
        # Move to next platform
        self.current_platform_index += 1
        self._setup_current_platform()
        
        # Update embed
        embed = await self._create_progress_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def _skip_platform(self, interaction: discord.Interaction):
        """Skip current platform"""
        self.current_platform_index += 1
        self._setup_current_platform()
        
        embed = await self._create_progress_embed()
        await interaction.response.edit_message(embed=embed, view=self)
    
    def _setup_final_view(self):
        """Setup final confirmation view"""
        self.clear_items()
        
        # Add save button
        save_btn = discord.ui.Button(
            label="Speichern",
            style=discord.ButtonStyle.success,
            emoji="💾"
        )
        save_btn.callback = self._save_creator
        self.add_item(save_btn)
    
    async def _create_progress_embed(self):
        """Create embed showing current progress"""
        if self.current_platform_index >= len(self.platforms):
            # Final summary
            embed = discord.Embed(
                title="✅ Channel-Auswahl abgeschlossen",
                description="Bereit zum Speichern!",
                color=discord.Color.green()
            )
        else:
            platform = self.platforms[self.current_platform_index]
            remaining = len(self.platforms) - self.current_platform_index
            embed = discord.Embed(
                title=f"📺 {platform.title()} Channel auswählen",
                description=f"Noch {remaining} Plattform{'en' if remaining > 1 else ''} zu konfigurieren",
                color=discord.Color.blue()
            )
        
        # Show selected channels so far
        if self.selected_channels:
            channel_text = []
            emojis = {'twitch': '🟣', 'youtube': '🔴', 'tiktok': '🔵'}
            for platform, channel_id in self.selected_channels.items():
                # We'll use channel mentions directly since we don't have guild context
                channel_mention = f"<#{channel_id}>" if channel_id else "Unbekannt"
                channel_text.append(f"{emojis[platform]} {platform.title()}: {channel_mention}")
            
            embed.add_field(
                name="Ausgewählte Channels",
                value="\n".join(channel_text),
                inline=False
            )
        
        return embed

    async def _save_creator(self, interaction: discord.Interaction):
        """Save creator with platform-specific channels"""
        if not self.selected_channels:
            await interaction.response.send_message(
                "❌ Mindestens ein Channel muss ausgewählt werden.",
                ephemeral=True
            )
            return
        
        # Parse Discord user
        discord_user_str = self.creator_data['discord_user']
        discord_user = None
        
        # Try to get user by mention or ID
        if discord_user_str.startswith('<@') and discord_user_str.endswith('>'):
            user_id = discord_user_str[2:-1].replace('!', '')
            try:
                discord_user = interaction.guild.get_member(int(user_id))
            except:
                pass
        else:
            # Try to find by username or ID
            try:
                user_id = int(discord_user_str)
                if interaction.guild:
                    discord_user = interaction.guild.get_member(user_id)
            except:
                # Search by username
                if interaction.guild and interaction.guild.members:
                    for member in interaction.guild.members:
                        if member.name.lower() == discord_user_str.lower() or member.display_name.lower() == discord_user_str.lower():
                            discord_user = member
                            break
        
        if not discord_user:
            await interaction.response.send_message(
                f"❌ Discord User '{discord_user_str}' konnte nicht gefunden werden.",
                ephemeral=True
            )
            return
        
        # Validate that we have the required platforms (removed duplicate logic)
        
        # Save to database
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Get first selected channel for legacy notification_channel_id (backward compatibility)
            first_channel_id = list(self.selected_channels.values())[0].id if self.selected_channels else "0"
            
            # Insert or update creator
            cursor.execute('''
                INSERT OR IGNORE INTO creators 
                (discord_user_id, discord_username, streamer_type, notification_channel_id, 
                 twitch_username, youtube_username, tiktok_username)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(discord_user.id),
                discord_user.display_name,
                self.streamer_type,
                str(first_channel_id),
                self.creator_data['twitch_username'],
                self.creator_data['youtube_username'],
                self.creator_data['tiktok_username']
            ))
            
            # Get creator ID
            cursor.execute('SELECT id FROM creators WHERE discord_user_id = ?', (str(discord_user.id),))
            creator_id = cursor.fetchone()[0]
            
            # Update existing creator if needed
            cursor.execute('''
                UPDATE creators 
                SET discord_username = ?, streamer_type = ?, notification_channel_id = ?,
                    twitch_username = ?, youtube_username = ?, tiktok_username = ?
                WHERE discord_user_id = ?
            ''', (
                discord_user.display_name,
                self.streamer_type,
                str(first_channel_id),
                self.creator_data['twitch_username'],
                self.creator_data['youtube_username'],
                self.creator_data['tiktok_username'],
                str(discord_user.id)
            ))
            
            # Clear existing platform channels for this creator
            cursor.execute('DELETE FROM creator_channels WHERE creator_id = ?', (creator_id,))
            
            # Insert platform-specific channels
            for platform, channel in self.selected_channels.items():
                cursor.execute('''
                    INSERT INTO creator_channels (creator_id, platform, channel_id)
                    VALUES (?, ?, ?)
                ''', (creator_id, platform, str(channel.id)))
            
            # Initialize streak data for Karma streamers
            if self.streamer_type == 'karma':
                cursor.execute('''
                    INSERT OR REPLACE INTO daily_streaks (creator_id, current_streak)
                    VALUES (?, 0)
                ''', (creator_id,))
            
            # Initialize event streak data for both types
            cursor.execute('''
                INSERT OR REPLACE INTO event_streaks (creator_id, current_event_streak, event_points)
                VALUES (?, 0, 0)
            ''', (creator_id,))
            
            conn.commit()
            
            embed = discord.Embed(
                title="✅ Creator erfolgreich hinzugefügt",
                color=discord.Color.green()
            )
            embed.add_field(name="Discord User", value=discord_user.mention, inline=True)
            embed.add_field(
                name="Typ", 
                value=f"{'⭐ Karma Streamer' if self.selected_streamer_type == 'karma' else '👾 Regular Streamer'}",
                inline=True
            )
            
            # Show platform-specific channels
            channel_info = []
            emojis = {'twitch': '🟣', 'youtube': '🔴', 'tiktok': '🔵'}
            for platform, channel in self.selected_channels.items():
                username = self.creator_data.get(f'{platform}_username', 'N/A')
                channel_info.append(f"{emojis[platform]} {platform.title()}: {channel.mention}")
            
            if channel_info:
                embed.add_field(name="Notification Channels", value="\n".join(channel_info), inline=False)
            
            # Show usernames
            platforms = []
            if self.creator_data['twitch_username']:
                platforms.append(f"🟣 Twitch: {self.creator_data['twitch_username']}")
            if self.creator_data['youtube_username']:
                platforms.append(f"🔴 YouTube: {self.creator_data['youtube_username']}")
            if self.creator_data['tiktok_username']:
                platforms.append(f"🔵 TikTok: {self.creator_data['tiktok_username']}")
            
            if platforms:
                embed.add_field(name="Plattform-Accounts", value="\n".join(platforms), inline=False)
            
            await interaction.response.edit_message(embed=embed, view=None)
            
        except sqlite3.IntegrityError as e:
            await interaction.response.send_message(
                f"❌ Fehler beim Speichern: Creator bereits vorhanden oder andere Datenbank-Constraint verletzt.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error saving creator: {e}")
            await interaction.response.send_message(
                "❌ Unerwarteter Fehler beim Speichern.",
                ephemeral=True
            )
        finally:
            conn.close()

class UserCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db

    @app_commands.command(name="subcreator", description="Einen Streamer für private Live-Benachrichtigungen abonnieren")
    @has_user_role()
    async def subscribe_creator(self, interaction: discord.Interaction):
        """Subscribe to a creator for private notifications"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, discord_username, streamer_type FROM creators')
        creators = cursor.fetchall()
        
        if not creators:
            await interaction.response.send_message(
                "❌ Keine Creator gefunden.", 
                ephemeral=True
            )
            conn.close()
            return
        
        # Create select options
        options = []
        for creator_id, username, streamer_type in creators:
            emoji = "⭐" if streamer_type == "karma" else "👾"
            options.append(discord.SelectOption(
                label=f"{username}",
                value=str(creator_id),
                emoji=emoji,
                description=f"{streamer_type.title()} Streamer"
            ))
        
        if len(options) > 25:  # Discord limit
            options = options[:25]
        
        view = SubscribeView(self.db, options, str(interaction.user.id))
        
        embed = discord.Embed(
            title="📺 Creator abonnieren",
            description="Wählen Sie einen Creator aus, um private Live-Benachrichtigungen zu erhalten:",
            color=discord.Color.blue()
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        conn.close()

    @app_commands.command(name="unsub", description="Creator-Abonnements verwalten")
    @has_user_role()
    async def unsubscribe_creator(self, interaction: discord.Interaction):
        """Unsubscribe from creators"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT c.id, c.discord_username, c.streamer_type 
            FROM creators c
            JOIN user_subscriptions us ON c.id = us.creator_id
            WHERE us.user_id = ?
        ''', (str(interaction.user.id),))
        
        subscriptions = cursor.fetchall()
        
        if not subscriptions:
            await interaction.response.send_message(
                "❌ Sie haben keine Abonnements.", 
                ephemeral=True
            )
            conn.close()
            return
        
        options = []
        for creator_id, username, streamer_type in subscriptions:
            emoji = "⭐" if streamer_type == "karma" else "👾"
            options.append(discord.SelectOption(
                label=f"{username}",
                value=str(creator_id),
                emoji=emoji,
                description=f"Abonniert - {streamer_type.title()} Streamer"
            ))
        
        view = UnsubscribeView(self.db, options, str(interaction.user.id))
        
        embed = discord.Embed(
            title="🚫 Abonnements verwalten",
            description="Wählen Sie Creator aus, die Sie nicht mehr abonnieren möchten:",
            color=discord.Color.orange()
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        conn.close()

class SubscribeView(discord.ui.View):
    def __init__(self, db, options, user_id: str):
        super().__init__(timeout=300)
        self.db = db
        self.user_id = user_id
        self.add_item(CreatorSubscribeSelect(db, options, user_id))

class CreatorSubscribeSelect(discord.ui.Select):
    def __init__(self, db, options, user_id: str):
        super().__init__(placeholder="Creator auswählen...", options=options)
        self.db = db
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        creator_id = int(self.values[0])
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Get creator info and available platforms
        cursor.execute('''
            SELECT discord_username, twitch_username, youtube_username, tiktok_username, streamer_type
            FROM creators WHERE id = ?
        ''', (creator_id,))
        
        creator_data = cursor.fetchone()
        if not creator_data:
            await interaction.response.send_message("❌ Creator nicht gefunden.", ephemeral=True)
            conn.close()
            return
        
        creator_name, twitch, youtube, tiktok, streamer_type = creator_data
        
        # Get already subscribed platforms for this user/creator
        cursor.execute('''
            SELECT platform FROM user_subscriptions 
            WHERE user_id = ? AND creator_id = ?
        ''', (self.user_id, creator_id))
        
        existing_platforms = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        # Build available platforms list
        available_platforms = []
        if twitch:
            available_platforms.append(('twitch', f"🟣 Twitch: {twitch}"))
        if youtube:
            available_platforms.append(('youtube', f"🔴 YouTube: {youtube}"))
        if tiktok:
            available_platforms.append(('tiktok', f"🔵 TikTok: {tiktok}"))
        
        if not available_platforms:
            await interaction.response.send_message(
                f"❌ **{creator_name}** hat keine konfigurierten Plattformen.", 
                ephemeral=True
            )
            return
        
        # Show platform selection view
        platform_view = PlatformSubscribeView(
            self.db, self.user_id, creator_id, creator_name, 
            available_platforms, existing_platforms, streamer_type
        )
        
        embed = discord.Embed(
            title=f"📺 {creator_name} abonnieren",
            description="Wählen Sie die Plattformen aus, für die Sie Benachrichtigungen erhalten möchten:",
            color=discord.Color.blue()
        )
        
        # Show already subscribed platforms
        if existing_platforms:
            if 'all' in existing_platforms:
                embed.add_field(
                    name="Aktuell abonniert",
                    value="🌟 Alle Plattformen",
                    inline=False
                )
            else:
                platform_names = []
                emojis = {'twitch': '🟣', 'youtube': '🔴', 'tiktok': '🔵'}
                for platform in existing_platforms:
                    if platform in emojis:
                        platform_names.append(f"{emojis[platform]} {platform.title()}")
                
                if platform_names:
                    embed.add_field(
                        name="Aktuell abonniert",
                        value="\n".join(platform_names),
                        inline=False
                    )
        
        await interaction.response.edit_message(embed=embed, view=platform_view)


class PlatformSubscribeView(discord.ui.View):
    def __init__(self, db, user_id: str, creator_id: int, creator_name: str, 
                 available_platforms: list, existing_platforms: list, streamer_type: str):
        super().__init__(timeout=300)
        self.db = db
        self.user_id = user_id
        self.creator_id = creator_id
        self.creator_name = creator_name
        self.available_platforms = available_platforms
        self.existing_platforms = existing_platforms
        self.streamer_type = streamer_type
        
        # Build platform selection options
        options = []
        
        # Add "All Platforms" option if not already subscribed to all
        if 'all' not in existing_platforms:
            options.append(discord.SelectOption(
                label="Alle Plattformen",
                value="all",
                emoji="🌟",
                description="Benachrichtigungen von allen verfügbaren Plattformen"
            ))
        
        # Add individual platforms
        emojis = {'twitch': '🟣', 'youtube': '🔴', 'tiktok': '🔵'}
        for platform, display_name in available_platforms:
            if platform not in existing_platforms:
                options.append(discord.SelectOption(
                    label=display_name,
                    value=platform,
                    emoji=emojis[platform]
                ))
        
        if options:
            self.add_item(PlatformSubscribeSelect(
                db, user_id, creator_id, creator_name, options, existing_platforms, streamer_type
            ))


class PlatformSubscribeSelect(discord.ui.Select):
    def __init__(self, db, user_id: str, creator_id: int, creator_name: str, 
                 options: list, existing_platforms: list, streamer_type: str):
        super().__init__(
            placeholder="Plattformen auswählen...", 
            options=options,
            max_values=len(options),
            min_values=1
        )
        self.db = db
        self.user_id = user_id
        self.creator_id = creator_id
        self.creator_name = creator_name
        self.existing_platforms = existing_platforms
        self.streamer_type = streamer_type

    async def callback(self, interaction: discord.Interaction):
        selected_platforms = self.values
        
        # Show confirmation view instead of immediately subscribing
        confirm_view = ConfirmSubscriptionView(
            self.db, self.user_id, self.creator_id, self.creator_name, 
            selected_platforms, self.streamer_type
        )
        
        # Create confirmation embed
        embed = discord.Embed(
            title="🔔 Abonnement bestätigen",
            description=f"Sie möchten **{self.creator_name}** für folgende Plattformen abonnieren:",
            color=discord.Color.blue()
        )
        
        # Show selected platforms
        if "all" in selected_platforms:
            subscription_preview = "🌟 **Alle Plattformen**"
        else:
            subscription_names = []
            emojis = {'twitch': '🟣', 'youtube': '🔴', 'tiktok': '🔵'}
            for platform in selected_platforms:
                subscription_names.append(f"{emojis[platform]} **{platform.title()}**")
            subscription_preview = "\n".join(subscription_names)
        
        embed.add_field(
            name="Ausgewählte Plattformen",
            value=subscription_preview,
            inline=False
        )
        
        streamer_emoji = "⭐" if self.streamer_type == "karma" else "👾"
        embed.add_field(
            name="Streamer-Typ", 
            value=f"{streamer_emoji} {self.streamer_type.title()} Streamer",
            inline=True
        )
        
        embed.add_field(
            name="ℹ️ Info",
            value="Sie erhalten private DM-Benachrichtigungen wenn dieser Creator live geht.",
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=confirm_view)


class ConfirmSubscriptionView(discord.ui.View):
    def __init__(self, db, user_id: str, creator_id: int, creator_name: str, selected_platforms: list, streamer_type: str):
        super().__init__(timeout=300)
        self.db = db
        self.user_id = user_id
        self.creator_id = creator_id
        self.creator_name = creator_name
        self.selected_platforms = selected_platforms
        self.streamer_type = streamer_type

    @discord.ui.button(label="✅ Bestätigen", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_subscription(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Confirm and actually subscribe the user"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # If "all" is selected, remove individual platform subscriptions and add "all"
            if "all" in self.selected_platforms:
                # Remove any existing individual platform subscriptions
                cursor.execute('''
                    DELETE FROM user_subscriptions 
                    WHERE user_id = ? AND creator_id = ? AND platform != 'all'
                ''', (self.user_id, self.creator_id))
                
                # Add "all" subscription if not exists
                cursor.execute('''
                    INSERT OR IGNORE INTO user_subscriptions (user_id, creator_id, platform)
                    VALUES (?, ?, 'all')
                ''', (self.user_id, self.creator_id))
                
                subscription_text = "🌟 **Alle Plattformen**"
            else:
                # Remove "all" subscription if exists
                cursor.execute('''
                    DELETE FROM user_subscriptions 
                    WHERE user_id = ? AND creator_id = ? AND platform = 'all'
                ''', (self.user_id, self.creator_id))
                
                # Add selected individual platforms
                subscription_names = []
                emojis = {'twitch': '🟣', 'youtube': '🔴', 'tiktok': '🔵'}
                
                for platform in self.selected_platforms:
                    cursor.execute('''
                        INSERT OR IGNORE INTO user_subscriptions (user_id, creator_id, platform)
                        VALUES (?, ?, ?)
                    ''', (self.user_id, self.creator_id, platform))
                    
                    subscription_names.append(f"{emojis[platform]} **{platform.title()}**")
                
                subscription_text = "\n".join(subscription_names)
            
            conn.commit()
            
            # Success embed with /unsub information
            embed = discord.Embed(
                title="🎉 Abonnement erfolgreich!",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="✅ Abonnierte Plattformen:",
                value=subscription_text,
                inline=False
            )
            
            embed.add_field(
                name="👤 Streamer:",
                value=f"**{self.creator_name}**",
                inline=False
            )
            
            embed.add_field(
                name="🔔 Benachrichtigungen:",
                value="Private DM-Nachrichten",
                inline=False
            )
            
            # Important: Add /unsub information
            embed.add_field(
                name="ℹ️ Abonnement verwalten:",
                value="Verwenden Sie `/unsub` um Ihre Abonnements zu bearbeiten oder zu löschen.",
                inline=False
            )
            
            embed.set_footer(text="Sie erhalten nur eine Benachrichtigung pro Stream-Session.")
            
            await interaction.response.edit_message(embed=embed, view=None)
            
        except Exception as e:
            logger.error(f"Error confirming subscription: {e}")
            await interaction.response.send_message(
                f"❌ Fehler beim Bestätigen des Abonnements: {str(e)}",
                ephemeral=True
            )
        finally:
            conn.close()

    @discord.ui.button(label="❌ Abbrechen", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_subscription(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel the subscription process"""
        embed = discord.Embed(
            title="❌ Abonnement abgebrochen",
            description="Das Abonnement wurde nicht erstellt.",
            color=discord.Color.orange()
        )
        
        embed.add_field(
            name="💡 Tipp",
            value="Verwenden Sie `/subcreator` um es erneut zu versuchen.",
            inline=False
        )
        
        await interaction.response.edit_message(embed=embed, view=None)


class UnsubscribeView(discord.ui.View):
    def __init__(self, db, options, user_id: str):
        super().__init__(timeout=300)
        self.db = db
        self.user_id = user_id
        self.add_item(CreatorUnsubscribeSelect(db, options, user_id))

class CreatorUnsubscribeSelect(discord.ui.Select):
    def __init__(self, db, options, user_id: str):
        super().__init__(placeholder="Creator zum Abbestellen auswählen...", options=options, max_values=len(options))
        self.db = db
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        creator_ids = [int(val) for val in self.values]
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Get creator names before deletion
        placeholders = ','.join('?' * len(creator_ids))
        cursor.execute(f'SELECT discord_username FROM creators WHERE id IN ({placeholders})', creator_ids)
        creator_names = [row[0] for row in cursor.fetchall()]
        
        # Remove subscriptions
        for creator_id in creator_ids:
            cursor.execute(
                'DELETE FROM user_subscriptions WHERE user_id = ? AND creator_id = ?',
                (self.user_id, creator_id)
            )
        
        conn.commit()
        conn.close()
        
        embed = discord.Embed(
            title="✅ Erfolgreich abbestellt",
            description=f"Sie erhalten keine privaten Benachrichtigungen mehr von:\n" + "\n".join(f"• **{name}**" for name in creator_names),
            color=discord.Color.green()
        )
        
        await interaction.response.edit_message(embed=embed, view=None)


class ServerManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db

    @app_commands.command(name="setupstatschannel", description="Stats-Channels erstellen für Server-Statistiken")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    async def setup_stats_channels(self, interaction: discord.Interaction):
        """Setup stats channels command"""
        # Check how many stats channels already exist
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM stats_channels WHERE guild_id = ?', (str(interaction.guild.id),))
        existing_count = cursor.fetchone()[0]
        conn.close()
        
        if existing_count >= 16:
            embed = discord.Embed(
                title="❌ Limit erreicht",
                description="Maximal 16 Stats-Channels sind erlaubt. Lösche zuerst bestehende Channels.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create setup view
        view = StatsChannelSetupView(self.db, interaction.guild, existing_count)
        
        embed = discord.Embed(
            title="📊 Stats-Channels Setup",
            description="Wählen Sie die gewünschten Statistiken aus, die als Voice Channels angezeigt werden sollen:",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📋 Verfügbare Basis-Statistiken",
            value="• Online-Mitglieder\n• Peak Online-Mitglieder\n• Mitglieder insgesamt\n• Kanäle insgesamt\n• Rollen insgesamt",
            inline=False
        )
        
        embed.add_field(
            name="🏷️ Rollen-Zähler",
            value="Optional: Bis zu 8 Rollen für individuelle Zähler auswählen",
            inline=False
        )
        
        embed.add_field(
            name="⚠️ Hinweise",
            value=f"• Bereits verwendet: {existing_count}/16 Slots\n• Channels werden gesperrt (nur Anzeige)\n• Updates alle 30 Minuten",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class StatsChannelSetupView(discord.ui.View):
    def __init__(self, db, guild, existing_count):
        super().__init__(timeout=300)
        self.db = db
        self.guild = guild
        self.existing_count = existing_count
        self.selected_stats = []
        self.selected_roles = []
        
        # Add base stats select
        self.add_item(BaseStatsSelect())
        # Add role select
        self.add_item(RoleSelect(guild))
        # Add confirm button
        self.add_item(ConfirmStatsButton(db, guild))

    async def update_message(self, interaction: discord.Interaction):
        """Update the message with current selections"""
        total_selected = len(self.selected_stats) + len(self.selected_roles)
        remaining_slots = 16 - self.existing_count - total_selected
        
        embed = discord.Embed(
            title="📊 Stats-Channels Setup",
            description="Ihre aktuelle Auswahl:",
            color=discord.Color.blue()
        )
        
        if self.selected_stats:
            stats_text = "\n".join(f"• {stat}" for stat in self.selected_stats)
            embed.add_field(name="📋 Basis-Statistiken", value=stats_text, inline=False)
        
        if self.selected_roles:
            roles_text = "\n".join(f"• {role.name}" for role in self.selected_roles)
            embed.add_field(name="🏷️ Rollen-Zähler", value=roles_text, inline=False)
        
        embed.add_field(
            name="📊 Zusammenfassung",
            value=f"Gewählt: {total_selected}\nVerfügbare Slots: {remaining_slots}/16",
            inline=False
        )
        
        # Enable/disable confirm button based on selection
        for item in self.children:
            if isinstance(item, ConfirmStatsButton):
                item.disabled = total_selected == 0 or remaining_slots < 0
        
        await interaction.response.edit_message(embed=embed, view=self)


class BaseStatsSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Online-Mitglieder", value="online", emoji="🟢"),
            discord.SelectOption(label="Peak Online-Mitglieder", value="peak_online", emoji="📈"),
            discord.SelectOption(label="Mitglieder insgesamt", value="members", emoji="👥"),
            discord.SelectOption(label="Kanäle insgesamt", value="channels", emoji="📝"),
            discord.SelectOption(label="Rollen insgesamt", value="roles", emoji="👾"),
        ]
        super().__init__(placeholder="Basis-Statistiken auswählen...", options=options, max_values=5)

    async def callback(self, interaction: discord.Interaction):
        # Map values to display names
        value_to_name = {
            "online": "🟢ONLINE MEMBER",
            "peak_online": "📈DAILY PEAK ONLINE", 
            "members": "👥DISCORD MEMBER",
            "channels": "📝DISCORD CHANNEL",
            "roles": "👾DISCORD ROLES"
        }
        
        self.view.selected_stats = [value_to_name[val] for val in self.values]
        await self.view.update_message(interaction)


class RoleSelect(discord.ui.Select):
    def __init__(self, guild):
        # Get roles (exclude @everyone and bot roles)
        roles = [role for role in guild.roles if not role.is_bot_managed() and role != guild.default_role]
        roles = sorted(roles, key=lambda r: r.position, reverse=True)[:20]  # Top 20 roles by position
        
        options = [
            discord.SelectOption(
                label=role.name[:100],  # Discord limit
                value=str(role.id),
                emoji="🎭"
            )
            for role in roles
        ]
        
        if not options:
            options = [discord.SelectOption(label="Keine Rollen verfügbar", value="none", disabled=True)]
        
        super().__init__(placeholder="Optional: Rollen für Zähler auswählen...", options=options, max_values=min(8, len(options)))

    async def callback(self, interaction: discord.Interaction):
        if "none" in self.values:
            self.view.selected_roles = []
        else:
            # Get role objects
            self.view.selected_roles = [
                interaction.guild.get_role(int(role_id)) 
                for role_id in self.values 
                if interaction.guild.get_role(int(role_id))
            ]
        
        await self.view.update_message(interaction)


class ConfirmStatsButton(discord.ui.Button):
    def __init__(self, db, guild):
        super().__init__(label="✅ Stats-Channels erstellen", style=discord.ButtonStyle.green)
        self.db = db
        self.guild = guild

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Map display names back to database values
        name_to_value = {
            "Online-Mitglieder": "online",
            "Peak Online-Mitglieder": "peak_online",
            "Mitglieder insgesamt": "members", 
            "Kanäle insgesamt": "channels",
            "Rollen insgesamt": "roles"
        }
        
        created_channels = []
        errors = []
        
        try:
            # Create base stats channels
            for stat_name in self.view.selected_stats:
                try:
                    counter_type = name_to_value[stat_name]
                    channel_name = f"{stat_name}: 0"
                    
                    # Create locked voice channel
                    overwrites = {
                        self.guild.default_role: discord.PermissionOverwrite(connect=False),
                        self.guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True)
                    }
                    
                    channel = await self.guild.create_voice_channel(
                        name=channel_name,
                        overwrites=overwrites,
                        reason="Stats-Channel Setup"
                    )
                    
                    # Save to database
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO stats_channels (guild_id, channel_id, counter_type, last_count)
                        VALUES (?, ?, ?, ?)
                    ''', (str(self.guild.id), str(channel.id), counter_type, 0))
                    conn.commit()
                    conn.close()
                    
                    created_channels.append(channel.name)
                    
                except Exception as e:
                    logger.error(f"Error creating stats channel for {stat_name}: {e}")
                    errors.append(f"{stat_name}: {str(e)}")
            
            # Create role count channels
            for role in self.view.selected_roles:
                try:
                    channel_name = f"{role.name}: 0"
                    
                    # Create locked voice channel
                    overwrites = {
                        self.guild.default_role: discord.PermissionOverwrite(connect=False),
                        self.guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True)
                    }
                    
                    channel = await self.guild.create_voice_channel(
                        name=channel_name,
                        overwrites=overwrites,
                        reason="Stats-Channel Setup"
                    )
                    
                    # Save to database
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO stats_channels (guild_id, channel_id, counter_type, role_id, last_count)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (str(self.guild.id), str(channel.id), "role_count", str(role.id), 0))
                    conn.commit()
                    conn.close()
                    
                    created_channels.append(channel.name)
                    
                except Exception as e:
                    logger.error(f"Error creating role stats channel for {role.name}: {e}")
                    errors.append(f"{role.name}: {str(e)}")
            
            # Create result embed
            if created_channels:
                embed = discord.Embed(
                    title="✅ Stats-Channels erstellt",
                    description=f"Erfolgreich {len(created_channels)} Stats-Channels erstellt:",
                    color=discord.Color.green()
                )
                
                channels_text = "\n".join(f"• {name}" for name in created_channels)
                embed.add_field(name="📊 Erstellte Channels", value=channels_text, inline=False)
                
                embed.add_field(
                    name="🔄 Updates",
                    value="Die Statistiken werden automatisch alle 30 Minuten aktualisiert.",
                    inline=False
                )
                
                if errors:
                    errors_text = "\n".join(f"• {error}" for error in errors)
                    embed.add_field(name="⚠️ Fehler", value=errors_text, inline=False)
            else:
                embed = discord.Embed(
                    title="❌ Fehler beim Erstellen",
                    description="Es konnten keine Stats-Channels erstellt werden.",
                    color=discord.Color.red()
                )
                
                if errors:
                    errors_text = "\n".join(f"• {error}" for error in errors)
                    embed.add_field(name="🚫 Fehler", value=errors_text, inline=False)
            
            await interaction.edit_original_response(embed=embed, view=None)
            
        except Exception as e:
            logger.error(f"Error in stats channel creation: {e}")
            embed = discord.Embed(
                title="❌ Unerwarteter Fehler",
                description=f"Ein unerwarteter Fehler ist aufgetreten: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed, view=None)