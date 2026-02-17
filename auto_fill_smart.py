import os
import sys
import math
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from config import Config

def get_rounded_time():
    now = datetime.now()
    minute = int(5 * round(now.minute / 5))
    hour = now.hour
    if minute == 60:
        minute = 0
        hour += 1
    if hour >= 24: hour = 0
    
    am_pm = "AM"
    if hour >= 12:
        am_pm = "PM"
        if hour > 12: hour -= 12
    elif hour == 0: hour = 12

    return str(hour), f"{minute:02d}", am_pm

def main():
    if not os.path.exists(Config.DRAFT_FILE):
        print("❌ Draft file not found.")
        return

    with open(Config.DRAFT_FILE, 'r', encoding='utf-8') as f:
        text = f.read()

    options = webdriver.ChromeOptions()
    options.add_experimental_option("detach", True)
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get("https://www.mbta.com/customer-support")

    print("👉 Select 'Complaint' -> 'Service Complaint'...")

    try:
        wait = WebDriverWait(driver, 300)
        box = wait.until(EC.visibility_of_element_located((By.TAG_NAME, "textarea")))
        
        box.click()
        box.clear()
        box.send_keys(text)

        # Time Selection
        h, m, ap = get_rounded_time()
        Select(driver.find_element(By.ID, "support_date_time_hour")).select_by_value(h)
        Select(driver.find_element(By.ID, "support_date_time_minute")).select_by_value(m)
        Select(driver.find_element(By.ID, "support_date_time_am_pm")).select_by_value(ap)
        
        print("✅ Auto-fill Complete.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()