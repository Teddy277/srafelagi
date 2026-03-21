# check_links.py
from database import Database
from dotenv import load_dotenv
import os

load_dotenv()
db = Database(os.getenv('DATABASE_URL'))

print("="*60)
print("🔎 CHECKING FOR REAL APPLY LINKS")
print("="*60)

with db.get_cursor() as cursor:
    cursor.execute("""
        SELECT id, title, source_url, apply_url, description 
        FROM jobs 
        ORDER BY id DESC 
        LIMIT 10
    """)
    jobs = cursor.fetchall()

for job in jobs:
    print(f"\n🆔 Job ID: {job['id']}")
    print(f"💼 Title:  {job['title']}")
    print(f"🌍 Source: {job['source_url']}")
    
    if job['apply_url']:
        if job['apply_url'] == job['source_url']:
            print(f"❌ Apply Link: SAME AS SOURCE (Bad)")
        else:
            print(f"✅ Apply Link: {job['apply_url']} (Good!)")
    else:
        print(f"❌ Apply Link: NULL (Scraper didn't find it)")
        
    print(f"📝 Desc Len: {len(job['description'] or '')} chars")

print("\n" + "="*60)