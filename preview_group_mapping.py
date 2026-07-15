"""
posst.app — Preview Group Mapping
Maps all 208 business types → 29 preview groups for style gallery images.
Each preview group has a composition style (from prompt_style_library) and scene description.

Usage:
    from preview_group_mapping import get_preview_group, PREVIEW_GROUPS
    
    group_slug = get_preview_group("Dog Grooming")  # → "pet_services"
    group = PREVIEW_GROUPS[group_slug]
    # group["scene"] → scene description for image generation
    # group["composition_style"] → matches prompt_style_library style_id
"""

PREVIEW_GROUPS = {
    # ──────────────────────────────────────────────────────────────
    # 12 groups mapping 1:1 from existing BIZ_CATEGORIES groups
    # ──────────────────────────────────────────────────────────────

    "fitness_leisure": {
        "label": "Fitness & Leisure",
        "composition_style": "golden_hour_action",
        "scene": (
            "A dynamic fitness studio mid-session — equipment in use, energy and movement visible. "
            "Warm low sun streaming through windows, motion in the air. "
            "No human faces — hands gripping equipment and silhouettes only."
        ),
    },

    "pet_services": {
        "label": "Pet Services",
        "composition_style": "golden_hour_action",
        "scene": (
            "A happy well-groomed dog in a professional pet care setting — clean salon or outdoor environment. "
            "Warm golden light, soft background. The dog looks clean, healthy, and content. No human faces."
        ),
    },

    "automotive": {
        "label": "Automotive",
        "composition_style": "golden_hour_action",
        "scene": (
            "An automotive workshop with a vehicle being worked on — tools arranged, hood open, "
            "detailed mechanical work in progress. Warm workshop lighting with some natural light. "
            "No human faces — hands with tools only."
        ),
    },

    "accommodation_tourism": {
        "label": "Accommodation & Tourism",
        "composition_style": "wide_environment",
        "scene": (
            "A welcoming accommodation entrance or lobby — inviting interior with warm ambient lighting, "
            "comfortable furnishings, and a sense of arrival. Wide establishing shot showing the full space. "
            "No human faces."
        ),
    },

    "online_ecommerce": {
        "label": "Online & eCommerce",
        "composition_style": "abstract_workspace",
        "scene": (
            "A modern digital workspace — laptop screen with analytics dashboard, coffee beside it, "
            "clean minimal desk setup. Abstract tech elements suggesting online business. "
            "Soft directional lighting. No human faces."
        ),
    },

    "health_wellness": {
        "label": "Health & Wellness",
        "composition_style": "wide_environment",
        "scene": (
            "A calming wellness or care environment — peaceful treatment room or community care space "
            "with natural light, plants, and comfortable seating. Wide shot showing the welcoming atmosphere. "
            "No human faces."
        ),
    },

    "spiritual_alternative": {
        "label": "Spiritual & Alternative Wellness",
        "composition_style": "symbolic_scene",
        "scene": (
            "Symbolic still-life representing holistic healing — arranged crystals, essential oils, herbs, "
            "candles, and natural materials on a clean modern surface. No people. "
            "Soft directional lighting with shallow depth of field."
        ),
    },

    "events_entertainment": {
        "label": "Events & Entertainment",
        "composition_style": "wide_environment",
        "scene": (
            "An entertainment venue set up for an event — stage lighting, seating arranged, "
            "atmosphere of anticipation before showtime. Wide establishing shot with dramatic venue lighting. "
            "No human faces."
        ),
    },

    "food_drink_production": {
        "label": "Food & Drink Production",
        "composition_style": "documentary_candid",
        "scene": (
            "An artisan food or drink production space — raw ingredients, production equipment, "
            "bottles or packages being prepared. Natural indoor lighting from a nearby window. "
            "Authentic craft production feel. No human faces — hands at work only."
        ),
    },

    "kids_family": {
        "label": "Kids & Family",
        "composition_style": "wide_environment",
        "scene": (
            "A colourful kids activity space — play equipment, bright colours, toys and creative materials "
            "set up for fun. Bright overcast natural light filling the space. "
            "Joyful, safe environment. No people."
        ),
    },

    "trade_industrial": {
        "label": "Trade & Industrial",
        "composition_style": "documentary_candid",
        "scene": (
            "An industrial worksite or workshop — heavy equipment, welding sparks, metal fabrication "
            "in progress. Natural mixed lighting with industrial fixtures. "
            "Raw, authentic working environment. No human faces — gloved hands and equipment only."
        ),
    },

    "education_childcare": {
        "label": "Education & Childcare",
        "composition_style": "wide_environment",
        "scene": (
            "A bright learning environment — classroom or tutoring space with books, learning materials, "
            "colourful educational displays. Morning light streaming in. "
            "Warm, nurturing educational setting. No human faces."
        ),
    },

    # ──────────────────────────────────────────────────────────────
    # FOOD & HOSPITALITY → 4 sub-groups
    # ──────────────────────────────────────────────────────────────

    "food_bakery_sweets": {
        "label": "Bakery & Sweets",
        "parent_group": "Food & Hospitality",
        "composition_style": "macro_detail",
        "scene": (
            "Extreme close-up of freshly baked pastries and artisan bread — golden crusts, dusted flour, "
            "layers of flaky dough. Fill the frame with texture and warmth. "
            "Shallow depth of field. No human faces."
        ),
    },

    "food_dining": {
        "label": "Dining & Cafes",
        "parent_group": "Food & Hospitality",
        "composition_style": "wide_environment",
        "scene": (
            "A welcoming restaurant or cafe interior — tables set with plated food, ambient lighting, "
            "warm inviting atmosphere. Wide establishing shot showing the full dining space. "
            "No human faces — figures at distance only."
        ),
    },

    "food_street_casual": {
        "label": "Street Food & Takeaway",
        "parent_group": "Food & Hospitality",
        "composition_style": "golden_hour_action",
        "scene": (
            "A vibrant food truck or takeaway counter — food being prepared mid-action, steam rising, "
            "colourful menu boards. Warm golden hour light with movement and energy. "
            "No human faces — hands preparing food only."
        ),
    },

    "food_specialty": {
        "label": "Specialty Food & Catering",
        "parent_group": "Food & Hospitality",
        "composition_style": "documentary_candid",
        "scene": (
            "A specialty food workspace — butcher's cuts on display, brewing equipment, fresh juice "
            "ingredients, or catering prep in progress. Natural indoor lighting. "
            "Authentic craft food feel. No human faces — hands at work only."
        ),
    },

    # ──────────────────────────────────────────────────────────────
    # BEAUTY & HEALTH → 3 sub-groups
    # ──────────────────────────────────────────────────────────────

    "beauty_salon": {
        "label": "Salon & Beauty",
        "parent_group": "Beauty & Health",
        "composition_style": "macro_detail",
        "scene": (
            "Extreme close-up of salon tools and beauty products — brushes, scissors, styling products, "
            "nail polish arranged professionally. Fill the frame with texture and detail. "
            "Shallow depth of field. No human faces."
        ),
    },

    "beauty_clinical": {
        "label": "Clinical & Medical",
        "parent_group": "Beauty & Health",
        "composition_style": "wide_environment",
        "scene": (
            "A clean modern clinical environment — treatment chair, professional medical equipment, "
            "bright sterile lighting. Wide shot showing the professional, reassuring space. "
            "No human faces."
        ),
    },

    "beauty_therapy": {
        "label": "Therapy & Allied Health",
        "parent_group": "Beauty & Health",
        "composition_style": "over_shoulder",
        "scene": (
            "A calming therapy or treatment room — massage table, therapeutic equipment, warm ambient "
            "lighting. Over-the-shoulder perspective showing the treatment space and tools. "
            "No human faces — hands providing care only."
        ),
    },

    # ──────────────────────────────────────────────────────────────
    # RETAIL → 4 sub-groups
    # ──────────────────────────────────────────────────────────────

    "retail_fashion": {
        "label": "Fashion & Jewellery",
        "parent_group": "Retail",
        "composition_style": "high_contrast_studio",
        "scene": (
            "Fashion retail display — clothing on racks, jewellery in cases, accessories artfully arranged. "
            "High-contrast studio-style lighting with deep shadows. "
            "Elegant, curated retail feel. No human faces."
        ),
    },

    "retail_specialty": {
        "label": "Specialty Shops",
        "parent_group": "Retail",
        "composition_style": "macro_detail",
        "scene": (
            "Extreme close-up of specialty retail items — book spines, flower stems, handcrafted gifts, "
            "hobby supplies. Fill the frame with rich colour and detail. "
            "Shallow depth of field. No human faces."
        ),
    },

    "retail_tech": {
        "label": "Tech & Electronics",
        "parent_group": "Retail",
        "composition_style": "product_still",
        "scene": (
            "Tech products displayed on a clean surface — smartphones, accessories, electronics neatly "
            "arranged. Clean white or dark background, crisp product lighting. "
            "Minimal, modern tech retail aesthetic. No human faces."
        ),
    },

    "retail_general": {
        "label": "General Retail",
        "parent_group": "Retail",
        "composition_style": "wide_environment",
        "scene": (
            "A well-stocked retail store interior — shelves of products, display areas, welcoming "
            "shopping environment. Wide shot showing the breadth of the store. "
            "Bright overhead and natural light. No human faces."
        ),
    },

    # ──────────────────────────────────────────────────────────────
    # HOME & GARDEN → 3 sub-groups
    # ──────────────────────────────────────────────────────────────

    "home_trades": {
        "label": "Trades",
        "parent_group": "Home & Garden",
        "composition_style": "over_shoulder",
        "scene": (
            "A tradesperson's workspace — tools laid out, construction or repair work in progress, "
            "tradie van visible. Over-the-shoulder perspective of the work being done. "
            "Natural daylight on a job site. No human faces — hands with tools only."
        ),
    },

    "home_services": {
        "label": "Home Services",
        "parent_group": "Home & Garden",
        "composition_style": "documentary_candid",
        "scene": (
            "A home service in progress — cleaning equipment, pest control tools, or moving supplies "
            "in a residential setting. Natural indoor lighting. "
            "Candid documentary feel of professional service being delivered. No human faces."
        ),
    },

    "home_improvement": {
        "label": "Home Improvement",
        "parent_group": "Home & Garden",
        "composition_style": "outdoor_natural",
        "scene": (
            "A beautiful home exterior or garden — landscaped yard, pool area, solar panels on roof, "
            "or freshly renovated exterior. Natural outdoor light, lush greenery. "
            "Wide view of the improved home environment. No human faces."
        ),
    },

    # ──────────────────────────────────────────────────────────────
    # PROFESSIONAL SERVICES → 3 sub-groups
    # ──────────────────────────────────────────────────────────────

    "professional_corporate": {
        "label": "Corporate & Professional",
        "parent_group": "Professional Services",
        "composition_style": "abstract_workspace",
        "scene": (
            "A professional office workspace — modern desk setup, legal documents, financial reports, "
            "laptop with business software. Abstract composition suggesting expertise and trust. "
            "Soft directional lighting. No human faces."
        ),
    },

    "professional_creative": {
        "label": "Creative Services",
        "parent_group": "Professional Services",
        "composition_style": "over_shoulder",
        "scene": (
            "A creative studio workspace — camera equipment, design software on screen, editing suite, "
            "creative tools. Over-the-shoulder perspective of the creative workspace. "
            "Warm studio lighting. No human faces — hands at work only."
        ),
    },

    "professional_specialist": {
        "label": "Specialist Services",
        "parent_group": "Professional Services",
        "composition_style": "wide_environment",
        "scene": (
            "A specialist professional environment — architectural blueprints on a table, real estate "
            "property showcase, event setup in progress, or modern IT server room. "
            "Wide establishing shot. Natural light. No human faces."
        ),
    },
}


# ──────────────────────────────────────────────────────────────
# TYPE → PREVIEW GROUP LOOKUP
# Every one of the 208 business types maps to exactly one group.
# ──────────────────────────────────────────────────────────────

TYPE_TO_PREVIEW_GROUP = {
    # Fitness & Leisure
    "Boxing / MMA Gym": "fitness_leisure",
    "CrossFit / Functional Fitness": "fitness_leisure",
    "Cycling Studio": "fitness_leisure",
    "Dance Studio": "fitness_leisure",
    "Golf Coaching": "fitness_leisure",
    "Gym / Fitness Studio": "fitness_leisure",
    "Martial Arts": "fitness_leisure",
    "Personal Trainer": "fitness_leisure",
    "Pilates Studio": "fitness_leisure",
    "Rock Climbing": "fitness_leisure",
    "Sports Complex": "fitness_leisure",
    "Swimming School": "fitness_leisure",
    "Tennis Coaching": "fitness_leisure",
    "Yoga Studio": "fitness_leisure",

    # Pet Services
    "Aquarium & Fish": "pet_services",
    "Aviary & Bird Services": "pet_services",
    "Boarding Kennels": "pet_services",
    "Dog Grooming": "pet_services",
    "Dog Training": "pet_services",
    "Exotic Pets": "pet_services",
    "Fresh Pet Food": "pet_services",
    "Pet Grooming (Cats)": "pet_services",
    "Pet Photography": "pet_services",
    "Pet Shop": "pet_services",
    "Pet Sitting / Dog Walking": "pet_services",
    "Veterinary Clinic": "pet_services",

    # Automotive
    "Auto Parts": "automotive",
    "Car Dealership": "automotive",
    "Car Detailing": "automotive",
    "Car Wash": "automotive",
    "Caravan & RV": "automotive",
    "Mechanic / Auto Repair": "automotive",
    "Motorcycle Dealer / Repair": "automotive",
    "Panel Beating": "automotive",
    "Roadside Assistance": "automotive",
    "Second Hand Car Sales": "automotive",
    "Tyres & Accessories": "automotive",
    "Vehicle Wrapping": "automotive",

    # Accommodation & Tourism
    "Amusement / Entertainment Centre": "accommodation_tourism",
    "B&B / Guest House": "accommodation_tourism",
    "Escape Room": "accommodation_tourism",
    "Event / Function Centre": "accommodation_tourism",
    "Glamping / Eco Stays": "accommodation_tourism",
    "Holiday Park / Caravan Park": "accommodation_tourism",
    "Hotel / Motel": "accommodation_tourism",
    "Serviced Apartments": "accommodation_tourism",
    "Tour Operator": "accommodation_tourism",
    "Travel Agency": "accommodation_tourism",

    # Online & eCommerce
    "Digital Products": "online_ecommerce",
    "Dropshipping": "online_ecommerce",
    "Marketplace Seller": "online_ecommerce",
    "Online Courses / Education": "online_ecommerce",
    "Online Store": "online_ecommerce",
    "Print on Demand": "online_ecommerce",
    "SaaS / Software": "online_ecommerce",
    "Subscription Box": "online_ecommerce",

    # Health & Wellness
    "Aged Care": "health_wellness",
    "Community Services": "health_wellness",
    "Disability Services": "health_wellness",
    "Fertility Clinic": "health_wellness",
    "Life Coaching": "health_wellness",
    "Meditation & Mindfulness": "health_wellness",
    "Sleep Clinic": "health_wellness",

    # Spiritual & Alternative Wellness
    "Acupuncture": "spiritual_alternative",
    "Aromatherapy": "spiritual_alternative",
    "Astrologer": "spiritual_alternative",
    "Crystal Healing": "spiritual_alternative",
    "Herbalist": "spiritual_alternative",
    "Hypnotherapy": "spiritual_alternative",
    "Kinesiology": "spiritual_alternative",
    "Naturopath": "spiritual_alternative",
    "Numerologist": "spiritual_alternative",
    "Psychic / Clairvoyant": "spiritual_alternative",
    "Reiki / Energy Healing": "spiritual_alternative",
    "Sound Healing": "spiritual_alternative",
    "Spiritual Coaching": "spiritual_alternative",
    "Tarot Reader": "spiritual_alternative",

    # Events & Entertainment
    "Comedy Club": "events_entertainment",
    "Cinema": "events_entertainment",
    "DJ / Entertainment": "events_entertainment",
    "Festival / Market Organiser": "events_entertainment",
    "Live Music Venue": "events_entertainment",
    "Photography Studio": "events_entertainment",
    "Theatre": "events_entertainment",
    "Wedding Venue": "events_entertainment",

    # Food & Drink Production
    "Artisan Food Producer": "food_drink_production",
    "Distillery": "food_drink_production",
    "Farmers Market Vendor": "food_drink_production",
    "Specialty Coffee Roaster": "food_drink_production",
    "Winery": "food_drink_production",

    # Kids & Family
    "Childrens Clothing": "kids_family",
    "Jumping Castle Hire": "kids_family",
    "Kids Gym / Play Centre": "kids_family",
    "Party Entertainment": "kids_family",
    "Toy Library": "kids_family",

    # Trade & Industrial
    "Crane & Heavy Equipment": "trade_industrial",
    "Industrial Cleaning": "trade_industrial",
    "Scaffolding": "trade_industrial",
    "Waste Management": "trade_industrial",
    "Welding & Fabrication": "trade_industrial",

    # Education & Childcare
    "After School Care": "education_childcare",
    "Art Classes": "education_childcare",
    "Child Care / Daycare": "education_childcare",
    "Coding School": "education_childcare",
    "Driving School": "education_childcare",
    "Early Childhood / Kindergarten": "education_childcare",
    "Language School": "education_childcare",
    "Music School": "education_childcare",
    "Sports Coaching (Kids)": "education_childcare",
    "Tutoring": "education_childcare",
    "Vocational Training": "education_childcare",

    # Food & Hospitality → Bakery & Sweets
    "Bakery": "food_bakery_sweets",
    "Dessert Shop": "food_bakery_sweets",
    "Ice Cream Shop": "food_bakery_sweets",
    "Deli": "food_bakery_sweets",

    # Food & Hospitality → Dining & Cafes
    "Cafe / Coffee Shop": "food_dining",
    "Restaurant": "food_dining",
    "Wine Bar": "food_dining",
    "Pizza Shop": "food_dining",

    # Food & Hospitality → Street Food & Takeaway
    "Food Truck": "food_street_casual",
    "Takeaway / Fast Food": "food_street_casual",
    "Fish & Chips": "food_street_casual",

    # Food & Hospitality → Specialty Food & Catering
    "Butcher": "food_specialty",
    "Brewery / Craft Beer": "food_specialty",
    "Juice Bar": "food_specialty",
    "Catering": "food_specialty",
    "Catering Equipment Hire": "food_specialty",
    "Meal Prep / Delivery": "food_specialty",

    # Beauty & Health → Salon & Beauty
    "Barber Shop": "beauty_salon",
    "Beauty Salon": "beauty_salon",
    "Brow & Lash Studio": "beauty_salon",
    "Cosmetic Tattoo": "beauty_salon",
    "Hair Salon / Hairdresser": "beauty_salon",
    "Nail Salon": "beauty_salon",
    "Skin Clinic": "beauty_salon",

    # Beauty & Health → Clinical & Medical
    "Dental Clinic": "beauty_clinical",
    "Medical Practice": "beauty_clinical",
    "Pharmacy": "beauty_clinical",
    "Optical": "beauty_clinical",
    "Hearing Clinic": "beauty_clinical",

    # Beauty & Health → Therapy & Allied Health
    "Chiropractor": "beauty_therapy",
    "Dietitian / Nutritionist": "beauty_therapy",
    "Health Spa": "beauty_therapy",
    "Massage Therapist": "beauty_therapy",
    "Natural Therapies": "beauty_therapy",
    "Occupational Therapist": "beauty_therapy",
    "Osteopath": "beauty_therapy",
    "Podiatrist": "beauty_therapy",
    "Psychologist / Counsellor": "beauty_therapy",
    "Speech Therapist": "beauty_therapy",

    # Retail → Fashion & Jewellery
    "Clothing & Fashion": "retail_fashion",
    "Jewellery": "retail_fashion",
    "Vintage & Secondhand": "retail_fashion",

    # Retail → Specialty Shops
    "Bookshop": "retail_specialty",
    "Florist": "retail_specialty",
    "Gift Shop": "retail_specialty",
    "Craft & Hobby": "retail_specialty",
    "Newsagency": "retail_specialty",

    # Retail → Tech & Electronics
    "Electronics": "retail_tech",
    "Phone & Tech Accessories": "retail_tech",
    "Appliances": "retail_tech",

    # Retail → General Retail
    "Baby & Kids": "retail_general",
    "Furniture": "retail_general",
    "Health Food Store": "retail_general",
    "Homewares": "retail_general",
    "Sporting Goods": "retail_general",
    "Supplement Store": "retail_general",
    "Toy Shop": "retail_general",
    "Vape & Smoke Shop": "retail_general",

    # Home & Garden → Trades
    "Building & Construction": "home_trades",
    "Electrical": "home_trades",
    "Fencing": "home_trades",
    "Painting & Decorating": "home_trades",
    "Plumbing": "home_trades",
    "Roofing": "home_trades",
    "Tiling": "home_trades",

    # Home & Garden → Home Services
    "Cleaning Services": "home_services",
    "Pest Control": "home_services",
    "Removalist": "home_services",
    "Skip Bin Hire": "home_services",

    # Home & Garden → Home Improvement
    "Air Conditioning / HVAC": "home_improvement",
    "Carpet & Flooring": "home_improvement",
    "Interior Design": "home_improvement",
    "Landscaping / Gardening": "home_improvement",
    "Pool Services": "home_improvement",
    "Security Systems": "home_improvement",
    "Solar & Energy": "home_improvement",

    # Professional Services → Corporate & Professional
    "Accounting / Bookkeeping": "professional_corporate",
    "Consulting": "professional_corporate",
    "Engineering": "professional_corporate",
    "Financial Planning": "professional_corporate",
    "Insurance": "professional_corporate",
    "Legal": "professional_corporate",
    "Recruitment": "professional_corporate",
    "Surveying": "professional_corporate",
    "Translation": "professional_corporate",

    # Professional Services → Creative Services
    "Copywriting": "professional_creative",
    "Graphic Design": "professional_creative",
    "Marketing Agency": "professional_creative",
    "Photography": "professional_creative",
    "PR & Communications": "professional_creative",
    "Social Media Marketing": "professional_creative",
    "Video Production": "professional_creative",
    "Web Design & Development": "professional_creative",

    # Professional Services → Specialist Services
    "Architecture": "professional_specialist",
    "Event Planning": "professional_specialist",
    "IT / Technology": "professional_specialist",
    "Real Estate": "professional_specialist",
}


# ──────────────────────────────────────────────────────────────
# ARTISTIC STYLES (the 9 styles that get applied to each scene)
# ──────────────────────────────────────────────────────────────

ARTISTIC_STYLES = {
    "photorealistic": {
        "label": "Photorealistic",
        "prompt_prefix": "",  # No prefix — default
        "tier": "all",  # Available to Standard + Pro
    },
    "soft_watercolour": {
        "label": "Soft Watercolour",
        "prompt_prefix": "Soft watercolour painting style.",
        "tier": "all",
    },
    "studio_ghibli": {
        "label": "Studio Ghibli",
        "prompt_prefix": "Studio Ghibli anime style.",
        "tier": "pro",
    },
    "minimalist_line_art": {
        "label": "Minimalist Line Art",
        "prompt_prefix": "Minimalist line art illustration style.",
        "tier": "all",
    },
    "flat_illustration": {
        "label": "Flat Illustration",
        "prompt_prefix": "Modern flat illustration style.",
        "tier": "all",
    },
    "oil_painting": {
        "label": "Oil Painting",
        "prompt_prefix": "Classical oil painting style.",
        "tier": "pro",
    },
    "pop_art": {
        "label": "Pop Art",
        "prompt_prefix": "Bold pop art style with vivid colours.",
        "tier": "pro",
    },
    "cinematic_noir": {
        "label": "Cinematic Noir",
        "prompt_prefix": "Dramatic cinematic noir style with deep shadows and moody contrast.",
        "tier": "pro",
    },
    "vintage_film": {
        "label": "Vintage Film",
        "prompt_prefix": "Warm vintage film photography style with retro grain and muted tones.",
        "tier": "pro",
    },
}


def get_preview_group(business_type: str) -> str:
    """Look up the preview group slug for a business type.
    
    Returns the slug (e.g. 'pet_services') or 'professional_corporate' as fallback.
    """
    return TYPE_TO_PREVIEW_GROUP.get(business_type, "professional_corporate")


def get_preview_image_url(business_type: str, style_slug: str) -> str:
    """Build the R2 URL for a preview image.
    
    Args:
        business_type: e.g. "Dog Grooming"
        style_slug: e.g. "soft_watercolour"
    
    Returns:
        R2 public URL for the cached preview image.
    """
    group_slug = get_preview_group(business_type)
    return f"https://pub-f5f1d08da66048808d14f48cb78ebb36.r2.dev/style_previews/{group_slug}/{style_slug}.jpg"


def get_all_preview_urls(business_type: str) -> dict:
    """Get all 9 preview image URLs for a business type.
    
    Returns dict: {style_slug: url, ...}
    """
    return {
        slug: get_preview_image_url(business_type, slug)
        for slug in ARTISTIC_STYLES
    }


# ──────────────────────────────────────────────────────────────
# VALIDATION
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Validate all types are mapped
    all_types = list(TYPE_TO_PREVIEW_GROUP.keys())
    all_groups = set(TYPE_TO_PREVIEW_GROUP.values())
    defined_groups = set(PREVIEW_GROUPS.keys())
    
    print(f"Total types mapped: {len(all_types)}")
    print(f"Unique groups referenced: {len(all_groups)}")
    print(f"Groups defined: {len(defined_groups)}")
    
    # Check for groups referenced but not defined
    missing = all_groups - defined_groups
    if missing:
        print(f"ERROR — groups referenced but not defined: {missing}")
    
    # Check for groups defined but never referenced
    unused = defined_groups - all_groups
    if unused:
        print(f"WARNING — groups defined but never referenced: {unused}")
    
    # Check for duplicate types
    if len(all_types) != len(set(all_types)):
        seen = set()
        for t in all_types:
            if t in seen:
                print(f"DUPLICATE: {t}")
            seen.add(t)
    else:
        print("No duplicate types ✅")
    
    print(f"\nTotal images needed: {len(defined_groups)} × {len(ARTISTIC_STYLES)} = {len(defined_groups) * len(ARTISTIC_STYLES)}")
    
    # Test lookups
    print(f"\nSample lookups:")
    for biz_type in ["Dog Grooming", "Bakery", "Legal", "Plumbing", "Yoga Studio"]:
        group = get_preview_group(biz_type)
        label = PREVIEW_GROUPS[group]["label"]
        print(f"  {biz_type} → {group} ({label})")
