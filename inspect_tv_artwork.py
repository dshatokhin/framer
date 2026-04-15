#!/usr/bin/env python3
"""Inspect TV artwork structure"""

import os
import sys
import asyncio
import json
from samsungtvws.async_art import SamsungTVAsyncArt

async def inspect():
    tv_ip = os.getenv('SMARTTHING_TV_IP_ADDRESS')
    if not tv_ip:
        print("Set SMARTTHING_TV_IP_ADDRESS")
        return
    
    tv = SamsungTVAsyncArt(host=tv_ip)
    available = await tv.available()
    print(f"Total artworks: {len(available)}")
    
    for i, art in enumerate(available):
        print(f"\n--- Artwork {i} ---")
        for key, value in art.items():
            print(f"  {key}: {value}")
        # Look for MY patterns
        for key, value in art.items():
            if isinstance(value, str) and 'MY' in value:
                print(f"  >>> MY found in {key}: {value}")

if __name__ == "__main__":
    asyncio.run(inspect())