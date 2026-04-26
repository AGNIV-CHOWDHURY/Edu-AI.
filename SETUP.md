# EduAI — Deployment & Setup Guide

## 🐛 Bug Fixes Applied

### 1. Sign-in not working / forced to create new account on every visit

**Root cause A — Ephemeral SQLite database:**
Render's free tier does not persist files between deploys or restarts.
The `sqlite:///eduai.db` file was wiped on every restart, deleting all user accounts.

**Fix:** Added a PostgreSQL database to `render.yaml`. You must link Render's Postgres
addon (see setup steps below). The app now reads `DATABASE_URL` from the environment
and also corrects the `postgres://` → `postgresql://` URL prefix that Render emits
but SQLAlchemy requires.

**Root cause B — Regenerating SECRET_KEY:**
`render.yaml` had `generateValue: true` on `SECRET_KEY`, which generated a brand-new
random key on every deploy. Flask uses this key to sign session cookies — when it
changes, every existing session (login) is invalidated, and users appear to be
"logged out / new user".

**Fix:** Removed `generateValue: true`. You must now manually set a stable
`SECRET_KEY` in the Render dashboard (see setup steps below).

---

## 🚀 Deployment Steps (Render)

### Step 1 — Create a PostgreSQL database on Render
1. Go to your Render dashboard → **New → PostgreSQL**
2. Name it `eduai-db`, choose the **Free** plan, click **Create Database**
3. Copy the **Internal Database URL** from the database info page

### Step 2 — Set environment variables
In your Render **Web Service** → **Environment**, add:

| Key | Value |
|-----|-------|
| `SECRET_KEY` | A long random string. Generate one: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | The Internal Database URL you copied in Step 1 |
| `GEMINI_API_KEY` | Your Google Gemini API key |
| `PINECONE_API_KEY` | Your Pinecone API key |
| `DAILY_API_KEY` | Your Daily.co API key (for video classes — see below) |

### Step 3 — Deploy
Push to your repo or trigger a manual deploy. The app will auto-create all tables on first boot.

---

## 📹 Video Conferencing Setup (Daily.co)

The app uses [Daily.co](https://daily.co) for in-app video classes. It's **free** for up to 1,000 minutes/month.

1. Sign up at https://dashboard.daily.co
2. Go to **Developers** → copy your **API key**
3. Set `DAILY_API_KEY` in your Render environment variables
4. Redeploy — teachers can now schedule and host live video classes from the **📹 Classes** tab

### How it works
- **Teacher** clicks **📹 Classes** → **Schedule Class** → fills in title, date/time, duration
- A Daily.co room is automatically created
- Teacher copies the **Student Link** and shares it (via WhatsApp, email, etc.)
- Students open the link or go to **📹 Classes** in their portal and click **Join Now**
- Both teacher and students are in the same embedded video call — no app download needed

### Without a Daily.co key
The app still works — classes are scheduled and listed, but the in-app video embed
won't load. Students receive an error message. Add the API key and redeploy to fix this.

---

## 🔑 .env (for local development)

```
SECRET_KEY=your-local-dev-secret
DATABASE_URL=sqlite:///eduai.db
GEMINI_API_KEY=...
PINECONE_API_KEY=...
PINECONE_INDEX_NAME=eduai-students
DAILY_API_KEY=...
```

Run locally:
```bash
pip install -r requirements.txt
python app.py
```
