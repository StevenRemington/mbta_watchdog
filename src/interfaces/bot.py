import discord
import os
import aiohttp
from datetime import datetime
from typing import Optional, List, Dict, Any
from dateutil import parser

from database.database import DatabaseManager
from utils.reporter import Reporter
from utils.config import Config
from utils.logger import get_logger

log = get_logger("Bot")

class WatchdogBot(discord.Client):
    """
    Discord Bot interface for the MBTA Watchdog system.
    """

    def __init__(self, db_manager: Optional[DatabaseManager] = None, reporter: Optional[Reporter] = None, monitor=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = db_manager or DatabaseManager()
        self.reporter = reporter or Reporter(db_manager=self.db)
        self.monitor = monitor
        
        # Command Registry
        self.command_map = {
            '!help': self.cmd_help,
            '!list': self.cmd_list,
            '!status': self.cmd_status,
            '!feedback': self.cmd_feedback,
            '!health': self.cmd_health,
            '!analyze': self.cmd_analyze,
            '!leaderboard': self.cmd_leaderboard
        }

    async def on_ready(self):
        log.info(f'Logged in as {self.user} (ID: {self.user.id})')

    async def on_message(self, message: discord.Message):
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
                await message.channel.send("⚠️ An internal error occurred.")

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    async def cmd_help(self, message: discord.Message, args: Optional[str]):
        """Displays the help menu."""
        help_text = (
            "**🚆 MBTA Watchdog Help**\n"
            "```\n"
            "!list           : Live board of all active trains\n"
            "!status <num>   : Live status & next stop prediction (e.g., !status 508)\n"
            "!analyze <num>  : 30-Day Performance Report Card for a train\n"
            "!leaderboard    : The 'Wall of Shame' (Top 3 worst trains)\n"
            "!feedback       : Generate a complaint email draft for the MBTA\n"
            "!health         : Check system health and database connection\n"
            "```"
        )
        await message.channel.send(help_text)
    async def cmd_analyze(self, message: discord.Message, args: Optional[str]):
        """Generates a 30-day performance report card for a train."""
        if not args:
            await message.channel.send("⚠️ Usage: `!analyze <train_number>` (e.g., `!analyze 508`)")
            return

        train_num = args.strip()
        
        # 1. Fetch Data from DB
        stats = self.db.get_train_analysis(train_num, days=30)
        
        if not stats:
            await message.channel.send(f"❌ No history found for **Train {train_num}** in the last 30 days.")
            return

        # 2. Determine Color / Grade
        rel = stats['reliability_percent']
        if rel >= 90: color = 0x2ecc71 # Green
        elif rel >= 80: color = 0xf1c40f # Yellow
        elif rel >= 70: color = 0xe67e22 # Orange
        else: color = 0xe74c3c # Red

        # 3. Build Embed
        embed = discord.Embed(
            title=f"📊 Analysis: Train {train_num}",
            description=f"Performance Report (Last 30 Days)",
            color=color
        )
        
        embed.add_field(name="Reliability", value=f"**{stats['reliability_percent']}%**", inline=True)
        embed.add_field(name="Avg Delay", value=f"{stats['avg_delay_minutes']} min", inline=True)
        embed.add_field(name="Worst Day", value=stats['worst_day'], inline=True)
        
        embed.add_field(
            name="Incidents", 
            value=f"🛑 **{stats['canceled_count']}** Canceled\n⚠️ **{stats['late_count']}** Major Delayed Trips", 
            inline=False
        )
        
        # Updated Footer Text
        embed.set_footer(text=f"Based on {stats['total_runs']} trips.")
        
        await message.channel.send(embed=embed)

    async def cmd_health(self, message: discord.Message, args: Optional[str]):
        try:
            df = self._get_recent_data(minutes=15)
            if df is None:
                await message.channel.send("❌ **Critical:** Database inaccessible.")
                return

            if df.empty:
                await message.channel.send("⚠️ **Warning:** No data recorded in the last 15 minutes.")
            else:
                last_time = df['LogTime'].max()
                await message.channel.send(f"✅ **System Healthy**\n🕒 Latest: `{last_time}`\n📊 Rows: `{len(df)}`")
        except Exception as e:
            await message.channel.send(f"❌ **Error:** {e}")

    async def cmd_feedback(self, message: discord.Message, args: Optional[str]):
        await message.channel.send("**1️⃣ Open Form:** https://www.mbta.com/customer-support")
        df = self._get_recent_data(minutes=60)
        if df is not None:
            content = self.reporter.generate_email(df)
            await message.channel.send("**2️⃣ Copy Text:**")
            await self._send_chunked_code_block(message.channel, content)
        else:
            await message.channel.send("⚠️ Database unavailable.")

    async def cmd_list(self, message: discord.Message, args: Optional[str]):
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
        if args:
            await self._handle_specific_train_status(message, args.strip())
        else:
            df = self._get_recent_data(minutes=30)
            if df is not None and not df.empty:
                active = sorted(df['Train'].unique().tolist())
                t_list = ", ".join([f"`{t}`" for t in active])
                await message.channel.send(f"⚠️ Usage: `!status <num>`\nActive: {t_list}")
            else:
                await message.channel.send("⚠️ Usage: `!status <num>` (No active trains)")

    async def cmd_leaderboard(self, message: discord.Message, args: Optional[str]):
        """Displays the Wall of Shame (Top 3 Worst trains of the month)."""
        leaders = self.db.get_leaderboard_stats(days=30)
        
        if not leaders:
            await message.channel.send("🏆 Amazing! No major delays or cancellations in the last 30 days.")
            return

        embed = discord.Embed(
            title="🏆 Wall of Shame (Last 30 Days)",
            description="The Top 3 most unreliable trains.",
            color=0x2c3e50
        )

        medals = ["🥇", "🥈", "🥉"]

        for i, row in enumerate(leaders):
            if i >= 3: break 
            
            # Text generation
            details = []
            if row['cancels'] > 0: details.append(f"🚫 **{row['cancels']}** Cancel(s)")
            
            # UPDATED TEXT HERE:
            if row['major_lates'] > 0: details.append(f"⚠️ **{row['major_lates']}** Major Delay Record(s)")
            
            stats_text = f"{' • '.join(details)}\n🐌 Max Delay: {row['max_delay']}m"
            
            embed.add_field(
                name=f"{medals[i]} Train {row['train']}",
                value=stats_text,
                inline=False
            )
        
        await message.channel.send(embed=embed)

    async def send_alert(self, title: str, description: str, color: int = 0xFF0000):
        if Config.DISCORD_ALERT_CHANNEL_ID == 0: return
        channel = self.get_channel(Config.DISCORD_ALERT_CHANNEL_ID)
        if not channel:
            try: channel = await self.fetch_channel(Config.DISCORD_ALERT_CHANNEL_ID)
            except: return

        if channel:
            try:
                embed = discord.Embed(title=title, description=description, color=color)
                await channel.send(embed=embed)
            except Exception as e:
                log.error(f"Alert Error: {e}")

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    async def _handle_specific_train_status(self, message: discord.Message, train_num: str):
        df = self._get_recent_data(minutes=60)
        if df is None: return

        train_data = df[df['Train'].astype(str) == train_num]
        if train_data.empty:
            await message.channel.send(f"❌ No recent logs found for **Train {train_num}**.")
            return

        # Use the injected Monitor to get live predictions (Refactored logic)
        live_pred = None
        if self.monitor:
             live_pred = await self.monitor.get_live_prediction(train_num)

        last_entry = train_data.iloc[-1]
        max_delay = train_data['DelayMinutes'].max()
        
        log_time = last_entry['LogTime']
        if isinstance(log_time, str):
            try: log_time = pd.to_datetime(log_time)
            except: log_time = None
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

    def _get_recent_data(self, minutes: int):
        try: return self.db.get_recent_logs(minutes=minutes)
        except: return None

    async def _send_chunked_code_block(self, channel, content: str):
        chunk_size = 1900
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            await channel.send(f"```text\n{chunk}```")