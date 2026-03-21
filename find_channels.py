"""
Find and verify Ethiopian Job Telegram channels
Run this to discover which channels are valid
"""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from telethon import TelegramClient
from telethon.errors import UsernameNotOccupiedError, UsernameInvalidError, FloodWaitError

API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
PHONE = os.getenv('PHONE')


# Potential Ethiopian job channel names to check
CHANNELS_TO_CHECK = [
    # Common job channel patterns
    'ethaborede',
    'dailyjobethiopia',
    'effoyjobs',
    'efloyjobs',
    'vacancy3',
    'jobsethio',
    'ethiopiajobs',
    'ethiopianjobs',
    'ethiojobs',
    'addisababajobs',
    'Aborede_vacancy',
    'ethiovacancies',
    'ethiovacancy',
    'elelanajobs',
    'kaborede',
    'saborede',
    'zaborede',
    'aaborede',
    'ethiikiiraree',
    'ethiopianjobscom',
    'newjobsethiopia',
    'ethiopiawork',
    'jobsaddis',
    'addiswork',
    'ethiorecruitment',
    'ethiotalent',
    'hiringethiopia',
    'careersethiopia',
    'jobboardethiopia',
    'ethioemploy',
    'workethiopia',
    # Add more variations...
]


async def main():
    print("=" * 60)
    print("🔍 ETHIOPIAN JOB CHANNEL FINDER")
    print("=" * 60)
    
    client = TelegramClient('finder_session', int(API_ID), API_HASH)
    await client.start(phone=PHONE)
    
    me = await client.get_me()
    print(f"👤 Logged in as: {me.first_name}\n")
    
    valid_channels = []
    invalid_channels = []
    
    print("Checking channels...\n")
    
    for channel in CHANNELS_TO_CHECK:
        try:
            entity = await client.get_entity(channel)
            title = getattr(entity, 'title', 'Unknown')
            members = getattr(entity, 'participants_count', 'N/A')
            
            valid_channels.append({
                'username': channel,
                'title': title,
                'members': members
            })
            print(f"✅ @{channel}")
            print(f"   Title: {title}")
            print(f"   Members: {members}")
            print()
            
        except UsernameNotOccupiedError:
            invalid_channels.append(channel)
            print(f"❌ @{channel} - Does not exist")
            
        except UsernameInvalidError:
            invalid_channels.append(channel)
            print(f"❌ @{channel} - Invalid username")
            
        except FloodWaitError as e:
            print(f"⚠️ Rate limited! Wait {e.seconds} seconds...")
            await asyncio.sleep(e.seconds)
            
        except Exception as e:
            print(f"⚠️ @{channel} - Error: {e}")
        
        # Small delay to avoid rate limits
        await asyncio.sleep(1)
    
    await client.disconnect()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    
    print(f"\n✅ Valid channels ({len(valid_channels)}):")
    for ch in valid_channels:
        print(f"   '{ch['username']}',  # {ch['title']}")
    
    print(f"\n❌ Invalid channels ({len(invalid_channels)}):")
    for ch in invalid_channels:
        print(f"   '{ch}',")
    
    # Generate code snippet
    print("\n" + "=" * 60)
    print("📋 Copy this to main.py:")
    print("=" * 60)
    print("\nCHANNELS = [")
    for ch in valid_channels:
        print(f"    '{ch['username']}',  # {ch['title']}")
    print("]")


if __name__ == '__main__':
    asyncio.run(main())