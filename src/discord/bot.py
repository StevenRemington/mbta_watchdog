import discord
import os
import subprocess
import pandas as pd
from datetime import datetime
from database import DatabaseManager

from utils.config import Config
from utils.logger import get_logger

log = get_logger("Bot")

class WatchdogBot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = DatabaseManager()
        self.command_map = {
            '!help': self.cmd_help,
            '!list': self.cmd_list,
            '!status': self.cmd_status,
            '!email': self.cmd_status,
            '!copy': self.cmd_copy,
            '!launch': self.cmd_launch
        }

    async def on_ready(self):
        log.info(f'Logged in as {self.user}')

    async def on_message(self, message):
        if message.author == self.user or not message.content.startswith('!'):
            return
        
        parts = message.content.strip().split(' ', 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else None

        handler = self.command_map.get(command)
        if handler:
            await handler(message, args)

    # --- HANDLERS ---
    async def cmd_help(self, message, args):
        await message.channel.send(
            "**🚆 MBTA Watchdog**\n```\n"
            "!list          : Active trains\n"
            "!status        : Email Draft\n"
            "!status <num>  : Train History\n"
            "!copy          : Mobile Copy/Paste\n"
            "!launch        : Desktop Auto-Fill\n```"
        )

    async def cmd_list(self, message, args):
        df = self.db.get_recent_logs(minutes=30)
        
        if df.empty:
            await message.channel.send("⚠️ No active trains (last 30m).")
            return

        latest = df.sort_values('LogTime').groupby('Train').tail(1)
        
        # Added 'DIR' column
        resp = "**🚆 Active Trains**\n```\nID    DIR  STATUS     DELAY  STATION\n" + "-"*40 + "\n"
        
        for _, row in latest.iterrows():
            alert = "!" if row['DelayMinutes'] > 5 or row['Status'] == 'CANCELED' else " "
            
            # Handle missing direction (for old logs)
            direction = row.get('Direction', 'UNK')
            
            # Truncate station slightly more to fit the new column
            st = str(row['Station'])[:13]
            
            resp += f"{alert}{str(row['Train']):<5} {direction:<4} {str(row['Status']):<10} {str(row['DelayMinutes']):<6} {st}\n"
            
        resp += "```"
        await message.channel.send(resp)

    async def cmd_status(self, message, args):
        if args:
            # Specific Train
            df = self.db.get_recent_logs(minutes=60)
            train_data = df[df['Train'].astype(str) == args]
            if train_data.empty:
                await message.channel.send(f"❌ No data for Train {args}")
                return
            
            max_d = train_data['DelayMinutes'].max()
            last = train_data.iloc[-1]
            icon = "🟢" if max_d < 5 else "🔴"
            
            await message.channel.send(
                f"**🚆 Train {args}**\n{icon} Max Delay: {max_d} min\n"
                f"ℹ️ Status: {last['Status']}\n📍 Location: {last['Station']}"
            )
        else:
            # Email Draft
            if os.path.exists(Config.DRAFT_FILE):
                with open(Config.DRAFT_FILE, 'r') as f:
                    content = f.read()
                # Chunking for Discord limit
                for i in range(0, len(content), 1900):
                    await message.channel.send(f"```text\n{content[i:i+1900]}```")
            else:
                await message.channel.send("⚠️ No draft found.")

    async def cmd_copy(self, message, args):
        await message.channel.send("**1️⃣ Open:** https://www.mbta.com/customer-support")
        if os.path.exists(Config.DRAFT_FILE):
            with open(Config.DRAFT_FILE, 'r') as f:
                content = f.read()
            await message.channel.send("**2️⃣ Copy:**")
            await message.channel.send(f"```text\n{content[:1900]}```")

    async def cmd_launch(self, message, args):
        if os.path.exists("auto_fill_smart.py"):
            subprocess.Popen(["python", "auto_fill_smart.py"])
            await message.channel.send("🚀 Browser Launched! Select **'Complaint | Service Complaint'**.")
        else:
            await message.channel.send("❌ Script not found.")

    async def send_alert(self, title, description, color=0xFF0000):
        """Proactive Alert Logic"""
        if Config.DISCORD_ALERT_CHANNEL_ID == 0: return
        channel = self.get_channel(Config.DISCORD_ALERT_CHANNEL_ID)
        if channel:
            embed = discord.Embed(title=title, description=description, color=color)
            await channel.send(embed=embed)