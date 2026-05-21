[SEMOR_User_Guide_updated.txt](https://github.com/user-attachments/files/28102472/SEMOR_User_Guide_updated.txt)
================================================================================
SEMOR — Telegram Channel OSINT Scraper
User Guide: From Setup to Analysis
Updated for enhanced SEMOR capabilities
================================================================================

################################################################################
##                                                                            ##
##   DEPLOYMENT REQUIREMENT — RESEARCH INFRASTRUCTURE ONLY                   ##
##                                                                            ##
##   This tool MUST be run exclusively on dedicated research infrastructure.  ##
##   It is NOT approved for use on corporate devices, personal computers,     ##
##   or shared workstations.                                                  ##
##                                                                            ##
##   WHY THIS REQUIREMENT EXISTS:                                             ##
##                                                                            ##
##   - The tool authenticates as a live Telegram account and creates a        ##
##     persistent session file (tg_session.session) that is cryptographically ##
##     bound to the machine it runs on. Running on a corporate device ties    ##
##     your organization's hardware identity to the research account,         ##
##     creating a direct attribution risk.                                    ##
##                                                                            ##
##   - The tool issues high-volume automated requests to Telegram's API       ##
##     servers. This traffic profile is inconsistent with acceptable use on   ##
##     corporate networks and may trigger security alerts or violate          ##
##     acceptable use policies.                                               ##
##                                                                            ##
##   - Bot enrichment queries (userinfobot, SangMataInfo) interact with       ##
##     third-party bots and must not be conducted from infrastructure that    ##
##     can be linked back to your organization.                               ##
##                                                                            ##
##   If you are unsure whether your environment qualifies as research         ##
##   infrastructure, consult your team lead or security officer first.        ##
##                                                                            ##
################################################################################

--------------------------------------------------------------------------------
1. WHAT DOES THIS TOOL DO?
--------------------------------------------------------------------------------

SEMOR is a Python script that automatically collects information from Telegram
channels and groups. You give it a list of Telegram channels to study, and it
gathers and organizes data about those channels in a structured, repeatable way.

For each channel, the tool collects:

  - Channel metadata (title, username, creation date, member count, flags)
  - Admin list (who runs the channel)
  - Member list (up to 5,000 participants)
  - Recent messages, including timestamps, text, views, forwards, and replies
  - Forward-origin tracking for forwarded messages
  - URL extraction from message text, Telegram URL entities, and text-link entities
  - Media metadata for photos, documents, web previews, stickers, audio, and video
  - Date-range message depth so older windows can be collected without relying only
    on a fixed recent-message limit
  - User enrichment via two Telegram bots (userinfobot and SangMataInfo), which can
    reveal historical usernames and name changes
  - Reply graphs — who is replying to whom within each channel
  - Cross-channel overlap — users who appear in multiple channels

All results are saved as CSV files you can open in Excel, Google Sheets, or load
into analysis tools.

--------------------------------------------------------------------------------
2. WHAT YOU NEED BEFORE STARTING
--------------------------------------------------------------------------------

2.1  A Telegram Account
     You need a real Telegram account. The script logs in as you and reads
     channels on your behalf. Use a dedicated research account rather than your
     personal account.

2.2  Telegram API Credentials  [HUMAN ACTION REQUIRED]
     You must register your own application with Telegram to get credentials.

     Steps:
       1. Go to: https://my.telegram.org
       2. Log in with your Telegram account phone number.
       3. Click "API Development Tools."
       4. Fill in the form. App title and short name can be anything.
       5. Click "Create application."
       6. You will see an api_id and api_hash.
       7. Copy both values into the script in Step 3.

     IMPORTANT: Treat your api_id and api_hash like passwords. Do not share them.

2.3  Python and Required Libraries
     The script requires Python 3.8 or newer. Install libraries by running:

       pip install telethon pandas langdetect deep_translator

2.4  Your Target List File  [HUMAN ACTION REQUIRED]
     Create a plain text file in the same folder as the script. The current
     enhanced script uses:

       chinanscc.txt

     Put one Telegram channel per line. Valid formats:

       @example_channel
       https://t.me/another_channel
       1234567890
       example_group

--------------------------------------------------------------------------------
3. CONFIGURING THE SCRIPT  [HUMAN ACTION REQUIRED]
--------------------------------------------------------------------------------

Open the script file in a text editor. Find the CONFIG section near the top and
change these two lines:

  BEFORE:
    api_id = add yours
    api_hash = 'add yours'

  AFTER (example):
    api_id = 12345678
    api_hash = 'abc123def456ghi789jkl012mno345pqr678stu'

Optional settings you can adjust in the CONFIG section:

  Setting                         Default             What It Does
  ------------------------------  ------------------  -----------------------------------------
  TARGETS_FILE                    chinanscc.txt       Target list file to read
  MESSAGE_LIMIT                   300                 Max recent messages if no date range is set
  MESSAGE_START_DATE              None                Start of message collection window
  MESSAGE_END_DATE                None                End of message collection window
  MESSAGE_DEPTH_BY_DATE_RANGE     True                Keep walking back to MESSAGE_START_DATE
  MESSAGE_DATE_RANGE_MAX_MESSAGES 5000                Safety cap for date-range collection
  MEMBER_LIMIT                    5000                Max members to enumerate
  ENABLE_MEMBER_ENUM              True                Whether to collect the member list
  INCLUDE_MESSAGE_TEXT            True                Whether to save message text
  EXTRACT_URLS                    True                Extract URLs into messages.csv/url_mentions.csv
  INCLUDE_FORWARD_ORIGIN          True                Add forward-origin fields to messages.csv
  INCLUDE_MEDIA_METADATA          True                Add media/web-preview fields to messages.csv
  ENABLE_USERINFOBOT              True                Use userinfobot for enrichment
  ENABLE_SANGMATA                 True                Use SangMataInfo_bot for history
  LOCAL_TZ_NAME                   America/New_York    Local timezone for timestamps
  DISCOVERED_ENRICHMENT_LIMIT     100                 Max users to enrich in the second pass

Date-range examples:

  MESSAGE_START_DATE = "2025-01-01"
  MESSAGE_END_DATE = "2025-01-31T23:59:59Z"

If MESSAGE_START_DATE is set and MESSAGE_DEPTH_BY_DATE_RANGE is True, SEMOR will
use MESSAGE_DATE_RANGE_MAX_MESSAGES instead of MESSAGE_LIMIT so it can reach the
requested historical window. Messages outside the configured date range are
skipped.

--------------------------------------------------------------------------------
4. RUNNING THE SCRIPT
--------------------------------------------------------------------------------

Open a terminal in the folder containing the script and run:

  python semor_enhanced.py

First-Time Login:
  The first time you run the script, Telegram will ask you to verify your
  identity. You will see prompts like:

    Please enter your phone (or bot token): +12025551234
    Please enter the code you received: 12345

  Enter your phone number with country code and the verification code Telegram
  sends you. A session file (tg_session.session) is created so future runs do
  not require re-authentication.

What You Will See While Running:

    [+] Loaded 5 targets
    [+] Processing @example_channel (1/5)
    [✓] @example_channel: type=Channel, admins=3, members=1200, messages=300

  Delays between requests are intentional. Do not run multiple instances at the
  same time.

--------------------------------------------------------------------------------
5. OUTPUT FILES — WHAT GETS CREATED
--------------------------------------------------------------------------------

When finished, you will find these CSV files in the same folder.

  admins.csv
      Admin users for each channel, with user IDs and usernames.

  group_members.csv
      All enumerated members, including bot/verified/scam/fake flags.

  messages.csv
      Individual messages: sender, timestamp, text, views, forwards, reply
      links, extracted URL summary, forward-origin fields, and media metadata.

      New enhanced columns include:
        is_forwarded, forward_date_utc, forward_from_id, forward_from_name,
        forward_channel_post, forward_post_author, forward_saved_from_peer_id,
        forward_saved_from_msg_id, forward_psa_type, url_count, urls_json,
        urls_flat, has_media, media_type, mime_type, file_name, file_size,
        duration_seconds, width, height, photo_id, document_id, sticker_alt,
        webpage_url, webpage_display_url, webpage_title, webpage_site_name,
        media_attributes_json.

  url_mentions.csv
      One row per extracted URL. Use this file to pivot by domain, message,
      source type, user, or target.

  target_status.csv
      Run summary: whether each channel was accessible, errors if any, and the
      configured message date-range settings used for the run.

  target_metadata.csv
      Channel-level info: title, type, member count, creation date,
      scam/verified flags.

  user_map.csv
      Simple lookup table: Telegram user ID to current username.

  user_first_seen.csv
      Earliest timestamp each user was observed across all targets.

  usernames_by_user.csv
      All usernames observed for each user ID during the scrape.

  user_target_overlap.csv
      Which targets each user appeared in, and how many.

  multi_target_users.csv
      Users who appeared in more than one target channel.

  user_target_message_counts.csv
      How many messages each user posted in each target.

  early_users_by_target.csv
      The first 50 users to post in each channel.

  first_seen_clusters_1h.csv
      Histogram of new user arrivals by one-hour window.

  user_enriched_profiles.csv
      Consolidated profile per user: all targets seen, usernames, first-seen dates.

  top_posters_by_target.csv
      Top 50 most active posters per channel, with message share percentage.

  reply_edges.csv
      Each individual reply event: who replied to whom.

  reply_summary_by_user.csv
      Aggregated reply counts between users.

  translated_messages.csv
      Translated versions of non-English messages if translation is enabled.

  bot_enrichment.csv
      Raw responses from userinfobot and SangMataInfo_bot.

--------------------------------------------------------------------------------
6. ANALYZING YOUR RESULTS
--------------------------------------------------------------------------------

6.1  Start With target_status.csv
     Confirm which channels resolved, which were accessible, and what message
     date-range settings were active during the run.

6.2  Finding Cross-Channel Users (multi_target_users.csv)
     Sort by target_count descending to find users present in the most channels.

6.3  Identifying Top Posters (top_posters_by_target.csv)
     Sort by message_count descending. A high message_share_pct may indicate a
     bot, administrator, or heavy influencer.

6.4  Detecting Coordinated Joins (first_seen_clusters_1h.csv)
     Chart user_count by first_seen_bucket_1h to detect spikes.

6.5  Tracking Username Changes
     Use usernames_by_user.csv and bot_enrichment.csv together.

6.6  Reply Network Analysis (reply_summary_by_user.csv)
     Import rows into Gephi or Maltego as edges between src_user_id and dst_user_id.

6.7  Forward-Origin Analysis (messages.csv)
     Filter is_forwarded = True. Group by forward_from_id, forward_from_name, or
     forward_saved_from_peer_id to identify recurring source channels or upstream
     origin accounts.

6.8  URL / Domain Analysis (url_mentions.csv)
     Normalize domains from the url column, then pivot by target, user_id, source,
     and date_utc. The source column shows whether the URL came from regex text,
     a URL entity, or a text-link entity.

6.9  Media Analysis (messages.csv)
     Filter has_media = True. Use media_type, mime_type, file_name, file_size,
     duration_seconds, width, height, and webpage_* columns to identify repeated
     media, web previews, documents, stickers, video, or audio.

6.10 Date-Range Depth Analysis
     Use MESSAGE_START_DATE and MESSAGE_END_DATE to compare the same channel set
     across specific windows. Keep MESSAGE_DATE_RANGE_MAX_MESSAGES high enough to
     reach the requested start date, but conservative enough to avoid excessive API
     pressure.

--------------------------------------------------------------------------------
7. TROUBLESHOOTING COMMON ISSUES
--------------------------------------------------------------------------------

Problem: api_id is invalid / syntax error on startup
Solution: Make sure you replaced placeholder values and did not quote api_id.

Problem: Flood wait error
Solution: Telegram is rate-limiting you. Let the script wait, increase sleeps,
          reduce target count, reduce date-range depth, or disable enrichment.

Problem: Date-range run does not reach MESSAGE_START_DATE
Solution: Increase MESSAGE_DATE_RANGE_MAX_MESSAGES or narrow the target list/window.

Problem: Channel shows resolved=False in target_status.csv
Solution: The channel may be private, deleted, or inaccessible to your account.

Problem: member_access=False but message_access=True
Solution: Member enumeration only works for megagroups, not broadcast channels.

Problem: url_mentions.csv is empty
Solution: Confirm EXTRACT_URLS = True and that collected messages contain URLs or
          Telegram link entities.

Problem: Media columns are empty
Solution: Confirm INCLUDE_MEDIA_METADATA = True. Text-only messages will not have
          media fields.

Problem: Bot enrichment shows empty results
Solution: Try messaging the bots manually from the research account.

Problem: SessionPasswordNeededError during login
Solution: Your account has two-factor authentication; enter the Telegram password.

--------------------------------------------------------------------------------
IMPORTANT NOTE
--------------------------------------------------------------------------------

All data collected using this tool should be handled according to your organization's
policies on open-source intelligence and applicable privacy regulations.

================================================================================
SEMOR Telegram OSINT Scraper — User Guide
================================================================================
