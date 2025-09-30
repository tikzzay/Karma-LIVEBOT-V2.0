"""
Custom Commands Module for KARMA-LiveBOT
Allows admins to create custom slash commands per server
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional

from config import Config

logger = logging.getLogger('KARMA-LiveBOT.CustomCommands')

MAX_CUSTOM_COMMANDS = 50

def has_admin_role():
    """Check if user has admin permissions"""
    def predicate(interaction: discord.Interaction) -> bool:
        if not hasattr(interaction, 'guild') or not interaction.guild:
            return False
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.roles:
            return False
        user_roles = [role.id for role in member.roles]
        return any(role_id in Config.ADMIN_ROLES for role_id in user_roles)
    return app_commands.check(predicate)

class CreateCustomCommandModal(discord.ui.Modal, title='Custom Command erstellen'):
    """Modal for creating a custom command"""
    
    command_name = discord.ui.TextInput(
        label='Command Name',
        placeholder='z.B. teamspeak',
        required=True,
        max_length=32,
        style=discord.TextStyle.short
    )
    
    response_text = discord.ui.TextInput(
        label='Antwort-Text (optional wenn Embed)',
        placeholder='z.B. ts.meinserver.de',
        required=False,
        max_length=2000,
        style=discord.TextStyle.paragraph
    )
    
    embed_title = discord.ui.TextInput(
        label='Embed-Titel (optional)',
        placeholder='z.B. 📡 Teamspeak',
        required=False,
        max_length=256,
        style=discord.TextStyle.short
    )
    
    embed_description = discord.ui.TextInput(
        label='Embed-Beschreibung (optional)',
        placeholder='z.B. Unser Teamspeak Server',
        required=False,
        max_length=4000,
        style=discord.TextStyle.paragraph
    )
    
    button_info = discord.ui.TextInput(
        label='Button (optional): Label|URL',
        placeholder='z.B. Join TS|https://ts.meinserver.de',
        required=False,
        max_length=500,
        style=discord.TextStyle.short
    )
    
    def __init__(self, db, bot):
        super().__init__()
        self.db = db
        self.bot = bot
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            guild_id = str(interaction.guild.id)
            name = self.command_name.value.lower().strip()
            
            # Validate command name (alphanumeric + underscore only)
            if not name.replace('_', '').isalnum():
                await interaction.response.send_message(
                    "❌ Command Name darf nur Buchstaben, Zahlen und Unterstriche enthalten!",
                    ephemeral=True
                )
                return
            
            # Check if command name is reserved
            reserved_names = ['custom', 'help', 'ping', 'addcreator', 'deletecreator', 
                            'request', 'ranking', 'live', 'subcreator', 'unsub']
            if name in reserved_names:
                await interaction.response.send_message(
                    f"❌ Der Name `{name}` ist reserviert und kann nicht verwendet werden!",
                    ephemeral=True
                )
                return
            
            # Check current command count for this guild
            cursor.execute('SELECT COUNT(*) FROM custom_commands WHERE guild_id = ?', (guild_id,))
            current_count = cursor.fetchone()[0]
            
            if current_count >= MAX_CUSTOM_COMMANDS:
                await interaction.response.send_message(
                    f"❌ **Limit erreicht**: Maximal {MAX_CUSTOM_COMMANDS} Custom-Befehle pro Server erlaubt.\n\n"
                    f"Verwende `/custom delete` um einen Befehl zu löschen.",
                    ephemeral=True
                )
                conn.close()
                return
            
            # Check if command already exists
            cursor.execute('SELECT id FROM custom_commands WHERE guild_id = ? AND name = ?', 
                          (guild_id, name))
            if cursor.fetchone():
                await interaction.response.send_message(
                    f"❌ Ein Command mit dem Namen `{name}` existiert bereits!\n\n"
                    f"Verwende `/custom edit` um ihn zu bearbeiten.",
                    ephemeral=True
                )
                conn.close()
                return
            
            # Parse button info
            button_label = None
            button_url = None
            if self.button_info.value and '|' in self.button_info.value:
                parts = self.button_info.value.split('|', 1)
                button_label = parts[0].strip()
                button_url = parts[1].strip()
                
                # Validate URL
                if button_url and not button_url.startswith(('http://', 'https://')):
                    await interaction.response.send_message(
                        "❌ Button-URL muss mit http:// oder https:// beginnen!",
                        ephemeral=True
                    )
                    conn.close()
                    return
            
            # Validate that at least response_text or embed is provided
            if not self.response_text.value and not self.embed_title.value and not self.embed_description.value:
                await interaction.response.send_message(
                    "❌ Du musst entweder einen Antwort-Text ODER ein Embed (Titel/Beschreibung) angeben!",
                    ephemeral=True
                )
                conn.close()
                return
            
            # Insert into database
            cursor.execute('''
                INSERT INTO custom_commands 
                (guild_id, name, response, embed_title, embed_description, embed_color, button_label, button_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                guild_id,
                name,
                self.response_text.value if self.response_text.value else None,
                self.embed_title.value if self.embed_title.value else None,
                self.embed_description.value if self.embed_description.value else None,
                None,  # embed_color - can be added later
                button_label,
                button_url
            ))
            
            conn.commit()
            
            # Register the command dynamically
            await self.bot.get_cog('CustomCommands').register_guild_commands(interaction.guild.id)
            
            embed = discord.Embed(
                title="✅ Custom Command erstellt",
                description=f"Command `/{name}` wurde erfolgreich erstellt!",
                color=discord.Color.green()
            )
            embed.add_field(name="Verwendung", value=f"Benutze `/{name}` um den Command auszuführen", inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"Custom command '{name}' created for guild {guild_id}")
            
        except Exception as e:
            logger.error(f"Error creating custom command: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Erstellen des Custom Commands.",
                ephemeral=True
            )
        finally:
            conn.close()

class EditCustomCommandModal(discord.ui.Modal, title='Custom Command bearbeiten'):
    """Modal for editing a custom command"""
    
    response_text = discord.ui.TextInput(
        label='Antwort-Text (optional wenn Embed)',
        placeholder='z.B. ts.meinserver.de',
        required=False,
        max_length=2000,
        style=discord.TextStyle.paragraph
    )
    
    embed_title = discord.ui.TextInput(
        label='Embed-Titel (optional)',
        placeholder='z.B. 📡 Teamspeak',
        required=False,
        max_length=256,
        style=discord.TextStyle.short
    )
    
    embed_description = discord.ui.TextInput(
        label='Embed-Beschreibung (optional)',
        placeholder='z.B. Unser Teamspeak Server',
        required=False,
        max_length=4000,
        style=discord.TextStyle.paragraph
    )
    
    button_info = discord.ui.TextInput(
        label='Button (optional): Label|URL',
        placeholder='z.B. Join TS|https://ts.meinserver.de',
        required=False,
        max_length=500,
        style=discord.TextStyle.short
    )
    
    def __init__(self, db, bot, command_name: str, current_data: dict):
        super().__init__()
        self.db = db
        self.bot = bot
        self.command_name = command_name
        
        # Pre-fill with current values
        if current_data.get('response'):
            self.response_text.default = current_data['response']
        if current_data.get('embed_title'):
            self.embed_title.default = current_data['embed_title']
        if current_data.get('embed_description'):
            self.embed_description.default = current_data['embed_description']
        if current_data.get('button_label') and current_data.get('button_url'):
            self.button_info.default = f"{current_data['button_label']}|{current_data['button_url']}"
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            guild_id = str(interaction.guild.id)
            
            # Parse button info
            button_label = None
            button_url = None
            if self.button_info.value and '|' in self.button_info.value:
                parts = self.button_info.value.split('|', 1)
                button_label = parts[0].strip()
                button_url = parts[1].strip()
                
                # Validate URL
                if button_url and not button_url.startswith(('http://', 'https://')):
                    await interaction.response.send_message(
                        "❌ Button-URL muss mit http:// oder https:// beginnen!",
                        ephemeral=True
                    )
                    conn.close()
                    return
            
            # Validate that at least response_text or embed is provided
            if not self.response_text.value and not self.embed_title.value and not self.embed_description.value:
                await interaction.response.send_message(
                    "❌ Du musst entweder einen Antwort-Text ODER ein Embed (Titel/Beschreibung) angeben!",
                    ephemeral=True
                )
                conn.close()
                return
            
            # Update in database
            cursor.execute('''
                UPDATE custom_commands 
                SET response = ?, embed_title = ?, embed_description = ?, 
                    button_label = ?, button_url = ?
                WHERE guild_id = ? AND name = ?
            ''', (
                self.response_text.value if self.response_text.value else None,
                self.embed_title.value if self.embed_title.value else None,
                self.embed_description.value if self.embed_description.value else None,
                button_label,
                button_url,
                guild_id,
                self.command_name
            ))
            
            conn.commit()
            
            embed = discord.Embed(
                title="✅ Custom Command aktualisiert",
                description=f"Command `/{self.command_name}` wurde erfolgreich aktualisiert!",
                color=discord.Color.green()
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"Custom command '{self.command_name}' updated for guild {guild_id}")
            
        except Exception as e:
            logger.error(f"Error editing custom command: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Bearbeiten des Custom Commands.",
                ephemeral=True
            )
        finally:
            conn.close()

class CustomCommands(commands.Cog):
    """Cog for managing custom commands"""
    
    def __init__(self, bot: commands.Bot, db):
        self.bot = bot
        self.db = db
        self.registered_commands = {}  # Track registered commands per guild
    
    custom_group = app_commands.Group(name="custom", description="Custom Commands verwalten")
    
    @custom_group.command(name="create", description="Neuen Custom Command erstellen")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    async def create_command(self, interaction: discord.Interaction):
        """Create a new custom command"""
        modal = CreateCustomCommandModal(self.db, self.bot)
        await interaction.response.send_modal(modal)
    
    @custom_group.command(name="edit", description="Bestehenden Custom Command bearbeiten")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    @app_commands.describe(name="Name des Commands")
    async def edit_command(self, interaction: discord.Interaction, name: str):
        """Edit an existing custom command"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            guild_id = str(interaction.guild.id)
            name = name.lower().strip()
            
            # Get current command data
            cursor.execute('''
                SELECT response, embed_title, embed_description, button_label, button_url
                FROM custom_commands
                WHERE guild_id = ? AND name = ?
            ''', (guild_id, name))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                await interaction.response.send_message(
                    f"❌ Command `{name}` nicht gefunden!",
                    ephemeral=True
                )
                return
            
            current_data = {
                'response': result[0],
                'embed_title': result[1],
                'embed_description': result[2],
                'button_label': result[3],
                'button_url': result[4]
            }
            
            modal = EditCustomCommandModal(self.db, self.bot, name, current_data)
            await interaction.response.send_modal(modal)
            
        except Exception as e:
            logger.error(f"Error in edit command: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Laden des Commands.",
                ephemeral=True
            )
            conn.close()
    
    @custom_group.command(name="delete", description="Custom Command löschen")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    @app_commands.describe(name="Name des Commands")
    async def delete_command(self, interaction: discord.Interaction, name: str):
        """Delete a custom command"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            guild_id = str(interaction.guild.id)
            name = name.lower().strip()
            
            # Check if command exists
            cursor.execute('SELECT id FROM custom_commands WHERE guild_id = ? AND name = ?', 
                          (guild_id, name))
            
            if not cursor.fetchone():
                await interaction.response.send_message(
                    f"❌ Command `{name}` nicht gefunden!",
                    ephemeral=True
                )
                conn.close()
                return
            
            # Delete the command
            cursor.execute('DELETE FROM custom_commands WHERE guild_id = ? AND name = ?', 
                          (guild_id, name))
            conn.commit()
            
            # Unregister the command
            await self.unregister_guild_command(interaction.guild.id, name)
            
            embed = discord.Embed(
                title="✅ Custom Command gelöscht",
                description=f"Command `/{name}` wurde erfolgreich gelöscht!",
                color=discord.Color.green()
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"Custom command '{name}' deleted for guild {guild_id}")
            
        except Exception as e:
            logger.error(f"Error deleting custom command: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Löschen des Custom Commands.",
                ephemeral=True
            )
        finally:
            conn.close()
    
    @custom_group.command(name="list", description="Alle Custom Commands anzeigen")
    @app_commands.default_permissions(administrator=True)
    @has_admin_role()
    async def list_commands(self, interaction: discord.Interaction):
        """List all custom commands for this server"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            guild_id = str(interaction.guild.id)
            
            cursor.execute('''
                SELECT name, response, embed_title, embed_description, button_label
                FROM custom_commands
                WHERE guild_id = ?
                ORDER BY name ASC
            ''', (guild_id,))
            
            commands = cursor.fetchall()
            conn.close()
            
            if not commands:
                await interaction.response.send_message(
                    "📝 Noch keine Custom Commands erstellt.\n\n"
                    f"Verwende `/custom create` um einen zu erstellen!",
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title=f"📝 Custom Commands ({len(commands)}/{MAX_CUSTOM_COMMANDS})",
                description=f"Alle Custom Commands für **{interaction.guild.name}**",
                color=discord.Color.blue()
            )
            
            for cmd in commands:
                name, response, embed_title, embed_desc, button_label = cmd
                
                # Create preview
                preview_parts = []
                if response:
                    preview_parts.append(f"Text: {response[:50]}{'...' if len(response) > 50 else ''}")
                if embed_title:
                    preview_parts.append(f"Embed: {embed_title}")
                if button_label:
                    preview_parts.append(f"Button: {button_label}")
                
                preview = "\n".join(preview_parts) if preview_parts else "Keine Vorschau"
                
                embed.add_field(
                    name=f"/{name}",
                    value=preview,
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error listing custom commands: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Laden der Custom Commands.",
                ephemeral=True
            )
            conn.close()
    
    async def register_guild_commands(self, guild_id: int):
        """Register all custom commands for a guild"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT name FROM custom_commands WHERE guild_id = ?', (str(guild_id),))
            commands = cursor.fetchall()
            
            guild = self.bot.get_guild(guild_id)
            if not guild:
                logger.warning(f"Guild {guild_id} not found for command registration")
                return
            
            # Clear old commands for this guild
            self.bot.tree.clear_commands(guild=guild)
            
            # Re-add all cogs commands
            for cog_name, cog in self.bot.cogs.items():
                if hasattr(cog, '__cog_app_commands__'):
                    for command in cog.__cog_app_commands__:
                        self.bot.tree.add_command(command, guild=guild)
            
            # Add custom commands
            for (name,) in commands:
                await self.add_custom_command(guild_id, name)
            
            # Sync commands
            await self.bot.tree.sync(guild=guild)
            logger.info(f"Registered {len(commands)} custom commands for guild {guild_id}")
            
        except Exception as e:
            logger.error(f"Error registering guild commands: {e}")
        finally:
            conn.close()
    
    async def add_custom_command(self, guild_id: int, command_name: str):
        """Add a single custom command to the command tree"""
        
        async def custom_command_callback(interaction: discord.Interaction):
            """Callback for custom command execution"""
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            try:
                cursor.execute('''
                    SELECT response, embed_title, embed_description, embed_color, 
                           button_label, button_url
                    FROM custom_commands
                    WHERE guild_id = ? AND name = ?
                ''', (str(interaction.guild.id), command_name))
                
                result = cursor.fetchone()
                
                if not result:
                    await interaction.response.send_message(
                        "❌ Command nicht gefunden.",
                        ephemeral=True
                    )
                    return
                
                response, embed_title, embed_desc, embed_color, button_label, button_url = result
                
                # Build response
                view = None
                embed = None
                
                # Create embed if title or description exists
                if embed_title or embed_desc:
                    embed = discord.Embed(
                        title=embed_title if embed_title else discord.Embed.Empty,
                        description=embed_desc if embed_desc else discord.Embed.Empty,
                        color=discord.Color.blue()
                    )
                
                # Add button if exists
                if button_label and button_url:
                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(
                        label=button_label,
                        url=button_url,
                        style=discord.ButtonStyle.link
                    ))
                
                # Send response
                if embed and response:
                    await interaction.response.send_message(content=response, embed=embed, view=view)
                elif embed:
                    await interaction.response.send_message(embed=embed, view=view)
                elif response:
                    await interaction.response.send_message(content=response, view=view)
                else:
                    await interaction.response.send_message(
                        "❌ Command hat keinen Inhalt.",
                        ephemeral=True
                    )
                
            except Exception as e:
                logger.error(f"Error executing custom command '{command_name}': {e}")
                await interaction.response.send_message(
                    "❌ Fehler beim Ausführen des Commands.",
                    ephemeral=True
                )
            finally:
                conn.close()
        
        # Create the command
        guild = self.bot.get_guild(guild_id)
        if guild:
            command = app_commands.Command(
                name=command_name,
                description=f"Custom Command: {command_name}",
                callback=custom_command_callback
            )
            self.bot.tree.add_command(command, guild=guild)
    
    async def unregister_guild_command(self, guild_id: int, command_name: str):
        """Unregister a specific custom command"""
        try:
            guild = self.bot.get_guild(guild_id)
            if guild:
                # Re-sync all commands (which will exclude the deleted one)
                await self.register_guild_commands(guild_id)
        except Exception as e:
            logger.error(f"Error unregistering command '{command_name}': {e}")

async def setup(bot: commands.Bot):
    """Setup function for the cog"""
    pass
