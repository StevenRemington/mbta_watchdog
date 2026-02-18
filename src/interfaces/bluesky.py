from atproto import Client, client_utils
from datetime import datetime
from utils.config import Config
from utils.logger import get_logger

log = get_logger("Bluesky")

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
        Posts a skeet with functional facets and returns the public web URL.
        """
        if not self.is_logged_in: 
            return None
        try:
            if len(text) > 300: text = text[:297] + "..."
            
            tb = client_utils.TextBuilder()
            words = text.split(' ')
            for i, word in enumerate(words):
                if word.startswith('@') and len(word) > 1:
                    handle = word[1:].rstrip('.,!?:;')
                    try:
                        resolved = self.client.resolve_handle(handle)
                        tb.mention(word, resolved.did)
                    except:
                        tb.text(word)
                elif word.startswith('#') and len(word) > 1:
                    tag = word[1:].rstrip('.,!?:;')
                    tb.tag(word, tag)
                elif word.startswith('http'):
                    tb.link(word, word.rstrip('.,!?:;'))
                else:
                    tb.text(word)
                
                if i < len(words) - 1: 
                    tb.text(' ')
            
            # Post to Bluesky
            resp = self.client.send_post(tb)
            log.info(f"Skeet posted successfully.")
            
            # Construct and return the public URL
            rkey = resp.uri.split('/')[-1]
            return f"https://bsky.app/profile/{Config.BLUESKY_HANDLE}/post/{rkey}"
            
        except Exception as e:
            log.error(f"Skeet failed: {e}")
            return None

    def post_morning_grade(self, stats):
        """Formats and posts the morning commute grade."""
        if not stats or not self.is_logged_in: return None
        
        # Select Icon based on Grade
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

    def post_daily_summary(self, stats):
        """Formats and posts the daily highlight summary."""
        if not stats or not self.is_logged_in: return
        
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

if __name__ == "__main__":
    # Standalone Test Suite
    # Note: Do NOT import BlueskyClient here; use it directly as it is in the same file.
    print("🧪 Starting Bluesky Integration Test...")
    bsky = BlueskyClient()
    
    if bsky.is_logged_in:
        test_msg = f"🤖 Test Skeet from @{Config.BLUESKY_HANDLE}\n#MBTAWatchdog Integration Verified."
        print("Sending test post...")
        url = bsky.send_skeet(test_msg)
        if url:
            print(f"✅ Success! View here: {url}")
        else:
            print("❌ Post failed.")
    else:
        print("❌ Login failed. Verify .env credentials.")