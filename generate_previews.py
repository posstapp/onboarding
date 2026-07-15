#!/usr/bin/env python3
"""
generate_previews.py — Batch generate style gallery preview images
Generates 29 preview groups × 9 artistic styles = 261 images
Uses GPT Image 2 Medium quality, uploads to R2

Run on server: python3 /opt/posst/generate_previews.py

Resumes from where it left off — checks R2 for existing images before generating.
"""

import os
import sys
import json
import time
import base64
import requests
from preview_group_mapping import PREVIEW_GROUPS, ARTISTIC_STYLES

# ── Config ────────────────────────────────────────────────
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
R2_UPLOAD_URL = 'http://127.0.0.1:5679/upload'
R2_PUBLIC_BASE = 'https://pub-f5f1d08da66048808d14f48cb78ebb36.r2.dev'
MODEL = 'gpt-image-2'
QUALITY = 'medium'
SIZE = '1024x1024'
SLEEP_BETWEEN = 3  # seconds between API calls (rate limit safety)

if not OPENAI_API_KEY:
    print('ERROR: OPENAI_API_KEY not set. Source .env first:')
    print('  export $(grep OPENAI_API_KEY /opt/posst/oauth/.env)')
    sys.exit(1)


def image_exists_on_r2(group_slug, style_slug):
    """Check if the preview image already exists on R2."""
    url = f'{R2_PUBLIC_BASE}/style_previews/{group_slug}/{style_slug}.jpg'
    try:
        resp = requests.head(url, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def generate_image(prompt):
    """Call OpenAI GPT Image 2 API and return base64 image bytes."""
    resp = requests.post(
        'https://api.openai.com/v1/images/generations',
        headers={
            'Authorization': f'Bearer {OPENAI_API_KEY}',
            'Content-Type': 'application/json',
        },
        json={
            'model': MODEL,
            'prompt': prompt,
            'quality': QUALITY,
            'size': SIZE,
            'n': 1,
        },
        timeout=120,
    )
    if resp.status_code != 200:
        raise Exception(f'OpenAI API error {resp.status_code}: {resp.text[:300]}')

    data = resp.json()
    b64 = data['data'][0].get('b64_json', '')
    if not b64:
        raise Exception('No b64_json in response')
    return b64


def upload_to_r2(b64_data, filename):
    """Upload base64 image to R2 via the upload service."""
    resp = requests.post(
        R2_UPLOAD_URL,
        json={
            'filename': filename,
            'image_b64': b64_data,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise Exception(f'R2 upload error {resp.status_code}: {resp.text[:200]}')
    return f'{R2_PUBLIC_BASE}/{filename}'


def build_prompt(scene, style_slug, style_label, style_prefix):
    """Combine scene description with artistic style prefix."""
    if style_slug == 'photorealistic' or not style_prefix:
        return scene
    return f'{style_prefix} {scene}'


def main():
    total = len(PREVIEW_GROUPS) * len(ARTISTIC_STYLES)
    print(f'=== Style Gallery Preview Generator ===')
    print(f'Model: {MODEL} | Quality: {QUALITY} | Size: {SIZE}')
    print(f'Total images: {total} ({len(PREVIEW_GROUPS)} groups × {len(ARTISTIC_STYLES)} styles)')
    print()

    # Check which images already exist
    existing = 0
    to_generate = []
    for group_slug, group in PREVIEW_GROUPS.items():
        for style_slug, style in ARTISTIC_STYLES.items():
            if image_exists_on_r2(group_slug, style_slug):
                existing += 1
            else:
                to_generate.append((group_slug, group, style_slug, style))

    print(f'Already on R2: {existing}')
    print(f'To generate: {len(to_generate)}')
    if not to_generate:
        print('All images already exist. Nothing to do!')
        return

    print(f'Estimated cost: ~${len(to_generate) * 0.05:.2f}')
    print(f'Estimated time: ~{len(to_generate) * (SLEEP_BETWEEN + 5) // 60} minutes')
    print()

    # Confirm
    if '--yes' not in sys.argv:
        answer = input(f'Generate {len(to_generate)} images? [y/N] ')
        if answer.lower() != 'y':
            print('Cancelled.')
            return

    # Generate
    success = 0
    failed = 0
    for i, (group_slug, group, style_slug, style) in enumerate(to_generate, 1):
        label = f'[{i}/{len(to_generate)}]'
        prompt = build_prompt(
            group['scene'],
            style_slug,
            style['label'],
            style['prompt_prefix'],
        )
        filename = f'style_previews/{group_slug}/{style_slug}.jpg'

        print(f'{label} {group["label"]} × {style["label"]}... ', end='', flush=True)

        try:
            b64 = generate_image(prompt)
            url = upload_to_r2(b64, filename)
            success += 1
            print(f'✅ {url.split("/")[-1]}')
        except Exception as e:
            failed += 1
            print(f'❌ {e}')
            # Log failed ones for retry
            with open('/tmp/preview_gen_failures.log', 'a') as f:
                f.write(f'{group_slug}/{style_slug}: {e}\n')

        # Rate limit
        if i < len(to_generate):
            time.sleep(SLEEP_BETWEEN)

    print()
    print(f'=== Done ===')
    print(f'Success: {success} | Failed: {failed} | Skipped (existing): {existing}')
    if failed:
        print(f'Failures logged to /tmp/preview_gen_failures.log')
        print(f'Re-run this script to retry failed images.')


if __name__ == '__main__':
    main()
