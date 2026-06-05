import requests
import json

API = 'http://127.0.0.1:5680'

# Clippers data from the handover doc and testing session
clippers = {
    "client_id":           "POSST_20260604_001",
    "status":              "Active",
    "phone":               "+61414208895",
    "business_name":       "Clippers Expert Hair Care for dogs",
    "business_city":       "Melbourne",
    "business_suburb":     "Glen Waverley",
    "business_country":    "Australia",
    "contact_email":       "jmdpetgrooming@gmail.com",
    "business_type":       "Dog Grooming",
    "business_desc":       "Clippers is a Dog Grooming Salon. located in Glen Waverely, Melbourne\nWe specialise in dog grooming for all types of dogs. We are specially known for Breed cuts, Large Dog Groming, Fusion grooming. We also provide Organic Dog Spa treatments. We make fresh home cooked for Dogs.",
    "brand_keywords":      "dog grooming, large dog grooming, breed cuts, organic dog spa",
    "plan":                "Pro",
    "platforms":           "facebook,instagram,gbp",
    "fb_page_name":        "Clippers Hair Care for Dogz",
    "fb_page_url":         "https://www.facebook.com/clippersexperthaircarefordogs",
    "fb_page_id":          "240829512611712",
    "ig_handle":           "clippershaircarefordogz",
    "ig_business_id":      "17841408045839532",
    "gbp_name":            "Clippers Expert Hair Care for dogs",
    "gbp_location_id":     "8615982486413375677",
    "posting_days":        "Mon,Tue,Wed,Thu,Fri,Sat,Sun",
    "posting_time":        "11:00",
    "timezone":            "Australia/Melbourne",
    "posting_time_utc":    "01:00",
    "go_live_email_sent":  True,
    "monthly_report_day":  4,
    "notes":               {"caption_phone": "0398037070"},
    "google_drive_url":    "https://drive.google.com/drive/folders/1r97zjONwK2_DKJo2Qy0S-4beDQJQapcR?usp=sharing",
    "drive_categories":    [{"name":"Big Dog Grooming","day":"","subcategories":[]},{"name":"Breed cuts","day":"","subcategories":[]},{"name":"Dog Spa Treatment","day":"","subcategories":[]},{"name":"Funny dogs","day":"","subcategories":[]}],
    "google_drive_intent": "now",
    "caption_email":       "info@clippersgrooming.com.au",
    "caption_phone":       "0398037070",
}

r = requests.post(f'{API}/api/client', json=clippers)
print('Create client:', r.status_code, r.json())

# Also add prospect record as converted
prospect = {
    "phone":  "+61414208895",
    "business_name": "Clippers Expert Hair Care for dogs",
    "business_city": "Melbourne",
    "business_type": "Dog Grooming",
    "status": "converted"
}
r2 = requests.post(f'{API}/api/prospect', json=prospect)
print('Create prospect:', r2.status_code, r2.json())

# Convert prospect
r3 = requests.post(f'{API}/api/prospect/convert', json={"phone": "+61414208895"})
print('Convert prospect:', r3.status_code, r3.json())

print('Migration complete!')
