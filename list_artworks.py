#!/usr/bin/env python3
"""
Samsung Frame TV Artwork Lister
Lists all available artwork on your Samsung Frame TV
"""

import os
import sys
import logging
import asyncio
import json
from samsungtvws.async_art import SamsungTVAsyncArt
from samsungtvws.exceptions import ConnectionFailure

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def list_artworks():
    """List all available artwork on the TV"""
    # Get TV IP from environment variable
    tv_ip = os.getenv('SMARTTHING_TV_IP_ADDRESS')
    if not tv_ip:
        logger.error("SMARTTHING_TV_IP_ADDRESS environment variable not set")
        logger.error("Please set it to your TV's IP address")
        return False
    
    # Get auth token from environment variable (optional)
    auth_token = os.getenv('SMARTTHING_AUTH_TOKEN')
    
    logger.info(f"Connecting to Samsung TV at {tv_ip}")
    
    try:
        # Initialize async TV art connection
        if auth_token:
            tv = SamsungTVAsyncArt(host=tv_ip, token=auth_token)
        else:
            tv = SamsungTVAsyncArt(host=tv_ip)
        
        logger.info("✓ Connection established successfully")
        
        # Get available artwork
        logger.info("Fetching available artwork...")
        available_art = await tv.available()
        
        if not available_art:
            logger.info("No artwork found on the TV")
            return True
        
        logger.info(f"✓ Found {len(available_art)} pieces of artwork")
        
        # Debug: Show sample artwork data structure
        if available_art and len(available_art) > 0:
            logger.debug(f"Sample artwork data: {available_art[0]}")
        
        # Get current artwork
        # Get current artwork
        try:
            current_art = await tv.get_current()
            current_id = current_art.get('content_id', 'None') if current_art else 'None'
            logger.info(f"✓ Current artwork: {current_id}")
        except Exception:
            current_id = 'Unknown'
            logger.info("✓ Current artwork: Unknown (may not be set)")
        
        # Categorize artwork
        uploaded_images = []
        builtin_images = []
        other_images = []
        
        for art in available_art:
            art_id = art.get('content_id', 'Unknown')
            art_category = art.get('category_id', 'unknown')
            art_type = art.get('content_type', 'unknown')
            
            # Debug: Print raw art data for first few items
            if len(uploaded_images) + len(builtin_images) + len(other_images) < 3:
                logger.debug(f"Raw art data: {art}")
            
            if art_id.startswith('MY'):
                # User-uploaded artwork (MY_Fxxxx or MY-xxxx)
                uploaded_images.append({
                    'id': art_id,
                    'category': art_category,
                    'type': art_type,
                    'is_current': art_id == current_id
                })
            elif art_id.startswith('SAM-'):
                # Built-in Samsung artwork
                builtin_images.append({
                    'id': art_id,
                    'category': art_category,
                    'type': art_type,
                    'is_current': art_id == current_id
                })
            else:
                # Other artwork (unknown type)
                other_images.append({
                    'id': art_id,
                    'category': art_category,
                    'type': art_type,
                    'is_current': art_id == current_id
                })
        
        # Output results
        logger.info("\n" + "="*60)
        logger.info("UPLOADED ARTWORK (MY_*)")
        logger.info("="*60)
        
        if uploaded_images:
            for art in uploaded_images:
                status = "[CURRENT]" if art['is_current'] else ""
                logger.info(f"ID: {art['id']} - category:{art['category']} type:{art['type']} {status}")
        else:
            logger.info("No uploaded artwork found")
        
        logger.info("\n" + "="*60)
        logger.info("BUILT-IN ARTWORK")
        logger.info("="*60)
        
        if builtin_images:
            for art in builtin_images[:10]:  # Show first 10 to avoid spam
                status = "[CURRENT]" if art['is_current'] else ""
                logger.info(f"ID: {art['id']} - category:{art['category']} type:{art['type']} {status}")
            if len(builtin_images) > 10:
                logger.info(f"... and {len(builtin_images) - 10} more built-in artwork")
        else:
            logger.info("No built-in artwork found")
        
        logger.info("\n" + "="*60)
        logger.info("OTHER ARTWORK")
        logger.info("="*60)
        
        if other_images:
            for art in other_images:
                status = "[CURRENT]" if art['is_current'] else ""
                logger.info(f"ID: {art['id']} - category:{art['category']} type:{art['type']} {status}")
        else:
            logger.info("No other artwork found")
        
        # Save to JSON file for reference
        all_artworks = {
            'total_count': len(available_art),
            'current_artwork': current_id,
            'uploaded': uploaded_images,
            'builtin': builtin_images,
            'other': other_images,
            'timestamp': asyncio.get_event_loop().time()
        }
        
        with open('artwork_list.json', 'w') as f:
            json.dump(all_artworks, f, indent=2)
        
        logger.info(f"\n📄 Saved detailed artwork list to 'artwork_list.json'")
        logger.info(f"🎉 Total artwork on TV: {len(available_art)}")
        logger.info(f"📁 Uploaded artwork: {len(uploaded_images)}")
        logger.info(f"🏛️  Built-in artwork: {len(builtin_images)}")
        logger.info(f"🎨 Other artwork: {len(other_images)}")
        
        return True
        
    except ConnectionFailure as e:
        logger.error(f"✗ TV connection error: {e}")
        logger.error("Possible issues:")
        logger.error("  - TV is off or not on the network")
        logger.error("  - Incorrect IP address")
        logger.error("  - Authentication required (check TV for pairing prompt)")
        return False
    except Exception as e:
        logger.error(f"✗ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(list_artworks())
    sys.exit(0 if success else 1)