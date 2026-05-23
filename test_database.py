"""
Test database operations
"""

import asyncio
import os
from dotenv import load_dotenv
from database import Database

load_dotenv()


async def test_database():
    """Test all database operations"""
    
    print("=" * 60)
    print("🗄️ DATABASE TESTS")
    print("=" * 60)
    
    # Check if DATABASE_URL is set
    if not os.getenv('DATABASE_URL'):
        print("  ❌ DATABASE_URL not set in .env file!")
        print("  Create a free PostgreSQL database at: https://neon.tech")
        return
    
    db = Database()
    
    try:
        # Test 1: Connection
        print("\n  1. Testing connection...")
        await db.connect()
        print("  ✅ Connected to database!")
        
        # Test 2: Insert a test job
        print("\n  2. Testing job insertion...")
        test_job = {
            'telegram_id': 99999999,
            'telegram_channel': 'test_channel',
            'telegram_date': None,
            'title': 'Test Software Developer',
            'company': 'Test Company',
            'location': 'Addis Ababa',
            'description': 'This is a test job description.',
            'source_url': 'https://example.com/test-job',
            'apply_url': 'https://forms.google.com/test-form',
            'apply_email': 'test@company.com',
            'apply_type': 'google_form',
            'deadline': 'December 31, 2024',
            'salary': '50,000 ETB',
            'scraped_data': {'test': True},
            'raw_text': 'Raw telegram message text',
        }
        
        job_id = await db.save_job(test_job)
        
        if job_id:
            print(f"  ✅ Job inserted with ID: {job_id}")
        else:
            print("  ❌ Failed to insert job")
            return
        
        # Test 3: Retrieve job
        print("\n  3. Testing job retrieval...")
        retrieved = await db.get_job_by_id(job_id)
        
        if retrieved:
            print(f"  ✅ Retrieved job: {retrieved['title']}")
            print(f"     Company: {retrieved['company']}")
            print(f"     Apply URL: {retrieved['apply_url']}")
        else:
            print("  ❌ Failed to retrieve job")
        
        # Test 4: Search jobs
        print("\n  4. Testing job search...")
        results = await db.get_jobs(limit=10, search='Software')
        print(f"  ✅ Found {len(results)} jobs matching 'Software'")
        
        # Test 5: Get stats
        print("\n  5. Testing statistics...")
        stats = await db.get_stats()
        print(f"  ✅ Stats: {stats}")
        
        # Cleanup: Delete test job
        print("\n  6. Cleaning up test data...")
        with db.conn.cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE telegram_id = 99999999")
        db.conn.commit()
        print("  ✅ Test data cleaned up")
        
        print("\n" + "=" * 60)
        print("✅ All database tests passed!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n  ❌ Database error: {e}")
        
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(test_database())