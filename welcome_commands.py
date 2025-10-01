#!/usr/bin/env python3
"""
Welcome System Module for KARMA-LiveBOT
Manages welcome messages with custom banners and auto-role assignment
"""

import discord
from discord import app_commands
from discord.ext import commands
import logging
import io
import asyncio
import aiohttp
from PIL import Image, ImageDraw, ImageFont
from typing import Optional
import socket
from urllib.parse import urlparse
import ipaddress

logger = logging.getLogger('KARMA-LiveBOT.Welcome')

Image.MAX_IMAGE_PIXELS = 178956970

class WelcomeTextModal(discord.ui.Modal):
    """Modal for configuring welcome text and banner URL"""
    
    def __init__(self, current_text: str, current_banner: Optional[str]):
        super().__init__(title="Text & Banner Konfiguration")
        
        self.welcome_text = discord.ui.TextInput(
            label="Willkommenstext",
            placeholder="{user} = Mention, {username} = Name, {server} = Server",
            default=current_text,
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=True
        )
        self.add_item(self.welcome_text)
        
        self.banner_url = discord.ui.TextInput(
            label="Banner-URL (optional)",
            placeholder="https://example.com/banner.png",
            default=current_banner or "",
            style=discord.TextStyle.short,
            max_length=500,
            required=False
        )
        self.add_item(self.banner_url)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission"""
        await interaction.response.defer()
        self.text_value = self.welcome_text.value
        self.banner_value = self.banner_url.value if self.banner_url.value else None

class WelcomeConfigView(discord.ui.View):
    """Interactive view for configuring the welcome system"""
    
    def __init__(self, db, guild: discord.Guild, current_channel: Optional[str], 
                 current_text: str, current_role: Optional[str], 
                 current_banner: Optional[str], current_enabled: bool):
        super().__init__(timeout=300)
        self.db = db
        self.guild = guild
        self.channel_id = current_channel
        self.text = current_text
        self.role_id = current_role
        self.banner = current_banner
        self.enabled = current_enabled
        
        self.update_buttons()
    
    def update_buttons(self):
        """Update button labels to reflect current state"""
        self.clear_items()
        
        self.add_item(self.channel_select)
        self.add_item(self.role_select)
        
        toggle_button = discord.ui.Button(
            label=f"System: {'🟢 Aktiviert' if self.enabled else '🔴 Deaktiviert'}",
            style=discord.ButtonStyle.success if self.enabled else discord.ButtonStyle.danger,
            custom_id="toggle_enabled"
        )
        toggle_button.callback = self.toggle_enabled_callback
        self.add_item(toggle_button)
        
        text_button = discord.ui.Button(
            label="📝 Text & Banner bearbeiten",
            style=discord.ButtonStyle.primary,
            custom_id="edit_text"
        )
        text_button.callback = self.edit_text_callback
        self.add_item(text_button)
        
        save_button = discord.ui.Button(
            label="💾 Speichern",
            style=discord.ButtonStyle.success,
            custom_id="save_config"
        )
        save_button.callback = self.save_callback
        self.add_item(save_button)
    
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="📢 Wähle den Willkommens-Channel",
        min_values=1,
        max_values=1
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        """Handle channel selection"""
        self.channel_id = str(select.values[0].id)
        await interaction.response.send_message(
            f"✅ Channel auf {select.values[0].mention} gesetzt!",
            ephemeral=True,
            delete_after=3
        )
        logger.info(f"Channel selected: {select.values[0].name}")
    
    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="🎭 Wähle die Auto-Rolle (optional)",
        min_values=0,
        max_values=1
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        """Handle role selection"""
        if select.values:
            self.role_id = str(select.values[0].id)
            await interaction.response.send_message(
                f"✅ Auto-Rolle auf {select.values[0].mention} gesetzt!",
                ephemeral=True,
                delete_after=3
            )
            logger.info(f"Role selected: {select.values[0].name}")
        else:
            self.role_id = None
            await interaction.response.send_message(
                "✅ Auto-Rolle entfernt!",
                ephemeral=True,
                delete_after=3
            )
    
    async def toggle_enabled_callback(self, interaction: discord.Interaction):
        """Toggle enabled/disabled state"""
        self.enabled = not self.enabled
        self.update_buttons()
        
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"✅ System {'aktiviert' if self.enabled else 'deaktiviert'}!",
            ephemeral=True,
            delete_after=3
        )
        logger.info(f"Welcome system toggled: {self.enabled}")
    
    async def edit_text_callback(self, interaction: discord.Interaction):
        """Open modal for text and banner editing"""
        modal = WelcomeTextModal(self.text, self.banner)
        await interaction.response.send_modal(modal)
        
        await modal.wait()
        
        if hasattr(modal, 'text_value'):
            self.text = modal.text_value
            self.banner = modal.banner_value
            logger.info(f"Text and banner updated via modal")
    
    async def save_callback(self, interaction: discord.Interaction):
        """Save configuration to database"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT guild_id FROM welcome_config WHERE guild_id = ?
            ''', (str(self.guild.id),))
            
            existing = cursor.fetchone()
            
            if existing:
                cursor.execute('''
                    UPDATE welcome_config
                    SET channel_id = ?, welcome_text = ?, role_id = ?, banner_url = ?, enabled = ?
                    WHERE guild_id = ?
                ''', (self.channel_id, self.text, self.role_id, self.banner, self.enabled, str(self.guild.id)))
            else:
                cursor.execute('''
                    INSERT INTO welcome_config (guild_id, channel_id, welcome_text, role_id, banner_url, enabled)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (str(self.guild.id), self.channel_id, self.text, self.role_id, self.banner, self.enabled))
            
            conn.commit()
            conn.close()
            
            embed = discord.Embed(
                title="✅ Willkommens-System gespeichert!",
                color=discord.Color.green()
            )
            
            if self.channel_id:
                channel = self.guild.get_channel(int(self.channel_id))
                embed.add_field(name="📢 Channel", value=channel.mention if channel else "Nicht gesetzt", inline=False)
            else:
                embed.add_field(name="📢 Channel", value="❌ Nicht gesetzt", inline=False)
            
            embed.add_field(name="📝 Text", value=self.text[:100] + "..." if len(self.text) > 100 else self.text, inline=False)
            
            if self.role_id:
                role = self.guild.get_role(int(self.role_id))
                embed.add_field(name="🎭 Auto-Rolle", value=role.mention if role else "Nicht gesetzt", inline=False)
            else:
                embed.add_field(name="🎭 Auto-Rolle", value="❌ Keine Auto-Rolle", inline=False)
            
            if self.banner:
                embed.add_field(name="🖼️ Banner", value="✅ Gesetzt", inline=False)
            else:
                embed.add_field(name="🖼️ Banner", value="Standard-Banner", inline=False)
            
            embed.add_field(name="⚡ Status", value="🟢 Aktiviert" if self.enabled else "🔴 Deaktiviert", inline=False)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            self.stop()
            logger.info(f"Welcome config saved for {self.guild.name}")
            
        except Exception as e:
            logger.error(f"Error saving welcome config: {e}")
            await interaction.followup.send("❌ Fehler beim Speichern der Konfiguration.", ephemeral=True)

class WelcomeCommands(commands.Cog):
    """Welcome system with custom banners and auto-roles"""
    
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self.session = None
        logger.info("Welcome system initialized")
    
    async def cog_load(self):
        """Create aiohttp session when cog loads"""
        self.session = aiohttp.ClientSession()
        logger.info("Welcome system: ClientSession created")
    
    async def cog_unload(self):
        """Close aiohttp session when cog unloads"""
        if self.session:
            await self.session.close()
            logger.info("Welcome system: ClientSession closed")
    
    def _is_safe_url(self, url: str) -> bool:
        """
        Enhanced SSRF protection with IPv6 support and comprehensive IP validation
        Blocks private/internal IPs, validates all resolved addresses, and restricts ports
        Returns True if URL is safe to access, False otherwise
        """
        try:
            parsed = urlparse(url)
            
            if parsed.scheme not in ('http', 'https'):
                logger.warning(f"SSRF Protection: Invalid protocol '{parsed.scheme}'")
                return False
            
            hostname = parsed.hostname
            if not hostname:
                logger.warning("SSRF Protection: No hostname found in URL")
                return False
            
            port = parsed.port
            if port and port not in (80, 443, None):
                logger.warning(f"SSRF Protection: Non-standard port {port} blocked")
                return False
            
            try:
                addr_info = socket.getaddrinfo(hostname, port or (443 if parsed.scheme == 'https' else 80), 
                                               family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
            except (socket.gaierror, ValueError) as e:
                logger.warning(f"SSRF Protection: DNS resolution failed for {hostname}: {e}")
                return False
            
            if not addr_info:
                logger.warning(f"SSRF Protection: No addresses resolved for {hostname}")
                return False
            
            blocked_ipv4_ranges = [
                ipaddress.ip_network('0.0.0.0/8'),
                ipaddress.ip_network('10.0.0.0/8'),
                ipaddress.ip_network('100.64.0.0/10'),
                ipaddress.ip_network('127.0.0.0/8'),
                ipaddress.ip_network('169.254.0.0/16'),
                ipaddress.ip_network('172.16.0.0/12'),
                ipaddress.ip_network('192.168.0.0/16'),
                ipaddress.ip_network('224.0.0.0/4'),
                ipaddress.ip_network('240.0.0.0/4'),
            ]
            
            checked_ips = []
            for family, socktype, proto, canonname, sockaddr in addr_info:
                ip_str = sockaddr[0]
                
                try:
                    ip = ipaddress.ip_address(ip_str)
                except ValueError:
                    logger.warning(f"SSRF Protection: Invalid IP format {ip_str}")
                    return False
                
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    logger.warning(f"SSRF Protection: Blocked private/internal IP {ip} for {hostname}")
                    return False
                
                if isinstance(ip, ipaddress.IPv4Address):
                    for blocked in blocked_ipv4_ranges:
                        if ip in blocked:
                            logger.warning(f"SSRF Protection: Blocked IPv4 {ip} in range {blocked}")
                            return False
                
                if isinstance(ip, ipaddress.IPv6Address):
                    if ip.is_site_local:
                        logger.warning(f"SSRF Protection: Blocked site-local IPv6 {ip}")
                        return False
                
                if not ip.is_global:
                    logger.warning(f"SSRF Protection: Blocked non-global IP {ip}")
                    return False
                
                checked_ips.append(str(ip))
            
            logger.info(f"SSRF Protection: URL {hostname} passed validation with {len(checked_ips)} global IPs: {', '.join(checked_ips)}")
            return True
            
        except Exception as e:
            logger.error(f"SSRF Protection: Error validating URL: {e}")
            return False
    
    async def _safe_download_image(self, url: str, timeout: aiohttp.ClientTimeout, max_size: int) -> Optional[bytes]:
        """Safely download image data with size limits, content-type validation, and redirect protection"""
        try:
            async with self.session.get(url, timeout=timeout, allow_redirects=False) as resp:
                if resp.status != 200:
                    return None
                
                content_type = resp.headers.get('Content-Type', '')
                if not content_type.startswith('image/'):
                    logger.warning(f"Invalid content-type: {content_type}")
                    return None
                
                chunks = []
                total_size = 0
                
                async for chunk in resp.content.iter_chunked(8192):
                    total_size += len(chunk)
                    if total_size > max_size:
                        logger.warning(f"Image download exceeded {max_size} bytes, aborting")
                        return None
                    chunks.append(chunk)
                
                return b''.join(chunks)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(f"Failed to download image: {e}")
            return None
    
    async def create_welcome_image(self, member: discord.Member, banner_url: Optional[str] = None) -> io.BytesIO:
        """Create a welcome image with banner, profile picture, and username"""
        
        width, height = 1200, 400
        max_image_size = 10 * 1024 * 1024
        timeout = aiohttp.ClientTimeout(total=5, connect=3)
        
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            if banner_url:
                if not banner_url.startswith(('http://', 'https://')):
                    logger.warning(f"Invalid banner URL protocol: {banner_url}")
                    banner = Image.new('RGB', (width, height), color=(54, 57, 63))
                elif not self._is_safe_url(banner_url):
                    logger.warning(f"Banner URL failed SSRF validation: {banner_url}")
                    banner = Image.new('RGB', (width, height), color=(54, 57, 63))
                else:
                    banner_data = await self._safe_download_image(banner_url, timeout, max_image_size)
                    if banner_data:
                        try:
                            banner = Image.open(io.BytesIO(banner_data))
                            banner = banner.resize((width, height), Image.Resampling.LANCZOS)
                        except (Image.DecompressionBombError, OSError) as e:
                            logger.warning(f"Failed to process banner image: {e}")
                            banner = Image.new('RGB', (width, height), color=(54, 57, 63))
                    else:
                        banner = Image.new('RGB', (width, height), color=(54, 57, 63))
            else:
                banner = Image.new('RGB', (width, height), color=(54, 57, 63))
            
            avatar_url = str(member.display_avatar.url)
            avatar_data = await self._safe_download_image(avatar_url, timeout, max_image_size)
            if avatar_data:
                try:
                    avatar = Image.open(io.BytesIO(avatar_data))
                except (Image.DecompressionBombError, OSError) as e:
                    logger.warning(f"Failed to process avatar image: {e}")
                    avatar = Image.new('RGB', (200, 200), color=(128, 128, 128))
            else:
                avatar = Image.new('RGB', (200, 200), color=(128, 128, 128))
            
            avatar = avatar.resize((200, 200), Image.Resampling.LANCZOS)
            
            mask = Image.new('L', (200, 200), 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0, 200, 200), fill=255)
            
            avatar_position = ((width - 200) // 2, (height - 200) // 2)
            banner.paste(avatar, avatar_position, mask)
            
            draw = ImageDraw.Draw(banner)
            
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
                small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
            except:
                font = ImageFont.load_default()
                small_font = ImageFont.load_default()
            
            username = str(member.display_name)
            
            text_bbox = draw.textbbox((0, 0), username, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_x = (width - text_width) // 2
            text_y = avatar_position[1] + 220
            
            for offset_x in [-3, -2, -1, 0, 1, 2, 3]:
                for offset_y in [-3, -2, -1, 0, 1, 2, 3]:
                    if offset_x != 0 or offset_y != 0:
                        draw.text((text_x + offset_x, text_y + offset_y), username, font=font, fill=(0, 0, 0))
            
            draw.text((text_x, text_y), username, font=font, fill=(138, 43, 226))
            
            buffer = io.BytesIO()
            banner.save(buffer, format='PNG')
            buffer.seek(0)
            
            return buffer
            
        except Exception as e:
            logger.error(f"Error creating welcome image: {e}")
            fallback = Image.new('RGB', (width, height), color=(54, 57, 63))
            buffer = io.BytesIO()
            fallback.save(buffer, format='PNG')
            buffer.seek(0)
            return buffer
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Handle member join event and send welcome message"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT channel_id, welcome_text, role_id, banner_url, enabled
                FROM welcome_config
                WHERE guild_id = ?
            ''', (str(member.guild.id),))
            
            config = cursor.fetchone()
            conn.close()
            
            if not config or not config[4]:
                return
            
            channel_id, welcome_text, role_id, banner_url, enabled = config
            
            if not channel_id:
                return
            
            channel = member.guild.get_channel(int(channel_id))
            if not channel:
                logger.warning(f"Welcome channel {channel_id} not found in {member.guild.name}")
                return
            
            welcome_message = welcome_text.replace('{user}', member.mention)
            welcome_message = welcome_message.replace('{server}', member.guild.name)
            welcome_message = welcome_message.replace('{username}', str(member.display_name))
            
            image_buffer = await self.create_welcome_image(member, banner_url)
            
            file = discord.File(fp=image_buffer, filename='welcome.png')
            
            embed = discord.Embed(
                description=welcome_message,
                color=discord.Color.green()
            )
            embed.set_image(url='attachment://welcome.png')
            
            await channel.send(embed=embed, file=file)
            logger.info(f"Welcome message sent for {member.display_name} in {member.guild.name}")
            
            if role_id:
                try:
                    role = member.guild.get_role(int(role_id))
                    if role:
                        await member.add_roles(role)
                        logger.info(f"Assigned role {role.name} to {member.display_name}")
                    else:
                        logger.warning(f"Welcome role {role_id} not found in {member.guild.name}")
                except Exception as e:
                    logger.error(f"Error assigning welcome role: {e}")
            
        except Exception as e:
            logger.error(f"Error in on_member_join: {e}")
    
    @app_commands.command(name="welcome", description="Konfiguriere das Willkommens-System für diesen Server")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_config(self, interaction: discord.Interaction):
        """Configure welcome system for this server - opens interactive configuration window"""
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT channel_id, welcome_text, role_id, banner_url, enabled
                FROM welcome_config
                WHERE guild_id = ?
            ''', (str(interaction.guild.id),))
            
            existing = cursor.fetchone()
            conn.close()
            
            if existing:
                current_channel = existing[0]
                current_text = existing[1]
                current_role = existing[2]
                current_banner = existing[3]
                current_enabled = bool(existing[4])
            else:
                current_channel = None
                current_text = 'Willkommen {user}!'
                current_role = None
                current_banner = None
                current_enabled = True
            
            view = WelcomeConfigView(
                self.db, 
                interaction.guild, 
                current_channel, 
                current_text, 
                current_role, 
                current_banner, 
                current_enabled
            )
            
            embed = discord.Embed(
                title="🎉 Willkommens-System Konfiguration",
                description="Nutze die Buttons und Menüs unten, um das Willkommens-System einzurichten.",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="📝 Verfügbare Platzhalter für Text:",
                value="`{user}` - Erwähnt den neuen User\n`{username}` - Zeigt den Usernamen\n`{server}` - Zeigt den Servernamen",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            logger.info(f"Welcome config view opened for {interaction.guild.name}")
            
        except Exception as e:
            logger.error(f"Error opening welcome config: {e}")
            await interaction.response.send_message("❌ Fehler beim Öffnen der Konfiguration.", ephemeral=True)
    
    @app_commands.command(name="welcome_status", description="Zeige die aktuelle Willkommens-System Konfiguration")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_status(self, interaction: discord.Interaction):
        """Show current welcome system configuration"""
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT channel_id, welcome_text, role_id, banner_url, enabled
                FROM welcome_config
                WHERE guild_id = ?
            ''', (str(interaction.guild.id),))
            
            config = cursor.fetchone()
            conn.close()
            
            if not config:
                await interaction.followup.send("❌ Willkommens-System ist noch nicht konfiguriert. Nutze `/welcome` um es einzurichten.", ephemeral=True)
                return
            
            channel_id, welcome_text, role_id, banner_url, enabled = config
            
            embed = discord.Embed(
                title="Willkommens-System Konfiguration",
                color=discord.Color.blue() if enabled else discord.Color.red()
            )
            
            if channel_id:
                channel = interaction.guild.get_channel(int(channel_id))
                embed.add_field(name="Channel", value=channel.mention if channel else "❌ Channel nicht gefunden", inline=False)
            else:
                embed.add_field(name="Channel", value="❌ Nicht gesetzt", inline=False)
            
            embed.add_field(name="Text", value=welcome_text, inline=False)
            
            if role_id:
                role = interaction.guild.get_role(int(role_id))
                embed.add_field(name="Auto-Rolle", value=role.mention if role else "❌ Rolle nicht gefunden", inline=False)
            else:
                embed.add_field(name="Auto-Rolle", value="❌ Nicht gesetzt", inline=False)
            
            if banner_url:
                embed.add_field(name="Banner", value="✅ Gesetzt", inline=False)
            else:
                embed.add_field(name="Banner", value="Standard-Banner", inline=False)
            
            embed.add_field(name="Status", value="🟢 Aktiviert" if enabled else "🔴 Deaktiviert", inline=False)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error showing welcome status: {e}")
            await interaction.followup.send("❌ Fehler beim Abrufen der Konfiguration.", ephemeral=True)

async def setup(bot, db):
    """Setup function for the Welcome cog"""
    await bot.add_cog(WelcomeCommands(bot, db))
