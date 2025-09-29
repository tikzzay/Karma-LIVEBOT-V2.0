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

from database import DatabaseManager
from instantgaming import InstantGamingAPI

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

# DatabaseManager will be set at runtime via set_database function

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
    async def delete_creator(self, interaction: discord.Interaction):
        """Delete creator command - shows selection interface"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, discord_username, streamer_type, discord_user_id FROM creators')
        creators = cursor.fetchall()
        conn.close()
        
        if not creators:
            embed = discord.Embed(
                title="❌ Keine Creator gefunden",
                description="Es sind noch keine Creator in der Datenbank registriert.\n\nVerwende `/addcreator` um zuerst Creator hinzuzufügen.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create delete creator view
        view = DeleteCreatorView(self.db, creators)
        
        embed = discord.Embed(
            title="🗑️ Creator entfernen",
            description="Wähle einen Creator aus der Liste aus, den du entfernen möchtest.\n\n**⚠️ Warnung:** Alle zugehörigen Daten werden unwiderruflich gelöscht!",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="💡 Hinweise:",
            value="• Wähle den Creator aus der Dropdown-Liste\n• Alle Abonnements, Live-Status und Streak-Daten werden gelöscht\n• Diese Aktion kann nicht rückgängig gemacht werden",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @app_commands.command(name="customstreamermessage", description="Custom Benachrichtigungstext für einen Streamer setzen oder entfernen")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    async def custom_streamer_message(self, interaction: discord.Interaction):
        """Interactive command to set or remove custom notification message for a streamer"""
        # Create the streamer selection view
        view = StreamerSelectView(self.db)
        
        # Populate the streamers from database
        await view.populate_streamers()
        
        # Check if any streamers exist
        if view.streamer_select.disabled:
            embed = discord.Embed(
                title="❌ Keine Streamer gefunden",
                description="Es sind noch keine Streamer in der Datenbank registriert.\n\nVerwende `/addcreator` um zuerst Streamer hinzuzufügen.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create initial embed
        embed = discord.Embed(
            title="📝 Custom Streamer Message",
            description="Wähle einen Streamer aus der Liste aus, um eine benutzerdefinierte Benachrichtigung zu setzen oder zu entfernen.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="💡 Hinweise:",
            value="• Wähle einen Streamer aus der Dropdown-Liste\n• Ein Fenster wird sich öffnen, um die Nachricht zu bearbeiten\n• Lass das Feld leer, um die custom Message zu entfernen",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @app_commands.command(name="editigreftag", description="Instant Gaming Referral Tag ändern")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    async def edit_ig_ref_tag(self, interaction: discord.Interaction):
        """Admin command to change the Instant Gaming referral tag - opens modal"""
        try:
            # Get current tag from database
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT affiliate_tag FROM instant_gaming_config WHERE id = 1')
            current_result = cursor.fetchone()
            current_tag = current_result[0] if current_result else "tikzzay"
            conn.close()
            
            # Create and send modal
            modal = EditIGRefTagModal(self.db, current_tag)
            await interaction.response.send_modal(modal)
            
        except Exception as e:
            logger.error(f"Error opening IG ref tag edit modal: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Öffnen des Bearbeitungsfensters. Bitte versuche es erneut.",
                ephemeral=True
            )

class EditIGRefTagModal(discord.ui.Modal):
    def __init__(self, db, current_tag):
        super().__init__(title='Instant Gaming Referral Tag bearbeiten')
        self.db = db
        self.current_tag = current_tag
        
        # Create input field with current tag as default value
        self.new_tag_input = discord.ui.TextInput(
            label=f'Aktueller Tag: {current_tag}',
            placeholder='Gib deinen neuen Referral Tag ein...',
            default=current_tag,
            style=discord.TextStyle.short,
            max_length=50,
            required=True
        )
        self.add_item(self.new_tag_input)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle the submission of the new referral tag"""
        new_tag = self.new_tag_input.value.strip()
        
        # Validate tag format
        if not new_tag:
            await interaction.response.send_message(
                "❌ Der Referral Tag darf nicht leer sein!",
                ephemeral=True
            )
            return
        
        # Check for invalid characters
        invalid_chars = ['&', '?', '#', '/', '\\', ' ', '=']
        if any(char in new_tag for char in invalid_chars):
            await interaction.response.send_message(
                f"❌ Der Referral Tag darf folgende Zeichen nicht enthalten: {', '.join(invalid_chars)}",
                ephemeral=True
            )
            return
        
        # Check if tag is the same as current
        if new_tag == self.current_tag:
            await interaction.response.send_message(
                f"❌ Der neue Tag ist identisch mit dem aktuellen Tag: `{self.current_tag}`",
                ephemeral=True
            )
            return
        
        try:
            # Update the affiliate tag in database
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE instant_gaming_config SET affiliate_tag = ? WHERE id = 1', (new_tag,))
            conn.commit()
            conn.close()
            
            # Clear InstantGamingAPI cache to ensure new tag is used immediately
            try:
                from main import instant_gaming
                instant_gaming.clear_cache()
                logger.info("InstantGamingAPI cache cleared after affiliate tag update")
            except Exception as cache_error:
                logger.warning(f"Could not clear InstantGamingAPI cache: {cache_error}")
            
            # Create success embed
            embed = discord.Embed(
                title="✅ Instant Gaming Referral Tag aktualisiert",
                description=f"Der Referral Tag wurde erfolgreich geändert!",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Vorher:",
                value=f"`{self.current_tag}`",
                inline=True
            )
            embed.add_field(
                name="Nachher:",
                value=f"`{new_tag}`",
                inline=True
            )
            embed.add_field(
                name="💡 Hinweis:",
                value="Alle neuen Instant Gaming Links verwenden nun den neuen Referral Tag.",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed)
            
            # Log the change
            logger.info(f"Instant Gaming referral tag changed from '{self.current_tag}' to '{new_tag}' by {interaction.user}")
            
        except Exception as e:
            logger.error(f"Error updating Instant Gaming referral tag: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Aktualisieren des Referral Tags. Bitte versuche es erneut.",
                ephemeral=True
            )

class CustomMessageModal(discord.ui.Modal):
    def __init__(self, db, creator_id, creator_name):
        super().__init__(title=f'Custom Message für {creator_name}')
        self.db = db
        self.creator_id = creator_id
        self.creator_name = creator_name

    message_input = discord.ui.TextInput(
        label='Custom Benachrichtigungstext',
        placeholder='Gib hier deine benutzerdefinierte Nachricht ein (leer lassen um zu entfernen)',
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        """Handle the submission of the custom message"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            message = self.message_input.value.strip()
            
            if not message:
                # Remove custom message (set to NULL)
                cursor.execute('UPDATE creators SET custom_message = NULL WHERE id = ?', (self.creator_id,))
                conn.commit()
                
                embed = discord.Embed(
                    title="✅ Custom Message entfernt",
                    description=f"Die custom Benachrichtigung für **{self.creator_name}** wurde entfernt.\n\n🔄 Es wird wieder die Standard-Benachrichtigung verwendet.",
                    color=discord.Color.green()
                )
            else:
                # Set custom message
                cursor.execute('UPDATE creators SET custom_message = ? WHERE id = ?', (message, self.creator_id))
                conn.commit()
                
                embed = discord.Embed(
                    title="✅ Custom Message gesetzt",
                    description=f"Custom Benachrichtigung für **{self.creator_name}** wurde erfolgreich gesetzt!",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="📝 Neue Benachrichtigung:",
                    value=f"```{message}```",
                    inline=False
                )
                embed.add_field(
                    name="💡 Hinweis:",
                    value="Diese Nachricht wird nun anstelle der Standard-Benachrichtigung gesendet, wenn der Streamer live geht.",
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Fehler beim Setzen der Custom Message: {str(e)}", 
                ephemeral=True
            )
        finally:
            conn.close()

class StreamerSelectView(discord.ui.View):
    def __init__(self, db):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.db = db

    @discord.ui.select(
        placeholder="Wähle einen Streamer aus der Datenbank...",
        min_values=1,
        max_values=1
    )
    async def streamer_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        """Handle streamer selection"""
        selected_creator_id = int(select.values[0])
        
        # Get creator details
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT discord_username, custom_message FROM creators WHERE id = ?', (selected_creator_id,))
            creator_data = cursor.fetchone()
            
            if creator_data:
                creator_name = creator_data[0]
                current_message = creator_data[1]
                
                # Create and show the custom message modal
                modal = CustomMessageModal(self.db, selected_creator_id, creator_name)
                
                # Pre-fill with current custom message if exists
                if current_message:
                    modal.message_input.default = current_message
                
                await interaction.response.send_modal(modal)
            else:
                await interaction.response.send_message(
                    "❌ Streamer nicht gefunden.", 
                    ephemeral=True
                )
        finally:
            conn.close()

    async def populate_streamers(self):
        """Populate the select menu with streamers from database"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT id, discord_username, streamer_type FROM creators ORDER BY discord_username')
            creators = cursor.fetchall()
            
            if not creators:
                # Create a disabled option if no creators exist
                self.streamer_select.options = [
                    discord.SelectOption(
                        label="Keine Streamer gefunden",
                        value="none",
                        description="Füge zuerst Streamer mit /addcreator hinzu",
                        emoji="❌"
                    )
                ]
                self.streamer_select.disabled = True
            else:
                # Create options for each creator
                options = []
                for creator_id, username, streamer_type in creators:
                    # Use appropriate emoji based on streamer type
                    emoji = "⭐" if streamer_type == "karma" else "👾"
                    
                    options.append(
                        discord.SelectOption(
                            label=username,
                            value=str(creator_id),
                            description=f"{streamer_type.title()} Streamer",
                            emoji=emoji
                        )
                    )
                
                self.streamer_select.options = options[:25]  # Discord limit of 25 options
                
        finally:
            conn.close()

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
        
        if existing_count >= 30:
            embed = discord.Embed(
                title="❌ Limit erreicht",
                description="Maximal 30 Stats-Channels sind erlaubt. Lösche zuerst bestehende Channels.",
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
            value=f"• Bereits verwendet: {existing_count}/30 Slots\n• Channels werden gesperrt (nur Anzeige)\n• Updates alle 30 Minuten",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    @app_commands.command(name="socialmediastatschannel", description="Social Media Stats-Channels erstellen für Follower-Zahlen")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    async def setup_social_media_stats_channels(self, interaction: discord.Interaction):
        """Setup social media stats channels command"""
        # Check how many social media stats channels already exist
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM social_media_stats_channels WHERE guild_id = ?', (str(interaction.guild.id),))
        existing_count = cursor.fetchone()[0]
        conn.close()
        
        if existing_count >= 20:
            embed = discord.Embed(
                title="❌ Limit erreicht",
                description="Maximal 20 Social Media Stats-Channels sind erlaubt. Verwende `/deletesocialmediastatschannel` um bestehende zu löschen.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create simple platform selection view
        view = SimplePlatformSelectionView(self.db, interaction.guild)
        
        embed = discord.Embed(
            title="📱 Social Media Stats-Channels Setup",
            description="Wähle die Plattformen aus, für die du Follower-Counter erstellen möchtest:",
            color=discord.Color.purple()
        )
        
        embed.add_field(
            name="📋 Verfügbare Plattformen",
            value="🟣 Twitch\n📹 YouTube\n🎥 TikTok\n📷 Instagram\n🐦 X (Twitter)",
            inline=False
        )
        
        embed.add_field(
            name="⚠️ Hinweise",
            value=f"• Verwendet: {existing_count}/20 Channels\n• Updates alle 30 Minuten\n• Username wird validiert",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="deletesocialmediastatschannel", description="Social Media Stats-Channels löschen")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    async def delete_social_media_stats_channels(self, interaction: discord.Interaction):
        """Delete social media stats channels command"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Get existing social media stats channels for this guild
        cursor.execute('''
            SELECT channel_id, platform, username, last_follower_count
            FROM social_media_stats_channels 
            WHERE guild_id = ?
        ''', (str(interaction.guild.id),))
        channels = cursor.fetchall()
        conn.close()
        
        if not channels:
            embed = discord.Embed(
                title="📱 Keine Social Media Channels",
                description="Keine Social Media Stats-Channels in diesem Server konfiguriert.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create deletion view
        view = SocialMediaDeletionView(self.db, interaction.guild, channels)
        
        embed = discord.Embed(
            title="🗑️ Social Media Stats-Channels löschen",
            description=f"Wähle die Channels aus, die gelöscht werden sollen:\n\n",
            color=discord.Color.red()
        )
        
        # List existing channels
        channel_list = []
        for channel_id, platform, username, count in channels:
            channel = interaction.guild.get_channel(int(channel_id))
            if channel:
                emoji_map = {'instagram': '📷', 'x': '❌', 'twitter': '🐦', 'youtube': '📹', 'tiktok': '🎥', 'twitch': '🟣'}
                emoji = emoji_map.get(platform, '📱')
                channel_list.append(f"{emoji} {platform.title()}: @{username} ({count:,} Follower)")
        
        if channel_list:
            embed.add_field(
                name="📋 Bestehende Channels",
                value="\n".join(channel_list[:10]),  # Limit to 10 for display
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="managestatschannels", description="Bestehende Stats-Channels verwalten und löschen")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    async def manage_stats_channels(self, interaction: discord.Interaction):
        """Manage existing stats channels"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Get existing stats channels for this guild
        cursor.execute('''
            SELECT channel_id, counter_type, role_id, last_count 
            FROM stats_channels 
            WHERE guild_id = ?
        ''', (str(interaction.guild.id),))
        stats_channels = cursor.fetchall()
        conn.close()
        
        if not stats_channels:
            embed = discord.Embed(
                title="📊 Keine Stats-Channels",
                description="Keine Stats-Channels in diesem Server konfiguriert.\nVerwenden Sie `/setupstatschannel` um welche zu erstellen.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Create management view
        view = StatsChannelManagementView(self.db, interaction.guild, stats_channels)
        
        embed = discord.Embed(
            title="📊 Stats-Channels Verwaltung",
            description=f"Verwaltung von {len(stats_channels)} Stats-Channels:",
            color=discord.Color.blue()
        )
        
        # List all channels
        channel_list = []
        for channel_id, counter_type, role_id, last_count in stats_channels:
            channel = interaction.guild.get_channel(int(channel_id))
            if channel:
                if counter_type == 'role_count' and role_id:
                    role = interaction.guild.get_role(int(role_id))
                    channel_name = f"{role.name if role else 'Unbekannte Rolle'}: {last_count}"
                else:
                    type_names = {
                        'online': '🟢ONLINE MEMBER',
                        'peak_online': '📈DAILY PEAK ONLINE',
                        'members': '👥DISCORD MEMBER',
                        'channels': '📝DISCORD CHANNEL',
                        'roles': '👾DISCORD ROLES'
                    }
                    channel_name = f"{type_names.get(counter_type, counter_type)}: {last_count}"
                channel_list.append(f"• {channel_name}")
            else:
                channel_list.append(f"• ❌ Gelöschter Channel (ID: {channel_id})")
        
        embed.add_field(
            name="📋 Aktuelle Stats-Channels",
            value="\n".join(channel_list) if channel_list else "Keine Channels gefunden",
            inline=False
        )
        
        embed.add_field(
            name="🗑️ Aktionen",
            value="Verwenden Sie die Buttons unten um Channels zu löschen oder alle zu entfernen.",
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
        remaining_slots = 30 - self.existing_count - total_selected
        
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
            value=f"Gewählt: {total_selected}\nVerfügbare Slots: {remaining_slots}/30",
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
            "🟢ONLINE MEMBER": "online",
            "📈DAILY PEAK ONLINE": "peak_online",
            "👥DISCORD MEMBER": "members", 
            "📝DISCORD CHANNEL": "channels",
            "👾DISCORD ROLES": "roles"
        }
        
        created_channels = []
        errors = []
        
        try:
            # Create base stats channels
            for stat_name in self.view.selected_stats:
                try:
                    counter_type = name_to_value[stat_name]
                    
                    # Calculate current value immediately
                    current_count = 0
                    if counter_type == 'online':
                        # Check if we have presences intent for accurate online counting
                        if hasattr(self.guild.me, 'guild_permissions') and self.guild.me.guild_permissions.view_audit_log:
                            # Try to count actual online members using member.status
                            online_members = 0
                            for member in self.guild.members:
                                if hasattr(member, 'status') and member.status != discord.Status.offline:
                                    online_members += 1
                            # Fallback to voice channel count if status-based count is 0 (indicating missing presences intent)
                            if online_members == 0:
                                voice_members = set()
                                for voice_channel in self.guild.voice_channels:
                                    voice_members.update(voice_channel.members)
                                current_count = len(voice_members)
                            else:
                                current_count = online_members
                        else:
                            # Fallback to voice channel members as alternative to presences intent
                            voice_members = set()
                            for voice_channel in self.guild.voice_channels:
                                voice_members.update(voice_channel.members)
                            current_count = len(voice_members)
                    elif counter_type == 'members':
                        current_count = self.guild.member_count
                    elif counter_type == 'channels':
                        current_count = len(self.guild.channels)
                    elif counter_type == 'roles':
                        current_count = len(self.guild.roles) - 1  # Exclude @everyone
                    elif counter_type == 'peak_online':
                        current_count = 0  # Peak tracking starts at 0
                    
                    channel_name = f"{stat_name}: {current_count}"
                    
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
                    ''', (str(self.guild.id), str(channel.id), counter_type, current_count))
                    conn.commit()
                    conn.close()
                    
                    created_channels.append(channel.name)
                    
                except Exception as e:
                    logger.error(f"Error creating stats channel for {stat_name}: {e}")
                    errors.append(f"{stat_name}: {str(e)}")
            
            # Create role count channels
            for role in self.view.selected_roles:
                try:
                    # Get current role member count
                    current_count = len(role.members)
                    channel_name = f"{role.name}: {current_count}"
                    
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
                    ''', (str(self.guild.id), str(channel.id), "role_count", str(role.id), current_count))
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


class StatsChannelManagementView(discord.ui.View):
    def __init__(self, db, guild, stats_channels):
        super().__init__(timeout=300)
        self.db = db
        self.guild = guild
        self.stats_channels = stats_channels
        
        # Add select for individual channel deletion if there are channels
        if stats_channels:
            self.add_item(StatsChannelSelect(db, guild, stats_channels))
            self.add_item(DeleteAllStatsButton(db, guild))
        
        # Add refresh button
        self.add_item(RefreshStatsButton(db, guild))


class StatsChannelSelect(discord.ui.Select):
    def __init__(self, db, guild, stats_channels):
        self.db = db
        self.guild = guild
        
        options = []
        for channel_id, counter_type, role_id, last_count in stats_channels[:25]:  # Discord limit
            channel = guild.get_channel(int(channel_id))
            if channel:
                if counter_type == 'role_count' and role_id:
                    role = guild.get_role(int(role_id))
                    label = f"{role.name if role else 'Unbekannte Rolle'}"[:100]
                else:
                    type_names = {
                        'online': '🟢ONLINE MEMBER',
                        'peak_online': '📈DAILY PEAK ONLINE',
                        'members': '👥DISCORD MEMBER', 
                        'channels': '📝DISCORD CHANNEL',
                        'roles': '👾DISCORD ROLES'
                    }
                    label = type_names.get(counter_type, counter_type)[:100]
                
                options.append(discord.SelectOption(
                    label=label,
                    value=channel_id,
                    description=f"Aktueller Wert: {last_count}",
                    emoji="🗑️"
                ))
        
        if not options:
            options = [discord.SelectOption(label="Keine Channels verfügbar", value="none", disabled=True)]
        
        super().__init__(
            placeholder="Channel zum Löschen auswählen...",
            options=options,
            max_values=min(len(options), 25)
        )

    async def callback(self, interaction: discord.Interaction):
        if "none" in self.values:
            return
        
        await interaction.response.defer(ephemeral=True)
        
        deleted_channels = []
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        for channel_id in self.values:
            try:
                # Delete from database
                cursor.execute('DELETE FROM stats_channels WHERE channel_id = ?', (channel_id,))
                
                # Try to delete the actual channel
                channel = self.guild.get_channel(int(channel_id))
                if channel:
                    await channel.delete(reason="Stats-Channel entfernt")
                    deleted_channels.append(channel.name)
                    
            except Exception as e:
                logger.error(f"Error deleting stats channel {channel_id}: {e}")
        
        conn.commit()
        conn.close()
        
        embed = discord.Embed(
            title="✅ Channels gelöscht",
            description=f"Erfolgreich {len(deleted_channels)} Stats-Channels entfernt.",
            color=discord.Color.green()
        )
        await interaction.edit_original_response(embed=embed)


class DeleteAllStatsButton(discord.ui.Button):
    def __init__(self, db, guild):
        super().__init__(label="🗑️ Alle löschen", style=discord.ButtonStyle.danger)
        self.db = db
        self.guild = guild

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Get and delete all stats channels
        cursor.execute('SELECT channel_id FROM stats_channels WHERE guild_id = ?', (str(self.guild.id),))
        channel_ids = [row[0] for row in cursor.fetchall()]
        
        deleted_count = 0
        for channel_id in channel_ids:
            try:
                channel = self.guild.get_channel(int(channel_id))
                if channel:
                    await channel.delete(reason="Alle Stats-Channels entfernt")
                    deleted_count += 1
            except Exception as e:
                logger.error(f"Error deleting channel {channel_id}: {e}")
        
        # Remove all from database
        cursor.execute('DELETE FROM stats_channels WHERE guild_id = ?', (str(self.guild.id),))
        conn.commit()
        conn.close()
        
        embed = discord.Embed(
            title="✅ Alle Stats-Channels gelöscht",
            description=f"Erfolgreich {deleted_count} Channels entfernt.",
            color=discord.Color.green()
        )
        await interaction.edit_original_response(embed=embed)


class RefreshStatsButton(discord.ui.Button):
    def __init__(self, db, guild):
        super().__init__(label="🔄 Aktualisieren", style=discord.ButtonStyle.secondary)
        self.db = db
        self.guild = guild

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # Trigger manual stats update for immediate results
        from main import stats_updater
        await stats_updater()
        
        embed = discord.Embed(
            title="✅ Stats aktualisiert",
            description="Alle Stats-Channels wurden manuell aktualisiert.",
            color=discord.Color.green()
        )
        await interaction.edit_original_response(embed=embed)


# ===== SOCIAL MEDIA STATS SETUP VIEWS =====

class SimplePlatformSelectionView(discord.ui.View):
    def __init__(self, db, guild):
        super().__init__(timeout=300)
        self.db = db
        self.guild = guild
        self.selected_platforms = []
        
        # Add platform selection dropdown
        self.add_item(PlatformDropdown())
        # Add create button (initially disabled)
        self.create_button = CreateSocialMediaChannelsButtonSimple(db, guild, self)
        self.create_button.disabled = True
        self.add_item(self.create_button)
    
    def update_create_button(self):
        """Enable/disable create button based on selection"""
        self.create_button.disabled = len(self.selected_platforms) == 0

class PlatformDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Twitch", description="Twitch-Follower anzeigen", emoji="🟣", value="twitch"),
            discord.SelectOption(label="YouTube", description="YouTube-Abonnenten anzeigen", emoji="📹", value="youtube"),
            discord.SelectOption(label="TikTok", description="TikTok-Follower anzeigen", emoji="🎥", value="tiktok"),
            discord.SelectOption(label="Instagram", description="Instagram-Follower anzeigen", emoji="📷", value="instagram"),
            discord.SelectOption(label="X (Twitter)", description="X/Twitter-Follower anzeigen", emoji="🐦", value="x")
        ]
        super().__init__(placeholder="Wähle Plattformen aus...", min_values=1, max_values=5, options=options)
    
    async def callback(self, interaction: discord.Interaction):
        self.view.selected_platforms = self.values
        self.view.update_create_button()
        
        selected_names = []
        emoji_map = {'twitch': '🟣', 'youtube': '📹', 'tiktok': '🎥', 'instagram': '📷', 'x': '❌'}
        for platform in self.values:
            emoji = emoji_map.get(platform, '📱')
            selected_names.append(f"{emoji} {platform.title()}")
        
        embed = discord.Embed(
            title="📱 Social Media Stats-Channels Setup",
            description=f"**Ausgewählte Plattformen:** {', '.join(selected_names)}\n\nKlicke auf '\u2705 Kanäle erstellen' um fortzufahren.",
            color=discord.Color.green()
        )
        
        await interaction.response.edit_message(embed=embed, view=self.view)

class CreateSocialMediaChannelsButtonSimple(discord.ui.Button):
    def __init__(self, db, guild, parent_view):
        super().__init__(label="✅ Kanäle erstellen", style=discord.ButtonStyle.green)
        self.db = db
        self.guild = guild
        self.parent_view = parent_view
    
    async def callback(self, interaction: discord.Interaction):
        # Show modal for username input
        modal = UsernameInputModal(self.db, self.guild, self.parent_view.selected_platforms)
        await interaction.response.send_modal(modal)


class UsernameInputModal(discord.ui.Modal):
    def __init__(self, db, guild, selected_platforms):
        super().__init__(title="Nutzernamen eingeben")
        self.db = db
        self.guild = guild
        self.selected_platforms = selected_platforms
        
        # Add input fields for each selected platform
        platform_names = {'twitch': 'Twitch', 'youtube': 'YouTube', 'tiktok': 'TikTok', 'instagram': 'Instagram', 'x': 'X (Twitter)'}
        
        for i, platform in enumerate(selected_platforms[:5]):  # Discord modal limit is 5 fields
            field = discord.ui.TextInput(
                label=f"{platform_names.get(platform, platform.title())} Nutzername",
                placeholder=f"Gib den {platform_names.get(platform, platform.title())}-Nutzernamen ein...",
                required=True,
                max_length=50
            )
            setattr(self, f"input_{i}", field)
            self.add_item(field)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Get usernames from input fields
        usernames = []
        for i, platform in enumerate(self.selected_platforms[:5]):
            input_field = getattr(self, f"input_{i}")
            username = input_field.value.strip().replace('@', '')  # Remove @ if present
            usernames.append((platform, username))
        
        created_channels = []
        errors = []
        
        try:
            # Import social media APIs from main module
            from main import social_media_scraping_apis
            
            for platform, username in usernames:
                try:
                    # Validate username exists first
                    logger.info(f"Validating {platform} username: {username}")
                    is_valid, error_type = await social_media_scraping_apis.validate_username_scraping_only(platform, username)
                    
                    if not is_valid:
                        if error_type == "not_found":
                            errors.append(f"{platform.title()}: @{username} - Nutzer nicht gefunden")
                        elif error_type == "scraping_error":
                            errors.append(f"{platform.title()}: @{username} - Temporärer Fehler")
                        else:
                            errors.append(f"{platform.title()}: @{username} - Unbekannter Fehler")
                        continue
                    
                    # Get initial follower count
                    initial_count = await social_media_scraping_apis.get_follower_count_scraping_only(platform, username)
                    if initial_count is None:
                        initial_count = 0
                    
                    # Create voice channel
                    channel_name = f"{platform.title()} Follower: {initial_count:,}"
                    
                    # Create channel with proper permissions
                    overwrites = {
                        self.guild.default_role: discord.PermissionOverwrite(connect=False),
                        self.guild.me: discord.PermissionOverwrite(
                            connect=True,
                            manage_channels=True,
                            view_channel=True
                        )
                    }
                    
                    channel = await self.guild.create_voice_channel(
                        name=channel_name,
                        overwrites=overwrites,
                        reason="Social Media Stats Channel erstellt"
                    )
                    
                    # Store in database with proper error handling
                    try:
                        conn = self.db.get_connection()
                        cursor = conn.cursor()
                        
                        # Check if entry already exists to avoid UNIQUE constraint conflicts
                        cursor.execute('''
                            SELECT id FROM social_media_stats_channels 
                            WHERE channel_id = ? OR (guild_id = ? AND platform = ? AND username = ?)
                        ''', (str(channel.id), str(self.guild.id), platform, username))
                        
                        existing = cursor.fetchone()
                        if existing:
                            # Update existing entry instead of creating new one
                            cursor.execute('''
                                UPDATE social_media_stats_channels 
                                SET channel_id = ?, last_follower_count = ?, last_update = CURRENT_TIMESTAMP
                                WHERE guild_id = ? AND platform = ? AND username = ?
                            ''', (str(channel.id), initial_count, str(self.guild.id), platform, username))
                        else:
                            # Insert new entry
                            cursor.execute('''
                                INSERT INTO social_media_stats_channels 
                                (guild_id, channel_id, platform, username, last_follower_count)
                                VALUES (?, ?, ?, ?, ?)
                            ''', (str(self.guild.id), str(channel.id), platform, username, initial_count))
                        
                        conn.commit()
                        conn.close()
                    except sqlite3.Error as db_error:
                        errors.append(f"{platform.title()}: @{username} - database is locked")
                        logger.error(f"Database error for {platform}/{username}: {db_error}")
                        if 'conn' in locals():
                            conn.close()
                        continue
                    
                    created_channels.append(f"✅ {platform.title()}: @{username} ({initial_count:,} Follower)")
                    logger.info(f"Created social media stats channel for {platform}/{username}")
                    
                except Exception as e:
                    error_msg = f"{platform.title()}: @{username} - {str(e)[:50]}"
                    errors.append(error_msg)
                    logger.error(f"Error creating channel for {platform}/{username}: {e}")
            
            # Create response embed
            if created_channels or errors:
                embed = discord.Embed(
                    title="📱 Social Media Stats-Channels Erstellt",
                    color=discord.Color.green() if created_channels else discord.Color.red()
                )
                
                if created_channels:
                    embed.add_field(
                        name="✅ Erfolgreich erstellt",
                        value="\n".join(created_channels),
                        inline=False
                    )
                
                if errors:
                    embed.add_field(
                        name="❌ Fehler",
                        value="\n".join(errors),
                        inline=False
                    )
                
                embed.add_field(
                    name="🔄 Updates",
                    value="Die Follower-Zahlen werden alle 30 Minuten automatisch aktualisiert.",
                    inline=False
                )
            else:
                embed = discord.Embed(
                    title="❌ Keine Kanäle erstellt",
                    description="Es konnten keine Social Media Stats-Channels erstellt werden.",
                    color=discord.Color.red()
                )
            
            await interaction.edit_original_response(embed=embed, view=None)
            
        except Exception as e:
            logger.error(f"Error in social media stats channel creation: {e}")
            embed = discord.Embed(
                title="❌ Unerwarteter Fehler",
                description=f"Ein unerwarteter Fehler ist aufgetreten: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed, view=None)


class SocialMediaChannelModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title='Social Media Kanal hinzufügen')
        self.setup_view = view
        
        # Platform selection
        self.platform = discord.ui.TextInput(
            label='Plattform',
            placeholder='instagram, x, twitter, youtube, tiktok, twitch',
            required=True,
            max_length=20
        )
        self.add_item(self.platform)
        
        # Username input
        self.username = discord.ui.TextInput(
            label='Nutzername',
            placeholder='Nutzername ohne @',
            required=True,
            max_length=50
        )
        self.add_item(self.username)
    
    async def on_submit(self, interaction: discord.Interaction):
        platform = self.platform.value.lower().strip()
        username = self.username.value.strip().replace('@', '')
        
        # Validate platform
        valid_platforms = ['instagram', 'x', 'twitter', 'youtube', 'tiktok', 'twitch']
        if platform not in valid_platforms:
            embed = discord.Embed(
                title="❌ Ungültige Plattform",
                description=f"Plattform '{platform}' ist nicht unterstützt.\nGültige Plattformen: {', '.join(valid_platforms)}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Check for duplicates
        for existing_platform, existing_username in self.setup_view.selected_platforms:
            if existing_platform == platform and existing_username == username:
                embed = discord.Embed(
                    title="❌ Bereits hinzugefügt",
                    description=f"{platform.title()}: @{username} ist bereits ausgewählt.",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        
        # Add to selection
        self.setup_view.selected_platforms.append((platform, username))
        
        # Update the main view
        await self.setup_view.update_display(interaction)


# ===== SOCIAL MEDIA DELETION VIEW =====

class SocialMediaDeletionView(discord.ui.View):
    def __init__(self, db, guild, channels):
        super().__init__(timeout=300)
        self.db = db
        self.guild = guild
        self.channels = channels
        
        # Add dropdown for channel selection
        if channels:
            self.add_item(ChannelDeletionDropdown(channels))
            # Add delete button
            self.delete_button = DeleteSelectedChannelsButton(db, guild, self)
            self.delete_button.disabled = True
            self.add_item(self.delete_button)
    
    def update_delete_button(self):
        """Enable/disable delete button based on selection"""
        self.delete_button.disabled = not hasattr(self, 'selected_channels') or len(self.selected_channels) == 0

class ChannelDeletionDropdown(discord.ui.Select):
    def __init__(self, channels):
        options = []
        emoji_map = {'instagram': '📷', 'x': '❌', 'twitter': '🐦', 'youtube': '📹', 'tiktok': '🎥', 'twitch': '🟣'}
        
        for channel_id, platform, username, count in channels[:25]:  # Discord limit
            emoji = emoji_map.get(platform, '📱')
            label = f"{platform.title()}: @{username}"
            description = f"{count:,} Follower"
            options.append(discord.SelectOption(
                label=label, 
                description=description, 
                emoji=emoji, 
                value=f"{channel_id}_{platform}_{username}"
            ))
        
        super().__init__(placeholder="Wähle Channels zum Löschen aus...", min_values=1, max_values=len(options), options=options)
    
    async def callback(self, interaction: discord.Interaction):
        self.view.selected_channels = self.values
        self.view.update_delete_button()
        
        selected_names = []
        for value in self.values:
            _, platform, username = value.split('_', 2)
            emoji_map = {'instagram': '📷', 'x': '❌', 'twitter': '🐦', 'youtube': '📹', 'tiktok': '🎥', 'twitch': '🟣'}
            emoji = emoji_map.get(platform, '📱')
            selected_names.append(f"{emoji} {platform.title()}: @{username}")
        
        embed = discord.Embed(
            title="🗑️ Social Media Stats-Channels löschen",
            description=f"**Ausgewählte Channels:**\n{chr(10).join(selected_names)}\n\n⚠️ Diese Aktion kann nicht rückgängig gemacht werden!",
            color=discord.Color.red()
        )
        
        await interaction.response.edit_message(embed=embed, view=self.view)

class DeleteSelectedChannelsButton(discord.ui.Button):
    def __init__(self, db, guild, parent_view):
        super().__init__(label="🗑️ Löschen", style=discord.ButtonStyle.danger)
        self.db = db
        self.guild = guild
        self.parent_view = parent_view
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        deleted_channels = []
        errors = []
        
        try:
            for value in self.parent_view.selected_channels:
                channel_id, platform, username = value.split('_', 2)
                
                try:
                    # Delete the Discord channel
                    channel = self.guild.get_channel(int(channel_id))
                    if channel:
                        await channel.delete(reason="Social Media Stats Channel gelöscht")
                    
                    # Remove from database
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM social_media_stats_channels WHERE channel_id = ?', (channel_id,))
                    conn.commit()
                    conn.close()
                    
                    deleted_channels.append(f"{platform.title()}: @{username}")
                    logger.info(f"✅ Deleted social media channel for {platform}/{username}")
                    
                except Exception as e:
                    logger.error(f"Error deleting channel {channel_id}: {e}")
                    errors.append(f"{platform.title()}: @{username} - Fehler beim Löschen")
            
            # Send result message
            embed = discord.Embed(
                title="🗑️ Löschvorgang abgeschlossen",
                color=discord.Color.green() if deleted_channels and not errors else discord.Color.yellow()
            )
            
            if deleted_channels:
                embed.add_field(
                    name="✅ Erfolgreich gelöscht",
                    value="\n".join(deleted_channels),
                    inline=False
                )
            
            if errors:
                embed.add_field(
                    name="❌ Fehler",
                    value="\n".join(errors),
                    inline=False
                )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in social media channel deletion: {e}")
            embed = discord.Embed(
                title="❌ Fehler",
                description="Ein unerwarteter Fehler ist aufgetreten.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


# ====================== DELETE CREATOR INTERFACE ======================

class DeleteCreatorView(discord.ui.View):
    def __init__(self, db, creators):
        super().__init__(timeout=300)
        self.db = db
        self.add_item(DeleteCreatorSelect(db, creators))

class DeleteCreatorSelect(discord.ui.Select):
    def __init__(self, db, creators):
        self.db = db
        
        # Create select options
        options = []
        for creator_id, username, streamer_type, discord_user_id in creators:
            emoji = "⭐" if streamer_type == "karma" else "👾"
            options.append(discord.SelectOption(
                label=f"{username} ({streamer_type.title()})",
                value=str(creator_id),
                emoji=emoji,
                description=f"Discord ID: {discord_user_id}"
            ))
        
        super().__init__(
            placeholder="Creator zum Löschen auswählen...",
            options=options,
            max_values=1
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle creator deletion"""
        await interaction.response.defer(ephemeral=True)
        
        creator_id = int(self.values[0])
        
        # Get creator details for confirmation
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'SELECT discord_username, streamer_type, discord_user_id FROM creators WHERE id = ?',
                (creator_id,)
            )
            creator_details = cursor.fetchone()
            
            if not creator_details:
                embed = discord.Embed(
                    title="❌ Fehler",
                    description="Creator nicht gefunden.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            username, streamer_type, discord_user_id = creator_details
            
            # Delete all related data
            cursor.execute('DELETE FROM user_subscriptions WHERE creator_id = ?', (creator_id,))
            cursor.execute('DELETE FROM live_status WHERE creator_id = ?', (creator_id,))
            cursor.execute('DELETE FROM event_streaks WHERE creator_id = ?', (creator_id,))
            cursor.execute('DELETE FROM daily_streaks WHERE creator_id = ?', (creator_id,))
            cursor.execute('DELETE FROM creator_channels WHERE creator_id = ?', (creator_id,))
            cursor.execute('DELETE FROM creators WHERE id = ?', (creator_id,))
            
            conn.commit()
            
            # Get Discord user mention if possible
            user_mention = f"<@{discord_user_id}>"
            try:
                user = interaction.client.get_user(int(discord_user_id))
                if user:
                    user_mention = f"{user.mention} ({user.display_name})"
            except:
                pass
            
            embed = discord.Embed(
                title="✅ Creator erfolgreich entfernt",
                description=f"**{username}** ({streamer_type.title()}) wurde aus der Datenbank entfernt.\n\nUser: {user_mention}",
                color=discord.Color.green()
            )
            embed.add_field(
                name="🗑️ Gelöschte Daten:",
                value="• Creator-Profil\n• Alle Abonnements\n• Live-Status Tracking\n• Daily & Event Streaks\n• Kanal-Konfigurationen",
                inline=False
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            logger.info(f"✅ Creator {username} (ID: {creator_id}) successfully deleted by admin")
            
        except Exception as e:
            logger.error(f"Error deleting creator {creator_id}: {e}")
            embed = discord.Embed(
                title="❌ Fehler beim Löschen",
                description="Ein unerwarteter Fehler ist aufgetreten beim Löschen des Creators.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        finally:
            conn.close()