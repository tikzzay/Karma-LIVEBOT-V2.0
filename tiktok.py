#!/usr/bin/env python3
"""
TikTok Platform Module for KARMA-LiveBOT
Handles all TikTok live stream checking with dual verification
"""

import asyncio
import logging
import requests
import re
import json
import time
from datetime import datetime
from typing import Optional, Dict, Any

# Import the existing improved TikTok checker
try:
    from TikTokLive import TikTokLiveClient
    TIKTOKLIVE_AVAILABLE = True
except ImportError:
    TIKTOKLIVE_AVAILABLE = False

logger = logging.getLogger('KARMA-LiveBOT.TikTok')

class TikTokLiveChecker:
    """Verbesserte TikTok Live-Status-Überprüfung mit doppelter Verifikation"""
    
    def __init__(self):
        # Client-Cache für Wiederverwendung (Performance-Optimierung)
        self.tiktok_clients = {}  # username -> TikTokLiveClient
        self.client_creation_time = {}  # username -> creation timestamp
        self.client_max_age = 3600  # Clients nach 1 Stunde erneuern

    def _get_or_create_client(self, username: str):
        """Holt wiederverwendbaren Client oder erstellt neuen (Performance-Optimierung)"""
        current_time = time.time()
        
        # Prüfe ob Client existiert und noch gültig ist
        if username in self.tiktok_clients:
            client_age = current_time - self.client_creation_time.get(username, 0)
            if client_age < self.client_max_age:
                # Client ist noch gültig, wiederverwenden
                return self.tiktok_clients[username]
            else:
                # Client zu alt, entfernen
                del self.tiktok_clients[username]
                del self.client_creation_time[username]
        
        # Neuen Client erstellen und cachen
        client = TikTokLiveClient(unique_id=username)
        self.tiktok_clients[username] = client
        self.client_creation_time[username] = current_time
        logger.debug(f"TikTok {username}: Neuer Client erstellt (Cache: {len(self.tiktok_clients)} Clients)")
        return client
    
    async def check_tiktoklive_library(self, username: str) -> bool:
        """Überprüfung mit TikTokLive library (async)"""
        try:
            if not TIKTOKLIVE_AVAILABLE:
                logger.warning(f"TikTokLive library nicht verfügbar für {username}")
                return False
                
            logger.info(f"TikTok {username}: Teste TikTokLive library...")
            # Wiederverwendbaren Client holen statt neuen zu erstellen
            client = self._get_or_create_client(username)
            
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

    def _sync_html_parsing(self, username: str) -> Dict[str, Any]:
        """Synchrone HTML-Parsing Hilfsfunktion (wird in Thread ausgeführt)"""
        try:
            url = f"https://www.tiktok.com/@{username}"
            
            # Erstelle neue Session pro Call für Thread-Sicherheit
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            })
            
            # Mache Request zur TikTok-Seite
            response = session.get(url, timeout=10)
            
            if response.status_code != 200:
                logger.warning(f"TikTok {username}: HTTP Status {response.status_code}")
                return {"is_live": False, "thumbnail_url": "", "profile_image_url": "", "follower_count": 0, "viewer_count": 0, "title": f"{username} Live Stream"}
            
            html_content = response.text
            
            # Suche nach SIGI_STATE JSON
            match = re.search(r"window\['SIGI_STATE'\]\s*=\s*(.*?);</script>", html_content, re.DOTALL)
            if not match:
                logger.warning(f"TikTok {username}: SIGI_STATE nicht gefunden")
                return {"is_live": False, "thumbnail_url": "", "profile_image_url": "", "follower_count": 0, "viewer_count": 0, "title": f"{username} Live Stream"}
            
            try:
                data = json.loads(match.group(1))
                
                # Initialisiere Variablen
                live_status = 0
                thumbnail_url = ""
                profile_image_url = ""
                follower_count = 0
                
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
                
                # Extrahiere Profilbild und Follower-Anzahl aus UserModule
                if "UserModule" in data:
                    user_module = data["UserModule"]
                    if isinstance(user_module, dict) and "users" in user_module:
                        users = user_module["users"]
                        if isinstance(users, dict):
                            for user_id, user_data in users.items():
                                if isinstance(user_data, dict) and user_data.get("uniqueId") == username:
                                    # Profilbild extrahieren
                                    if "avatarLarger" in user_data:
                                        profile_image_url = user_data["avatarLarger"]
                                    elif "avatarMedium" in user_data:
                                        profile_image_url = user_data["avatarMedium"]
                                    elif "avatarThumb" in user_data:
                                        profile_image_url = user_data["avatarThumb"]
                                    
                                    # Follower-Anzahl extrahieren
                                    follower_count = user_data.get("followerCount", 0)
                                    break
                
                # Extrahiere Thumbnail, Zuschauerzahl und Titel aus LiveRoom-Daten
                viewer_count = 0
                title = f"{username} Live Stream"  # Fallback-Titel
                if "LiveRoom" in data and isinstance(data["LiveRoom"], dict):
                    live_room = data["LiveRoom"]
                    if "liveRoomInfo" in live_room and isinstance(live_room["liveRoomInfo"], dict):
                        live_room_info = live_room["liveRoomInfo"]
                        # Versuche verschiedene Thumbnail-Felder
                        if "cover" in live_room_info and isinstance(live_room_info["cover"], dict):
                            cover = live_room_info["cover"]
                            for size in ["url_list", "urlList"]:
                                if size in cover and isinstance(cover[size], list) and len(cover[size]) > 0:
                                    thumbnail_url = cover[size][0]
                                    break
                        # Versuche Zuschauerzahl zu extrahieren
                        viewer_count = live_room_info.get("userCount", 0)
                        if viewer_count == 0:
                            viewer_count = live_room_info.get("liveRoomUserInfo", {}).get("userCount", 0)
                        
                        # Versuche Titel zu extrahieren
                        title = live_room_info.get("title", title)
                        if "titleStruct" in live_room_info and isinstance(live_room_info["titleStruct"], dict):
                            title = live_room_info["titleStruct"].get("default", title)
                
                is_live = live_status == 1
                
                if is_live:
                    logger.info(f"TikTok {username}: HTML-Parsing bestätigt - user LIVE ✅ (liveStatus: {live_status})")
                    logger.info(f"TikTok {username}: Profilbild: {profile_image_url[:50] if profile_image_url else 'Keine'}")
                    logger.info(f"TikTok {username}: Thumbnail: {thumbnail_url[:50] if thumbnail_url else 'Keine'}")
                    logger.info(f"TikTok {username}: Follower: {follower_count}")
                    logger.info(f"TikTok {username}: Zuschauer: {viewer_count}")
                    logger.info(f"TikTok {username}: Titel: {title}")
                else:
                    logger.info(f"TikTok {username}: HTML-Parsing bestätigt - user offline (liveStatus: {live_status})")
                
                return {
                    "is_live": is_live,
                    "thumbnail_url": thumbnail_url,
                    "profile_image_url": profile_image_url,
                    "follower_count": follower_count,
                    "viewer_count": viewer_count,
                    "title": title
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"TikTok {username}: JSON-Parsing Fehler: {e}")
                return {"is_live": False, "thumbnail_url": "", "profile_image_url": "", "follower_count": 0, "viewer_count": 0, "title": f"{username} Live Stream"}
                
        except Exception as e:
            logger.error(f"TikTok {username}: HTML-Parsing Fehler: {e}")
            return {"is_live": False, "thumbnail_url": "", "profile_image_url": "", "follower_count": 0, "viewer_count": 0, "title": f"{username} Live Stream"}
    
    async def check_html_parsing(self, username: str) -> Dict[str, Any]:
        """Asynchrone Überprüfung mit HTML-Parsing (Event-Loop-sicher)"""
        logger.info(f"TikTok {username}: Teste HTML-Parsing von https://www.tiktok.com/@{username}...")
        try:
            # Führe synchrones HTML-Parsing in separatem Thread aus (verhindert Event-Loop Blocking)
            result = await asyncio.to_thread(self._sync_html_parsing, username)
            return result
        except Exception as e:
            logger.error(f"TikTok {username}: Async HTML-Parsing Fehler: {e}")
            return {"is_live": False, "thumbnail_url": "", "profile_image_url": "", "follower_count": 0, "viewer_count": 0, "title": f"{username} Live Stream"}

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
        
        # Methode 2: HTML-Parsing (Zusatzbestätigung + Bild-Extraktion)
        html_data = await self.check_html_parsing(username)
        html_result = html_data.get("is_live", False)
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
        
        # Fallback-URLs für TikTok Profile und Thumbnails
        profile_fallback = f"https://p16-sign-sg.tiktokcdn.com/aweme/100x100/{username}.jpeg"
        thumbnail_fallback = f"https://www.tiktok.com/@{username}/live"
        
        # Extrahiere Daten aus HTML-Parsing oder verwende Fallbacks
        thumbnail_url = html_data.get("thumbnail_url", "") or thumbnail_fallback
        profile_image_url = html_data.get("profile_image_url", "") or profile_fallback
        follower_count = html_data.get("follower_count", 0)
        viewer_count = html_data.get("viewer_count", 0)
        title = html_data.get("title", f"{username} Live Stream")
        
        # Rückgabe im Format, das der Bot erwartet
        if is_live:
            return {
                'is_live': True,
                'viewer_count': viewer_count,
                'game_name': 'TikTok Live',
                'title': title,
                'thumbnail_url': thumbnail_url,
                'profile_image_url': profile_image_url,
                'platform_url': f'https://www.tiktok.com/@{username}/live',
                'follower_count': follower_count,
                'method': verification_method,
                'library_confirmed': library_result,
                'html_confirmed': html_result
            }
        else:
            return {
                'is_live': False,
                'method': verification_method,
                'library_confirmed': library_result,
                'html_confirmed': html_result,
                'thumbnail_url': thumbnail_url,
                'profile_image_url': profile_image_url,
                'follower_count': follower_count,
                'viewer_count': viewer_count
            }

# Globale Instanz für den Bot
improved_tiktok_checker = TikTokLiveChecker()

# Kompatibilitätsfunktionen für einfache Integration (async)

async def check_tiktoklive(username: str) -> bool:
    """Einfache TikTokLive library Überprüfung"""
    return await improved_tiktok_checker.check_tiktoklive_library(username)

async def check_html(username: str) -> bool:
    """Einfache HTML-Parsing Überprüfung (async)"""
    result = await improved_tiktok_checker.check_html_parsing(username)
    return result.get("is_live", False)

async def is_user_live(username: str) -> bool:
    """Einfache intelligente Verifikation (nur True/False)"""
    result = await improved_tiktok_checker.is_user_live(username)
    return result.get('is_live', False)

async def get_live_info(username: str) -> Dict[str, Any]:
    """Vollständige Live-Informationen mit intelligenter Verifikation"""
    return await improved_tiktok_checker.is_user_live(username)

# Task function for TikTok platform checking
async def tiktok_platform_task(db, bot, creators):
    """Background task for checking TikTok streams"""
    logger.info("🎵 Starting TikTok platform task")
    
    while True:
        try:
            tiktok_creators = [c for c in creators if c[7]]  # Has tiktok_username
            
            if not tiktok_creators:
                await asyncio.sleep(60)  # Wait 1 minute if no TikTok creators
                continue
            
            logger.info(f"🎵 Checking {len(tiktok_creators)} TikTok creators")
            
            for creator in tiktok_creators:
                creator_id, discord_user_id, username, streamer_type, channel_id, twitch_user, youtube_user, tiktok_user = creator
                
                try:
                    # Check if user is live
                    stream_info = await improved_tiktok_checker.is_user_live(tiktok_user)
                    
                    if stream_info and stream_info.get('is_live'):
                        logger.info(f"🎵 {tiktok_user} is LIVE on TikTok!")
                        # Here you would call handle_stream_status or similar notification logic
                        # This will be handled by the main bot coordination
                    else:
                        logger.debug(f"🎵 {tiktok_user} is offline on TikTok")
                    
                except Exception as e:
                    logger.error(f"🎵 Error checking TikTok user {tiktok_user}: {e}")
                
                # Small delay between checks to avoid rate limits
                await asyncio.sleep(1)
            
            # Wait based on streamer type intervals
            # For now, use 3 minutes as a reasonable default
            await asyncio.sleep(180)
            
        except Exception as e:
            logger.error(f"🎵 Error in TikTok platform task: {e}")
            await asyncio.sleep(30)  # Wait before retrying on error