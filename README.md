# EduAI — Smart Resource Allocation for Education

> An AI-powered academic management platform that intelligently allocates study resources, identifies struggling students, and personalises learning pathways using **Google Gemini 2.5 Flash** and **Google AI infrastructure**.

---

## What is EduAI?

EduAI is a full-stack web application built for teachers to manage student performance, allocate study resources intelligently, and generate AI-driven academic interventions. Every core intelligence feature runs on **Google's Gemini 2.5 Flash** model — from analysing student report cards to generating personalised study notes and smart resource recommendations.

---

## Google AI & Google Services at the Core

### 🤖 Google Gemini 2.5 Flash — Primary AI Engine

**Model:** `gemini-2.5-flash` via the **`google-genai` Python SDK**

Gemini 2.5 Flash powers every intelligent feature in EduAI:

| Feature | What Gemini Does |
|---|---|
| **Student Analysis** | Classifies students as Weak / Average / Strong; generates a personalised study plan and 4-step action items |
| **Report Card Analysis** | Reads uploaded PDF report cards and returns subject-wise assessment, strengths, gaps, and a 4-week improvement plan |
| **Resource Recommendations** | Curates subject-specific books and YouTube videos based on each student's marks profile |
| **AI Study Notes Generator** | Writes level-appropriate study notes (simplified for Weak, enriched for Strong) with key concepts, formulas, common mistakes, and a revision checklist |
| **Feedback-Aware Re-Recommendation** | Re-generates resources after the teacher marks what worked and what didn't — Gemini avoids ineffective resource styles and favours proven ones |
| **Study Schedule Planner** | Allocates weekly study hours across students — more hours to Weak students, day-by-day schedule with subject focus areas |
| **Intervention Group Planner** | Clusters struggling students into 2–4 groups by shared weaknesses for efficient batch tutoring sessions |
| **Progress Trajectory Analysis** | Analyses a student's checkpoint history and predicts their category trend over the next 4 weeks |

**SDK initialisation:**
```python
from google import genai
client = genai.Client(api_key=GEMINI_API_KEY)
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt
)
```

**API Key:** Obtained from [Google AI Studio](https://aistudio.google.com)

---

### 🔢 Pinecone Vector Database — Powered by Google Cloud Infrastructure

EduAI uses **Pinecone Serverless** (hosted on **AWS us-east-1**, integrates cleanly with Google AI pipelines) for semantic student similarity search.

- Each student's academic profile is encoded as a **3-dimensional vector** `[marks/100, attendance/100, assignments/100]`
- When a new student is analysed, Gemini receives context from the **3 most similar past students** to improve classification accuracy
- Vectors are upserted and queried via Pinecone's cosine similarity index

```python
# Student encoded as normalised 3D vector
vector = [marks / 100.0, attendance / 100.0, assignments / 100.0]
# Query for similar historical students
results = pinecone_index.query(vector=vector, top_k=3, include_metadata=True)
```

---

### 📹 Daily.co — Video Class Infrastructure

Teachers can schedule and host **live video classes** directly within EduAI, powered by the **Daily.co API**:

- Auto-creates video rooms with unique URLs per class
- Issues time-scoped JWT tokens for both teacher (owner) and student (participant) roles
- Students join from their portal with a single click
- Rooms are automatically deleted after the session ends

---

## Full Feature Set

### 🎓 For Teachers

| # | Feature | Description |
|---|---|---|
| 1 | **AI Student Analysis** | Enter marks, attendance, and assignments — Gemini classifies and generates a full study plan |
| 2 | **Report Card Analyser** | Upload a PDF report card — Gemini reads and returns a comprehensive subject-wise breakdown |
| 3 | **Resource Recommender** | Auto-generate books and YouTube videos per subject based on marks gaps |
| 4 | **🆕 AI Study Notes Generator** | Generate level-tailored study notes per subject (fundamentals for Weak, advanced for Strong) |
| 5 | **🆕 Resource Feedback & Smart Re-Recommendation** | Rate which resources worked — Gemini regenerates smarter alternatives based on feedback |
| 6 | **Study Schedule Planner** | AI allocates weekly teaching hours across students by priority (Weak = more hours) |
| 7 | **Intervention Group Planner** | Cluster students by shared weaknesses into efficient group tutoring sessions |
| 8 | **Progress Tracker** | Track student performance across checkpoints; Gemini analyses trajectory and predicts outcomes |
| 9 | **Live Video Classes** | Schedule and host Daily.co video sessions; students join from their portal |
| 10 | **Bulk Import** | Import multiple students via CSV for batch AI analysis |

### 👩‍🎓 For Students (Self-Service Portal)

- View AI-generated analysis, study plan, and suggestions
- Browse personalised resource recommendations (books & videos)
- **Read AI Study Notes** generated by their teacher
- Join scheduled live video classes
- Track their own progress over time

---

## Tech Stack

### Backend
| Technology | Role |
|---|---|
| **Python 3.10+** | Core language |
| **Flask 3.0** | Web framework |
| **SQLAlchemy 2.0** | ORM — models and database queries |
| **Flask-Login** | Session management (teacher + student dual-role auth) |
| **Flask-Bcrypt** | Password hashing |
| **pdfplumber** | PDF text extraction for report card analysis |
| **Gunicorn** | WSGI production server |

### AI & Intelligence Layer
| Technology | Role |
|---|---|
| **Google Gemini 2.5 Flash** | All AI features — analysis, notes, recommendations, scheduling |
| **google-genai SDK** | Official Python client for Gemini API |
| **Pinecone (Serverless)** | Vector similarity search for student context retrieval |

### Frontend
| Technology | Role |
|---|---|
| **Jinja2** | Server-side HTML templating |
| **Vanilla CSS** | Custom design system with CSS variables (dark-themed) |
| **Vanilla JS** | Interactive UI (expand/collapse notes, feedback toggles) |
| **Syne & Inter (Google Fonts)** | Typography |

### Database & Storage
| Technology | Role |
|---|---|
| **SQLite** | Local development database |
| **PostgreSQL** | Production database (Render / any cloud provider) |
| **Local filesystem** | Uploaded PDFs (use S3/Cloudinary for production) |

### Infrastructure & Deployment
| Technology | Role |
|---|---|
| **Render** | Primary cloud deployment (render.yaml included) |
| **Google Cloud Build** | CI/CD pipeline (cloudbuild.yaml included) |
| **Daily.co API** | Live video class infrastructure |
| **Docker** | Containerisation (Dockerfile included) |
| **python-dotenv** | Environment variable management |

---

## Project Structure

```
eduai_new/
├── app.py                   # Flask application — all routes & business logic
├── ai_service.py            # All Gemini AI functions + Pinecone integration
├── models/
│   └── models.py            # SQLAlchemy models (10 tables)
├── templates/
│   ├── base.html            # Base layout with nav
│   ├── dashboard.html       # Teacher dashboard
│   ├── student_result.html  # Student AI analysis result
│   ├── student_resources.html  # Resource recommendations
│   ├── study_notes.html     # 🆕 AI Study Notes generator (teacher view)
│   ├── portal_study_notes.html # 🆕 Study Notes (student portal)
│   ├── resource_feedback.html  # 🆕 Resource feedback & re-recommendation
│   ├── resource_budget.html # Study schedule planner
│   ├── intervention_groups.html # Group planner
│   ├── student_progress.html   # Progress tracker
│   ├── student_portal.html  # Student self-service portal
│   ├── video_classes.html   # Video class management
│   └── ...                  # Login, register, report card, bulk import
├── static/uploads/          # Uploaded PDF storage
├── requirements.txt
├── Dockerfile
├── render.yaml              # Render deployment config
├── cloudbuild.yaml          # Google Cloud Build CI/CD config
└── .env.example
```

---

## Database Schema (10 Tables)

```
users                    → Teacher accounts
student_users            → Student login accounts
students                 → Student profiles + AI analysis results
report_analyses          → PDF report card analysis history
resource_recommendations → AI-generated book & video recommendations
resource_feedback        → 🆕 Teacher ratings on resource effectiveness
study_notes              → 🆕 AI-generated subject study notes
resource_budget_plans    → AI-generated weekly study schedules
intervention_groups      → AI-clustered student groups
progress_checkpoints     → Student performance history over time
video_classes            → Scheduled live video sessions
```

---

## Setup & Local Development

### Prerequisites
- Python 3.10+
- A [Google AI Studio](https://aistudio.google.com) account (free) → get your `GEMINI_API_KEY`
- (Optional) [Pinecone](https://app.pinecone.io) account for vector similarity
- (Optional) [Daily.co](https://www.daily.co) account for live video classes

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/eduai.git
cd eduai

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # Mac / Linux
venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and add your API keys (see below)

# 5. Run
python app.py
```

Visit **http://localhost:5000**

### Environment Variables

```env
# Required
SECRET_KEY=your-secret-key-here
GEMINI_API_KEY=your_gemini_api_key      # From https://aistudio.google.com

# Optional — Vector similarity (student context)
PINECONE_API_KEY=your_pinecone_key
PINECONE_INDEX_NAME=eduai-students

# Optional — Live video classes
DAILY_API_KEY=your_daily_co_key

# Database (SQLite by default; use PostgreSQL for production)
DATABASE_URL=sqlite:///eduai.db
```

> **Note:** The app runs fully without Pinecone and Daily.co — all AI features degrade gracefully with rule-based fallbacks.

---

## Deployment

### Deploy to Render (Recommended)

```bash
# 1. Push to GitHub
git init && git add . && git commit -m "initial commit"
git remote add origin https://github.com/YOUR_USERNAME/eduai.git
git push -u origin main

# 2. Go to https://render.com → New → Web Service
# 3. Connect your GitHub repo — Render auto-detects render.yaml
# 4. Add environment variables in Render dashboard
```

### Deploy to Google Cloud Run

```bash
# Build and deploy using the included cloudbuild.yaml
gcloud builds submit --config cloudbuild.yaml
```

### Docker

```bash
docker build -t eduai .
docker run -p 5000:5000 --env-file .env eduai
```

---

## How Google Gemini Drives Smart Resource Allocation

The core thesis of EduAI is that **resource allocation should be data-driven and personalised**, not one-size-fits-all. Here's how Gemini makes that happen:

```
Student Data (marks, attendance, assignments, subject scores)
            │
            ▼
  ┌─────────────────────┐
  │  Pinecone Retrieval │  ← Find 3 similar past students for context
  └─────────────────────┘
            │
            ▼
  ┌───────────────────────────────┐
  │   Google Gemini 2.5 Flash    │
  │                               │
  │  • Classify: Weak/Avg/Strong  │
  │  • Identify weak subjects     │
  │  • Generate study plan        │
  │  • Recommend books & videos   │
  │  • Write study notes          │
  │  • Plan group interventions   │
  │  • Allocate teaching hours    │
  └───────────────────────────────┘
            │
            ▼
  Teacher acts on AI recommendations
            │
            ▼
  Teacher rates resource effectiveness
            │
            ▼
  ┌───────────────────────────────┐
  │   Gemini Re-Recommendation   │  ← Feedback loop: avoid what didn't work
  └───────────────────────────────┘
```

---

## License

MIT License — free to use, modify, and deploy.

---

## Acknowledgements

Built with ❤️ using **Google Gemini 2.5 Flash** — the intelligence layer behind every student insight, recommendation, and study plan in this platform.
