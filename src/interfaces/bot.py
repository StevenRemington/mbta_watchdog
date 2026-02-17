import discord
import os
import subprocess
import pandas as pd
from datetime import datetime
from typing import Optional, List, Dict, Any

from database.database import DatabaseManager
from utils.config import Config
from utils.logger import get_logger

log = get_logger("Bot")

class WatchdogBot(discord.Client):
    """
    Discord Bot interface for the MBTA Watchdog system.
    Uses a Command Dispatcher pattern to route messages to specific handlers.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None, *args, **kwargs):
        """
        Initialize the bot with dependency injection.
        
        :param db_manager: An instance of DatabaseManager. If None, a new one is created.
        """
        super().__init__(*args, **kwargs)
        self.db = db_manager or DatabaseManager()
        
        # Command Registry: Maps trigger words to handler methods
        self.command_map = {
            '!help': self.cmd_help,
            '!list': self.cmd_list,
            '!status': self.cmd_status,
            '!email': self.cmd_status,  # Alias for status
            '!copy': self.cmd_copy,
            '!launch': self.cmd_launch,
            '!health': self.cmd_health  # New command for DB verification
        }

    async def on_ready(self):
        """Triggered when the bot successfully connects to Discord."""
        log.info(f'Logged in as {self.user} (ID: {self.user.id})')
        log.info(f'Ready to serve {len(self.guilds)} guilds.')

    async def on_message(self, message: discord.Message):
        """Core event listener. Filters messages and dispatches commands."""
        # 1. Validation: Ignore self and empty messages
        if message.author == self.user or not message.content:
            return

        # 2. Parsing: Normalize content
        content = message.content.strip()
        if not content.startswith('!'):
            return
        
        # Split command and arguments (e.g., "!status 508" -> cmd="!status", args="508")
        parts = content.split(' ', 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else None

        # 3. Dispatch: Route to handler
        handler = self.command_map.get(command)
        if handler:
            log.info(f"Command received: {command} from {message.author}")
            try:
                await handler(message, args)
            except Exception as e:
                log.error(f"Error executing {command}: {e}", exc_info=True)
                await message.channel.send("⚠️ An internal error occurred while processing your command.")

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    async def cmd_help(self, message: discord.Message, args: Optional[str]):
        """Displays the help menu."""
        help_text = (
            "**🚆 MBTA Watchdog Help**\n"
            "```\n"
            "!list          : Live board of active trains & locations\n"
            "!status        : View current complaint email draft\n"
            "!status <num>  : View stats for specific train (e.g. !status 508)\n"
            "!health        : Check database connection and recent updates\n"
            "!copy          : Get mobile-friendly link & text for complaints\n"
            "!launch        : Auto-fill the MBTA form (Desktop Only)\n"
            "```"
        )
        await message.channel.send(help_text)

    async def cmd_health(self, message: discord.Message, args: Optional[str]):
        """Checks if the database is receiving updates."""
        try:
            # Check for data in the last 15 minutes
            df = self._get_recent_data(minutes=15)
            
            if df is None:
                await message.channel.send("❌ **Critical:** Database file not found or inaccessible.")
                return

            if df.empty:
                await message.channel.send("⚠️ **Warning:** No data recorded in the last 15 minutes. Monitor loop may be down.")
            else:
                # Get the most recent timestamp
                last_time = df['LogTime'].max()
                row_count = len(df)
                
                # Check file size if possible
                db_size = "Unknown"
                if os.path.exists(Config.DB_FILE):
                    size_kb = os.path.getsize(Config.DB_FILE) / 1024
                    db_size = f"{size_kb:.2f} KB"

                await message.channel.send(
                    f"✅ **System Healthy**\n"
                    f"🕒 Latest Data: `{last_time}`\n"
                    f"📊 Recent Entries (15m): `{row_count}`\n"
                    f"💾 DB Size: `{db_size}`"
                )
        except Exception as e:
            log.error(f"Health check failed: {e}")
            await message.channel.send("❌ **Error:** Health check failed.")

    async def cmd_copy(self, message: discord.Message, args: Optional[str]):
        """Provides mobile-friendly copy-paste text and link."""
        content = self._read_draft_file()
        if not content:
            await message.channel.send("⚠️ No draft found. System may be initializing.")
            return

        # Step 1: Link
        await message.channel.send(
            "**1️⃣ Tap to Open Form:**\n"
            "https://www.mbta.com/customer-support\n"
            "*(Select 'Complaint' -> 'Service Complaint')*"
        )
        
        # Step 2: Content (Chunked if necessary)
        await message.channel.send("**2️⃣ Tap block below to Copy Text:**")
        await self._send_chunked_code_block(message.channel, content)

    async def cmd_launch(self, message: discord.Message, args: Optional[str]):
        """Triggers the Selenium automation script on the host machine."""
        script_path = "auto_fill_smart.py"
        
        if not os.path.exists(script_path):
            await message.channel.send(f"❌ Configuration Error: Script '{script_path}' not found.")
            return

        await message.channel.send("🚀 Launching Chrome on host machine...")
        try:
            # Run detached process
            subprocess.Popen(["python", script_path])
            await message.channel.send("✅ Browser opened! Please select **'Complaint | Service Complaint'** to trigger auto-fill.")
        except Exception as e:
            log.error(f"Subprocess failed: {e}")
            await message.channel.send("❌ Failed to launch automation script.")

    async def cmd_list(self, message: discord.Message, args: Optional[str]):
        """Displays a live board of all active trains in the last 30 minutes."""
        df = self._get_recent_data(minutes=30)
        
        if df is None or df.empty:
            await message.channel.send("⚠️ No active trains detected in the last 30 minutes.")
            return

        # Get the most recent status entry for each unique train
        latest_status = df.sort_values('LogTime').groupby('Train').tail(1)

        # Build Header
        response = "**🚆 Active Trains**\n```\n"
        response += f"{'ID':<5} {'DIR':<4} {'STATUS':<10} {'DELAY':<6} {'STATION'}\n"
        response += "-"*45 + "\n"

        # Build Rows
        for _, row in latest_status.iterrows():
            response += self._format_list_row(row)
        
        response += "```"
        await message.channel.send(response)

    async def cmd_status(self, message: discord.Message, args: Optional[str]):
        """Handles both general status (email draft) and specific train lookup."""
        # Case A: Specific Train (Argument provided)
        if args:
            await self._handle_specific_train_status(message, args)
            return

        # Case B: General Status (Email Draft)
        content = self._read_draft_file()
        if content:
            await message.channel.send(f"**Current Draft:**")
            await self._send_chunked_code_block(message.channel, content)
        else:
            await message.channel.send("⚠️ No draft found.")

    async def send_alert(self, title: str, description: str, color: int = 0xFF0000):
        """Proactive Alert Logic"""
        if Config.DISCORD_ALERT_CHANNEL_ID == 0: return
        channel = self.get_channel(Config.DISCORD_ALERT_CHANNEL_ID)
        if channel:
            embed = discord.Embed(title=title, description=description, color=color)
            await channel.send(embed=embed)

    # =========================================================================
    # PRIVATE HELPER METHODS (Business Logic)
    # =========================================================================

    async def _handle_specific_train_status(self, message: discord.Message, train_num: str):
        """Logic to lookup and format stats for a single train."""
        df = self._get_recent_data(minutes=60)
        
        if df is None:
            await message.channel.send("⚠️ Log data unavailable.")
            return

        # Filter for specific train
        train_data = df[df['Train'].astype(str) == train_num]

        if train_data.empty:
            await message.channel.send(f"❌ No data found for **Train {train_num}** in the last hour.")
            return

        # Calculate Stats
        max_delay = train_data['DelayMinutes'].max()
        last_entry = train_data.iloc[-1]
        
        # Visual Indicators
        status_icon = "🟢" if max_delay < 5 else "🔴"
        
        response = (
            f"**🚆 Report: Train {train_num}**\n"
            f"{status_icon} **Max Delay (1h):** {max_delay} min\n"
            f"ℹ️ **Current Status:** {last_entry['Status']}\n"
            f"📍 **Last Location:** {last_entry['Station']}\n"
            f"🕒 **Last Seen:** {last_entry['LogTime'].strftime('%H:%M')}"
        )
        await message.channel.send(response)

    def _get_recent_data(self, minutes: int) -> Optional[pd.DataFrame]:
        """Reads CSV and returns DataFrame filtered by time window."""
        # Use the DB Manager's method instead of reading raw CSV
        try:
            return self.db.get_recent_logs(minutes=minutes)
        except Exception as e:
            log.error(f"Data Read Error: {e}")
            return None

    def _read_draft_file(self) -> Optional[str]:
        """Safely reads the email draft file."""
        if not os.path.exists(Config.DRAFT_FILE):
            return None
        try:
            with open(Config.DRAFT_FILE, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            log.error(f"Draft Read Error: {e}")
            return None

    def _format_list_row(self, row: pd.Series) -> str:
        """Formats a single DataFrame row into a fixed-width string."""
        # Visual Alert for delays or cancellations
        is_late = row['DelayMinutes'] > 5 or row['Status'] == 'CANCELED'
        alert_char = "!" if is_late else " "
        
        direction = row.get('Direction', 'UNK')

        # Truncate station name to fit layout
        station = str(row['Station'])
        if len(station) > 13:
            station = station[:11] + ".."
            
        return (
            f"{alert_char}"
            f"{str(row['Train']):<5} "
            f"{str(direction):<4} "
            f"{str(row['Status']):<10} "
            f"{str(row['DelayMinutes']):<6} "
            f"{station}\n"
        )

    async def _send_chunked_code_block(self, channel, content: str):
        """Splits long text into multiple Discord code blocks to avoid 2000 char limit."""
        chunk_size = 1900
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            await channel.send(f"```text\n{chunk}```")