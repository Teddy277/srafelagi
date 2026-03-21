# scrape_history.py
import asyncio
import os
from dotenv import load_dotenv
from telethon import TelegramClient
from telegram_parser import TelegramParser
from scrapers import ScraperFactory
from database import Database

load_dotenv()

API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
PHONE = os.getenv('PHONE')
DATABASE_URL = os.getenv('DATABASE_URL')

# Channels to scrape - JUST USERNAMES!
CHANNELS = [
    'dailyjobethiopia',
    'effoyjobs',
    'elelanajobs',
    'harmeejobs',
]

client = TelegramClient('job_session', API_ID, API_HASH)
parser = TelegramParser()
db = Database(DATABASE_URL)


async def scrape_channel(channel_name: str, limit: int = 30):
    """Scrape posts from a channel"""
    print(f"\n📡 Scraping @{channel_name}...")
    
    try:
        entity = await client.get_entity(channel_name)
        print(f"   Found: {entity.title}")
        
        saved_count = 0
        
        async for message in client.iter_messages(entity, limit=limit):
            text = message.text or ''
            
            if len(text) < 50:
                continue
            
            # Parse
            parsed = parser.parse(
                text,
                chat_id=entity.id,
                message_id=message.id,
                channel_username=channel_name
            )
            
            # Build job
            job = {
                'telegram_id': parsed['telegram_id'],
                'title': parsed.get('title'),
                'company': parsed.get('company_name'),
                'location': parsed.get('location'),
                'experience': parsed.get('experience_required'),
                'education': parsed.get('education_required'),
                'salary': parsed.get('salary'),
                'deadline_text': parsed.get('deadline_text'),
                'deadline_date': parsed.get('deadline_date'),
                'apply_email': parsed.get('apply_email'),
                'apply_phone': parsed.get('apply_phone'),
                'categories': parsed.get('categories', []),
                'is_fresh_graduate': parsed.get('is_fresh_graduate', False),
                'positions_count': parsed.get('positions_count', 1),
                'positions': parsed.get('positions', []),
                'source_url': parsed.get('source_url'),
                'source_domain': parsed.get('source_domain'),
                'channel_username': channel_name,
                'telegram_post_url': parsed.get('telegram_post_url'),
                'telegram_text': text,
                'scrape_status': 'pending',
            }
            
            # Save
            job_id = db.insert_job(job)
            
            if job_id:
                saved_count += 1
                title = parsed.get('title') or parsed.get('company_name') or 'Unknown'
                print(f"   💾 {saved_count}. {title[:50]}")
                
                # Scrape external link
                if parsed.get('source_url'):
                    try:
                        scraper = ScraperFactory.get_scraper(parsed['source_domain'])
                        scraped = await scraper.scrape(parsed['source_url'])
                        if scraped and scraped.get('scrape_status') == 'success':
                            db.update_job_scraped(job_id, scraped)
                            print(f"      ✅ Scraped external site")
                    except:
                        pass
                
                await asyncio.sleep(0.3)
        
        print(f"   ✅ Saved {saved_count} jobs from @{channel_name}")
        return saved_count
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return 0


async def main():
    print("=" * 60)
    print("📥 SCRAPING HISTORICAL JOBS")
    print("=" * 60)
    
    await client.start(phone=PHONE)
    print("✅ Connected to Telegram")
    
    total = 0
    
    for channel in CHANNELS:
        count = await scrape_channel(channel, limit=30)
        total += count
        await asyncio.sleep(1)
    
    stats = db.get_stats()
    
    print(f"\n" + "=" * 60)
    print(f"✅ DONE!")
    print(f"   Jobs scraped: {total}")
    print(f"   Total in database: {stats['total_jobs']}")
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())