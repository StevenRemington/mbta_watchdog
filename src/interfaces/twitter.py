import tweepy
import logging
from utils.config import Config
from utils.logger import get_logger

log = get_logger("Twitter")

class TwitterClient:
    def __init__(self):
        """Initializes the Twitter API v2 Client with Rate Limit handling."""
        try:
            self.client = tweepy.Client(
                bearer_token=Config.TWITTER_BEARER_TOKEN,
                consumer_key=Config.TWITTER_CONSUMER_KEY,
                consumer_secret=Config.TWITTER_CONSUMER_SECRET,
                access_token=Config.TWITTER_ACCESS_TOKEN,
                access_token_secret=Config.TWITTER_ACCESS_TOKEN_SECRET,
                wait_on_rate_limit=True  # Pauses if rate limits are hit
            )
            log.info("Twitter Client initialized successfully.")
        except Exception as e:
            log.error(f"Failed to initialize Twitter Client: {e}")
            self.client = None

    def post_alert(self, text: str):
        """Posts an alert to Twitter with error handling to prevent main loop crashes."""
        if not self.client:
            log.warning("Twitter client not initialized. Skipping post.")
            return

        try:
            # API v2 method to create a tweet
            response = self.client.create_tweet(text=text)
            log.info(f"Successfully posted to Twitter. Tweet ID: {response.data['id']}")
        except tweepy.errors.TweepyException as e:
            log.error(f"Tweepy error occurred: {e}")
        except Exception as e:
            log.error(f"Unexpected error posting to Twitter: {e}")