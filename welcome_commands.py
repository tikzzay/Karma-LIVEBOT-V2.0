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

logger = logging.getLogger('KARMA-LiveBOT.Welcome')

Image.MAX_IMAGE_PIXELS = 178956970

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
    
    async def _safe_download_image(self, url: str, timeout: aiohttp.ClientTimeout, max_size: int) -> Optional[bytes]:
        """Safely download image data with size limits and content-type validation"""
        try:
            async with self.session.get(url, timeout=timeout) as resp:
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
            
            draw.text((text_x + 2, text_y + 2), username, font=font, fill=(0, 0, 0))
            draw.text((text_x, text_y), username, font=font, fill=(255, 255, 255))
            
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
    @app_commands.describe(
        channel="Der Channel, in dem Willkommens-Nachrichten gesendet werden",
        text="Der Willkommenstext ({user} = Mention, {username} = Name, {server} = Servername)",
        role="Die Rolle, die neuen Mitgliedern automatisch zugewiesen wird",
        banner="URL des Banner-Bildes für Willkommens-Nachrichten",
        enabled="Aktiviere oder deaktiviere das Willkommens-System"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_config(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        text: Optional[str] = None,
        role: Optional[discord.Role] = None,
        banner: Optional[str] = None,
        enabled: Optional[bool] = None
    ):
        """Configure welcome system for this server"""
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT channel_id, welcome_text, role_id, banner_url, enabled
                FROM welcome_config
                WHERE guild_id = ?
            ''', (str(interaction.guild.id),))
            
            existing = cursor.fetchone()
            
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
            
            new_channel = str(channel.id) if channel else current_channel
            new_text = text if text else current_text
            new_role = str(role.id) if role else current_role
            new_banner = banner if banner else current_banner
            new_enabled = enabled if enabled is not None else current_enabled
            
            if existing:
                cursor.execute('''
                    UPDATE welcome_config
                    SET channel_id = ?, welcome_text = ?, role_id = ?, banner_url = ?, enabled = ?
                    WHERE guild_id = ?
                ''', (new_channel, new_text, new_role, new_banner, new_enabled, str(interaction.guild.id)))
            else:
                cursor.execute('''
                    INSERT INTO welcome_config (guild_id, channel_id, welcome_text, role_id, banner_url, enabled)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (str(interaction.guild.id), new_channel, new_text, new_role, new_banner, new_enabled))
            
            conn.commit()
            conn.close()
            
            embed = discord.Embed(
                title="✅ Willkommens-System konfiguriert",
                color=discord.Color.green()
            )
            
            if new_channel:
                channel_obj = interaction.guild.get_channel(int(new_channel))
                embed.add_field(name="Channel", value=channel_obj.mention if channel_obj else "Nicht gesetzt", inline=False)
            
            embed.add_field(name="Text", value=new_text, inline=False)
            
            if new_role:
                role_obj = interaction.guild.get_role(int(new_role))
                embed.add_field(name="Auto-Rolle", value=role_obj.mention if role_obj else "Nicht gesetzt", inline=False)
            
            if new_banner:
                embed.add_field(name="Banner", value="✅ Gesetzt", inline=False)
            else:
                embed.add_field(name="Banner", value="Standard-Banner", inline=False)
            
            embed.add_field(name="Status", value="🟢 Aktiviert" if new_enabled else "🔴 Deaktiviert", inline=False)
            
            await interaction.followup.send(embed=embed)
            logger.info(f"Welcome system configured for {interaction.guild.name}")
            
        except Exception as e:
            logger.error(f"Error configuring welcome system: {e}")
            await interaction.followup.send("❌ Fehler beim Konfigurieren des Willkommens-Systems.", ephemeral=True)
    
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
