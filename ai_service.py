import os
import json
import time
from dotenv import load_dotenv

load_dotenv()

# ─── Gemini (google-genai SDK) ────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = "gemini-2.5-flash"   # <-- updated
_gemini_client = None

def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None and GEMINI_API_KEY:
        try:
            from google import genai
            _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception as e:
            print(f"[Gemini] client init error: {e}")
    return _gemini_client


# ─── Pinecone (v3 SDK) ────────────────────────────────────────────────────────
# Vectors: [marks/100, attendance/100, assignments/100]  →  dim=3
# Create your index in Pinecone with dimension=3, metric=cosine
# OR let _init_pinecone() create it automatically (Serverless, AWS us-east-1).
PINECONE_API_KEY    = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "eduai-students")
VECTOR_DIM          = 3

pinecone_available = False
pinecone_index     = None
_pc                = None


def _init_pinecone():
    global pinecone_available, pinecone_index, _pc
    if not PINECONE_API_KEY:
        print("[Pinecone] No API key — vector storage disabled.")
        return
    try:
        from pinecone import Pinecone, ServerlessSpec
        _pc = Pinecone(api_key=PINECONE_API_KEY)

        existing_names = [idx.name for idx in _pc.list_indexes()]

        if PINECONE_INDEX_NAME not in existing_names:
            print(f"[Pinecone] Creating index '{PINECONE_INDEX_NAME}' (dim={VECTOR_DIM}) …")
            _pc.create_index(
                name=PINECONE_INDEX_NAME,
                dimension=VECTOR_DIM,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
            # Poll until ready
            for _ in range(20):
                info = _pc.describe_index(PINECONE_INDEX_NAME)
                if getattr(info.status, "ready", False):
                    break
                time.sleep(2)
            print(f"[Pinecone] Index ready.")

        pinecone_index     = _pc.Index(PINECONE_INDEX_NAME)
        pinecone_available = True
        print(f"[Pinecone] Connected to '{PINECONE_INDEX_NAME}'.")
    except Exception as e:
        print(f"[Pinecone] Init failed: {e}")


_init_pinecone()


# ─── System Prompt ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an advanced AI assistant integrated into a web-based academic support system.
Analyze the student data carefully. Classify the student into one of three categories:
Weak, Average, or Strong based on overall academic performance.

Your output MUST follow this EXACT format with these exact labels:
Category: <Weak/Average/Strong>
Reason: <clear short explanation in 1-2 sentences>
Weak Areas: <comma separated list or 'None'>
Suggestions:
- <suggestion 1>
- <suggestion 2>
- <suggestion 3>
- <suggestion 4>
Study Plan:
Step 1: <action>
Step 2: <action>
Step 3: <action>

Be concise, structured, and actionable."""


# ─── Student Analysis ─────────────────────────────────────────────────────────
def analyze_student(name, marks, attendance, assignments, similar_context=""):
    """Analyze student performance using Gemini 2.5 Flash."""
    try:
        client = _get_gemini_client()
        if not client:
            return _fallback_analysis(marks, attendance, assignments)

        context_block = (
            f"\nSimilar past students for context: {similar_context}"
            if similar_context else ""
        )
        prompt = (
            f"Analyze this student's academic performance:\n\n"
            f"Student Name: {name}\n"
            f"Marks (out of 100): {marks}\n"
            f"Attendance (%): {attendance}\n"
            f"Assignment Score (out of 100): {assignments}"
            f"{context_block}\n\n"
            f"{SYSTEM_PROMPT}"
        )
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print(f"[Gemini] analyze_student error: {e}")
        return _fallback_analysis(marks, attendance, assignments)


# ─── Report Card Analysis ─────────────────────────────────────────────────────
def analyze_report_card(pdf_text, filename=""):
    """Analyze a report card PDF using Gemini 2.5 Flash."""
    try:
        client = _get_gemini_client()
        if not client:
            return (
                "Gemini API key not configured. "
                "Please add GEMINI_API_KEY to your .env file."
            )
        prompt = f"""You are an expert academic advisor analyzing a student's report card.

Report Card Content:
{pdf_text}

Please provide a comprehensive analysis covering:

1. **Overall Grade Assessment** — Weak / Average / Strong with justification.
2. **Subject-wise Analysis** — Each subject, its score, and a one-line comment.
3. **Key Strengths** — Where the student excels.
4. **Areas Needing Improvement** — Subjects or skills requiring work.
5. **Personalized Recommendations**
   - Weak student: specific improvement strategies, study techniques, weekly schedule.
   - Average student: targeted steps to reach excellence, weak-spot reinforcement.
   - Strong student: advanced / challenging questions per subject, enrichment activities, competitions, higher coursework.
6. **4-Week Study Plan** — Practical week-by-week action plan.

Use clear headings (**bold**), bullet points, and an encouraging tone. Be specific and actionable."""

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        return response.text
    except Exception as e:
        return f"Analysis error: {e}. Please verify your Gemini API key."


# ─── Pinecone helpers ─────────────────────────────────────────────────────────
def _student_vector(marks, attendance, assignments):
    """Return a normalised 3-D vector."""
    return [round(marks / 100.0, 4),
            round(attendance / 100.0, 4),
            round(assignments / 100.0, 4)]


def get_similar_students(marks, attendance, assignments):
    """Query Pinecone for the 3 most similar past students and return context."""
    if not pinecone_available or pinecone_index is None:
        return ""
    try:
        vec = _student_vector(marks, attendance, assignments)
        results = pinecone_index.query(
            vector=vec,
            top_k=3,
            include_metadata=True,
        )
        parts = []
        for match in results.get("matches", []):
            meta = match.get("metadata", {})
            if meta:
                parts.append(
                    f"Student with marks={meta.get('marks')}, "
                    f"attendance={meta.get('attendance')}, "
                    f"assignments={meta.get('assignments')} "
                    f"→ classified as {meta.get('category')}"
                )
        return "; ".join(parts)
    except Exception as e:
        print(f"[Pinecone] query error: {e}")
    return ""


def store_student_in_pinecone(student_id, marks, attendance, assignments, category):
    """Upsert a student vector into Pinecone. Returns the vector ID or None."""
    if not pinecone_available or pinecone_index is None:
        return None
    try:
        vec = _student_vector(marks, attendance, assignments)
        pid = f"student-{student_id}"
        pinecone_index.upsert(vectors=[{
            "id": pid,
            "values": vec,
            "metadata": {
                "marks":       float(marks),
                "attendance":  float(attendance),
                "assignments": float(assignments),
                "category":    category,
            },
        }])
        print(f"[Pinecone] Upserted {pid}.")
        return pid
    except Exception as e:
        print(f"[Pinecone] upsert error: {e}")
    return None


# ─── Response parser ──────────────────────────────────────────────────────────
def parse_analysis(text):
    """Parse the structured Gemini response into a dict."""
    result = {
        "category":   "Average",
        "reason":     "",
        "weak_areas": "",
        "suggestions": [],
        "study_plan":  [],
    }
    lines   = text.strip().split("\n")
    section = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Category:"):
            val = line.split(":", 1)[1].strip()
            for cat in ("Strong", "Average", "Weak"):
                if cat.lower() in val.lower():
                    result["category"] = cat
                    break
        elif line.startswith("Reason:"):
            result["reason"] = line.split(":", 1)[1].strip()
            section = "reason"
        elif line.startswith("Weak Areas:"):
            result["weak_areas"] = line.split(":", 1)[1].strip()
            section = "weak_areas"
        elif line.startswith("Suggestions:"):
            section = "suggestions"
        elif line.startswith("Study Plan:"):
            section = "study_plan"
        elif section == "suggestions" and line.startswith("-"):
            result["suggestions"].append(line[1:].strip())
        elif section == "study_plan" and (
            line.lower().startswith("step") or
            (len(line) > 2 and line[0].isdigit() and line[1] in ".)")
        ):
            result["study_plan"].append(line)
        elif section == "reason":
            # continuation of reason on next line
            stop_keys = ("Weak Areas:", "Suggestions:", "Study Plan:")
            if not any(line.startswith(k) for k in stop_keys):
                result["reason"] += " " + line

    # Fallback bullet harvest
    if not result["suggestions"]:
        for raw in lines:
            line = raw.strip()
            if line.startswith(("•", "-")) and len(line) > 2:
                result["suggestions"].append(line[1:].strip())

    return result


# ─── Feature 1: Resource Recommendations ─────────────────────────────────────
def recommend_resources(name, weak_areas, category, marks, attendance, assignments, subject_marks=None):
    """Generate subject-by-subject book + YouTube video recommendations based on marks analysis."""
    try:
        client = _get_gemini_client()
        if not client:
            return _fallback_resources(weak_areas, category, subject_marks)

        # Build subject marks section
        subject_section = ""
        if subject_marks:
            try:
                sm = subject_marks if isinstance(subject_marks, dict) else json.loads(subject_marks)
                lines = [f"  - {subj}: {score}/100" for subj, score in sm.items()]
                subject_section = "Subject-wise Marks:\n" + "\n".join(lines)
            except Exception:
                subject_section = ""

        prompt = f"""You are an expert educational resource curator. Analyse the student's subject-wise performance and recommend specific books and YouTube videos for each weak subject.

Student: {name}
Category: {category}
Overall Marks: {marks}/100, Attendance: {attendance}%, Assignments: {assignments}/100
Weak Areas: {weak_areas or 'General improvement needed'}
{subject_section}

Rules:
- For every subject where marks < 70, recommend 1 book AND 1 YouTube video.
- If no subject_marks are provided, use the weak_areas and overall marks to infer 3-4 subjects and recommend resources for those.
- Books: prefer well-known textbooks or widely available titles (include author name in title).
- YouTube videos: use real YouTube search URLs in format https://www.youtube.com/results?search_query=TOPIC+tutorial
- Each resource must have: subject, type (book or youtube), title, url, reason, priority (high/medium/low).
- priority = high if subject marks < 50, medium if 50-69, low otherwise.

Respond ONLY with a valid JSON array, no markdown, no preamble:
[
  {{"subject": "Mathematics", "type": "book", "title": "NCERT Mathematics Class 10 by R.D. Sharma", "url": "https://www.amazon.in/s?k=RD+Sharma+Mathematics", "reason": "Covers all core topics with practice problems", "priority": "high"}},
  {{"subject": "Mathematics", "type": "youtube", "title": "Class 10 Maths Full Course – Vedantu", "url": "https://www.youtube.com/results?search_query=class+10+maths+full+course+vedantu", "reason": "Step-by-step video explanations matching school syllabus", "priority": "high"}},
  ...
]"""
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return text.strip()
    except Exception as e:
        print(f"[Gemini] recommend_resources error: {e}")
        return _fallback_resources(weak_areas, category, subject_marks)


def _fallback_resources(weak_areas, category, subject_marks=None):
    subjects = []
    if subject_marks:
        try:
            sm = subject_marks if isinstance(subject_marks, dict) else json.loads(subject_marks)
            subjects = [s for s, score in sm.items() if score < 70]
        except Exception:
            pass
    if not subjects:
        subjects = ["Mathematics", "Science", "English"]

    resources = []
    for subj in subjects[:4]:
        q = subj.lower().replace(" ", "+")
        resources.append({
            "subject": subj,
            "type": "book",
            "title": f"NCERT {subj} Textbook",
            "url": f"https://www.amazon.in/s?k=NCERT+{subj.replace(' ', '+')}+textbook",
            "reason": f"Standard reference covering all core {subj} topics",
            "priority": "high"
        })
        resources.append({
            "subject": subj,
            "type": "youtube",
            "title": f"{subj} Full Course – Free Lectures",
            "url": f"https://www.youtube.com/results?search_query={q}+full+course+tutorial",
            "reason": f"Visual, step-by-step {subj} explanations",
            "priority": "high"
        })
    return json.dumps(resources)


# ─── Feature 5: AI Study Notes Generator ─────────────────────────────────────
def generate_study_notes(name, subject, category, marks, subject_score=None):
    """Generate concise, level-appropriate AI study notes for a subject."""
    try:
        client = _get_gemini_client()
        if not client:
            return _fallback_study_notes(subject, category)

        level_context = {
            "Weak": "The student is struggling with this subject. Keep explanations simple, use analogies, focus on the most fundamental concepts first.",
            "Average": "The student has a basic understanding. Bridge gaps, clarify misconceptions, and reinforce key formulas/concepts.",
            "Strong": "The student performs well. Provide enriched content, advanced tips, exam strategy, and challenge-level insights.",
        }.get(category, "Provide clear, helpful notes.")

        score_line = f"Subject Score: {subject_score}/100\n" if subject_score is not None else ""

        prompt = f"""You are an expert {subject} teacher creating personalised study notes for a student.

Student: {name}
Category: {category}
{score_line}{level_context}

Create comprehensive yet concise study notes for **{subject}** that are perfectly tailored to this student's level.

Structure your notes EXACTLY as follows (use markdown):

## 📌 Key Concepts
List and briefly explain the 4-6 most important concepts the student must know.

## 📐 Formulas & Rules
(if applicable) List key formulas, rules, or definitions in a scannable format.

## 💡 Common Mistakes to Avoid
3-4 bullet points on mistakes students at this level typically make.

## ✏️ Practice Strategy
A short, actionable 3-step practice approach suited to the student's category.

## 🎯 Quick Revision Checklist
5-7 checkbox items the student can tick off before an exam.

Keep the tone encouraging, clear, and practical. Use simple language for Weak students, standard academic language for Average, and precise technical language for Strong."""

        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return response.text
    except Exception as e:
        print(f"[Gemini] generate_study_notes error: {e}")
        return _fallback_study_notes(subject, category)


def _fallback_study_notes(subject, category):
    return f"""## 📌 Key Concepts
- Review your class textbook chapters for {subject}
- Focus on definitions, theorems and solved examples

## 📐 Formulas & Rules
- Refer to your formula sheet or textbook appendix for {subject} formulas

## 💡 Common Mistakes to Avoid
- Not practising enough problems
- Skipping steps in working
- Ignoring units or labels in answers

## ✏️ Practice Strategy
1. Re-read your notes from class
2. Solve 5 practice problems daily
3. Review errors and understand why they happened

## 🎯 Quick Revision Checklist
- [ ] Read chapter summary
- [ ] Memorise key formulas
- [ ] Solve past exam questions
- [ ] Review marked homework
- [ ] Ask teacher about unclear topics"""


# ─── Feature 6: Resource Feedback-Aware Re-Recommendation ────────────────────
def recommend_resources_with_feedback(name, weak_areas, category, marks, attendance,
                                      assignments, subject_marks=None, feedback=None):
    """Re-generate resource recommendations informed by what worked/didn't work before."""
    try:
        client = _get_gemini_client()
        if not client:
            return _fallback_resources(weak_areas, category, subject_marks)

        # Build subject marks section
        subject_section = ""
        if subject_marks:
            try:
                sm = subject_marks if isinstance(subject_marks, dict) else json.loads(subject_marks)
                lines = [f"  - {subj}: {score}/100" for subj, score in sm.items()]
                subject_section = "Subject-wise Marks:\n" + "\n".join(lines)
            except Exception:
                subject_section = ""

        # Build feedback section
        feedback_section = ""
        if feedback:
            try:
                fb = feedback if isinstance(feedback, list) else json.loads(feedback)
                worked = [f"{f['subject']} – {f['type']} – \"{f['title']}\"" for f in fb if f.get("worked")]
                not_worked = [f"{f['subject']} – {f['type']} – \"{f['title']}\"" for f in fb if not f.get("worked")]
                if worked:
                    feedback_section += "\nPrevious resources that WORKED (similar style preferred):\n" + "\n".join(f"  ✓ {w}" for w in worked)
                if not_worked:
                    feedback_section += "\nPrevious resources that DID NOT WORK (avoid similar style/author):\n" + "\n".join(f"  ✗ {n}" for n in not_worked)
            except Exception:
                feedback_section = ""

        prompt = f"""You are an expert educational resource curator. Analyse the student's performance and FEEDBACK on previous resources to recommend better-targeted books and YouTube videos.

Student: {name}
Category: {category}
Overall Marks: {marks}/100, Attendance: {attendance}%, Assignments: {assignments}/100
Weak Areas: {weak_areas or 'General improvement needed'}
{subject_section}
{feedback_section}

Rules:
- For every weak subject (marks < 70), recommend 1 book AND 1 YouTube video.
- If a previous resource type WORKED for a subject, prefer a similar approach.
- If a resource DID NOT WORK, choose a completely different style, author, or channel.
- Books: prefer well-known textbooks or widely available titles (include author).
- YouTube videos: use real YouTube search URLs: https://www.youtube.com/results?search_query=TOPIC+tutorial
- Each resource must have: subject, type (book or youtube), title, url, reason, priority (high/medium/low).
- priority = high if marks < 50, medium if 50–69, low otherwise.

Respond ONLY with a valid JSON array, no markdown, no preamble:
[
  {{"subject": "Mathematics", "type": "book", "title": "...", "url": "...", "reason": "...", "priority": "high"}},
  ...
]"""

        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return text.strip()
    except Exception as e:
        print(f"[Gemini] recommend_resources_with_feedback error: {e}")
        return _fallback_resources(weak_areas, category, subject_marks)


# ─── Feature 2: Resource Budget Planner ──────────────────────────────────────
def plan_resource_budget(students_data, total_hours, study_days=5, session_length=1.5):
    """AI-driven study schedule allocation per student based on their academic results."""
    try:
        client = _get_gemini_client()
        if not client:
            return _fallback_budget(students_data, total_hours, study_days, session_length)
        student_list = "\n".join(
            f"- ID:{s['id']} Name:{s['name']} | Marks:{s['marks']}% Attendance:{s['attendance']}% "
            f"Assignments:{s['assignments']}% Category:{s['category']}"
            for s in students_data
        )
        days_list = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        available_days = days_list[:int(study_days)]
        prompt = f"""You are an expert educational study schedule planner.
Students have {total_hours} total study hours available this week across {study_days} days ({', '.join(available_days)}).
Each session is {session_length} hours long.

Students:
{student_list}

Rules:
1. Allocate MORE hours to Weak students (they need intensive study), MODERATE to Average, LESS to Strong.
2. Every student must get at least 1 session.
3. Total hours across ALL students must sum to exactly {total_hours}.
4. Create a day-by-day schedule for each student within their allocated hours.
5. Assign subject focus areas based on performance — Weak students need core subjects, Strong students can do enrichment.
6. Sessions per student should not exceed one session per day.

Respond ONLY with a valid JSON array (no markdown, no explanation):
[
  {{
    "student_id": <id>,
    "name": "...",
    "category": "Weak/Average/Strong",
    "hours": <total float hours for this student>,
    "priority": "critical/high/medium/low",
    "focus_areas": ["Subject1", "Subject2"],
    "schedule": [
      {{"day": "Monday", "subject": "Mathematics", "duration": {session_length}}},
      {{"day": "Wednesday", "subject": "Science", "duration": {session_length}}}
    ],
    "rationale": "1-sentence explanation of why this schedule suits this student"
  }},
  ...
]
All student hours must sum to exactly {total_hours}."""
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return text.strip()
    except Exception as e:
        print(f"[Gemini] plan_resource_budget error: {e}")
        return _fallback_budget(students_data, total_hours, study_days, session_length)


def _fallback_budget(students_data, total_hours, study_days=5, session_length=1.5):
    import math
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    available_days = days[:int(study_days)]
    weights = {"Weak": 3, "Average": 2, "Strong": 1}
    subject_map = {
        "Weak":    ["Mathematics", "Science", "English", "Reading Comprehension"],
        "Average": ["Mathematics", "English", "General Knowledge"],
        "Strong":  ["Advanced Mathematics", "Critical Thinking", "Enrichment"],
    }
    priority_map = {"Weak": "critical", "Average": "medium", "Strong": "low"}
    total_weight = sum(weights.get(s["category"], 2) for s in students_data) or 1
    result = []
    allocated = 0
    for i, s in enumerate(students_data):
        w = weights.get(s["category"], 2)
        if i == len(students_data) - 1:
            hours = round(total_hours - allocated, 1)
        else:
            hours = round((w / total_weight) * total_hours, 1)
        allocated += hours
        sessions = max(1, math.floor(hours / session_length))
        subjects = subject_map.get(s["category"], ["Mathematics", "English"])
        schedule = []
        for j in range(sessions):
            day = available_days[j % len(available_days)]
            subject = subjects[j % len(subjects)]
            schedule.append({"day": day, "subject": subject, "duration": session_length})
        priority = priority_map.get(s["category"], "medium")
        result.append({
            "student_id": s["id"], "name": s["name"], "category": s["category"],
            "hours": hours, "priority": priority,
            "focus_areas": subjects[:2],
            "schedule": schedule,
            "rationale": f"{s['category']} student with {s['marks']}% marks — schedule prioritises {'core remediation' if s['category']=='Weak' else 'steady progress' if s['category']=='Average' else 'enrichment'}."
        })
    return json.dumps(result)


# ─── Feature 3: Group Intervention Planner ───────────────────────────────────
def plan_group_intervention(students_data):
    """Cluster struggling students into optimal intervention groups."""
    try:
        client = _get_gemini_client()
        if not client:
            return _fallback_groups(students_data)
        student_list = "\n".join(
            f"- ID:{s['id']} {s['name']} | Marks:{s['marks']} Att:{s['attendance']} Asgn:{s['assignments']} | Weak areas: {s.get('weak_areas','?')}"
            for s in students_data
        )
        prompt = f"""You are an expert educational intervention planner.
Group these students into 2-4 intervention groups based on shared weaknesses for efficient batch tutoring:

{student_list}

Respond ONLY with valid JSON, no markdown:
[
  {{
    "group_name": "Group A – Math Foundations",
    "focus_area": "Mathematics & Problem Solving",
    "student_ids": [1, 3, 5],
    "session_plan": "3-bullet point session plan for this group",
    "sessions_per_week": 2,
    "rationale": "Why these students are grouped together"
  }},
  ...
]"""
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        text = response.text.strip()
        # Strip markdown code fences robustly: ```json ... ``` or ``` ... ```
        import re as _re
        text = _re.sub(r'^```(?:json)?\s*', '', text, flags=_re.IGNORECASE)
        text = _re.sub(r'\s*```$', '', text)
        text = text.strip()
        # Validate it's actually parseable JSON before returning
        json.loads(text)  # will raise if invalid, caught below
        return text
    except Exception as e:
        print(f"[Gemini] plan_group_intervention error: {e}")
        return _fallback_groups(students_data)


def _fallback_groups(students_data):
    weak = [s for s in students_data if s["category"] == "Weak"]
    avg  = [s for s in students_data if s["category"] == "Average"]
    groups = []
    if weak:
        groups.append({"group_name": "Group A – Intensive Support", "focus_area": "Core Subject Remediation",
                        "student_ids": [s["id"] for s in weak], "session_plan": "Daily 45-min sessions on fundamentals",
                        "sessions_per_week": 4, "rationale": "All weak students need intensive remediation."})
    if avg:
        groups.append({"group_name": "Group B – Skill Advancement", "focus_area": "Targeted Improvement",
                        "student_ids": [s["id"] for s in avg], "session_plan": "Weekly 60-min targeted practice",
                        "sessions_per_week": 2, "rationale": "Average students benefit from structured advancement."})
    return json.dumps(groups)


# ─── Feature 4: Progress Analysis (ROI of resources) ─────────────────────────
def analyze_progress(name, checkpoints):
    """Analyze student progress across multiple checkpoints."""
    try:
        client = _get_gemini_client()
        if not client:
            return "Progress analysis requires Gemini API key."
        history = "\n".join(
            f"Checkpoint {i+1} ({cp['date']}): Marks={cp['marks']}, Attendance={cp['attendance']}, Assignments={cp['assignments']}, Category={cp['category']}"
            for i, cp in enumerate(checkpoints)
        )
        prompt = f"""Analyze the progress trajectory of student {name}:

{history}

Provide:
1. **Trend Summary** — improving / declining / stable with key metrics
2. **Resource ROI** — are allocated resources working? What evidence?
3. **Next Steps** — specific 3-point action plan based on trajectory
4. **Predicted Category** — likely category in 4 weeks if current trend continues

Keep it concise and actionable."""
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return response.text
    except Exception as e:
        return f"Progress analysis error: {e}"


# ─── Fallback (no Gemini key) ─────────────────────────────────────────────────
def _fallback_analysis(marks, attendance, assignments):
    avg = (marks + attendance + assignments) / 3
    if avg >= 75:
        category = "Strong"
        reason   = "The student demonstrates excellent performance across all parameters."
    elif avg >= 50:
        category = "Average"
        reason   = "The student shows moderate performance with clear room for improvement."
    else:
        category = "Weak"
        reason   = "The student needs significant support and focused intervention."

    weak_areas = []
    if marks       < 50: weak_areas.append("Marks")
    if attendance  < 75: weak_areas.append("Attendance")
    if assignments < 50: weak_areas.append("Assignments")

    return (
        f"Category: {category}\n"
        f"Reason: {reason}\n"
        f"Weak Areas: {', '.join(weak_areas) if weak_areas else 'None'}\n"
        "Suggestions:\n"
        "- Review class notes and textbooks daily\n"
        "- Attend every scheduled class session\n"
        "- Submit all assignments on or before deadline\n"
        "- Seek teacher help for difficult topics\n"
        "Study Plan:\n"
        "Step 1: Allocate 2 focused hours daily to weakest subjects\n"
        "Step 2: Clear all pending assignments within this week\n"
        "Step 3: Conduct a weekly self-review quiz every Sunday"
    )
