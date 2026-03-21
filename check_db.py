# check_db.py
from database import Database
from dotenv import load_dotenv
import os

load_dotenv()

db = Database(os.getenv('DATABASE_URL'))

print("=" * 50)
print("DATABASE CHECK")
print("=" * 50)

stats = db.get_stats()
print(f"\n📊 Stats:")
print(f"   Total Jobs: {stats['total_jobs']}")
print(f"   Jobs Today: {stats['jobs_today']}")
print(f"   This Week: {stats['jobs_week']}")
print(f"   Total Views: {stats['total_views']}")

print(f"\n📁 Categories:")
categories = db.get_categories()
for cat in categories[:8]:
    print(f"   {cat['icon']} {cat['name']}: {cat['total_jobs']} jobs")

print(f"\n📋 Recent Jobs:")
result = db.get_jobs(page=1, per_page=5)
if result['jobs']:
    for job in result['jobs']:
        print(f"   • {job['title'] or 'No title'} at {job['company'] or 'Unknown'}")
else:
    print("   No jobs in database yet!")

print("\n" + "=" * 50)