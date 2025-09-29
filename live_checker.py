#!/usr/bin/env python3
"""
TikTok Live Checker - Doppelte Verifikation für zuverlässige Live-Stream-Erkennung
Kombiniert TikTokLive library mit HTML-Parsing für maximale Zuverlässigkeit
"""

import requests
import re
import json
import logging
from typing import Optional, Dict, Any

try:
    from TikTokLive import TikTokLiveClient
    TIKTOKLIVE_AVAILABLE = True
except ImportError:
    TIKTOKLIVE_AVAILABLE = False

logger = logging.getLogger('KARMA-LiveBOT.LiveChecker')

class TikTokLiveChecker:
    """Verbesserte TikTok Live-Status-Überprüfung mit doppelter Verifikation"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

    async def check_tiktoklive_library(self, username: str) -> bool:
        """Überprüfung mit TikTokLive library (async)"""
        try:
            if not TIKTOKLIVE_AVAILABLE:
                logger.warning(f"TikTokLive library nicht verfügbar für {username}")
                return False
                
            logger.info(f"TikTok {username}: Teste TikTokLive library...")
            client = TikTokLiveClient(unique_id=username)
            
            # Prüfe Live-Status (richtig mit await aufrufen!)
            try:
                is_live = await client.is_live()
                logger.info(f"TikTok {username}: TikTokLive async call erfolgreich: {is_live}")
            except Exception as async_error:
                logger.warning(f"TikTok {username}: Async call fehlgeschlagen: {async_error}")
                # Fallback: Versuche synchron
                is_live_method = getattr(client, "is_live", None)
                if callable(is_live_method):
                    result = is_live_method()
                    # Prüfe ob es eine coroutine ist
                    if hasattr(result, '__await__'):
                        logger.warning(f"TikTok {username}: is_live() ist async aber wurde nicht awaited")
                        return False
                    is_live = bool(result)
                else:
                    is_live = False
            
            if is_live:
                logger.info(f"TikTok {username}: TikTokLive library bestätigt - user LIVE ✅")
            else:
                logger.info(f"TikTok {username}: TikTokLive library bestätigt - user offline")
                
            return is_live
        except Exception as e:
            logger.error(f"TikTok {username}: TikTokLive library Fehler: {e}")
            return False

    def check_html_parsing(self, username: str) -> bool:
        """Überprüfung mit HTML-Parsing der TikTok-Seite"""
        try:
            url = f"https://www.tiktok.com/@{username}"
            logger.info(f"TikTok {username}: Teste HTML-Parsing von {url}...")
            
            # Mache Request zur TikTok-Seite
            response = self.session.get(url, timeout=10)
            
            if response.status_code != 200:
                logger.warning(f"TikTok {username}: HTTP Status {response.status_code}")
                return False
            
            html_content = response.text
            
            # Suche nach SIGI_STATE JSON
            match = re.search(r"window\['SIGI_STATE'\]\s*=\s*(.*?);</script>", html_content, re.DOTALL)
            if not match:
                logger.warning(f"TikTok {username}: SIGI_STATE nicht gefunden")
                return False
            
            try:
                data = json.loads(match.group(1))
                
                # Prüfe Live-Status in verschiedenen möglichen Pfaden
                live_status = 0
                
                # Pfad 1: Live -> liveStatus  
                if "Live" in data and isinstance(data["Live"], dict):
                    live_status = data["Live"].get("liveStatus", 0)
                
                # Pfad 2: LiveModule -> data -> liveStatus
                if live_status == 0 and "LiveModule" in data:
                    live_module = data["LiveModule"]
                    if isinstance(live_module, dict) and "data" in live_module:
                        live_data = live_module["data"]
                        if isinstance(live_data, dict):
                            live_status = live_data.get("liveStatus", 0)
                
                # Pfad 3: Suche in UserModule nach Live-Informationen
                if live_status == 0 and "UserModule" in data:
                    user_module = data["UserModule"]
                    if isinstance(user_module, dict) and "users" in user_module:
                        users = user_module["users"]
                        if isinstance(users, dict):
                            for user_id, user_data in users.items():
                                if isinstance(user_data, dict) and user_data.get("uniqueId") == username:
                                    # Prüfe auf Live-Indikatoren
                                    if user_data.get("roomId"):  # Hat aktuelle Live-Room
                                        live_status = 1
                                    if user_data.get("liveStatus"):
                                        live_status = user_data.get("liveStatus", 0)
                
                is_live = live_status == 1
                
                if is_live:
                    logger.info(f"TikTok {username}: HTML-Parsing bestätigt - user LIVE ✅ (liveStatus: {live_status})")
                else:
                    logger.info(f"TikTok {username}: HTML-Parsing bestätigt - user offline (liveStatus: {live_status})")
                
                return is_live
                
            except json.JSONDecodeError as e:
                logger.error(f"TikTok {username}: JSON-Parsing Fehler: {e}")
                return False
                
        except Exception as e:
            logger.error(f"TikTok {username}: HTML-Parsing Fehler: {e}")
            return False

    async def is_user_live(self, username: str) -> Dict[str, Any]:
        """
        Hauptfunktion: Intelligente Live-Verifikation
        TikTokLive library hat Priorität, HTML-Parsing als Zusatzbestätigung
        
        Returns:
            Dict mit Live-Status und Zusatzinfos
        """
        logger.info(f"TikTok {username}: Starte intelligente Live-Verifikation...")
        
        # Methode 1: TikTokLive library (PRIORITÄT)
        library_result = await self.check_tiktoklive_library(username)
        logger.info(f"TikTok {username}: TikTokLive library Ergebnis: {library_result}")
        
        # Methode 2: HTML-Parsing (Zusatzbestätigung)
        html_result = self.check_html_parsing(username)
        logger.info(f"TikTok {username}: HTML-Parsing Ergebnis: {html_result}")
        
        # NEUE INTELLIGENTE LOGIK:
        # 1. Wenn TikTokLive library LIVE sagt → User ist live (sehr zuverlässig)
        # 2. Wenn beide OFFLINE sagen → User ist offline
        # 3. Nur bei unklaren Fällen skeptisch sein
        
        is_live = False
        verification_method = ""
        
        if library_result:
            # TikTokLive library ist sehr zuverlässig für LIVE-Erkennung
            is_live = True
            verification_method = "library_priority"
            logger.info(f"TikTok {username}: ✅ LIVE bestätigt via TikTokLive library (zuverlässig)!")
        elif html_result:
            # HTML kann manchmal false-positives haben, also vorsichtiger
            is_live = True  
            verification_method = "html_only"
            logger.warning(f"TikTok {username}: ⚠️ LIVE via HTML-Parsing (TikTokLive library sagt offline)")
        else:
            # Beide sagen offline
            is_live = False
            verification_method = "both_offline"
            logger.info(f"TikTok {username}: ❌ Beide Methoden bestätigen - User offline")
        
        # Rückgabe im Format, das der Bot erwartet
        if is_live:
            return {
                'is_live': True,
                'viewer_count': 0,
                'game_name': 'TikTok Live',
                'title': f'{username} Live Stream',
                'thumbnail_url': '',
                'profile_image_url': '',
                'platform_url': f'https://www.tiktok.com/@{username}/live',
                'follower_count': 0,
                'method': verification_method,
                'library_confirmed': library_result,
                'html_confirmed': html_result
            }
        else:
            return {
                'is_live': False,
                'method': verification_method,
                'library_confirmed': library_result,
                'html_confirmed': html_result
            }

# Globale Instanz für den Bot
improved_tiktok_checker = TikTokLiveChecker()

# Kompatibilitätsfunktionen für einfache Integration (async)
import asyncio

async def check_tiktoklive(username: str) -> bool:
    """Einfache TikTokLive library Überprüfung"""
    return await improved_tiktok_checker.check_tiktoklive_library(username)

def check_html(username: str) -> bool:
    """Einfache HTML-Parsing Überprüfung"""
    return improved_tiktok_checker.check_html_parsing(username)

async def is_user_live(username: str) -> bool:
    """Einfache intelligente Verifikation (nur True/False)"""
    result = await improved_tiktok_checker.is_user_live(username)
    return result.get('is_live', False)

async def get_live_info(username: str) -> Dict[str, Any]:
    """Vollständige Live-Informationen mit intelligenter Verifikation"""
    return await improved_tiktok_checker.is_user_live(username)