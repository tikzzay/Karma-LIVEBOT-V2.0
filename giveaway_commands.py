#!/usr/bin/env python3
"""
Giveaway System für KARMA-LiveBOT
Verwaltung von Giveaways mit Timer, Gewinner-Auswahl und Teilnahme-Tracking
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
from datetime import datetime, timedelta
import random
import asyncio
from typing import Optional

logger = logging.getLogger('KARMA-LiveBOT.Giveaway')


class GiveawayModal(discord.ui.Modal, title='Giveaway erstellen'):
    """Modal für Giveaway-Eingaben"""
    
    description = discord.ui.TextInput(
        label='Beschreibung',
        placeholder='Was wird verlost? (z.B. "3x Steam Keys für XYZ")',
        required=True,
        max_length=500,
        style=discord.TextStyle.paragraph
    )
    
    keys = discord.ui.TextInput(
        label='Keys (durch Komma getrennt)',
        placeholder='KEY1,KEY2,KEY3',
        required=True,
        max_length=1000,
        style=discord.TextStyle.paragraph
    )
    
    duration = discord.ui.TextInput(
        label='Dauer in Minuten',
        placeholder='z.B. 15',
        required=True,
        max_length=4
    )
    
    winner_count = discord.ui.TextInput(
        label='Anzahl Gewinner',
        placeholder='z.B. 2',
        required=True,
        max_length=3
    )
    
    image_url = discord.ui.TextInput(
        label='Bild-URL (optional)',
        placeholder='https://example.com/image.png',
        required=False,
        max_length=500
    )
    
    def __init__(self, bot, db, selected_channel):
        super().__init__()
        self.bot = bot
        self.db = db
        self.selected_channel = selected_channel
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            duration_minutes = int(self.duration.value)
            winner_count = int(self.winner_count.value)
            
            if duration_minutes <= 0 or winner_count <= 0:
                await interaction.response.send_message(
                    '❌ Dauer und Gewinner-Anzahl müssen größer als 0 sein!',
                    ephemeral=True
                )
                return
            
            keys_list = [k.strip() for k in self.keys.value.split(',')]
            if len(keys_list) < winner_count:
                await interaction.response.send_message(
                    f'❌ Du hast nur {len(keys_list)} Keys angegeben, aber {winner_count} Gewinner!',
                    ephemeral=True
                )
                return
            
            await interaction.response.defer(ephemeral=True)
            
            ends_at = datetime.now() + timedelta(minutes=duration_minutes)
            
            embed = discord.Embed(
                title='🎉 GIVEAWAY',
                description=self.description.value,
                color=discord.Color.gold(),
                timestamp=ends_at
            )
            embed.add_field(name='⏰ Endet', value=f'<t:{int(ends_at.timestamp())}:R>', inline=True)
            embed.add_field(name='🏆 Gewinner', value=str(winner_count), inline=True)
            embed.add_field(name='👥 Teilnehmer', value='0', inline=True)
            embed.set_footer(text='Drücke den Button um teilzunehmen!')
            
            if self.image_url.value:
                try:
                    embed.set_image(url=self.image_url.value)
                except:
                    pass
            
            view = GiveawayView(self.bot, self.db, None)
            message = await self.selected_channel.send(embed=embed, view=view)
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO giveaways (guild_id, channel_id, message_id, description, keys, 
                                      duration_minutes, winner_count, image_url, ends_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(interaction.guild.id),
                str(self.selected_channel.id),
                str(message.id),
                self.description.value,
                self.keys.value,
                duration_minutes,
                winner_count,
                self.image_url.value if self.image_url.value else None,
                ends_at
            ))
            giveaway_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            view.giveaway_id = giveaway_id
            await message.edit(view=view)
            
            asyncio.create_task(self._end_giveaway_after_timer(
                giveaway_id, duration_minutes, message, self.selected_channel, winner_count
            ))
            
            await interaction.followup.send(
                f'✅ Giveaway erfolgreich in {self.selected_channel.mention} gestartet!',
                ephemeral=True
            )
            logger.info(f'Giveaway {giveaway_id} gestartet von {interaction.user} in {self.selected_channel.name}')
            
        except ValueError:
            await interaction.followup.send(
                '❌ Dauer und Gewinner-Anzahl müssen Zahlen sein!',
                ephemeral=True
            )
        except Exception as e:
            logger.error(f'Fehler beim Erstellen des Giveaways: {e}')
            await interaction.followup.send(
                f'❌ Fehler beim Erstellen des Giveaways: {str(e)}',
                ephemeral=True
            )
    
    async def _end_giveaway_after_timer(self, giveaway_id, duration_minutes, message, channel, winner_count):
        """Timer-Funktion für automatisches Giveaway-Ende"""
        try:
            await asyncio.sleep(duration_minutes * 60)
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT is_active FROM giveaways WHERE id = ?', (giveaway_id,))
            result = cursor.fetchone()
            
            if not result or not result[0]:
                conn.close()
                return
            
            cursor.execute('SELECT user_id FROM giveaway_participants WHERE giveaway_id = ?', (giveaway_id,))
            participants = [row[0] for row in cursor.fetchall()]
            
            if len(participants) == 0:
                cursor.execute('UPDATE giveaways SET is_active = FALSE WHERE id = ?', (giveaway_id,))
                conn.commit()
                conn.close()
                
                await channel.send('😢 Das Giveaway endete ohne Teilnehmer!')
                
                try:
                    embed = message.embeds[0]
                    embed.color = discord.Color.red()
                    embed.set_footer(text='Giveaway beendet - Keine Teilnehmer')
                    await message.edit(embed=embed, view=None)
                except:
                    pass
                
                return
            
            actual_winner_count = min(winner_count, len(participants))
            winners = random.sample(participants, actual_winner_count)
            
            for winner_id in winners:
                cursor.execute('INSERT OR IGNORE INTO past_winners (user_id, giveaway_id) VALUES (?, ?)',
                              (winner_id, giveaway_id))
            
            cursor.execute('UPDATE giveaways SET is_active = FALSE WHERE id = ?', (giveaway_id,))
            conn.commit()
            conn.close()
            
            winner_mentions = [f'<@{winner_id}>' for winner_id in winners]
            winner_text = ', '.join(winner_mentions)
            
            await channel.send(f'🎉 **GEWINNER:** {winner_text}\n\nGlückwunsch! Die Keys werden vom Admin vergeben.')
            
            try:
                embed = message.embeds[0]
                embed.color = discord.Color.green()
                embed.set_footer(text=f'Giveaway beendet - Gewinner: {len(winners)}')
                await message.edit(embed=embed, view=None)
            except:
                pass
            
            logger.info(f'Giveaway {giveaway_id} beendet - Gewinner: {winners}')
            
        except Exception as e:
            logger.error(f'Fehler beim Beenden des Giveaways {giveaway_id}: {e}')


class ChannelSelectView(discord.ui.View):
    """View mit Channel-Auswahl Dropdown"""
    
    def __init__(self, bot, db, timeout=180):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.db = db
        self.selected_channel = None
    
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder='Wähle einen Channel für das Giveaway',
        min_values=1,
        max_values=1,
        channel_types=[discord.ChannelType.text]
    )
    async def channel_select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        selected_channel = select.values[0]
        actual_channel = self.bot.get_channel(int(selected_channel.id))
        modal = GiveawayModal(self.bot, self.db, actual_channel)
        await interaction.response.send_modal(modal)


class GiveawayView(discord.ui.View):
    """View mit Teilnahme-Button"""
    
    def __init__(self, bot, db, giveaway_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.db = db
        self.giveaway_id = giveaway_id
    
    @discord.ui.button(label='🎟️ Teilnehmen', style=discord.ButtonStyle.primary, custom_id='giveaway_join')
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not self.giveaway_id:
                await interaction.response.send_message(
                    '❌ Giveaway ID nicht gefunden. Bitte kontaktiere einen Admin.',
                    ephemeral=True
                )
                return
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT is_active FROM giveaways WHERE id = ?', (self.giveaway_id,))
            result = cursor.fetchone()
            
            if not result or not result[0]:
                conn.close()
                await interaction.response.send_message(
                    '❌ Dieses Giveaway ist bereits beendet!',
                    ephemeral=True
                )
                return
            
            cursor.execute('SELECT COUNT(*) FROM past_winners WHERE user_id = ?', (str(interaction.user.id),))
            has_won = cursor.fetchone()[0] > 0
            
            if has_won:
                conn.close()
                await interaction.response.send_message(
                    '❌ Du hast bereits bei einem Giveaway gewonnen und kannst erst wieder teilnehmen, wenn ein Admin `/resetgewinner` ausführt!',
                    ephemeral=True
                )
                return
            
            cursor.execute(
                'SELECT COUNT(*) FROM giveaway_participants WHERE giveaway_id = ? AND user_id = ?',
                (self.giveaway_id, str(interaction.user.id))
            )
            already_joined = cursor.fetchone()[0] > 0
            
            if already_joined:
                conn.close()
                await interaction.response.send_message(
                    '❌ Du nimmst bereits an diesem Giveaway teil!',
                    ephemeral=True
                )
                return
            
            cursor.execute(
                'INSERT INTO giveaway_participants (giveaway_id, user_id) VALUES (?, ?)',
                (self.giveaway_id, str(interaction.user.id))
            )
            conn.commit()
            
            cursor.execute(
                'SELECT COUNT(*) FROM giveaway_participants WHERE giveaway_id = ?',
                (self.giveaway_id,)
            )
            total_participants = cursor.fetchone()[0]
            conn.close()
            
            try:
                message = interaction.message
                embed = message.embeds[0]
                
                for i, field in enumerate(embed.fields):
                    if field.name == '👥 Teilnehmer':
                        embed.set_field_at(i, name='👥 Teilnehmer', value=str(total_participants), inline=True)
                        break
                
                await message.edit(embed=embed)
            except:
                pass
            
            await interaction.response.send_message(
                f'✅ Du nimmst jetzt am Giveaway teil! (Teilnehmer: {total_participants})',
                ephemeral=True
            )
            logger.info(f'User {interaction.user} nimmt an Giveaway {self.giveaway_id} teil (Total: {total_participants})')
            
        except Exception as e:
            logger.error(f'Fehler bei Giveaway-Teilnahme: {e}')
            await interaction.response.send_message(
                f'❌ Ein Fehler ist aufgetreten: {str(e)}',
                ephemeral=True
            )


class GiveawayCommands(commands.Cog):
    """Giveaway Commands Cog"""
    
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self.restore_active_giveaways.start()
    
    def cog_unload(self):
        self.restore_active_giveaways.cancel()
    
    @tasks.loop(count=1)
    async def restore_active_giveaways(self):
        """Stelle aktive Giveaways nach Bot-Neustart wieder her"""
        await self.bot.wait_until_ready()
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, channel_id, message_id, duration_minutes, winner_count, ends_at
                FROM giveaways
                WHERE is_active = TRUE
            ''')
            active_giveaways = cursor.fetchall()
            conn.close()
            
            for giveaway_id, channel_id, message_id, duration_minutes, winner_count, ends_at_str in active_giveaways:
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if not channel:
                        continue
                    
                    message = await channel.fetch_message(int(message_id))
                    if not message:
                        continue
                    
                    ends_at = datetime.fromisoformat(ends_at_str)
                    remaining_seconds = (ends_at - datetime.now()).total_seconds()
                    
                    view = GiveawayView(self.bot, self.db, giveaway_id)
                    await message.edit(view=view)
                    
                    if remaining_seconds <= 0:
                        logger.info(f'Giveaway {giveaway_id} bereits abgelaufen, beende es jetzt')
                        asyncio.create_task(self._end_giveaway_now(giveaway_id, message, channel, winner_count))
                    else:
                        remaining_minutes = remaining_seconds / 60
                        logger.info(f'Stelle Giveaway {giveaway_id} wieder her, verbleibend: {remaining_minutes:.1f} Minuten')
                        
                        modal_instance = GiveawayModal(self.bot, self.db, channel)
                        asyncio.create_task(modal_instance._end_giveaway_after_timer(
                            giveaway_id, remaining_minutes, message, channel, winner_count
                        ))
                
                except Exception as e:
                    logger.error(f'Fehler beim Wiederherstellen von Giveaway {giveaway_id}: {e}')
            
            logger.info(f'✅ {len(active_giveaways)} aktive Giveaways wiederhergestellt')
            
        except Exception as e:
            logger.error(f'Fehler beim Wiederherstellen der Giveaways: {e}')
    
    async def _end_giveaway_now(self, giveaway_id, message, channel, winner_count):
        """Beendet ein abgelaufenes Giveaway sofort"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT user_id FROM giveaway_participants WHERE giveaway_id = ?', (giveaway_id,))
            participants = [row[0] for row in cursor.fetchall()]
            
            if len(participants) == 0:
                cursor.execute('UPDATE giveaways SET is_active = FALSE WHERE id = ?', (giveaway_id,))
                conn.commit()
                conn.close()
                
                await channel.send('😢 Das Giveaway endete ohne Teilnehmer!')
                return
            
            actual_winner_count = min(winner_count, len(participants))
            winners = random.sample(participants, actual_winner_count)
            
            for winner_id in winners:
                cursor.execute('INSERT OR IGNORE INTO past_winners (user_id, giveaway_id) VALUES (?, ?)',
                              (winner_id, giveaway_id))
            
            cursor.execute('UPDATE giveaways SET is_active = FALSE WHERE id = ?', (giveaway_id,))
            conn.commit()
            conn.close()
            
            winner_mentions = [f'<@{winner_id}>' for winner_id in winners]
            winner_text = ', '.join(winner_mentions)
            
            await channel.send(f'🎉 **GEWINNER:** {winner_text}\n\nGlückwunsch! Die Keys werden vom Admin vergeben.')
            
            try:
                embed = message.embeds[0]
                embed.color = discord.Color.green()
                embed.set_footer(text=f'Giveaway beendet - Gewinner: {len(winners)}')
                await message.edit(embed=embed, view=None)
            except:
                pass
            
            logger.info(f'Giveaway {giveaway_id} nachträglich beendet - Gewinner: {winners}')
            
        except Exception as e:
            logger.error(f'Fehler beim nachträglichen Beenden von Giveaway {giveaway_id}: {e}')
    
    @app_commands.command(name='startgiveaway', description='🎉 Startet ein neues Giveaway')
    @app_commands.default_permissions(administrator=True)
    async def start_giveaway(self, interaction: discord.Interaction):
        """Startet ein neues Giveaway mit Channel-Auswahl und Modal"""
        view = ChannelSelectView(self.bot, self.db)
        await interaction.response.send_message(
            '📢 Wähle den Channel für das Giveaway:',
            view=view,
            ephemeral=True
        )
    
    @app_commands.command(name='resetgewinner', description='🔄 Setzt alle Gewinner zurück')
    @app_commands.default_permissions(administrator=True)
    async def reset_winners(self, interaction: discord.Interaction):
        """Löscht alle gespeicherten Gewinner aus der Datenbank"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM past_winners')
            count = cursor.fetchone()[0]
            
            cursor.execute('DELETE FROM past_winners')
            conn.commit()
            conn.close()
            
            await interaction.response.send_message(
                f'✅ Alle {count} Gewinner wurden zurückgesetzt! Sie können jetzt wieder an Giveaways teilnehmen.',
                ephemeral=True
            )
            logger.info(f'{interaction.user} hat {count} Gewinner zurückgesetzt')
            
        except Exception as e:
            logger.error(f'Fehler beim Zurücksetzen der Gewinner: {e}')
            await interaction.response.send_message(
                f'❌ Fehler: {str(e)}',
                ephemeral=True
            )


async def setup(bot):
    """Setup function für Cog-Loading"""
    from database import DatabaseManager
    db = DatabaseManager()
    await bot.add_cog(GiveawayCommands(bot, db))
