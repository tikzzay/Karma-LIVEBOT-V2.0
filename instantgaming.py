#!/usr/bin/env python3
"""
Instant Gaming Module for KARMA-LiveBOT
Handles Instant Gaming affiliate link generation and game search
"""

import logging
import time
import difflib
from typing import Optional, Dict
import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger('KARMA-LiveBOT.InstantGaming')

class InstantGamingAPI:
    """Integration for Instant Gaming game searches and affiliate links"""
    
    def __init__(self, db=None):
        self.db = db
        self.search_base_url = "https://www.instant-gaming.com/en/search/"
        self.cache = {}  # Cache search results to avoid repeated requests
        self.cache_duration = 1800  # 30 minutes cache
    
    def get_affiliate_tag(self) -> str:
        """Get the current affiliate tag from database"""
        if not self.db:
            return "tikzzay"  # Fallback to default
        
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT affiliate_tag FROM instant_gaming_config WHERE id = 1')
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else "tikzzay"
        except Exception as e:
            logger.error(f"Error reading affiliate tag from database: {e}")
            return "tikzzay"
    
    def clear_cache(self):
        """Clear the search cache to force fresh requests"""
        self.cache.clear()
        logger.info("Instant Gaming cache cleared")
    
    def normalize_game_name(self, game: str) -> str:
        """Normalize game name for better matching on Instant Gaming"""
        game = game.lower()
        
        # Handle special cases for better matching
        special_cases = {
            "call of duty": "call of duty black ops 6",
            "cod": "call of duty black ops 6",
            "warzone": "call of duty warzone",
            "fortnite": "fortnite",
            "minecraft": "minecraft java edition",
            "gta": "grand theft auto v",
            "gta 5": "grand theft auto v",
            "gta v": "grand theft auto v"
        }
        
        # Check for special cases first
        for key, replacement in special_cases.items():
            if game.strip() == key:
                game = replacement
                break
        
        # Remove edition keywords that can interfere with search
        for bad in ["edition", "deluxe", "ultimate", "season", "beta", "early access", "definitive", "complete", "goty", "remastered"]:
            game = game.replace(bad, "")
        
        # Clean up punctuation and extra spaces
        game = game.replace(":", "").replace("-", " ").replace("_", " ")
        return " ".join(game.split())
    
    async def search_game(self, game_name: str) -> Optional[Dict]:
        """Search for a game on Instant Gaming with smart matching and return direct product link"""
        if not game_name or not game_name.strip():
            return None
        
        # Normalize game name for better search results
        normalized_game = self.normalize_game_name(game_name)
        cache_key = f"instant_gaming_{normalized_game}"
        current_time = time.time()
        
        # Check cache first
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if current_time - cached_data['timestamp'] < self.cache_duration:
                logger.info(f"Using cached Instant Gaming data for {game_name}")
                return cached_data['data']
        
        try:
            # Use German URL with normalized game name
            search_url = f"https://www.instant-gaming.com/de/suche/?q={normalized_game.replace(' ', '+')}"
            
            logger.info(f"Searching Instant Gaming for: {game_name} (normalized: {normalized_game})")
            logger.info(f"Using URL: {search_url}")
            
            # Headers to appear like a real browser
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            }
            
            timeout = aiohttp.ClientTimeout(total=15)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, headers=headers, timeout=timeout) as response:
                    if response.status == 200:
                        html = await response.text()
                        
                        # Parse HTML with BeautifulSoup
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Find all products with their titles and links
                        products = []
                        
                        # Try multiple selectors to find product links
                        link_elements = soup.find_all("a", class_="cover") or soup.select('a[href*="/de/"]')
                        
                        for element in link_elements:
                            href = element.get('href', '')
                            if href and '/de/' in href:
                                # Get product title from img alt or nearby text
                                title = ""
                                img = element.find('img')
                                if img and img.get('alt'):
                                    title = img.get('alt').strip()
                                
                                if title and href:
                                    # Convert relative URLs to absolute
                                    if href.startswith('/'):
                                        href = f"https://www.instant-gaming.com{href}"
                                    products.append({'title': title, 'url': href})
                        
                        logger.info(f"Found {len(products)} products for {normalized_game}")
                        
                        if products:
                            # Use difflib to find the best match
                            product_titles = [p['title'] for p in products]
                            
                            # Try to find close matches
                            best_matches = difflib.get_close_matches(game_name, product_titles, n=1, cutoff=0.4)
                            if not best_matches:
                                # If no close match with original name, try with normalized name
                                best_matches = difflib.get_close_matches(normalized_game, product_titles, n=1, cutoff=0.3)
                            
                            if best_matches:
                                # Find the product with the best matching title
                                best_title = best_matches[0]
                                best_product = next(p for p in products if p['title'] == best_title)
                                product_url = best_product['url']
                                
                                # Add affiliate tag to direct product link
                                separator = '&' if '?' in product_url else '?'
                                affiliate_url = f"{product_url}{separator}igr={self.get_affiliate_tag()}"
                                
                                result = {
                                    'found': True,
                                    'game_name': best_title,
                                    'product_url': product_url,
                                    'affiliate_url': affiliate_url,
                                    'search_url': search_url,
                                    'match_confidence': difflib.SequenceMatcher(None, game_name.lower(), best_title.lower()).ratio()
                                }
                                
                                # Cache the result
                                self.cache[cache_key] = {
                                    'data': result,
                                    'timestamp': current_time
                                }
                                
                                logger.info(f"✅ Found matching product for '{game_name}': {best_title} (confidence: {result['match_confidence']:.2f})")
                                return result
                            else:
                                logger.info(f"❌ No good matches found for '{game_name}' on Instant Gaming")
                        else:
                            logger.info(f"❌ No products found for '{game_name}' on Instant Gaming")
                        
                        # Cache negative result
                        self.cache[cache_key] = {
                            'data': None,
                            'timestamp': current_time
                        }
                        return None
                    else:
                        logger.warning(f"Instant Gaming search failed with status {response.status} for {game_name}")
                        return None
        
        except Exception as e:
            logger.error(f"Error searching Instant Gaming for {game_name}: {e}")
            return None
