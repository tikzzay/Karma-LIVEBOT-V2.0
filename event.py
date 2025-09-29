#!/usr/bin/env python3
"""
Event Module for KARMA-LiveBOT
Handles daily streak events, points calculation, and event management
"""

import logging
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger('KARMA-LiveBOT.Event')

class EventManager:
    """Manager for daily streak events and point calculations"""
    
    def __init__(self, db):
        self.db = db
    
    def is_event_active(self) -> bool:
        """Check if an event is currently active"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT is_active FROM event_status WHERE id = 1')
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else False
        except Exception as e:
            logger.error(f"Error checking event status: {e}")
            return False
    
    def start_event(self) -> bool:
        """Start a new event"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE event_status 
                SET is_active = TRUE, started_at = CURRENT_TIMESTAMP, ended_at = NULL 
                WHERE id = 1
            ''')
            conn.commit()
            conn.close()
            logger.info("🎉 Event started successfully")
            return True
        except Exception as e:
            logger.error(f"Error starting event: {e}")
            return False
    
    def stop_event(self) -> bool:
        """Stop the current event"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE event_status 
                SET is_active = FALSE, ended_at = CURRENT_TIMESTAMP 
                WHERE id = 1
            ''')
            conn.commit()
            conn.close()
            logger.info("🏁 Event stopped successfully")
            return True
        except Exception as e:
            logger.error(f"Error stopping event: {e}")
            return False
    
    def reset_event_data(self) -> bool:
        """Reset all event streaks and points"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE event_streaks SET current_event_streak = 0, event_points = 0')
            conn.commit()
            conn.close()
            logger.info("🔄 Event data reset successfully")
            return True
        except Exception as e:
            logger.error(f"Error resetting event data: {e}")
            return False
    
    def calculate_event_points(self, stream_duration_minutes: int, streak: int) -> int:
        """
        Calculate event points based on stream duration and streak multiplier
        
        Args:
            stream_duration_minutes: Duration of stream in minutes
            streak: Current event streak count
        
        Returns:
            Calculated points
        """
        base_points = stream_duration_minutes * 10  # 10 points per minute
        streak_multiplier = 1.0 + (streak * 0.1)  # 10% bonus per streak day
        total_points = int(base_points * streak_multiplier)
        
        logger.debug(f"Event points calculated: {total_points} (base: {base_points}, streak: {streak}, multiplier: {streak_multiplier:.2f})")
        return total_points
    
    def update_event_streak(self, creator_id: int) -> Tuple[int, int]:
        """
        Update event streak for a creator
        
        Returns:
            Tuple of (new_streak, total_points)
        """
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Get current event streak data
            cursor.execute('''
                SELECT current_event_streak, event_points, last_event_stream_date 
                FROM event_streaks 
                WHERE creator_id = ?
            ''', (creator_id,))
            
            result = cursor.fetchone()
            today = date.today()
            
            if result:
                current_streak, total_points, last_date_str = result
                last_date = datetime.strptime(last_date_str, '%Y-%m-%d').date() if last_date_str else None
                
                # Check if already streamed today
                if last_date == today:
                    logger.debug(f"Creator {creator_id} already streamed today for event")
                    conn.close()
                    return (current_streak, total_points)
                
                # Calculate new streak
                if last_date and (today - last_date).days == 1:
                    # Consecutive day - increment streak
                    new_streak = current_streak + 1
                else:
                    # Streak broken or first stream - reset to 1
                    new_streak = 1
                
                # Update event streak
                cursor.execute('''
                    UPDATE event_streaks 
                    SET current_event_streak = ?, last_event_stream_date = ? 
                    WHERE creator_id = ?
                ''', (new_streak, today.isoformat(), creator_id))
            else:
                # Create new event streak entry
                new_streak = 1
                total_points = 0
                cursor.execute('''
                    INSERT INTO event_streaks (creator_id, current_event_streak, event_points, last_event_stream_date)
                    VALUES (?, ?, ?, ?)
                ''', (creator_id, new_streak, total_points, today.isoformat()))
            
            conn.commit()
            conn.close()
            
            logger.info(f"✅ Event streak updated for creator {creator_id}: {new_streak} days")
            return (new_streak, total_points)
            
        except Exception as e:
            logger.error(f"Error updating event streak for creator {creator_id}: {e}")
            return (0, 0)
    
    def add_event_points(self, creator_id: int, points: int) -> int:
        """
        Add points to a creator's event total
        
        Returns:
            New total points
        """
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE event_streaks 
                SET event_points = event_points + ? 
                WHERE creator_id = ?
            ''', (points, creator_id))
            
            cursor.execute('SELECT event_points FROM event_streaks WHERE creator_id = ?', (creator_id,))
            result = cursor.fetchone()
            new_total = result[0] if result else 0
            
            conn.commit()
            conn.close()
            
            logger.info(f"✅ Added {points} event points to creator {creator_id}, new total: {new_total}")
            return new_total
            
        except Exception as e:
            logger.error(f"Error adding event points for creator {creator_id}: {e}")
            return 0
    
    def get_event_rankings(self) -> List[Tuple]:
        """Get event rankings sorted by points"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT c.discord_username, c.streamer_type, es.event_points, es.current_event_streak,
                       c.twitch_username, c.youtube_username, c.tiktok_username
                FROM creators c
                JOIN event_streaks es ON c.id = es.creator_id
                WHERE es.event_points > 0
                ORDER BY es.event_points DESC
            ''')
            
            rankings = cursor.fetchall()
            conn.close()
            
            logger.info(f"Retrieved {len(rankings)} event rankings")
            return rankings
            
        except Exception as e:
            logger.error(f"Error getting event rankings: {e}")
            return []
