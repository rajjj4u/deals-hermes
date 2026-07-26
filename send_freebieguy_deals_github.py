#!/usr/bin/env python3
"""
Fetch deals from thefreebieguy.com RSS feed and send via Telegram.
GitHub Actions version - reads config from environment variables.
"""

import os
import re
import json
import urllib.request
from datetime import datetime
from pathlib import Path

# Configuration from environment (set via GitHub Actions secrets)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RSS_URL = "https://thefreebieguy.com/feed/"
DEALS_PER_RUN = 10
STATE_FILE = Path("freebieguy_state.json")  # In working directory for GitHub Actions cache

if not BOT_TOKEN or not CHAT_ID:
    print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set as environment variables")
    exit(1)

def fetch_rss():
    """Fetch and parse RSS feed for deals."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/rss+xml, application/xml, text/xml, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cache-Control': 'no-cache',
    }
    req = urllib.request.Request(RSS_URL, headers=headers)
    response = urllib.request.urlopen(req, timeout=30)
    content = response.read().decode('utf-8')
    return content

def parse_deals(rss_content):
    """Extract deal items from RSS content using regex."""
    items = re.findall(r'<item>(.*?)</item>', rss_content, re.DOTALL)
    deals = []
    
    for item in items:
        title_match = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>', item, re.DOTALL)
        title = title_match.group(1) if title_match and title_match.group(1) else (title_match.group(2) if title_match else '')
        
        link_match = re.search(r'<link>(.*?)</link>', item)
        link = link_match.group(1) if link_match else ''
        
        pub_date_match = re.search(r'<pubDate>(.*?)</pubDate>', item)
        pub_date = pub_date_match.group(1) if pub_date_match else ''
        
        desc_match = re.search(r'<description><!\[CDATA\[(.*?)\]\]></description>|<description>(.*?)</description>', item, re.DOTALL)
        description = desc_match.group(1) if desc_match and desc_match.group(1) else (desc_match.group(2) if desc_match else '')
        
        categories = re.findall(r'<category><!\[CDATA\[(.*?)\]\]></category>|<category>(.*?)</category>', item)
        cat_list = [c[0] if c[0] else c[1] for c in categories]
        
        # Clean up
        def clean(text):
            text = text.replace('&#8211;', '-').replace('&#8217;', "'").replace('&', '&')
            text = text.replace('&#038;', '&').replace('&#124;', '|').replace('&#8243;', '"')
            text = text.replace('&#8230;', '...').replace('&#8242;', "'").replace('&#8216;', "'")
            text = text.replace('&#8220;', '"').replace('&#8221;', '"')
            text = re.sub(r'<[^>]+>', '', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text
        
        title = clean(title)
        description = clean(description)
        if len(description) > 180:
            description = description[:180] + '...'
        
        # Format date
        try:
            dt = datetime.strptime(pub_date[:25], '%a, %d %b %Y %H:%M:%S')
            date_str = dt.strftime('%b %d, %Y')
        except:
            date_str = pub_date[:16]
        
        # Create unique ID from link
        deal_id = link.split('/')[-2] if link else title[:50]
        
        deals.append({
            'id': deal_id,
            'title': title,
            'link': link,
            'description': description,
            'categories': cat_list,
            'date': date_str,
            'pub_date': pub_date
        })
    
    return deals

def load_state():
    """Load previously sent deal IDs."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'sent_ids': [], 'last_run': None}

def save_state(state):
    """Save sent deal IDs."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def send_telegram_message(text):
    """Send message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        'chat_id': CHAT_ID,
        'text': text,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'}
    )
    response = urllib.request.urlopen(req, timeout=30)
    return response.read().decode()

def format_deal_message(deal, index, total):
    """Format a single deal for Telegram."""
    cats = ', '.join(deal['categories']) if deal['categories'] else 'Deals'
    return (
        f"*{index}/{total}. {deal['title']}*\n"
        f"🏷️ {cats} • 📅 {deal['date']}\n"
        f"📝 {deal['description']}\n"
        f"🔗 {deal['link']}\n"
    )

def main():
    print(f"[{datetime.now()}] Starting FreebieGuy deals fetch...")
    
    state = load_state()
    sent_ids = set(state.get('sent_ids', []))
    
    try:
        rss = fetch_rss()
        all_deals = parse_deals(rss)
        print(f"Found {len(all_deals)} total deals in feed")
    except Exception as e:
        print(f"Error fetching RSS: {e}")
        return
    
    # Filter out already sent deals
    new_deals = [d for d in all_deals if d['id'] not in sent_ids]
    print(f"{len(new_deals)} new deals available")
    
    if not new_deals:
        print("No new deals to send")
        return
    
    # Send up to DEALS_PER_RUN deals
    to_send = new_deals[:DEALS_PER_RUN]
    
    for i, deal in enumerate(to_send, 1):
        message = format_deal_message(deal, i, len(to_send))
        try:
            result = send_telegram_message(message)
            print(f"Sent deal {i}/{len(to_send)}: {deal['title'][:50]}...")
            sent_ids.add(deal['id'])
        except Exception as e:
            print(f"Error sending deal {i}: {e}")
            if hasattr(e, 'read'):
                print(e.read().decode())
    
    # Update state (keep last 500 sent IDs)
    state['sent_ids'] = list(sent_ids)[-500:]
    state['last_run'] = datetime.now().isoformat()
    save_state(state)
    print(f"[{datetime.now()}] Done. Sent {len(to_send)} deals.")

if __name__ == '__main__':
    main()