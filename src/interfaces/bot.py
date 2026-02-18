import discord
import os
import subprocess
import pandas as pd
import aiohttp
from datetime import datetime
from typing import Optional, List, Dict, Any
from dateutil import parser

from database.database import DatabaseManager
from utils.config import Config
from utils.logger import get_logger

log = get_logger("Bot")

class WatchdogBot(discord.Client):
    """
    Discord Bot interface for the MBTA Watchdog system.
    Handles user commands and proactive service alerts.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None, *args, **kwargs):
        """
        Initialize the bot with dependency injection.
        """
        super().__init__(*args, **kwargs)
        self.db = db_manager or DatabaseManager()
        
        # Command Registry: Maps trigger words to handler methods
        self.command_map = {
            '!help': self.cmd_help,
            '!list': self.cmd_list,
            '!status': self.cmd_status,
            '!email': self.cmd_status,  # Alias
            '!copy': self.cmd_copy,
            '!launch': self.cmd_launch,
            '!health': self.cmd_health
        }

    async def on_ready(self):
        """Triggered when the bot successfully connects to Discord."""
        log.info(f'Logged in as {self.user} (ID: {self.user.id})')

    async def on_message(self, message: discord.Message):
        """Core event listener. Filters messages and dispatches commands."""
        if message.author == self.user or not message.content:
            return

        content = message.content.strip()
        if not content.startswith('!'):
            return
        
        parts = content.split(' ', 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else None

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
            "!status <num>  : View stats & predictions for a specific train\n"
            "!health        : Check database connection and recent updates\n"
            "!copy          : Get mobile-friendly text for complaints\n"
            "!launch        : Auto-fill the MBTA form (Desktop Only)\n"
            "```"
        )
        await message.channel.send(help_text)

    async def cmd_health(self, message: discord.Message, args: Optional[str]):
        """Checks if the system is receiving live updates."""
        try:
            df = self._get_recent_data(minutes=15)
            if df is None:
                await message.channel.send("❌ **Critical:** Database inaccessible.")
                return

            if df.empty:
                await message.channel.send("⚠️ **Warning:** No data recorded in the last 15 minutes.")
            else:
                last_time = df['LogTime'].max()
                await message.channel.send(f"✅ **System Healthy**\n🕒 Latest Data: `{last_time}`\n📊 Entries recorded (15m): `{len(df)}`")
        except Exception as e:
            await message.channel.send(f"❌ **Error:** {e}")

    async def cmd_copy(self, message: discord.Message, args: Optional[str]):
        """Provides mobile-friendly copy-paste text and link."""
        await message.channel.send("**1️⃣ Open Form:** https://www.mbta.com/customer-support")
        
        content = self._read_draft_file()
        if content:
            await message.channel.send("**2️⃣ Copy Text:**")
            await self._send_chunked_code_block(message.channel, content)
        else:
            await message.channel.send("⚠️ No email draft found yet.")

    async def cmd_launch(self, message: discord.Message, args: Optional[str]):
        """Triggers the Selenium automation on the host machine."""
        if os.path.exists("auto_fill_smart.py"):
            subprocess.Popen(["python", "auto_fill_smart.py"])
            await message.channel.send("🚀 Browser Launched on host! Select **'Complaint'** to auto-fill.")
        else:
            await message.channel.send("❌ Automation script not found.")

    async def cmd_list(self, message: discord.Message, args: Optional[str]):
        """Displays a live board of all active trains."""
        df = self._get_recent_data(minutes=30)
        if df is None or df.empty:
            await message.channel.send("⚠️ No active trains detected.")
            return

        latest = df.sort_values('LogTime').groupby('Train').tail(1)
        response = "**🚆 Active Trains (Worcester Line)**\n```\n"
        response += f"{'ID':<5} {'DIR':<4} {'STATUS':<10} {'DELAY':<6} {'STATION'}\n"
        response += "-"*45 + "\n"

        for _, row in latest.iterrows():
            is_late = row['DelayMinutes'] > Config.DELAY_THRESHOLD or row['Status'] == 'CANCELED'
            alert = "!" if is_late else " "
            station = str(row['Station'])[:13]
            response += f"{alert}{str(row['Train']):<5} {str(row['Direction']):<4} {str(row['Status']):<10} {str(row['DelayMinutes']):<6} {station}\n"
        
        response += "```"
        await message.channel.send(response)

    async def cmd_status(self, message: discord.Message, args: Optional[str]):
        """Handles email draft view or specific train lookup."""
        if args:
            await self._handle_specific_train_status(message, args)
        else:
            await self.cmd_copy(message, args)

    async def send_alert(self, title: str, description: str, color: int = 0xFF0000):
        """Sends a proactive alert with reliability fallback."""
        if Config.DISCORD_ALERT_CHANNEL_ID == 0: return
        
        channel = self.get_channel(Config.DISCORD_ALERT_CHANNEL_ID)
        if not channel:
            try:
                channel = await self.fetch_channel(Config.DISCORD_ALERT_CHANNEL_ID)
            except: 
                log.error(f"Failed to find channel ID {Config.DISCORD_ALERT_CHANNEL_ID}")
                return

        if channel:
            try:
                embed = discord.Embed(title=title, description=description, color=color)
                await channel.send(embed=embed)
            except Exception as e:
                log.error(f"Discord Alert Send Error: {e}")

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    async def _handle_specific_train_status(self, message: discord.Message, train_num: str):
        """Detailed report including historical DB data and live API predictions."""
        df = self._get_recent_data(minutes=60)
        if df is None: return

        train_data = df[df['Train'].astype(str) == train_num]
        if train_data.empty:
            await message.channel.send(f"❌ No recent logs found for **Train {train_num}**.")
            return

        # Get Live Data
        live_pred = await self._fetch_live_prediction(train_num)
        last_entry = train_data.iloc[-1]
        max_delay = train_data['DelayMinutes'].max()

        # Parse Time Safely
        log_time = last_entry['LogTime']
        if isinstance(log_time, str):
            try: 
                log_time = pd.to_datetime(log_time)
            except: 
                log_time = None
        time_str = log_time.strftime('%H:%M') if log_time else str(last_entry['LogTime'])

        response = (
            f"**🚆 Report: Train {train_num}**\n"
            f"{'🔴' if max_delay >= 5 else '🟢'} **Max Delay (1h):** {max_delay} min\n"
            f"ℹ️ **Status:** {last_entry['Status']}\n"
            f"📍 **Last Location:** {last_entry['Station']}\n"
            f"🕒 **Last Seen:** {time_str}\n"
        )

        if live_pred:
            response += f"\n**🔮 Next Stop: {live_pred['stop']}**\n"
            response += f"📅 Sched: `{live_pred['scheduled']}`\n"
            response += f"⏱️ Pred:  `{live_pred['predicted']}`\n"
            if live_pred['delay'] > 0: 
                response += f"⚠️ Delay: `+{live_pred['delay']} min`"
        
        await message.channel.send(response)

    async def _fetch_live_prediction(self, train_num: str) -> Optional[Dict]:
        """Fetches the immediate next stop prediction from MBTA API."""
        headers = {"x-api-key": Config.MBTA_API_KEY} if Config.MBTA_API_KEY else {}
        # Find Vehicle by Train Label
        url = f"https://api-v3.mbta.com/vehicles?filter[route]=CR-Worcester&filter[label]={train_num}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers) as resp:
                    v_data = await resp.json()
                    if not v_data['data']: return None
                    trip_id = v_data['data'][0]['relationships']['trip']['data']['id']

                # Fetch predictions for that trip
                pred_url = f"https://api-v3.mbta.com/predictions?filter[trip]={trip_id}&sort=time&page[limit]=1&include=stop,schedule"
                async with session.get(pred_url, headers=headers) as resp:
                    p_data = await resp.json()
                    if not p_data['data']: return None
                    
                    pred = p_data['data'][0]
                    p_ts = pred['attributes']['arrival_time'] or pred['attributes']['departure_time']
                    
                    s_ts = None
                    stop_name = "Unknown"
                    s_id = pred['relationships']['schedule']['data']['id']
                    
                    for inc in p_data.get('included', []):
                        if inc['type'] == 'schedule' and inc['id'] == s_id:
                            s_ts = inc['attributes']['arrival_time'] or inc['attributes']['departure_time']
                        if inc['type'] == 'stop' and inc['id'] == pred['relationships']['stop']['data']['id']:
                            stop_name = inc['attributes']['name']

                    def fmt(ts): 
                        return parser.parse(ts).strftime('%I:%M %p') if ts else "N/A"
                    
                    delay = 0
                    if p_ts and s_ts:
                        delay = round((parser.parse(p_ts) - parser.parse(s_ts)).total_seconds() / 60)

                    return {
                        "stop": stop_name, 
                        "predicted": fmt(p_ts), 
                        "scheduled": fmt(s_ts), 
                        "delay": max(0, delay)
                    }
            except: 
                return None

    def _get_recent_data(self, minutes: int):
        try: 
            return self.db.get_recent_logs(minutes=minutes)
        except: 
            return None

    def _read_draft_file(self) -> Optional[str]:
        if not os.path.exists(Config.DRAFT_FILE):
            return None
        try:
            with open(Config.DRAFT_FILE, 'r', encoding='utf-8') as f:
                return f.read()
        except:
            return None

    async def _send_chunked_code_block(self, channel, content: str):
        """Splits long text into multiple Discord code blocks to avoid 2000 char limit."""
        chunk_size = 1900
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            await channel.send(f"```text\n{chunk}```")