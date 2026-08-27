# ChatTrak

CS2 in-game chat analytics from [cstracker.gg](https://cstracker.gg) — fetch, analyze, and leaderboard dashboard.

## Local workflow

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1. Fetch chat (Steam URLs in steam_links.txt)
python fetch_player_chat.py --links-file steam_links.txt --output-dir data --continue-on-error

# 2. Enrich with Steam names/avatars
python enrich_steam_profiles.py

# 3. Analyze + build leaderboard JSON
python analyze_chat_stats.py

# 4. Preview locally
python serve_dashboard.py
# open http://127.0.0.1:8765/dashboard/

# 5. Build static site for GitHub Pages
python build_pages.py
```

Edit categories in `configs/chat_categories.json`, then re-run step 3–5.

## GitHub Pages

The site deploys from the `docs/` folder via GitHub Actions on push to `main`.

After updating stats locally:

```bash
python analyze_chat_stats.py
python enrich_steam_profiles.py   # if profiles changed
python build_pages.py
git add data/stats data/steam_profiles.json docs configs
git commit -m "Update leaderboard data"
git push
```

Enable Pages once in the repo: **Settings → Pages → Source: GitHub Actions**.

Live URL: `https://<username>.github.io/cstracker-tools/dashboard/`

## Push to a different GitHub account

```bash
# Log in with your other account (adds a second gh credential)
gh auth login

# Switch active account
gh auth switch

# Create repo under that account and push
gh repo create cstracker-tools --public --source=. --remote=origin --push
```

If the repo already exists on the other account:

```bash
git remote add origin git@github.com:OTHER_USER/cstracker-tools.git
git push -u origin main
```

Then enable **Pages → GitHub Actions** on that repo.
