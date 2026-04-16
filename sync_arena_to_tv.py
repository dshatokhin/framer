#!/usr/bin/env python3
"""
Arena → Samsung TV Sync Script
Downloads and uploads new Arena blocks to Frame TV
Stateless version - stores mappings in Are.na block
"""

import os
import sys
import logging
import asyncio
import requests
import json
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from samsungtvws.async_art import SamsungTVAsyncArt
from samsungtvws.exceptions import ConnectionFailure

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Are.na API constants
ARENA_API_BASE = "https://api.are.na/v3"


def clean_slug_value(value: str) -> str:
    """Clean slug value by stripping whitespace and surrounding quotes"""
    if not value:
        return value
    # Strip whitespace first
    value = value.strip()
    # Strip surrounding quotes if present
    if len(value) >= 2:
        if (value[0] == '"' and value[-1] == '"') or (
            value[0] == "'" and value[-1] == "'"
        ):
            value = value[1:-1]
    return value


# Parse channel slugs with optional defaults
def _get_channel_slug(env_var: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(env_var)
    if value:
        return clean_slug_value(value)
    return default


ARENA_CHANNEL_SLUG = _get_channel_slug("ARENA_CHANNEL_SLUG", "framer")
ARENA_SOURCE_CHANNEL_SLUG = _get_channel_slug("ARENA_SOURCE_CHANNEL_SLUG")
ARENA_MAPPING_BLOCK_TITLE = "ARENA_TV_MAPPINGS"
ARENA_SOURCE_CHANNEL_BLOCK_TITLE = "ARENA_SOURCE_CHANNEL_SLUG"
ARENA_SOURCE_CHANNEL_PLACEHOLDER = "your-source-channel-slug"


def get_arena_token() -> str:
    """Get Are.na API token from environment variable"""
    token = os.getenv("ARENA_TOKEN")
    if not token:
        logger.error("ARENA_TOKEN environment variable not set")
        sys.exit(1)
    # Clean the token (strip whitespace and quotes)
    token = clean_slug_value(token)
    if not token:
        logger.error(
            "ARENA_TOKEN environment variable is empty after cleaning (may be just whitespace or quotes)"
        )
        sys.exit(1)
    return token


def get_auth_headers(token: str) -> Dict[str, str]:
    """Return authorization headers for Are.na API"""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def parse_error_response(response_text: str) -> str:
    """Parse Are.na API error response to extract meaningful message"""
    try:
        error_data = json.loads(response_text)
        error_msg = error_data.get("error", "Unknown error")
        details = error_data.get("details", {})
        detail_msg = details.get("message", "")
        if detail_msg:
            return f"{error_msg}: {detail_msg}"
        return error_msg
    except (json.JSONDecodeError, AttributeError):
        # Not JSON, return truncated text
        if len(response_text) > 200:
            return response_text[:200] + "..."
        return response_text


async def get_channel_id(slug: str, token: str) -> Optional[int]:
    """Get channel ID from slug"""
    try:
        headers = get_auth_headers(token)
        url = f"{ARENA_API_BASE}/channels/{slug}"

        logger.info(f"Fetching channel info for slug: {slug}")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        channel_data = response.json()
        channel_id = channel_data.get("id")
        if channel_id is None:
            logger.error("Channel response missing 'id' field")
            return None
        logger.info(f"Found channel: {channel_data.get('title')} (ID: {channel_id})")
        return channel_id

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get channel info: {e}")
        if hasattr(e, "response") and e.response:
            error_msg = parse_error_response(e.response.text)
            logger.error(f"Response: {e.response.status_code} - {error_msg}")
        return None


async def find_mapping_block(channel_id: int, token: str) -> Optional[Dict[str, Any]]:
    """Find existing mapping block in channel"""
    try:
        headers = get_auth_headers(token)
        url = f"{ARENA_API_BASE}/channels/{channel_id}/contents?per=100"

        logger.info(f"Searching for mapping block in channel {channel_id}...")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        blocks = response.json().get("data", [])
        for block in blocks:
            if (
                block.get("title") == ARENA_MAPPING_BLOCK_TITLE
                and block.get("type") == "Text"
            ):
                logger.info(f"Found existing mapping block: {block.get('id')}")
                return block

        logger.info("No existing mapping block found")
        return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to search for mapping block: {e}")
        return None


async def find_text_block_by_title(
    channel_id: int, token: str, title: str
) -> Optional[Dict[str, Any]]:
    """Find text block by title in channel"""
    try:
        headers = get_auth_headers(token)
        url = f"{ARENA_API_BASE}/channels/{channel_id}/contents?per=100"

        logger.debug(
            f"Searching for text block with title '{title}' in channel {channel_id}..."
        )
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        blocks = response.json().get("data", [])
        for block in blocks:
            if block.get("title") == title and block.get("type") == "Text":
                logger.info(f"Found text block '{title}': {block.get('id')}")
                return block

        logger.debug(f"No text block found with title '{title}'")
        return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to search for text block '{title}': {e}")
        return None


async def get_source_channel_slug_from_block(
    storage_channel_id: int, token: str, default_slug: Optional[str] = None
) -> Optional[str]:
    """Get source channel slug from text block, fallback to default"""
    block = await find_text_block_by_title(
        storage_channel_id, token, ARENA_SOURCE_CHANNEL_BLOCK_TITLE
    )

    if not block:
        if default_slug is None:
            logger.warning(
                f"No '{ARENA_SOURCE_CHANNEL_BLOCK_TITLE}' block found and no environment variable set"
            )
            return None
        logger.info(
            f"No '{ARENA_SOURCE_CHANNEL_BLOCK_TITLE}' block found, using environment variable: {default_slug}"
        )
        return default_slug

    try:
        # Extract slug from block content (Are.na v3 uses content.markdown)
        content_data = block.get("content", {})
        if not content_data:
            logger.warning(
                f"'{ARENA_SOURCE_CHANNEL_BLOCK_TITLE}' block has empty content, using environment variable: {default_slug}"
            )
            return default_slug

        block_value = content_data.get("markdown", "").strip()
        if not block_value:
            logger.warning(
                f"'{ARENA_SOURCE_CHANNEL_BLOCK_TITLE}' block has empty markdown content, using environment variable: {default_slug}"
            )
            return default_slug

        # The block should contain just the slug string
        slug = clean_slug_value(block_value)
        logger.info(f"Using source channel slug from Are.na block: {slug}")
        return slug

    except Exception as e:
        logger.error(
            f"Failed to parse '{ARENA_SOURCE_CHANNEL_BLOCK_TITLE}' block: {e}, using environment variable: {default_slug}"
        )
        return default_slug


async def load_mappings_from_arena(
    channel_id: int, token: str
) -> tuple[List[Dict[str, Any]], Optional[str]]:
    """Load mappings and source channel slug from Are.na block

    Returns:
        tuple: (mappings, source_channel_slug) where source_channel_slug may be None
    """
    mapping_block = await find_mapping_block(channel_id, token)

    if not mapping_block:
        logger.info("No mapping block found, returning empty list")
        return [], None

    try:
        # Extract mappings from block content (Are.na v3 uses content.markdown)
        content_data = mapping_block.get("content", {})
        if not content_data:
            logger.warning("Mapping block has empty content")
            return [], None

        block_value = content_data.get("markdown", "")
        if not block_value:
            logger.warning("Mapping block has empty markdown content")
            return [], None

        # Parse JSON from block value
        block_data = json.loads(block_value)
        mappings = block_data.get("mappings", [])
        source_channel_slug = block_data.get("source_channel_slug")

        logger.info(f"Loaded {len(mappings)} mappings from Are.na block")
        if source_channel_slug:
            logger.info(f"Source channel slug in mappings: {source_channel_slug}")
        else:
            logger.info("No source channel slug found in mappings (old format)")

        return mappings, source_channel_slug

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse mapping block JSON: {e}")
        logger.error(f"Block value: {block_value[:200]}...")
        return [], None
    except Exception as e:
        logger.error(f"Failed to load mappings from block: {e}")
        return [], None


async def save_mappings_to_arena(
    mappings: List[Dict[str, Any]],
    channel_id: int,
    token: str,
    source_channel_slug: str = None,
) -> bool:
    """Save mappings to Are.na block (create or update)"""
    try:
        headers = get_auth_headers(token)

        # Format mappings with metadata
        block_data = {
            "format": "Simple mapping array",
            "schema": [
                "arena_block_id: Arena block ID (integer)",
                "arena_title: Title of Arena block (string)",
                "tv_id: Samsung TV artwork ID (string)",
            ],
            "timestamp": time.time(),
            "mappings": mappings,
            "total_mappings": len(mappings),
        }

        # Add source channel slug if provided
        if source_channel_slug:
            block_data["source_channel_slug"] = source_channel_slug

        json_content = json.dumps(block_data, indent=2, ensure_ascii=False)

        # Check if mapping block exists
        existing_block = await find_mapping_block(channel_id, token)

        if existing_block:
            # Update existing block
            block_id = existing_block.get("id")
            url = f"{ARENA_API_BASE}/blocks/{block_id}"

            payload = {"title": ARENA_MAPPING_BLOCK_TITLE, "content": json_content}

            logger.info(f"Updating existing mapping block {block_id}...")
            response = requests.put(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()

            logger.info(f"✓ Updated mapping block {block_id}")
            return True
        else:
            # Create new block
            url = f"{ARENA_API_BASE}/blocks"

            payload = {
                "title": ARENA_MAPPING_BLOCK_TITLE,
                "value": json_content,
                "channel_ids": [channel_id],
            }

            logger.info(f"Creating new mapping block in channel {channel_id}...")
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()

            block_data = response.json()
            block_id = block_data.get("id")
            logger.info(f"✓ Created mapping block {block_id}")
            return True

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to save mappings to Are.na: {e}")
        if hasattr(e, "response") and e.response:
            error_msg = parse_error_response(e.response.text)
            logger.error(f"Response: {e.response.status_code} - {error_msg}")
        return False
    except Exception as e:
        logger.error(f"Failed to save mappings: {e}")
        return False


def find_mapping_by_arena_id(arena_block_id, mappings):
    """Find mapping by Arena block ID"""
    for mapping in mappings:
        if mapping.get("arena_block_id") == arena_block_id:
            return mapping
    return None


def find_mapping_by_tv_id(tv_id, mappings):
    """Find mapping by TV ID"""
    for mapping in mappings:
        if mapping.get("tv_id") == tv_id:
            return mapping
    return None


async def create_channel(slug: str, title: str, token: str) -> Optional[int]:
    """Create a new Are.na channel if it doesn't exist"""
    try:
        # First check if channel already exists
        existing_id = await get_channel_id(slug, token)
        if existing_id:
            logger.info(f"Channel '{slug}' already exists (ID: {existing_id})")
            return existing_id

        # Create new channel
        headers = get_auth_headers(token)
        url = f"{ARENA_API_BASE}/channels"

        payload = {
            "title": title,
            "slug": slug,
            "visibility": "private",
        }

        logger.info(f"Creating channel '{slug}' with title '{title}'...")
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        channel_data = response.json()
        channel_id = channel_data.get("id")
        if channel_id is None:
            logger.error("Channel creation response missing 'id' field")
            return None

        logger.info(f"✓ Created channel '{slug}' (ID: {channel_id})")
        return channel_id

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to create channel '{slug}': {e}")
        if hasattr(e, "response") and e.response:
            error_msg = parse_error_response(e.response.text)
            logger.error(f"Response: {e.response.status_code} - {error_msg}")
        return None
    except Exception as e:
        logger.error(f"Failed to create channel: {e}")
        return None


async def create_or_update_text_block(
    channel_id: int, title: str, content: str, token: str
) -> bool:
    """Create or update a text block in a channel"""
    try:
        headers = get_auth_headers(token)

        # Check if block already exists
        existing_block = await find_text_block_by_title(channel_id, token, title)

        if existing_block:
            # Update existing block
            block_id = existing_block.get("id")
            url = f"{ARENA_API_BASE}/blocks/{block_id}"

            payload = {"title": title, "content": content}

            logger.info(f"Updating text block '{title}' (ID: {block_id})...")
            response = requests.put(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()

            logger.info(f"✓ Updated text block '{title}'")
            return True
        else:
            # Create new block
            url = f"{ARENA_API_BASE}/blocks"

            payload = {
                "title": title,
                "value": content,
                "channel_ids": [channel_id],
            }

            logger.info(f"Creating text block '{title}' in channel {channel_id}...")
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()

            block_data = response.json()
            block_id = block_data.get("id")
            logger.info(f"✓ Created text block '{title}' (ID: {block_id})")
            return True

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to create/update text block '{title}': {e}")
        if hasattr(e, "response") and e.response:
            error_msg = parse_error_response(e.response.text)
            logger.error(f"Response: {e.response.status_code} - {error_msg}")
        return False
    except Exception as e:
        logger.error(f"Failed to create/update text block: {e}")
        return False


async def ensure_empty_mapping_block(
    channel_id: int, source_channel_slug: str, token: str
) -> bool:
    """Ensure mapping block exists with empty mappings and correct source channel slug"""
    # Warn if using placeholder
    if source_channel_slug == ARENA_SOURCE_CHANNEL_PLACEHOLDER:
        logger.warning(
            f"Creating mapping block with placeholder source channel slug: '{source_channel_slug}'"
        )

    # Load existing mappings (if any)
    mappings, _ = await load_mappings_from_arena(channel_id, token)

    # Save mappings (empty or existing) with current source channel slug
    # This will create block if it doesn't exist
    success = await save_mappings_to_arena(
        mappings, channel_id, token, source_channel_slug
    )

    if success:
        if not mappings:
            logger.info(
                f"✓ Created/verified empty mapping block for source channel '{source_channel_slug}'"
            )
        else:
            logger.info(f"✓ Verified existing mapping block ({len(mappings)} mappings)")
    else:
        logger.error("Failed to create/verify mapping block")

    return success


async def init_arena_channels() -> bool:
    """Initialize Are.na channels and blocks for the sync system"""
    logger.info("🚀 Initializing Are.na channels and blocks...")

    # Get Are.na token
    token = get_arena_token()

    # Get configuration
    storage_channel_slug = ARENA_CHANNEL_SLUG
    source_channel_slug = ARENA_SOURCE_CHANNEL_SLUG
    using_placeholder = False

    # Use placeholder if source channel slug is not set
    if not source_channel_slug:
        source_channel_slug = ARENA_SOURCE_CHANNEL_PLACEHOLDER
        using_placeholder = True
        logger.warning(
            "ARENA_SOURCE_CHANNEL_SLUG not set, using placeholder value. "
            "Please update the 'ARENA_SOURCE_CHANNEL_SLUG' text block in the storage channel "
            "with your actual source channel slug."
        )
    elif source_channel_slug == ARENA_SOURCE_CHANNEL_PLACEHOLDER:
        using_placeholder = True
        logger.warning(
            "ARENA_SOURCE_CHANNEL_SLUG is set to placeholder value. "
            "Please update it with your actual source channel slug or "
            f"update the '{ARENA_SOURCE_CHANNEL_BLOCK_TITLE}' text block in the storage channel."
        )

    logger.info(f"Storage Channel Slug: {storage_channel_slug}")
    logger.info(f"Source Channel Slug: {source_channel_slug}")
    logger.info("=" * 50)

    # 1. Create/verify storage channel
    logger.info("Step 1: Creating/verifying storage channel...")
    storage_channel_id = await create_channel(
        storage_channel_slug, f"Framer TV Sync (Storage)", token
    )
    if not storage_channel_id:
        logger.error("Failed to create/verify storage channel")
        return False

    # 2. Verify source channel exists (but don't create it - user should create it with their images)
    logger.info("Step 2: Verifying source channel exists...")
    source_channel_id = await get_channel_id(source_channel_slug, token)
    if not source_channel_id:
        logger.warning(
            f"⚠️ Source channel '{source_channel_slug}' doesn't exist yet.\n"
            f"   Please create it at: https://are.na/new\n"
            f"   You'll add your images to this channel later."
        )
        # Continue anyway - user can create it later
        source_channel_exists = False
    else:
        source_channel_exists = True
        logger.info(f"✓ Source channel exists (ID: {source_channel_id})")

    # 3. Create source channel slug block
    logger.info("Step 3: Creating source channel configuration block...")
    if not await create_or_update_text_block(
        storage_channel_id, ARENA_SOURCE_CHANNEL_BLOCK_TITLE, source_channel_slug, token
    ):
        logger.error("Failed to create source channel configuration block")
        return False

    # 4. Create empty mapping block
    logger.info("Step 4: Creating empty mapping block...")
    if not await ensure_empty_mapping_block(
        storage_channel_id, source_channel_slug, token
    ):
        logger.error("Failed to create empty mapping block")
        return False

    # Success!
    logger.info("=" * 50)
    logger.info("✅ Initialization complete!")

    if using_placeholder:
        logger.warning("")
        logger.warning("⚠️  IMPORTANT: Using placeholder source channel slug!")
        logger.warning(f"   Current value: '{source_channel_slug}'")
        logger.warning("   Before running sync, update the text block titled")
        logger.warning(
            f"   '{ARENA_SOURCE_CHANNEL_BLOCK_TITLE}' in the storage channel"
        )
        logger.warning(f"   with your actual source channel slug.")
        logger.warning("")

    logger.info("")
    logger.info(
        f"Storage Channel (configuration): https://are.na/channel/{storage_channel_slug}"
    )
    if source_channel_exists:
        logger.info(
            f"Source Channel (add your images here): https://are.na/channel/{source_channel_slug}"
        )
    else:
        logger.info(
            f"Source Channel (to be created): https://are.na/channel/{source_channel_slug}"
        )
    logger.info("")
    logger.info("Next steps:")
    logger.info(
        f"1. {'Add images to your source channel' if source_channel_exists else 'Create your source channel and add images'}"
    )
    logger.info(f"   URL: https://are.na/channel/{source_channel_slug}")
    logger.info("2. Run the sync script:")
    logger.info(f"   python sync_arena_to_tv.py")
    logger.info("")
    logger.info("Configuration details:")
    logger.info(f"   - Storage channel slug: {storage_channel_slug}")
    logger.info(f"   - Source channel slug: {source_channel_slug}")
    logger.info(f"   - Both stored in: https://are.na/channel/{storage_channel_slug}")

    return True


def add_mapping(arena_block_id, arena_title, tv_id, mappings):
    """Add a new Arena-TV mapping"""
    # Check for duplicates
    existing = find_mapping_by_arena_id(arena_block_id, mappings)
    if existing:
        logger.warning(f"Duplicate mapping found for Arena block {arena_block_id}")
        return False, mappings

    new_mapping = {
        "arena_block_id": arena_block_id,
        "arena_title": arena_title,
        "tv_id": tv_id,
    }

    mappings.append(new_mapping)
    return True, mappings


def is_uploaded(arena_block_id, mappings):
    """Check if Arena block is already uploaded to TV"""
    return find_mapping_by_arena_id(arena_block_id, mappings) is not None


async def load_arena_blocks_from_channel(
    channel_id: int, token: str
) -> List[Dict[str, Any]]:
    """Load Arena blocks from channel (excluding mapping block)"""
    try:
        headers = get_auth_headers(token)
        url = f"{ARENA_API_BASE}/channels/{channel_id}/contents?per=100"

        logger.info(f"Fetching blocks from Are.na channel {channel_id}...")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        blocks_data = response.json()
        all_blocks = blocks_data.get("data", [])

        # Check pagination metadata
        meta = blocks_data.get("meta", {})
        if meta.get("has_more_pages", False):
            logger.warning(
                f"Channel has more than {len(all_blocks)} blocks. "
                f"Only fetching first 100 blocks (page {meta.get('current_page', 1)} of {meta.get('total_pages', '?')}). "
                "Consider reducing the number of images in your source channel."
            )

        # Filter out mapping block and non-image blocks
        image_blocks = []
        for block in all_blocks:
            # Skip mapping block
            if (
                block.get("title") == ARENA_MAPPING_BLOCK_TITLE
                and block.get("type") == "Text"
            ):
                continue

            # Only include image blocks
            if block.get("type") == "Image":
                image_blocks.append(block)

        logger.info(f"Found {len(image_blocks)} image blocks in channel")
        return image_blocks

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch Arena blocks: {e}")
        if hasattr(e, "response") and e.response:
            error_msg = parse_error_response(e.response.text)
            logger.error(f"Response: {e.response.status_code} - {error_msg}")
        return []
    except Exception as e:
        logger.error(f"Failed to load Arena blocks: {e}")
        return []


def get_unuploaded_blocks(arena_blocks, mappings):
    """Get list of Arena blocks that haven't been uploaded yet"""
    unuploaded = []
    for block in arena_blocks:
        if block.get("type") != "Image":
            continue

        block_id = block.get("id")
        if not is_uploaded(block_id, mappings):
            unuploaded.append(block)

    return unuploaded


async def get_tv_content_ids(tv_ip):
    """Fetch all content_id values from TV artwork list"""
    try:
        tv = SamsungTVAsyncArt(host=tv_ip)
        available_art = await tv.available()
        content_ids = [
            art.get("content_id") for art in available_art if art.get("content_id")
        ]
        logger.info(f"Fetched {len(content_ids)} content IDs from TV")
        return content_ids
    except Exception as e:
        logger.error(f"Failed to fetch TV artwork: {e}")
        return None


def get_unuploaded_blocks_with_validation(arena_blocks, mappings, tv_content_ids):
    """Get list of Arena blocks that need upload (missing or invalid mapping)"""
    unuploaded = []
    invalid_mappings = []

    for block in arena_blocks:
        if block.get("type") != "Image":
            continue

        block_id = block.get("id")
        mapping = find_mapping_by_arena_id(block_id, mappings)

        if not mapping:
            # No mapping exists → needs upload
            unuploaded.append(block)
        else:
            # Mapping exists, check if TV ID still on TV
            tv_id = mapping.get("tv_id")
            if tv_id not in tv_content_ids:
                # Invalid mapping → needs re-upload
                invalid_mappings.append(mapping)
                unuploaded.append(block)

    if invalid_mappings:
        logger.warning(
            f"Found {len(invalid_mappings)} invalid mappings (artwork not on TV)"
        )
        for mapping in invalid_mappings:
            logger.warning(
                f"  - Arena {mapping['arena_block_id']} → TV {mapping['tv_id']}"
            )

    return unuploaded


def get_image_url(block):
    """Get the best available image URL from Arena block"""
    image_data = block.get("image", {})

    def best_version_url(version_dict):
        """Get best URL from version dict (prefer src_2x for higher resolution)"""
        if not version_dict:
            return None
        # Prefer 2x version for higher TV resolution
        src_2x = version_dict.get("src_2x")
        if src_2x:
            return src_2x
        return version_dict.get("src")

    # Try original source first (highest quality)
    original_url = image_data.get("src")
    if original_url:
        # Check if it's a CloudFront URL that might have WAF
        if "cloudfront.net" in original_url:
            # Try large variant instead (via images.are.na)
            large_url = best_version_url(image_data.get("large"))
            if large_url:
                logger.info(f"Using large variant URL (bypass CloudFront WAF)")
                return large_url
        return original_url

    # Fallback to large variant (with 2x preference)
    large_url = best_version_url(image_data.get("large"))
    if large_url:
        return large_url

    # Fallback to medium
    medium_url = best_version_url(image_data.get("medium"))
    if medium_url:
        return medium_url

    # Fallback to small
    small_url = best_version_url(image_data.get("small"))
    if small_url:
        return small_url

    # Fallback to square (sometimes available)
    square_url = best_version_url(image_data.get("square"))
    if square_url:
        return square_url

    return None


def download_image(image_url):
    """Download image from URL with proper headers to bypass WAF"""
    try:
        logger.info(f"Downloading image from {image_url}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.are.na/",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        }

        response = requests.get(image_url, headers=headers, timeout=30)
        response.raise_for_status()

        # Check if we got actual image data
        content_type = response.headers.get("content-type", "")
        if "image" not in content_type and content_type != "application/octet-stream":
            logger.warning(f"Unexpected content type: {content_type}")
            # Might still be okay if it's an image with wrong header

        return response.content

    except requests.RequestException as e:
        logger.error(f"Download failed: {e}")
        if hasattr(e, "response") and e.response:
            error_msg = parse_error_response(e.response.text)
            logger.error(f"HTTP {e.response.status_code}: {error_msg}")
        return None


def process_image_for_tv(image_data):
    """Process image for Samsung Frame TV (3840×2160, 16:9)"""
    try:
        from PIL import Image
        from io import BytesIO

        # Open image
        img = Image.open(BytesIO(image_data))

        # Calculate target aspect ratio (16:9)
        target_ratio = 3840 / 2160  # 16:9
        current_ratio = img.width / img.height

        # Crop to 16:9 if needed
        if abs(current_ratio - target_ratio) > 0.01:
            if current_ratio > target_ratio:
                # Too wide - crop width
                new_width = int(img.height * target_ratio)
                left = (img.width - new_width) // 2
                img = img.crop((left, 0, left + new_width, img.height))
            else:
                # Too tall - crop height
                new_height = int(img.width / target_ratio)
                top = (img.height - new_height) // 2
                img = img.crop((0, top, img.width, top + new_height))

        # Resize to exact resolution
        img = img.resize((3840, 2160), Image.LANCZOS)

        # Convert back to bytes
        output = BytesIO()
        img.save(output, format="JPEG", quality=95, optimize=True)
        return output.getvalue()

    except Exception as e:
        logger.error(f"Image processing failed: {e}")
        return None


async def upload_to_tv(tv_ip, image_data, matte="none"):
    """Upload image to Samsung Frame TV"""
    try:
        logger.info(f"Connecting to TV at {tv_ip}")
        tv = SamsungTVAsyncArt(host=tv_ip)

        logger.info("Uploading to Art Mode...")
        upload_result = await tv.upload(
            image_data, file_type="JPEG", matte=matte, timeout=60
        )

        if upload_result:
            logger.info(f"✅ Upload successful! Artwork ID: {upload_result}")
            return upload_result
        else:
            logger.error("❌ Upload failed: No artwork ID returned")
            return None

    except ConnectionFailure as e:
        logger.error(f"TV connection failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return None


async def delete_tv_artwork(tv_ip, content_ids):
    """Delete artwork from Samsung Frame TV"""
    try:
        if not content_ids:
            logger.info("No artwork to delete")
            return True

        logger.info(f"Connecting to TV at {tv_ip} for deletion")
        tv = SamsungTVAsyncArt(host=tv_ip)

        logger.info(f"Deleting {len(content_ids)} artwork(s) from TV...")
        await tv.delete_list(content_ids)

        logger.info(f"✅ Successfully deleted {len(content_ids)} artwork(s)")
        return True

    except ConnectionFailure as e:
        logger.error(f"TV connection failed during deletion: {e}")
        return False
    except Exception as e:
        logger.error(f"Deletion failed: {e}")
        return False


async def sync_arena_to_tv():
    """Main sync function - stateless, uses Are.na for storage"""
    # Get TV IP from environment
    tv_ip = os.getenv("SMARTTHING_TV_IP_ADDRESS")
    if not tv_ip:
        logger.error("SMARTTHING_TV_IP_ADDRESS environment variable not set")
        return False
    # Clean the IP address (strip whitespace and quotes)
    tv_ip = clean_slug_value(tv_ip)
    if not tv_ip:
        logger.error(
            "SMARTTHING_TV_IP_ADDRESS environment variable is empty after cleaning (may be just whitespace or quotes)"
        )
        return False

    # Get Are.na token
    token = get_arena_token()

    # Get storage channel ID (for mappings)
    storage_channel_id = await get_channel_id(ARENA_CHANNEL_SLUG, token)
    if not storage_channel_id:
        logger.error(f"Could not get storage channel ID for slug: {ARENA_CHANNEL_SLUG}")
        return False

    # Get source channel slug from Are.na block (fallback to environment variable)
    actual_source_channel_slug = await get_source_channel_slug_from_block(
        storage_channel_id, token, ARENA_SOURCE_CHANNEL_SLUG
    )

    # Validate source channel configuration
    if actual_source_channel_slug is None:
        logger.error(
            "Source channel not configured. "
            "Set ARENA_SOURCE_CHANNEL_SLUG environment variable or "
            f"create '{ARENA_SOURCE_CHANNEL_BLOCK_TITLE}' text block in storage channel."
        )
        return False

    # Check for placeholder value
    if actual_source_channel_slug == ARENA_SOURCE_CHANNEL_PLACEHOLDER:
        logger.error(
            "Source channel slug is still using the placeholder value. "
            f"Please update the '{ARENA_SOURCE_CHANNEL_BLOCK_TITLE}' text block "
            f"in the storage channel with your actual source channel slug."
        )
        return False

    # Get source channel ID (for image blocks)
    if actual_source_channel_slug != ARENA_CHANNEL_SLUG:
        source_channel_id = await get_channel_id(actual_source_channel_slug, token)
        if not source_channel_id:
            logger.error(
                f"Could not get source channel ID for slug: {actual_source_channel_slug}"
            )
            return False
    else:
        source_channel_id = storage_channel_id

    logger.info("🎨 Arena → Samsung TV Sync (Stateless)")
    logger.info(f"   TV: {tv_ip}")
    logger.info(f"   Storage Channel: {ARENA_CHANNEL_SLUG} (ID: {storage_channel_id})")
    if actual_source_channel_slug != ARENA_CHANNEL_SLUG:
        logger.info(
            f"   Source Channel: {actual_source_channel_slug} (ID: {source_channel_id})"
        )
    logger.info("=" * 50)

    # Load mappings and stored source channel slug from Are.na block
    mappings, stored_source_channel_slug = await load_mappings_from_arena(
        storage_channel_id, token
    )
    logger.info(f"📁 Current mappings: {len(mappings)}")

    # Fetch TV content IDs early (needed for both validation and potential deletion)
    tv_content_ids = await get_tv_content_ids(tv_ip)

    # Check if source channel has changed
    source_channel_changed = False
    if stored_source_channel_slug is None:
        logger.warning("⚠️ No source channel slug stored in mappings (old format)")
        source_channel_changed = True
    elif stored_source_channel_slug != actual_source_channel_slug:
        logger.warning(
            f"⚠️ Source channel changed: {stored_source_channel_slug} → {actual_source_channel_slug}"
        )
        source_channel_changed = True

    # Handle source channel change
    if source_channel_changed:
        logger.warning("🔄 Source channel changed, cleaning up...")

        # Delete TV artwork if TV is reachable and we have mappings
        if mappings and tv_content_ids is not None:
            # Extract TV IDs from mappings
            tv_ids_to_delete = [m["tv_id"] for m in mappings if "tv_id" in m]
            if tv_ids_to_delete:
                logger.info(
                    f"🗑️  Attempting to delete {len(tv_ids_to_delete)} old artwork(s) from TV..."
                )
                delete_success = await delete_tv_artwork(tv_ip, tv_ids_to_delete)
                if not delete_success:
                    logger.error(
                        "❌ Failed to delete old TV artwork (artwork may remain on TV)"
                    )
        elif mappings:
            logger.warning(
                "📺 TV unreachable, cannot delete old artwork (artwork will remain on TV)"
            )

        # Clear all mappings
        mappings = []
        logger.info("🗑️  Cleared all mappings for new source channel")

        # Save empty mappings with new source channel slug
        if not await save_mappings_to_arena(
            mappings, storage_channel_id, token, actual_source_channel_slug
        ):
            logger.error("Failed to save cleared mappings to Are.na")
            return False

        logger.info("✅ Cleanup complete, starting fresh with new source channel")

    # Validate mappings with TV (if TV is reachable)
    if tv_content_ids is None:
        logger.warning("📺 TV connection failed - skipping mapping validation")
        # Keep all mappings since we can't validate
        pass
    else:
        logger.info(f"📺 TV artwork count: {len(tv_content_ids)}")

        # Filter out invalid mappings (where tv_id not on TV)
        valid_mappings = []
        invalid_mappings = []
        for mapping in mappings:
            tv_id = mapping.get("tv_id")
            if tv_id in tv_content_ids:
                valid_mappings.append(mapping)
            else:
                invalid_mappings.append(mapping)

        if invalid_mappings:
            logger.warning(
                f"⚠️ Found {len(invalid_mappings)} invalid mappings (artwork not on TV):"
            )
            for mapping in invalid_mappings:
                logger.warning(
                    f"   - Arena {mapping['arena_block_id']} → TV {mapping['tv_id']}"
                )
            # Remove invalid mappings
            mappings = valid_mappings
            logger.info(f"✓ Removed invalid mappings, {len(mappings)} remaining")
            # Save updated mappings to Are.na with current source channel slug
            if not await save_mappings_to_arena(
                mappings, storage_channel_id, token, actual_source_channel_slug
            ):
                logger.error("Failed to save updated mappings to Are.na")

    # Load Arena blocks from Are.na channel
    arena_blocks = await load_arena_blocks_from_channel(source_channel_id, token)
    logger.info(f"📚 Arena blocks: {len(arena_blocks)}")

    # Detect and handle blocks deleted from Are.na
    current_block_ids = {block["id"] for block in arena_blocks}
    deleted_mappings = [
        mapping
        for mapping in mappings
        if mapping["arena_block_id"] not in current_block_ids
    ]

    if deleted_mappings:
        logger.info(
            f"🗑️  Found {len(deleted_mappings)} blocks deleted from Are.na channel"
        )

        # Extract TV IDs for deletion
        tv_ids_to_delete = [m["tv_id"] for m in deleted_mappings if "tv_id" in m]

        if tv_ids_to_delete:
            if tv_content_ids is not None:
                # TV is reachable, attempt to delete artwork
                logger.info(
                    f"🗑️  Attempting to delete {len(tv_ids_to_delete)} artwork(s) from TV..."
                )
                delete_success = await delete_tv_artwork(tv_ip, tv_ids_to_delete)
                if not delete_success:
                    logger.error(
                        "❌ Failed to delete TV artwork (artwork may remain on TV)"
                    )
                else:
                    logger.info(
                        f"✅ Successfully deleted {len(tv_ids_to_delete)} artwork(s) from TV"
                    )
            else:
                logger.warning(
                    "📺 TV unreachable, cannot delete artwork (artwork will remain on TV)"
                )

        # Remove deleted mappings
        mappings = [m for m in mappings if m["arena_block_id"] in current_block_ids]
        logger.info(f"🗑️  Removed {len(deleted_mappings)} deleted mappings")

        # Save updated mappings to Are.na
        if not await save_mappings_to_arena(
            mappings, storage_channel_id, token, actual_source_channel_slug
        ):
            logger.error("Failed to save mappings after block deletion cleanup")

    # Get unuploaded blocks (using validated mappings)
    unuploaded = get_unuploaded_blocks(arena_blocks, mappings)
    logger.info(f"📤 New blocks to upload: {len(unuploaded)}")

    if not unuploaded:
        logger.info("✅ All Arena blocks already uploaded to TV")
        return True

    # Process each unuploaded block
    for i, block in enumerate(unuploaded, 1):
        logger.info(f"\n📦 Processing block {i}/{len(unuploaded)}")
        logger.info(f"   Arena ID: {block['id']}")
        logger.info(f"   Title: {block['title'][:50]}...")

        # Get image URL (with fallback for CloudFront WAF)
        image_url = get_image_url(block)
        if not image_url:
            logger.warning(f"⚠️ No image URL for block {block['id']}, skipping")
            continue

        # Download image
        image_data = download_image(image_url)
        if not image_data:
            logger.error(f"❌ Download failed for block {block['id']}, skipping")
            continue

        # Process image for TV
        processed_data = process_image_for_tv(image_data)
        if not processed_data:
            logger.error(f"❌ Processing failed for block {block['id']}, skipping")
            continue

        logger.info("✓ Image processed: 3840×2160, 16:9 aspect ratio")

        # Upload to TV
        tv_id = await upload_to_tv(tv_ip, processed_data, matte="none")
        if not tv_id:
            logger.error(f"❌ Upload failed for block {block['id']}")
            continue

        # Add mapping
        success, mappings = add_mapping(block["id"], block["title"], tv_id, mappings)
        if success:
            logger.info(
                f"✅ Successfully uploaded: {block['title'][:40]}... → TV {tv_id}"
            )

            # Save mappings to Are.na after each successful upload with current source channel slug
            if not await save_mappings_to_arena(
                mappings, storage_channel_id, token, actual_source_channel_slug
            ):
                logger.error("Failed to save mappings to Are.na, but upload succeeded")
        else:
            logger.warning(f"⚠️ Could not create mapping for block {block['id']}")

    logger.info(f"\n🎉 Sync completed!")
    logger.info(f"   Total Arena blocks: {len(arena_blocks)}")
    logger.info(f"   Already uploaded: {len(arena_blocks) - len(unuploaded)}")
    logger.info(
        f"   Newly uploaded: {len([m for m in mappings if m.get('arena_block_id') in [b['id'] for b in unuploaded]])}"
    )

    return True


async def run_sync_loop(interval_seconds: int = 300):
    """Run sync in a loop with specified interval"""
    logger.info(f"🔄 Starting sync loop (interval: {interval_seconds}s)")

    while True:
        try:
            logger.info("\n" + "=" * 60)
            logger.info(
                f"🕐 Sync cycle started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            success = await sync_arena_to_tv()

            if not success:
                logger.error("Sync cycle failed")

            logger.info(f"⏳ Waiting {interval_seconds} seconds before next cycle...")
            await asyncio.sleep(interval_seconds)

        except KeyboardInterrupt:
            logger.info("\n🛑 Sync loop interrupted by user")
            break
        except Exception as e:
            logger.error(f"Unexpected error in sync loop: {e}")
            logger.info(f"⏳ Waiting {interval_seconds} seconds before retry...")
            await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    import argparse

    # Safely parse SYNC_INTERVAL environment variable
    sync_interval_env = os.getenv("SYNC_INTERVAL")
    sync_interval_default = 300
    if sync_interval_env:
        # Clean the value (strip whitespace and quotes)
        sync_interval_env = clean_slug_value(sync_interval_env)
        try:
            sync_interval_default = int(sync_interval_env)
        except ValueError:
            logger.warning(
                f"Invalid SYNC_INTERVAL value '{sync_interval_env}', using default {sync_interval_default}"
            )

    # Safely parse ARENA_CHANNEL_SLUG environment variable
    channel_slug_env = os.getenv("ARENA_CHANNEL_SLUG")
    channel_slug_default = "framer"
    if channel_slug_env:
        channel_slug_default = clean_slug_value(channel_slug_env)

    parser = argparse.ArgumentParser(
        description="Sync Are.na images to Samsung Frame TV"
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize Are.na channels and blocks (does not run sync)",
    )
    parser.add_argument("--once", action="store_true", help="Run sync once and exit")
    parser.add_argument(
        "--interval",
        type=int,
        default=sync_interval_default,
        help="Sync interval in seconds (default: 300 or SYNC_INTERVAL env var)",
    )
    parser.add_argument(
        "--channel",
        type=str,
        default=channel_slug_default,
        help='Are.na channel slug (default: ARENA_CHANNEL_SLUG env var or "framer")',
    )

    args = parser.parse_args()

    # Handle INIT_MODE environment variable (unless overridden by CLI --init flag)
    if not args.init:
        init_mode_env = os.getenv("INIT_MODE", "")
        if init_mode_env:
            init_mode_env = clean_slug_value(init_mode_env).lower()
            if init_mode_env in ("true", "1", "yes"):
                args.init = True
                logger.info(
                    "INIT_MODE environment variable enabled initialization mode"
                )

    # Handle SYNC_ONCE environment variable (unless overridden by CLI --once flag)
    if not args.once:
        sync_once_env = os.getenv("SYNC_ONCE", "")
        if sync_once_env:
            sync_once_env = clean_slug_value(sync_once_env).lower()
            if sync_once_env in ("true", "1", "yes"):
                args.once = True
                logger.info("SYNC_ONCE environment variable enabled single sync mode")

    # Override channel slug if provided
    if args.channel:
        ARENA_CHANNEL_SLUG = clean_slug_value(args.channel)

    try:
        if args.init:
            logger.info("🚀 Running initialization mode")
            success = asyncio.run(init_arena_channels())
            sys.exit(0 if success else 1)
        elif args.once:
            logger.info("🚀 Running single sync cycle")
            success = asyncio.run(sync_arena_to_tv())
            sys.exit(0 if success else 1)
        else:
            logger.info(f"🔄 Starting continuous sync (interval: {args.interval}s)")
            asyncio.run(run_sync_loop(args.interval))
            sys.exit(0)

    except KeyboardInterrupt:
        logger.info("\n🛑 Sync interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
