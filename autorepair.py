#!/usr/bin/env python3
"""
Auto-Repair Module for KARMA-LiveBOT
OpenAI-based automatic repair system for scraping failures
"""

import os
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Optional
import discord

logger = logging.getLogger('KARMA-LiveBOT.AutoRepair')

# OpenAI for automatic scraping repair
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("🤖 OpenAI library not available - Auto-Repair System disabled")

class OpenAIAutoRepair:
    """Automatisches Reparatur-System für Scraping-Fehler mit OpenAI-Unterstützung"""
    
    def __init__(self, bot, openai_api_key: Optional[str] = None, dev_channel_id: Optional[int] = None):
        self.bot = bot
        self.openai_client = None
        self.repair_attempts = {}  # Track repair attempts per platform/method
        self.max_repairs_per_hour = 5  # Limit API calls
        self.repair_cooldown = {}  # Cooldown between repairs
        self.dev_channel_id = dev_channel_id
        
        if OPENAI_AVAILABLE and openai_api_key:
            try:
                self.openai_client = OpenAI(api_key=openai_api_key)
                logger.info("🤖 OpenAI Auto-Repair System initialized successfully")
            except Exception as e:
                logger.error(f"🤖 Failed to initialize OpenAI client: {e}")
                self.openai_client = None
        else:
            logger.warning("🤖 OpenAI Auto-Repair System disabled - missing API key or library")
    
    async def send_dev_notification(self, title: str, description: str, error_details: str = "", fix_applied: str = "", color: int = 0xFF6B6B):
        """Sendet Entwickler-Benachrichtigung an DEV_CHANNEL_ID"""
        if not self.dev_channel_id:
            logger.warning("🤖 DEV_CHANNEL_ID nicht konfiguriert - Benachrichtigung übersprungen")
            return
        
        try:
            channel = self.bot.get_channel(self.dev_channel_id)
            if not channel:
                logger.error(f"🤖 DEV_CHANNEL_ID {self.dev_channel_id} nicht gefunden")
                return
            
            embed = discord.Embed(
                title=f"🤖 {title}",
                description=description,
                color=color,
                timestamp=datetime.utcnow()
            )
            
            if error_details:
                embed.add_field(
                    name="❌ Fehler-Details",
                    value=f"```\n{error_details[:1000]}\n```",
                    inline=False
                )
            
            if fix_applied:
                embed.add_field(
                    name="🔧 Angewandte Reparatur",
                    value=f"```\n{fix_applied[:1000]}\n```",
                    inline=False
                )
            
            embed.set_footer(text="KARMA-LiveBOT Auto-Repair System")
            
            await channel.send(embed=embed)
            logger.info(f"🤖 Dev-Benachrichtigung gesendet: {title}")
            
        except Exception as e:
            logger.error(f"🤖 Fehler beim Senden der Dev-Benachrichtigung: {e}")
    
    async def attempt_repair(self, platform: str, method: str, error: str, html_content: str = "", url: str = "") -> Dict:
        """Versucht automatische Reparatur mit OpenAI"""
        if not self.openai_client:
            return {"success": False, "reason": "OpenAI nicht verfügbar"}
        
        repair_key = f"{platform}_{method}"
        current_time = datetime.now()
        
        # Check cooldown (1 hour)
        if repair_key in self.repair_cooldown:
            if current_time - self.repair_cooldown[repair_key] < timedelta(hours=1):
                return {"success": False, "reason": "Cooldown aktiv (1 Stunde)"}
        
        # Check hourly limit
        if repair_key not in self.repair_attempts:
            self.repair_attempts[repair_key] = []
        
        # Remove attempts older than 1 hour
        self.repair_attempts[repair_key] = [
            timestamp for timestamp in self.repair_attempts[repair_key]
            if current_time - timestamp < timedelta(hours=1)
        ]
        
        if len(self.repair_attempts[repair_key]) >= self.max_repairs_per_hour:
            return {"success": False, "reason": f"Stündliches Limit erreicht ({self.max_repairs_per_hour})"}
        
        try:
            # Prepare context for OpenAI
            context = f"""
Du bist ein Experte für Web-Scraping und sollst helfen, kaputte Scraping-Selektoren zu reparieren.

PLATFORM: {platform}
METHOD: {method}
ERROR: {error}
URL: {url or 'N/A'}

CURRENT TASK:
- Analysiere den Fehler und den HTML-Content
- Schlage neue CSS-Selektoren oder BeautifulSoup-Pattern vor
- Gib eine JSON-Antwort mit neuen Scraping-Parametern zurück

EXPECTED JSON RESPONSE FORMAT:
{{
    "success": true,
    "selectors": ["selector1", "selector2"],
    "patterns": ["pattern1", "pattern2"],
    "explanation": "Erklärung der Änderungen",
    "confidence": 0.8
}}

HTML CONTENT (erste 2000 Zeichen):
{html_content[:2000] if html_content else 'Nicht verfügbar'}
"""
            
            # Call OpenAI
            response = self.openai_client.chat.completions.create(
                model="gpt-5",
                messages=[{"role": "user", "content": context}],
                response_format={"type": "json_object"},
                max_tokens=1000
            )
            
            repair_suggestion = json.loads(response.choices[0].message.content)
            
            # Log attempt
            self.repair_attempts[repair_key].append(current_time)
            self.repair_cooldown[repair_key] = current_time
            
            # Send notification
            await self.send_dev_notification(
                title=f"Auto-Repair Versuch - {platform.title()}",
                description=f"OpenAI-Reparatur für {method} durchgeführt",
                error_details=f"Fehler: {error}\nURL: {url}",
                fix_applied=json.dumps(repair_suggestion, indent=2),
                color=0x57F287
            )
            
            return repair_suggestion
            
        except Exception as e:
            logger.error(f"🤖 OpenAI Auto-Repair Fehler: {e}")
            await self.send_dev_notification(
                title=f"Auto-Repair Fehler - {platform.title()}",
                description=f"OpenAI-Reparatur fehlgeschlagen für {method}",
                error_details=f"OpenAI Error: {str(e)}\nOriginal Error: {error}",
                color=0xED4245
            )
            return {"success": False, "reason": f"OpenAI Fehler: {str(e)}"}
