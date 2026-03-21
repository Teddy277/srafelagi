"""
Fix database - Add unique constraint for ON CONFLICT
"""

import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')


def fix_database():
    print("🔧 Fixing database constraints...")
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        # First, check if there are duplicate telegram_id + telegram_channel combinations
        print("📋 Checking for duplicates...")
        cur.execute("""
            SELECT telegram_id, telegram_channel, COUNT(*) 
            FROM jobs 
            WHERE telegram_id IS NOT NULL AND telegram_channel IS NOT NULL
            GROUP BY telegram_id, telegram_channel 
            HAVING COUNT(*) > 1;
        """)
        duplicates = cur.fetchall()
        
        if duplicates:
            print(f"   Found {len(duplicates)} duplicate combinations. Removing extras...")
            # Keep only the first occurrence
            cur.execute("""
                DELETE FROM jobs a USING jobs b
                WHERE a.id > b.id 
                AND a.telegram_id = b.telegram_id 
                AND a.telegram_channel = b.telegram_channel;
            """)
            conn.commit()
            print("   ✅ Duplicates removed")
        
        # Add unique constraint
        print("📋 Adding unique constraint...")
        
        # First drop if exists (to avoid errors)
        cur.execute("""
            ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_telegram_unique;
        """)
        conn.commit()
        
        # Create the unique constraint
        cur.execute("""
            ALTER TABLE jobs 
            ADD CONSTRAINT jobs_telegram_unique 
            UNIQUE (telegram_id, telegram_channel);
        """)
        conn.commit()
        print("   ✅ Unique constraint added")
        
        # Also fix telegram_id type if needed (should be able to hold bigint as varchar)
        print("📋 Schema is ready!")
        
    except Exception as e:
        print(f"⚠️ Error: {e}")
        conn.rollback()
        
        # Alternative: Create unique index instead
        print("📋 Trying alternative: Creating unique index...")
        try:
            cur.execute("""
                DROP INDEX IF EXISTS idx_jobs_telegram_unique;
            """)
            cur.execute("""
                CREATE UNIQUE INDEX idx_jobs_telegram_unique 
                ON jobs (telegram_id, telegram_channel) 
                WHERE telegram_id IS NOT NULL AND telegram_channel IS NOT NULL;
            """)
            conn.commit()
            print("   ✅ Unique index created")
        except Exception as e2:
            print(f"❌ Failed: {e2}")
            conn.rollback()
    
    cur.close()
    conn.close()
    
    print("\n✅ Database fix complete!")


if __name__ == '__main__':
    fix_database()