import sys
import os
from pathlib import Path

# This resolves to: .../mbta-watchdog/src
SRC_PATH = str(Path(__file__).resolve().parent.parent)
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from atproto import Client, client_utils
from datetime import datetime
import re
from utils.config import Config
from utils.logger import get_logger

log = get_logger("Bluesky")

# Static Identity Cache (Recommended for Backend Services)
# Pre-resolving critical handles ensures 100% reliability even if the PDS is slow.
KNOWN_DIDS = {
    "mbta.com": "did:plc:czvissxm5nhe6m6aydsdxe26"
}

class BlueskyClient:
    def __init__(self):
        """
        Handles Bluesky (AT Protocol) integration.
        """
        self.client = Client()
        self.is_logged_in = False
        self._login()

    def _login(self):
        if not Config.BLUESKY_HANDLE or not Config.BLUESKY_PASSWORD:
            log.warning("Bluesky credentials missing. Skipping login.")
            return
        try:
            self.client.login(Config.BLUESKY_HANDLE, Config.BLUESKY_PASSWORD)
            self.is_logged_in = True
            log.info(f"Logged into Bluesky as {Config.BLUESKY_HANDLE}")
        except Exception as e:
            log.error(f"Failed to login to Bluesky: {e}")

    def send_skeet(self, text):
        """
        Posts a skeet with functional facets (mentions/links/tags) and returns the URL.
        """
        if not self.is_logged_in: 
            return None
        try:
            # Truncate to limit
            if len(text) > 300: text = text[:297] + "..."
            
            tb = client_utils.TextBuilder()
            
            # Split by any whitespace but keep the whitespace tokens
            tokens = re.split(r'(\s+)', text)
            
            for token in tokens:
                # If the token is just whitespace (like \n or space), add it and move on
                if not token.strip():
                    tb.text(token)
                    continue
                    
                # --- HANDLE MENTIONS (@mbta.com) ---
                if token.startswith('@') and len(token) > 1:
                    # Regex: Remove leading @ and any trailing punctuation (.,!?:)
                    # Example: "@mbta.com." -> "mbta.com"
                    clean_handle = re.sub(r'^@|[^a-zA-Z0-9.-]', '', token).lower()
                    
                    try:
                        did = None
                        # 1. Check Static Cache (Fastest & Most Reliable)
                        if clean_handle in KNOWN_DIDS:
                            did = KNOWN_DIDS[clean_handle]
                        
                        # 2. Use Standard API (com.atproto.identity.resolveHandle)
                        if not did:
                            resolved = self.client.resolve_handle(clean_handle)
                            did = resolved.did
                        
                        # 3. Add Mention Facet
                        tb.mention(token, did)

                    except Exception as e:
                        # 4. Fallback: If API fails, check if it's a domain and Link it
                        # This handles cases where a handle is valid as a website but not a Bsky user.
                        if '.' in clean_handle:
                             tb.link(token, f"https://{clean_handle}")
                        else:
                             tb.text(token)

                # --- HASHTAGS (#MBTA) ---
                elif token.startswith('#') and len(token) > 1:
                    tag = re.sub(r'^#|[^a-zA-Z0-9]', '', token)
                    tb.tag(token, tag)
                
                # --- URLS (http...) ---
                elif token.startswith('http'):
                    clean_url = token.rstrip('.,!?:;')
                    tb.link(token, clean_url)
                
                # --- PLAIN TEXT ---
                else:
                    tb.text(token)
            
            # Post to Bluesky
            resp = self.client.send_post(tb)
            log.info(f"Skeet posted successfully.")
            
            # Return Public URL
            rkey = resp.uri.split('/')[-1]
            return f"https://bsky.app/profile/{Config.BLUESKY_HANDLE}/post/{rkey}"
            
        except Exception as e:
            log.error(f"Skeet failed: {e}")
            return None

    def post_daily_summary(self, stats):
        """Formats and posts the daily highlight summary."""
        if not stats or not self.is_logged_in: return None
        
        try:
            date_str = datetime.strptime(stats['date'], '%Y-%m-%d').strftime('%b %d')
        except:
            date_str = datetime.now().strftime('%b %d')
        
        text = (
            f"📊 MBTA #WorcesterLine Daily Highlights ({date_str})\n\n"
            f"🚆 Affected: {stats['percent_affected']:.1f}% "
            f"({stats['affected_count']}/{stats['total']} trains delayed or canceled)\n"
            f"🐌 Biggest Delay: Train {stats['max_train']} (+{stats['max_delay']} min)\n\n"
            f"@mbta.com #WorcesterLineDaily #MBTAWatchdog"
        )
        return self.send_skeet(text)

    def post_morning_grade(self, stats):
        """Formats and posts the morning commute grade."""
        if not stats or not self.is_logged_in: return None
        
        grade_map = {"A": "🟢", "B": "🟢", "C": "🟡", "D": "🔴", "F": "💀"}
        icon = grade_map.get(stats['grade'], "⚪")

        text = (
            f"🌅 Morning Commute Report ({stats['date']})\n\n"
            f"{icon} Grade: {stats['grade']}\n"
            f"🚆 {stats['total']} Trains Ran\n"
            f"✅ {stats['total'] - stats['late'] - stats['canceled']} On Time\n"
            f"⚠️ {stats['late']} Late\n"
            f"🚫 {stats['canceled']} Canceled\n\n"
            f"🐌 Worst Offender: Train {stats['worst_train']} (+{stats['worst_delay']}m)\n"
            f"@mbta.com #WorcesterLine #MBTA"
        )
        return self.send_skeet(text)

if __name__ == "__main__":
    print("🧪 Starting Bluesky Integration Test...")
    bsky = BlueskyClient()
    
    if bsky.is_logged_in:
        # Test the MBTA handle specifically
        test_msg = f"🤖 Test Link Logic: @mbta.com should be blue. #MBTAWatchdog"
        print("Sending test post...")
        url = bsky.send_skeet(test_msg)
        if url:
            print(f"✅ Success! View here: {url}")
        else:
            print("❌ Post failed.")
    else:
        print("❌ Login failed. Verify .env credentials.")