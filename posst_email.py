#!/usr/bin/env python3
"""
posst.app — Email Service
Replaces Google Apps Script email functions.
Uses Gmail SMTP via app password.
"""

import os
import smtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

log = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────
GMAIL_USER     = os.environ.get('GMAIL_USER', 'chief@posst.app')
GMAIL_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')
FROM_NAME      = 'posst.app'
NOTIFY_EMAIL   = 'chief@posst.app'

# ── DESIGN TOKENS ─────────────────────────────────────────────
BLUE     = '#1648FF'
BLUE_DIM = '#E8EEFF'
CREAM    = '#FFFAF4'
INK      = '#0F0E17'
MID      = '#4A4860'
LIGHT    = '#9896A8'
WHITE    = '#FFFFFF'
BORDER   = '#E4DFD6'
DARK     = '#1A1A2E'
GREEN    = '#16A34A'

# ── SEND ──────────────────────────────────────────────────────
def send_email(to, subject, html_body, reply_to=None):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f'{FROM_NAME} <{GMAIL_USER}>'
        msg['To']      = to
        msg['Reply-To'] = reply_to or GMAIL_USER
        msg.attach(MIMEText(html_body, 'html'))
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, to, msg.as_string())
        log.info(f'Email sent to {to}: {subject}')
        return True
    except Exception as e:
        log.error(f'Email failed to {to}: {e}')
        return False

# ── HTML HELPERS ──────────────────────────────────────────────
def wrap(body):
    return f'''<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{CREAM};font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{CREAM};">
<tr><td align="center" style="padding:32px 16px;">
<table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;background:{WHITE};border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(22,72,255,0.10);">
  <tr><td style="background:{BLUE};padding:24px 40px;text-align:center;">
    <img src="https://posst.app/posst_logo_white.png" alt="posst.app" style="height:32px;display:block;margin:0 auto 8px;">
    <p style="margin:0;font-size:11px;letter-spacing:2px;color:rgba(255,255,255,0.6);text-transform:uppercase;">Automated social media, done right.</p>
  </td></tr>
  <tr><td style="padding:40px 40px 32px;">{body}</td></tr>
  <tr><td style="background:{DARK};padding:28px 40px;text-align:center;">
    <p style="margin:0 0 6px;color:{WHITE};font-size:13px;font-weight:700;">posst.app</p>
    <a href="mailto:{NOTIFY_EMAIL}" style="color:rgba(255,255,255,0.5);font-size:11px;text-decoration:none;">{NOTIFY_EMAIL}</a>
    <p style="margin:14px 0 0;color:rgba(255,255,255,0.2);font-size:10px;">&copy; 2026 posst.app. All rights reserved.</p>
  </td></tr>
</table>
</td></tr>
</table>
</body></html>'''

def hero(emoji, heading, sub):
    return f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:28px;"><tr><td style="background:{BLUE_DIM};border-left:5px solid {BLUE};border-radius:0 10px 10px 0;padding:18px 22px;"><p style="margin:0 0 4px;font-size:26px;line-height:1;">{emoji}</p><p style="margin:0 0 6px;font-size:20px;font-weight:700;color:{INK};">{heading}</p><p style="margin:0;font-size:13px;color:{MID};line-height:1.5;">{sub}</p></td></tr></table>'

def hi(name):
    return f'<p style="margin:0 0 20px;font-size:16px;color:{INK};">Hi <strong>{name}</strong>,</p>'

def para(text, mb='18px'):
    return f'<p style="margin:0 0 {mb};font-size:14px;color:{MID};line-height:1.7;">{text}</p>'

def sec(text):
    return f'<p style="margin:26px 0 10px;font-size:10px;font-weight:700;color:{BLUE};letter-spacing:2.5px;text-transform:uppercase;border-bottom:2px solid {BLUE_DIM};padding-bottom:7px;">{text}</p>'

def divider():
    return f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:22px 0;"><tr><td style="border-top:1px solid {BORDER};"></td></tr></table>'

def sign_off():
    return f'{divider()}<p style="margin:0 0 3px;font-size:13px;font-weight:700;color:{INK};">The posst.app Team</p><p style="margin:0;font-size:12px;color:{MID};">Questions? Just reply to this email.</p>'

def tbl(rows):
    rs = ''.join([f'<tr style="background:{WHITE if i%2==0 else CREAM};"><td style="padding:10px 14px;font-size:11px;color:{LIGHT};font-weight:700;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid {BORDER};width:38%;">{l}</td><td style="padding:10px 14px;font-size:13px;color:{INK};font-weight:600;border-bottom:1px solid {BORDER};">{v}</td></tr>' for i,(l,v) in enumerate(rows)])
    return f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-radius:10px;overflow:hidden;border:1px solid {BORDER};margin-bottom:24px;">{rs}</table>'

def step(n, title, body):
    return f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:14px;"><tr><td valign="top" width="42"><div style="width:30px;height:30px;background:{BLUE};border-radius:50%;text-align:center;line-height:30px;font-size:13px;font-weight:700;color:{WHITE};">{n}</div></td><td valign="top" style="padding-left:10px;"><p style="margin:2px 0 4px;font-size:13px;font-weight:700;color:{INK};">{title}</p><p style="margin:0;font-size:12px;color:{MID};line-height:1.6;">{body}</p></td></tr></table>'

def hl(text, icon='&#x1F4A1;'):
    return f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:18px 0;"><tr><td style="background:{BLUE_DIM};border:1px solid {BLUE};border-radius:10px;padding:14px 18px;"><p style="margin:0;font-size:13px;color:{INK};line-height:1.6;">{icon}&nbsp; {text}</p></td></tr></table>'

def btn(text, href):
    return f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0 6px;"><tr><td align="center"><a href="{href}" style="display:inline-block;background:{BLUE};color:{WHITE};font-size:14px;font-weight:700;text-decoration:none;padding:13px 36px;border-radius:8px;letter-spacing:0.5px;">{text}</a></td></tr></table>'

def code_box(text):
    return f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:10px 0 18px;"><tr><td style="background:{DARK};border-radius:8px;padding:14px 20px;text-align:center;"><p style="margin:0;font-size:15px;font-weight:700;color:{WHITE};font-family:Courier New,monospace;letter-spacing:1px;">{text}</p></td></tr></table>'

# ── EMAIL FUNCTIONS ───────────────────────────────────────────

def send_go_live_email(client):
    is_pro = (client.get('plan') or '').lower() == 'pro'
    drive_intent = (client.get('google_drive_intent') or '').lower()
    drive_url = (client.get('google_drive_url') or '').strip()
    platforms = (client.get('platforms') or '').replace(',', ', ')
    posting_days = (client.get('posting_days') or '').replace(',', ', ')
    posting_time = client.get('posting_time') or '11:00'
    timezone = client.get('timezone') or 'Australia/Melbourne'

    drive_section = ''
    if is_pro and drive_intent != 'no':
        if drive_url:
            drive_section = f'{sec("Your Photo Library")}{hl("Your Google Drive folder is connected. Photos will be used from your next post.", "&#x1F4C1;")}'
        else:
            drive_section = f'{sec("Your Photo Library")}{hl("Set up your Google Drive photo library to use your own photos in posts.", "&#x1F4C1;")}{btn("Set up photo library &rarr;", "https://onboarding.posst.app/portal.html")}'

    upgrade_section = ''
    if not is_pro:
        upgrade_section = f'{sec("Upgrade to Pro")}{para("Want to use your own photos and set custom content themes per day? Upgrade to Pro anytime from your account portal.")}{btn("Manage my account &rarr;", "https://onboarding.posst.app/portal.html")}'
    else:
        upgrade_section = btn("Manage my account &rarr;", "https://onboarding.posst.app/portal.html")

    body = wrap(f'''
        {hero("&#x1F680;", "You are live!", "Your social media is now posting automatically.")}
        {hi(client.get("business_name") or "there")}
        {para("Your posst.app account is fully configured and your first posts are scheduled. You do not need to do anything.")}
        {sec("Your Setup")}
        {tbl([["Plan", client.get("plan") or "Standard"], ["Platforms", platforms], ["Posting Days", posting_days], ["Post Time", f"{posting_time} {timezone}"]])}
        {sec("What Happens Each Post")}
        {step(1, "Image selected", "Your photo from Google Drive or an AI-generated image" if is_pro and drive_url else "AI-generated image picked automatically")}
        {step(2, "Caption written", "AI writes a fresh on-brand caption for your business")}
        {step(3, "Post goes live", "Published on your platforms at your chosen time")}
        {drive_section}
        {hl("You can still post manually anytime &mdash; it will not affect the automation.", "&#x2705;")}
        {upgrade_section}
        {sign_off()}
    ''')
    return send_email(client.get('contact_email'), "You are live! Your social media is now posting automatically", body)

def send_confirmation_email(client):
    platforms = (client.get('platforms') or '').replace(',', ', ')
    posting_days = (client.get('posting_days') or '').replace(',', ', ')
    body = wrap(f'''
        {hero("&#x1F389;", "We have received your details!", "Your account is being set up &mdash; next step: connect your accounts.")}
        {hi(client.get("business_name") or "there")}
        {para("Thank you for choosing posst.app. We are setting up your account now.")}
        {sec("Your Setup Summary")}
        {tbl([["Plan", client.get("plan") or "Standard"], ["Platforms", platforms], ["Posting Days", posting_days], ["Post Time", client.get("posting_time") or "As selected"], ["Timezone", client.get("timezone") or "As selected"]])}
        {sec("What Happens Next")}
        {step(1, "Connect your accounts", "Complete the OAuth connection at connect.posst.app.")}
        {step(2, "We provision your workflow", "Within 5 minutes of connecting, your automated posting workflow goes live.")}
        {step(3, "You go live", "Posts will start going out on your chosen schedule.")}
        {hl("30-day free trial &mdash; no credit card needed. Cancel anytime.", "&#x1F381;")}
        {sign_off()}
    ''')
    return send_email(client.get('contact_email'), "We have received your details -- posst.app", body)

def send_cancellation_email(client):
    body = wrap(f'''
        {hero("&#x1F44B;", "Your account has been cancelled", "We are sorry to see you go.")}
        {hi(client.get("business_name") or "there")}
        {para("Your posst.app account has been cancelled as requested.")}
        {tbl([["Status", "Cancelled"], ["Posting stops", "Immediately"], ["Data retained", "30 days"]])}
        {step(1, "Posting stops immediately", "No more automated posts will go out.")}
        {step(2, "Your data is kept for 30 days", "Reply to this email within 30 days to reactivate.")}
        {hl("Changed your mind? Reply to this email within 30 days and we will reactivate your account.", "&#x1F499;")}
        {sign_off()}
    ''')
    return send_email(client.get('contact_email'), "Your posst.app account has been cancelled", body)

def send_pause_email(client):
    body = wrap(f'''
        {hero("&#x23F8;&#xFE0F;", "Your posting has been paused", "You can resume anytime.")}
        {hi(client.get("business_name") or "there")}
        {para("Your posst.app posting has been paused. No posts will go out until you resume.")}
        {hl("To resume posting, simply reply to this email and say Resume my account.", "&#x25B6;&#xFE0F;")}
        {sign_off()}
    ''')
    return send_email(client.get('contact_email'), "Your posst.app posting has been paused", body)

def send_day1_email(client):
    is_pro = (client.get('plan') or '').lower() == 'pro'
    body = wrap(f'''
        {hero("&#x1F389;", "Your first post just went live!", "Your social media is now running on autopilot.")}
        {hi(client.get("business_name") or "there")}
        {para("Your first automated post has gone out! posst.app is now posting for you every day, completely automatically.")}
        {sec("What Just Happened")}
        {step(1, "AI wrote your caption", "A fresh on-brand caption written specifically for your business")}
        {step(2, "Photo selected and posted", "Published on " + (client.get("platforms") or "your platforms").replace(",", ", "))}
        {hl("Check your social media pages to see your post live!", "&#x1F4F1;")}
        {'' if is_pro else f'{sec("Want Even Better Results?")}{para("Upgrade to Pro to use your own real photos.")}{btn("Upgrade to Pro &rarr;", "https://onboarding.posst.app/portal.html")}'}
        {btn("View my account &rarr;", "https://onboarding.posst.app/portal.html")}
        {sign_off()}
    ''')
    return send_email(client.get('contact_email'), "Your first post just went live!", body)

def send_day7_standard_email(client):
    body = wrap(f'''
        {hero("&#x1F4C5;", "You have been live for a week!", "Here is how to get even more from posst.app.")}
        {hi(client.get("business_name") or "there")}
        {para("You have been posting automatically for 7 days. Here is how to take it further.")}
        {sec("Upgrade to Pro")}
        {para("Use your own real photos from Google Drive and set custom content themes per day.")}
        {tbl([["Real photos", "3-5x more engagement than AI images"], ["Custom themes", "Service Spotlight, Tip Tuesday and more"], ["Cost", "Only A$10 more per month (A$34.99 total)"]])}
        {btn("Upgrade to Pro &rarr;", "https://onboarding.posst.app/portal.html")}
        {hl("Your 30-day free trial continues regardless. Upgrade anytime.", "&#x2705;")}
        {sign_off()}
    ''')
    return send_email(client.get('contact_email'), "You have been live for a week -- time to upgrade?", body)

def send_day7_pro_email(client):
    drive_ok = bool((client.get('google_drive_url') or '').strip())
    drive_section = hl("Google Drive is connected. Your real photos are being used in every post.", "&#x2705;") if drive_ok else f'{hl("You are on Pro but Google Drive is not connected yet.", "&#x1F4F7;")}{btn("Connect Google Drive &rarr;", "https://onboarding.posst.app/portal.html")}'
    body = wrap(f'''
        {hero("&#x1F4CA;", "One week live on Pro!", "A quick check-in on your account.")}
        {hi(client.get("business_name") or "there")}
        {para("You have been on Pro for 7 days. Your automated posting is running every day.")}
        {tbl([["Plan", "Pro"], ["Posting", (client.get("posting_days") or "").replace(",", ", ") + " at " + (client.get("posting_time") or "11:00")], ["Photo library", "Connected" if drive_ok else "Not connected yet"]])}
        {drive_section}
        {btn("Manage my account &rarr;", "https://onboarding.posst.app/portal.html")}
        {sign_off()}
    ''')
    return send_email(client.get('contact_email'), "One week live on Pro -- quick check-in", body)

def send_trial_ending_email(client, days_left):
    is_pro = (client.get('plan') or '').lower() == 'pro'
    price = '34.99' if is_pro else '24.99'
    subjects = {3: 'Your free trial ends in 3 days', 2: 'Your free trial ends tomorrow', 1: 'Last day of your free trial'}
    subject = subjects.get(days_left, 'Your trial is ending soon') + ' -- posst.app'
    icon = '&#x23F0;' if days_left == 3 else '&#x26A0;&#xFE0F;'
    body = wrap(f'''
        {hero(icon, subjects.get(days_left, "Trial ending soon"), "Keep your automated posting running without interruption.")}
        {hi(client.get("business_name") or "there")}
        {para(f"Your 30-day free trial ends in {days_left} day{'s' if days_left > 1 else ''}. Your subscription will continue at A${price}/month.")}
        {tbl([["Plan", "Pro" if is_pro else "Standard"], ["Monthly cost", f"A${price}"], ["Trial ends", f"{days_left} day{'s' if days_left > 1 else ''}"]])}
        {hl("To cancel before being charged, reply to this email with Cancel or log in to your account.", "&#x1F4AC;")}
        {btn("Manage my account &rarr;", "https://onboarding.posst.app/portal.html")}
        {sign_off()}
    ''')
    return send_email(client.get('contact_email'), subject, body)

def send_monthly_email(client):
    is_pro = (client.get('plan') or '').lower() == 'pro'
    drive_ok = bool((client.get('google_drive_url') or '').strip())
    cta = btn("Upgrade to Pro -- A$34.99/month &rarr;", "https://onboarding.posst.app/portal.html") if not is_pro else (btn("Connect Google Drive &rarr;", "https://onboarding.posst.app/portal.html") if is_pro and not drive_ok else btn("Manage my account &rarr;", "https://onboarding.posst.app/portal.html"))
    body = wrap(f'''
        {hero("&#x1F4CA;", "Your monthly posst.app update", "Another month of automated social media done.")}
        {hi(client.get("business_name") or "there")}
        {para("Your social media has been posting automatically every day. Here is your monthly account summary.")}
        {tbl([["Plan", "Pro" if is_pro else "Standard"], ["Platforms", (client.get("platforms") or "").replace(",", ", ")], ["Schedule", (client.get("posting_days") or "").replace(",", ", ") + " at " + (client.get("posting_time") or "11:00")]])}
        {cta}
        {sign_off()}
    ''')
    return send_email(client.get('contact_email'), "Your monthly posst.app update", body)

def send_missing_platform_email(client, missing):
    list_str = ' and '.join(missing)
    body = wrap(f'''
        {hero("&#x26A0;&#xFE0F;", "One platform still needs connecting", "Takes less than a minute to complete.")}
        {hi(client.get("business_name") or "there")}
        {para(f"{list_str} still needs to be connected to start posting automatically.")}
        {btn("Connect now &rarr;", "https://onboarding.posst.app/portal.html")}
        {hl("Takes less than 60 seconds. Click the button above and connect your account.", "&#x23F1;&#xFE0F;")}
        {sign_off()}
    ''')
    return send_email(client.get('contact_email'), "One platform still needs connecting -- posst.app", body)

def send_reengagement_email(to_email, business_name, resume_url):
    body = wrap(f'''
        {hero("&#x1F44B;", "You left something behind!", "Your posst.app setup is saved &mdash; pick up right where you left off.")}
        {hi(business_name)}
        {para("You started setting up posst.app but did not quite finish. No worries &mdash; we saved all your progress.")}
        {btn("Complete my setup &rarr;", resume_url)}
        {hl("Your details are saved &mdash; just enter your phone number and verify to continue.", "&#x1F4BE;")}
        {sign_off()}
    ''')
    return send_email(to_email, "You left something behind -- complete your posst.app setup", body)


def send_upgrade_email(to, business_name, has_drive=False, has_themes=False):
    drive_section = hl('Your Google Drive folder is connected. Real photos will be used in every post.', '&#x1F4F7;') if has_drive else ''
    themes_section = hl('Your custom day themes are active. Every day has its own unique flavour.', '&#x1F3A8;') if has_themes else ''
    body = wrap(
        hero('&#x2728;', 'Welcome to Pro, ' + business_name + '!', 'You just made the best decision for your business.')
        + hi(business_name)
        + sec('What You Unlocked')
        + hl('Real photos from your Google Drive in every post.', '&#x1F5BC;')
        + hl('Custom content themes — a different topic every day of the week.', '&#x1F4C5;')
        + hl('Priority support — faster responses and dedicated attention.', '&#x2B50;')
        + drive_section
        + themes_section
        + para('Your next post will already reflect your Pro settings. Sit back — we handle everything.')
        + btn('View my account &rarr;', 'https://onboarding.posst.app/portal.html')
        + sign_off()
    )
    return send_email(to, 'Welcome to Pro — ' + business_name, body)


def send_internal_alert(title, message, level='alert'):
    colors = {'alert': '#DC2626', 'info': '#2563EB', 'health': '#16A34A'}
    color = colors.get(level, '#DC2626')
    now = datetime.now().strftime('%d/%m/%Y %H:%M')
    body = wrap(f'''
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:24px;">
          <tr><td style="background:{color};border-radius:10px;padding:20px 24px;">
            <p style="margin:0 0 4px;font-size:18px;font-weight:700;color:#FFFFFF;">{title}</p>
            <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.75);">{now} AEST</p>
          </td></tr>
        </table>
        <p style="font-size:14px;color:{INK};line-height:1.7;">{message}</p>
    ''')
    return send_email(NOTIFY_EMAIL, f'[POSST] {title}', body)

if __name__ == '__main__':
    # Test
    print('Testing email...')
    result = send_internal_alert('posst-email.py test', 'Gmail SMTP is working correctly from the VPS.')
    print('Sent:', result)
