import os
import json
import pdfplumber
import requests as http_requests
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
from sqlalchemy import select, func
from dotenv import load_dotenv

from models.models import db, User, StudentUser, Student, ReportCardAnalysis, ResourceRecommendation, ResourceBudgetPlan, InterventionGroup, ProgressCheckpoint, VideoClass, StudyNote, ResourceFeedback
from ai_service import (
    analyze_student, analyze_report_card,
    get_similar_students, store_student_in_pinecone, parse_analysis,
    recommend_resources, plan_resource_budget, plan_group_intervention, analyze_progress,
    generate_study_notes, recommend_resources_with_feedback,
)

load_dotenv()

# ─── App factory ──────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"]                  = os.getenv("SECRET_KEY", "dev-secret-change-me-use-a-real-secret-in-production")

# Fix: Render provides DATABASE_URL starting with "postgres://" but SQLAlchemy
# requires "postgresql://".  This one-liner ensures it always works.
_db_url = os.getenv("DATABASE_URL", "sqlite:///eduai.db")
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"]     = _db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"]              = os.path.join(os.path.dirname(__file__), "static", "uploads")
app.config["MAX_CONTENT_LENGTH"]         = 16 * 1024 * 1024   # 16 MB

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# ─── Markdown Jinja filter ────────────────────────────────────────────────────
import re as _re_md
def _md_to_html(text):
    if not text:
        return ""
    # Bold
    text = _re_md.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Headings ##
    text = _re_md.sub(r'^##+ (.+)$', r'<h2>\1</h2>', text, flags=_re_md.MULTILINE)
    # Bullets
    lines = text.split("\n")
    out, in_ul = [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("• "):
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append(f"<li>{stripped[2:]}</li>")
        elif stripped.startswith("[ ] ") or stripped.startswith("[x] "):
            checked = 'checked' if stripped.startswith('[x]') else ''
            label = stripped[4:]
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append(f'<li><input type="checkbox" {checked} disabled> {label}</li>')
        else:
            if in_ul:
                out.append("</ul>"); in_ul = False
            out.append(line)
    if in_ul:
        out.append("</ul>")
    text = "\n".join(out)
    # Paragraphs (blank lines)
    text = _re_md.sub(r'\n{2,}', '</p><p>', text)
    return f"<p>{text}</p>"

app.jinja_env.filters['markdown'] = _md_to_html

db.init_app(app)
bcrypt      = Bcrypt(app)
login_mgr   = LoginManager(app)
login_mgr.login_view    = "login"
login_mgr.login_message = ""

@login_mgr.user_loader
def load_user(user_id):
    if str(user_id).startswith("student:"):
        sid = int(user_id.split(":")[1])
        return db.session.get(StudentUser, sid)
    return db.session.get(User, int(user_id))

with app.app_context():
    db.create_all()

# Register custom Jinja filter
import json as _json
app.jinja_env.filters['fromjson'] = _json.loads


# ─────────────────────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if current_user.is_authenticated:
        if isinstance(current_user, StudentUser):
            return redirect(url_for("student_portal"))
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        # Validate input
        if not email or "@" not in email or "." not in email.split("@")[-1]:
            flash("Invalid email format", "error")
            return render_template("login.html")
        if not password:
            flash("Password cannot be empty", "error")
            return render_template("login.html")

        # SQLAlchemy 2.x query
        stmt = select(User).where(User.email == email)
        user = db.session.execute(stmt).scalar_one_or_none()

        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Invalid email or password", "error")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm_password", "")

        if not name:
            flash("Name cannot be empty", "error")
            return render_template("register.html")
        if not email or "@" not in email or "." not in email.split("@")[-1]:
            flash("Invalid email format", "error")
            return render_template("register.html")
        if len(password) < 6:
            flash("Password too short (minimum 6 characters)", "error")
            return render_template("register.html")
        if password != confirm:
            flash("Passwords do not match", "error")
            return render_template("register.html")

        # Check duplicate email — SQLAlchemy 2.x
        stmt = select(User).where(User.email == email)
        if db.session.execute(stmt).scalar_one_or_none():
            flash("Email already registered", "error")
            return render_template("register.html")

        hashed = bcrypt.generate_password_hash(password).decode("utf-8")
        user   = User(name=name, email=email, password=hashed)
        db.session.add(user)
        db.session.commit()
        flash("Account created! Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    # SQLAlchemy 2.x: use select() + scalars()
    stmt     = (
        select(Student)
        .where(Student.teacher_id == current_user.id)
        .order_by(Student.created_at.desc())
    )
    students = db.session.execute(stmt).scalars().all()

    # Aggregate counts via Python (simple; for large sets use func.count)
    total   = len(students)
    weak    = sum(1 for s in students if s.category == "Weak")
    average = sum(1 for s in students if s.category == "Average")
    strong  = sum(1 for s in students if s.category == "Strong")

    # Recent report analyses
    rpt_stmt = (
        select(ReportCardAnalysis)
        .where(ReportCardAnalysis.teacher_id == current_user.id)
        .order_by(ReportCardAnalysis.created_at.desc())
        .limit(5)
    )
    reports = db.session.execute(rpt_stmt).scalars().all()

    return render_template(
        "dashboard.html",
        students=students, total=total,
        weak=weak, average=average, strong=strong,
        reports=reports,
    )


# ─────────────────────────────────────────────────────────────────────────────
# STUDENTS
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/add-student", methods=["GET", "POST"])
@login_required
def add_student():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        try:
            marks       = float(request.form.get("marks",       0))
            attendance  = float(request.form.get("attendance",  0))
            assignments = float(request.form.get("assignments", 0))
        except ValueError:
            flash("Please enter valid numeric values", "error")
            return render_template("add_student.html")

        if not name:
            flash("Student name is required", "error")
            return render_template("add_student.html")
        if not (0 <= marks <= 100 and 0 <= attendance <= 100 and 0 <= assignments <= 100):
            flash("All values must be between 0 and 100", "error")
            return render_template("add_student.html")

        # Parse per-subject marks (submitted as subject_name[]=X&subject_mark[]=Y pairs)
        subject_names = request.form.getlist("subject_name[]")
        subject_marks_vals = request.form.getlist("subject_mark[]")
        subject_marks_dict = {}
        for sname, smark in zip(subject_names, subject_marks_vals):
            sname = sname.strip()
            if sname:
                try:
                    subject_marks_dict[sname] = float(smark)
                except ValueError:
                    pass

        # Pinecone context
        similar_ctx  = get_similar_students(marks, attendance, assignments)

        # Gemini 2.5 Flash analysis
        raw_analysis = analyze_student(name, marks, attendance, assignments, similar_ctx)
        parsed       = parse_analysis(raw_analysis)

        # Persist with SQLAlchemy
        student = Student(
            name          = name,
            marks         = marks,
            attendance    = attendance,
            assignments   = assignments,
            category      = parsed["category"],
            reason        = parsed["reason"],
            weak_areas    = parsed["weak_areas"],
            suggestions   = json.dumps(parsed["suggestions"]),
            study_plan    = json.dumps(parsed["study_plan"]),
            teacher_id    = current_user.id,
            subject_marks = json.dumps(subject_marks_dict) if subject_marks_dict else None,
        )
        db.session.add(student)
        db.session.commit()

        # Store vector in Pinecone
        pid = store_student_in_pinecone(student.id, marks, attendance, assignments, parsed["category"])
        if pid:
            student.pinecone_id = pid
            db.session.commit()

        return redirect(url_for("student_result", student_id=student.id))

    return render_template("add_student.html")


@app.route("/student/<int:student_id>")
@login_required
def student_result(student_id):
    stmt    = select(Student).where(
        Student.id == student_id,
        Student.teacher_id == current_user.id,
    )
    student = db.session.execute(stmt).scalar_one_or_none()
    if not student:
        flash("Student not found", "error")
        return redirect(url_for("dashboard"))

    suggestions = json.loads(student.suggestions) if student.suggestions else []
    study_plan  = json.loads(student.study_plan)  if student.study_plan  else []
    return render_template("student_result.html",
                           student=student,
                           suggestions=suggestions,
                           study_plan=study_plan)


@app.route("/student/<int:student_id>/delete", methods=["POST"])
@login_required
def delete_student(student_id):
    stmt    = select(Student).where(
        Student.id == student_id,
        Student.teacher_id == current_user.id,
    )
    student = db.session.execute(stmt).scalar_one_or_none()
    if not student:
        flash("Student not found", "error")
        return redirect(url_for("dashboard"))

    db.session.delete(student)
    db.session.commit()
    flash("Student deleted successfully", "success")
    return redirect(url_for("dashboard"))


# ─────────────────────────────────────────────────────────────────────────────
# REPORT CARD ANALYZER
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/report-card", methods=["GET", "POST"])
@login_required
def report_card():
    if request.method == "POST":
        student_name = request.form.get("student_name", "").strip()
        file         = request.files.get("report_pdf")

        if not file or file.filename == "":
            flash("Please upload a PDF file", "error")
            return render_template("report_card.html")
        if not file.filename.lower().endswith(".pdf"):
            flash("Only PDF files are supported", "error")
            return render_template("report_card.html")

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        # Extract text from PDF
        pdf_text = ""
        try:
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pdf_text += text + "\n"
        except Exception as e:
            flash(f"Error reading PDF: {e}", "error")
            return render_template("report_card.html")

        if not pdf_text.strip():
            flash("Could not extract text. Ensure the PDF is text-based (not scanned).", "error")
            return render_template("report_card.html")

        # Gemini 2.5 Flash analysis
        analysis = analyze_report_card(pdf_text, filename)

        # Persist with SQLAlchemy
        report = ReportCardAnalysis(
            student_name = student_name or "Unknown",
            filename     = filename,
            analysis     = analysis,
            teacher_id   = current_user.id,
        )
        db.session.add(report)
        db.session.commit()

        return redirect(url_for("report_result", report_id=report.id))

    return render_template("report_card.html")


@app.route("/report/<int:report_id>")
@login_required
def report_result(report_id):
    stmt   = select(ReportCardAnalysis).where(
        ReportCardAnalysis.id == report_id,
        ReportCardAnalysis.teacher_id == current_user.id,
    )
    report = db.session.execute(stmt).scalar_one_or_none()
    if not report:
        flash("Report not found", "error")
        return redirect(url_for("dashboard"))
    return render_template("report_result.html", report=report)


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 1: RESOURCE RECOMMENDER
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/student/<int:student_id>/resources")
@login_required
def student_resources(student_id):
    stmt = select(Student).where(Student.id == student_id, Student.teacher_id == current_user.id)
    student = db.session.execute(stmt).scalar_one_or_none()
    if not student:
        flash("Student not found", "error")
        return redirect(url_for("dashboard"))

    # Check for existing recommendation
    rec_stmt = select(ResourceRecommendation).where(
        ResourceRecommendation.student_id == student_id,
        ResourceRecommendation.teacher_id == current_user.id,
    ).order_by(ResourceRecommendation.created_at.desc())
    existing = db.session.execute(rec_stmt).scalars().first()

    recommendations = []
    if existing:
        try:
            recommendations = json.loads(existing.recommendations)
        except Exception:
            pass

    return render_template("student_resources.html", student=student,
                           recommendations=recommendations, existing=existing)


@app.route("/student/<int:student_id>/resources/generate", methods=["POST"])
@login_required
def generate_resources(student_id):
    stmt = select(Student).where(Student.id == student_id, Student.teacher_id == current_user.id)
    student = db.session.execute(stmt).scalar_one_or_none()
    if not student:
        flash("Student not found", "error")
        return redirect(url_for("dashboard"))

    raw = recommend_resources(
        student.name, student.weak_areas, student.category,
        student.marks, student.attendance, student.assignments,
        subject_marks=student.subject_marks
    )
    try:
        recs = json.loads(raw)
    except Exception:
        recs = []

    rec = ResourceRecommendation(
        student_id=student_id,
        teacher_id=current_user.id,
        recommendations=json.dumps(recs),
    )
    db.session.add(rec)
    db.session.commit()
    flash("Resource recommendations generated!", "success")
    return redirect(url_for("student_resources", student_id=student_id))


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 2: RESOURCE BUDGET PLANNER
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/resource-budget", methods=["GET", "POST"])
@login_required
def resource_budget():
    stmt = select(Student).where(Student.teacher_id == current_user.id).order_by(Student.category)
    students = db.session.execute(stmt).scalars().all()

    plans_stmt = select(ResourceBudgetPlan).where(
        ResourceBudgetPlan.teacher_id == current_user.id
    ).order_by(ResourceBudgetPlan.created_at.desc()).limit(5)
    past_plans = db.session.execute(plans_stmt).scalars().all()

    if request.method == "POST":
        total_hours    = float(request.form.get("total_hours", 10))
        plan_name      = request.form.get("plan_name", "Weekly Study Schedule").strip()
        study_days     = int(request.form.get("study_days", 5))
        session_length = float(request.form.get("session_length", 1.5))

        students_data = [
            {"id": s.id, "name": s.name, "marks": s.marks,
             "attendance": s.attendance, "assignments": s.assignments, "category": s.category}
            for s in students
        ]
        if not students_data:
            flash("Add students first before generating a study schedule.", "error")
            return render_template("resource_budget.html", students=students, past_plans=past_plans)

        raw = plan_resource_budget(students_data, total_hours, study_days, session_length)
        try:
            allocations = json.loads(raw)
        except Exception:
            allocations = []

        plan = ResourceBudgetPlan(
            teacher_id=current_user.id,
            plan_name=plan_name,
            total_hours=total_hours,
            allocations=json.dumps(allocations),
        )
        db.session.add(plan)
        db.session.commit()
        flash("Study schedule generated!", "success")
        return redirect(url_for("budget_plan_detail", plan_id=plan.id))

    return render_template("resource_budget.html", students=students, past_plans=past_plans)


@app.route("/resource-budget/<int:plan_id>")
@login_required
def budget_plan_detail(plan_id):
    stmt = select(ResourceBudgetPlan).where(
        ResourceBudgetPlan.id == plan_id, ResourceBudgetPlan.teacher_id == current_user.id
    )
    plan = db.session.execute(stmt).scalar_one_or_none()
    if not plan:
        flash("Plan not found", "error")
        return redirect(url_for("resource_budget"))
    allocations = json.loads(plan.allocations) if plan.allocations else []
    return render_template("budget_plan_detail.html", plan=plan, allocations=allocations)


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 3: BULK CSV IMPORT + AUTO-PRIORITIZER
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/bulk-import", methods=["GET", "POST"])
@login_required
def bulk_import():
    if request.method == "POST":
        file = request.files.get("csv_file")
        if not file or not file.filename.lower().endswith(".csv"):
            flash("Please upload a valid CSV file", "error")
            return render_template("bulk_import.html")

        import csv, io
        content = file.read().decode("utf-8-sig")
        reader  = csv.DictReader(io.StringIO(content))

        imported = 0
        errors   = []
        for i, row in enumerate(reader, 1):
            try:
                name        = row.get("name", "").strip()
                marks       = float(row.get("marks", 0))
                attendance  = float(row.get("attendance", 0))
                assignments = float(row.get("assignments", 0))
                if not name:
                    errors.append(f"Row {i}: missing name")
                    continue
                similar_ctx  = get_similar_students(marks, attendance, assignments)
                raw_analysis = analyze_student(name, marks, attendance, assignments, similar_ctx)
                parsed       = parse_analysis(raw_analysis)
                student      = Student(
                    name=name, marks=marks, attendance=attendance, assignments=assignments,
                    category=parsed["category"], reason=parsed["reason"],
                    weak_areas=parsed["weak_areas"], suggestions=json.dumps(parsed["suggestions"]),
                    study_plan=json.dumps(parsed["study_plan"]), teacher_id=current_user.id,
                )
                db.session.add(student)
                db.session.flush()
                pid = store_student_in_pinecone(student.id, marks, attendance, assignments, parsed["category"])
                if pid:
                    student.pinecone_id = pid
                imported += 1
            except Exception as e:
                errors.append(f"Row {i}: {e}")

        db.session.commit()
        flash(f"Successfully imported {imported} student(s)." + (f" {len(errors)} errors." if errors else ""), "success")
        return redirect(url_for("bulk_import_result", imported=imported))

    return render_template("bulk_import.html")


@app.route("/bulk-import/result")
@login_required
def bulk_import_result():
    imported = request.args.get("imported", 0)
    stmt = select(Student).where(Student.teacher_id == current_user.id).order_by(Student.created_at.desc()).limit(20)
    students = db.session.execute(stmt).scalars().all()
    priority_order = {"Weak": 0, "Average": 1, "Strong": 2}
    students_sorted = sorted(students, key=lambda s: priority_order.get(s.category, 1))
    return render_template("bulk_import_result.html", students=students_sorted, imported=imported)


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 4: GROUP INTERVENTION PLANNER
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/intervention-groups", methods=["GET", "POST"])
@login_required
def intervention_groups():
    stmt = select(Student).where(Student.teacher_id == current_user.id, Student.category.in_(["Weak", "Average"]))
    students = db.session.execute(stmt).scalars().all()

    groups_stmt = select(InterventionGroup).where(
        InterventionGroup.teacher_id == current_user.id
    ).order_by(InterventionGroup.created_at.desc())
    existing_groups = db.session.execute(groups_stmt).scalars().all()

    if request.method == "POST":
        if not students:
            flash("No Weak/Average students to group.", "error")
            return render_template("intervention_groups.html", students=students, groups=existing_groups)

        students_data = [{"id": s.id, "name": s.name, "marks": s.marks, "attendance": s.attendance,
                           "assignments": s.assignments, "category": s.category,
                           "weak_areas": s.weak_areas or ""} for s in students]
        raw = plan_group_intervention(students_data)
        try:
            groups_data = json.loads(raw)
            if not isinstance(groups_data, list):
                raise ValueError("Expected a JSON array")
        except Exception as parse_err:
            print(f"[CreateGroup] JSON parse error: {parse_err} | raw={raw[:200]}")
            flash("AI returned an unexpected response. Please try again.", "error")
            return render_template("intervention_groups.html", students=students, groups=existing_groups,
                                   id_to_name={s.id: s.name for s in db.session.execute(
                                       select(Student).where(Student.teacher_id == current_user.id)
                                   ).scalars().all()})

        if not groups_data:
            flash("No groups were generated. Please try again.", "error")
            return render_template("intervention_groups.html", students=students, groups=existing_groups,
                                   id_to_name={s.id: s.name for s in db.session.execute(
                                       select(Student).where(Student.teacher_id == current_user.id)
                                   ).scalars().all()})

        # Clear old groups and save new ones
        old = db.session.execute(
            select(InterventionGroup).where(InterventionGroup.teacher_id == current_user.id)
        ).scalars().all()
        for og in old:
            db.session.delete(og)
        for g in groups_data:
            # Build a richer session_plan that includes sessions_per_week and rationale if available
            session_plan = g.get("session_plan", "")
            sessions_per_week = g.get("sessions_per_week")
            rationale = g.get("rationale", "")
            if sessions_per_week:
                session_plan = f"{session_plan}\n[{sessions_per_week} sessions/week]"
            if rationale:
                session_plan = f"{session_plan}\nRationale: {rationale}"
            group = InterventionGroup(
                teacher_id=current_user.id,
                group_name=g.get("group_name", "Group"),
                focus_area=g.get("focus_area", ""),
                student_ids=json.dumps(g.get("student_ids", [])),
                session_plan=session_plan.strip(),
            )
            db.session.add(group)
        db.session.commit()
        flash(f"Created {len(groups_data)} intervention group(s)!", "success")
        return redirect(url_for("intervention_groups"))

    # Enrich groups with student names
    id_to_name = {s.id: s.name for s in db.session.execute(
        select(Student).where(Student.teacher_id == current_user.id)
    ).scalars().all()}

    return render_template("intervention_groups.html", students=students,
                           groups=existing_groups, id_to_name=id_to_name)


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 5: PROGRESS TRACKER & RESOURCE ROI
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/student/<int:student_id>/progress", methods=["GET", "POST"])
@login_required
def student_progress(student_id):
    stmt = select(Student).where(Student.id == student_id, Student.teacher_id == current_user.id)
    student = db.session.execute(stmt).scalar_one_or_none()
    if not student:
        flash("Student not found", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        try:
            marks       = float(request.form.get("marks", 0))
            attendance  = float(request.form.get("attendance", 0))
            assignments = float(request.form.get("assignments", 0))
            notes       = request.form.get("notes", "").strip()
        except ValueError:
            flash("Please enter valid numeric values", "error")
            return redirect(url_for("student_progress", student_id=student_id))

        avg = (marks + attendance + assignments) / 3
        if avg >= 75:
            category = "Strong"
        elif avg >= 50:
            category = "Average"
        else:
            category = "Weak"

        checkpoint = ProgressCheckpoint(
            student_id=student_id, teacher_id=current_user.id,
            marks=marks, attendance=attendance, assignments=assignments,
            category=category, notes=notes,
        )
        db.session.add(checkpoint)
        db.session.commit()
        flash("Progress checkpoint saved!", "success")
        return redirect(url_for("student_progress", student_id=student_id))

    checkpoints_stmt = select(ProgressCheckpoint).where(
        ProgressCheckpoint.student_id == student_id,
        ProgressCheckpoint.teacher_id == current_user.id,
    ).order_by(ProgressCheckpoint.checked_at.asc())
    checkpoints = db.session.execute(checkpoints_stmt).scalars().all()

    # Build history including the initial record
    history = [{
        "date": student.created_at.strftime("%Y-%m-%d"),
        "marks": student.marks, "attendance": student.attendance,
        "assignments": student.assignments, "category": student.category,
    }] + [{
        "date": cp.checked_at.strftime("%Y-%m-%d"),
        "marks": cp.marks, "attendance": cp.attendance,
        "assignments": cp.assignments, "category": cp.category,
    } for cp in checkpoints]

    progress_analysis = None
    if len(history) >= 2:
        progress_analysis = analyze_progress(student.name, history)

    return render_template("student_progress.html", student=student,
                           checkpoints=checkpoints, history=history,
                           progress_analysis=progress_analysis)


# ─────────────────────────────────────────────────────────────────────────────
# STUDENT AUTH
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/student-login", methods=["GET", "POST"])
def student_login():
    if current_user.is_authenticated:
        if isinstance(current_user, StudentUser):
            return redirect(url_for("student_portal"))
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or "@" not in email:
            flash("Invalid email format", "error")
            return render_template("student_login.html")
        if not password:
            flash("Password cannot be empty", "error")
            return render_template("student_login.html")

        stmt = select(StudentUser).where(StudentUser.email == email)
        su   = db.session.execute(stmt).scalar_one_or_none()

        if su and bcrypt.check_password_hash(su.password, password):
            login_user(su)
            return redirect(url_for("student_portal"))
        flash("Invalid email or password", "error")

    return render_template("student_login.html")


@app.route("/student-register", methods=["GET", "POST"])
def student_register():
    if current_user.is_authenticated:
        return redirect(url_for("student_portal") if isinstance(current_user, StudentUser) else url_for("dashboard"))

    # Build list of students that don't yet have an account (for dropdown)
    taken_ids = {row[0] for row in db.session.execute(select(StudentUser.student_id)).all()}
    all_students_stmt = select(Student).order_by(Student.name)
    all_students = [s for s in db.session.execute(all_students_stmt).scalars().all() if s.id not in taken_ids]

    if request.method == "POST":
        student_id = request.form.get("student_id", "").strip()
        email      = request.form.get("email", "").strip()
        password   = request.form.get("password", "")
        confirm    = request.form.get("confirm_password", "")

        if not student_id:
            flash("Please select your name from the list", "error")
            return render_template("student_register.html", students=all_students)
        if not email or "@" not in email:
            flash("Invalid email format", "error")
            return render_template("student_register.html", students=all_students)
        if len(password) < 6:
            flash("Password too short (minimum 6 characters)", "error")
            return render_template("student_register.html", students=all_students)
        if password != confirm:
            flash("Passwords do not match", "error")
            return render_template("student_register.html", students=all_students)

        # Check duplicate email
        if db.session.execute(select(StudentUser).where(StudentUser.email == email)).scalar_one_or_none():
            flash("Email already registered", "error")
            return render_template("student_register.html", students=all_students)

        # Check student already has account
        if db.session.execute(select(StudentUser).where(StudentUser.student_id == int(student_id))).scalar_one_or_none():
            flash("This student already has an account", "error")
            return render_template("student_register.html", students=all_students)

        hashed = bcrypt.generate_password_hash(password).decode("utf-8")
        su = StudentUser(student_id=int(student_id), email=email, password=hashed)
        db.session.add(su)
        db.session.commit()
        flash("Account created! Please login.", "success")
        return redirect(url_for("student_login"))

    return render_template("student_register.html", students=all_students)


# ─────────────────────────────────────────────────────────────────────────────
# STUDENT PORTAL
# ─────────────────────────────────────────────────────────────────────────────

def require_student_login():
    """Return redirect if not logged in as a StudentUser, else None."""
    if not current_user.is_authenticated or not isinstance(current_user, StudentUser):
        flash("Please login as a student to access this page.", "error")
        return redirect(url_for("student_login"))
    return None


@app.route("/portal")
def student_portal():
    redir = require_student_login()
    if redir:
        return redir

    student = current_user.student

    suggestions  = json.loads(student.suggestions) if student.suggestions else []
    study_plan   = json.loads(student.study_plan)  if student.study_plan  else []

    # Resources
    rec_stmt = select(ResourceRecommendation).where(
        ResourceRecommendation.student_id == student.id,
    ).order_by(ResourceRecommendation.created_at.desc())
    rec = db.session.execute(rec_stmt).scalars().first()
    recommendations = json.loads(rec.recommendations) if rec else []

    # Progress checkpoints
    cp_stmt = select(ProgressCheckpoint).where(
        ProgressCheckpoint.student_id == student.id,
    ).order_by(ProgressCheckpoint.checked_at.asc())
    checkpoints = db.session.execute(cp_stmt).scalars().all()

    history = [{
        "date": student.created_at.strftime("%Y-%m-%d"),
        "marks": student.marks, "attendance": student.attendance,
        "assignments": student.assignments, "category": student.category,
    }] + [{
        "date": cp.checked_at.strftime("%Y-%m-%d"),
        "marks": cp.marks, "attendance": cp.attendance,
        "assignments": cp.assignments, "category": cp.category,
    } for cp in checkpoints]

    # Intervention groups this student is in
    all_groups_stmt = select(InterventionGroup).where(
        InterventionGroup.teacher_id == student.teacher_id
    )
    my_groups = []
    for g in db.session.execute(all_groups_stmt).scalars().all():
        ids = json.loads(g.student_ids) if g.student_ids else []
        if student.id in ids:
            my_groups.append(g)

    return render_template(
        "student_portal.html",
        student=student,
        suggestions=suggestions,
        study_plan=study_plan,
        recommendations=recommendations,
        history=history,
        my_groups=my_groups,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEACHER: Create student account (from student detail page)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/student/<int:student_id>/create-account", methods=["POST"])
@login_required
def teacher_create_student_account(student_id):
    stmt = select(Student).where(Student.id == student_id, Student.teacher_id == current_user.id)
    student = db.session.execute(stmt).scalar_one_or_none()
    if not student:
        flash("Student not found", "error")
        return redirect(url_for("dashboard"))

    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not email or "@" not in email:
        flash("Invalid email format", "error")
        return redirect(url_for("student_result", student_id=student_id))
    if len(password) < 6:
        flash("Password too short (minimum 6 characters)", "error")
        return redirect(url_for("student_result", student_id=student_id))

    if db.session.execute(select(StudentUser).where(StudentUser.email == email)).scalar_one_or_none():
        flash("Email already registered", "error")
        return redirect(url_for("student_result", student_id=student_id))

    if db.session.execute(select(StudentUser).where(StudentUser.student_id == student_id)).scalar_one_or_none():
        flash("This student already has a portal account", "error")
        return redirect(url_for("student_result", student_id=student_id))

    hashed = bcrypt.generate_password_hash(password).decode("utf-8")
    su = StudentUser(student_id=student_id, email=email, password=hashed)
    db.session.add(su)
    db.session.commit()
    flash(f"Student portal account created for {student.name}!", "success")
    return redirect(url_for("student_result", student_id=student_id))


# ─────────────────────────────────────────────────────────────────────────────
# JSON API helpers
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/validate-login", methods=["POST"])
def api_validate_login():
    data     = request.json or {}
    email    = data.get("email", "")
    password = data.get("password", "")
    if not email or "@" not in email:
        return jsonify({"valid": False, "message": "Invalid email format"})
    if not password:
        return jsonify({"valid": False, "message": "Password cannot be empty"})
    return jsonify({"valid": True, "message": "Login input is valid"})


@app.route("/api/dashboard-summary")
@login_required
def api_dashboard_summary():
    # SQLAlchemy 2.x aggregate query
    rows = db.session.execute(
        select(Student.category, func.count(Student.id).label("cnt"))
        .where(Student.teacher_id == current_user.id)
        .group_by(Student.category)
    ).all()

    counts = {"Weak": 0, "Average": 0, "Strong": 0}
    total  = 0
    for category, cnt in rows:
        if category in counts:
            counts[category] = cnt
        total += cnt

    return jsonify({
        "total":   total,
        "weak":    counts["Weak"],
        "average": counts["Average"],
        "strong":  counts["Strong"],
    })



# ─────────────────────────────────────────────────────────────────────────────
# VIDEO CLASSES (Daily.co)
# ─────────────────────────────────────────────────────────────────────────────

DAILY_API_KEY = os.getenv("DAILY_API_KEY", "")
DAILY_BASE    = "https://api.daily.co/v1"


def _daily_headers():
    return {"Authorization": f"Bearer {DAILY_API_KEY}", "Content-Type": "application/json"}


def _create_daily_room(room_name: str, exp_unix: int) -> dict | None:
    """Create a Daily.co room and return the API response dict, or None on error."""
    if not DAILY_API_KEY:
        return None
    try:
        resp = http_requests.post(
            f"{DAILY_BASE}/rooms",
            headers=_daily_headers(),
            json={
                "name": room_name,
                "privacy": "private",
                "properties": {
                    "exp": exp_unix,
                    "enable_chat": True,
                    "enable_screenshare": True,
                    "enable_recording": "cloud",
                    "start_video_off": False,
                    "start_audio_off": False,
                },
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return resp.json()
    except Exception:
        pass
    return None


def _create_daily_token(room_name: str, is_owner: bool, exp_unix: int) -> str | None:
    """Create a meeting token for a specific room."""
    if not DAILY_API_KEY:
        return None
    try:
        resp = http_requests.post(
            f"{DAILY_BASE}/meeting-tokens",
            headers=_daily_headers(),
            json={"properties": {"room_name": room_name, "is_owner": is_owner, "exp": exp_unix}},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return resp.json().get("token")
    except Exception:
        pass
    return None


@app.route("/classes")
@login_required
def video_classes():
    from datetime import datetime as dt
    stmt = (
        select(VideoClass)
        .where(VideoClass.teacher_id == current_user.id)
        .order_by(VideoClass.scheduled_at.desc())
    )
    classes = db.session.execute(stmt).scalars().all()
    now = dt.utcnow()
    return render_template("video_classes.html", classes=classes, now=now, daily_key=bool(DAILY_API_KEY))


@app.route("/classes/schedule", methods=["GET", "POST"])
@login_required
def schedule_class():
    if request.method == "POST":
        from datetime import datetime as dt
        import time, re

        title       = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        sched_str   = request.form.get("scheduled_at", "").strip()
        duration    = request.form.get("duration_minutes", "60").strip()

        if not title:
            flash("Class title is required", "error")
            return render_template("schedule_class.html")

        try:
            sched_dt = dt.strptime(sched_str, "%Y-%m-%dT%H:%M")
        except ValueError:
            flash("Invalid date/time format", "error")
            return render_template("schedule_class.html")

        try:
            duration = int(duration)
            if duration < 15 or duration > 480:
                raise ValueError
        except ValueError:
            flash("Duration must be between 15 and 480 minutes", "error")
            return render_template("schedule_class.html")

        # Build a URL-safe room name
        safe_title = re.sub(r"[^a-zA-Z0-9-]", "-", title.lower())[:40]
        room_name  = f"eduai-{current_user.id}-{int(time.time())}-{safe_title}"
        exp_unix   = int(sched_dt.timestamp()) + duration * 60 + 3600  # +1hr grace

        room_url = None
        if DAILY_API_KEY:
            room_data = _create_daily_room(room_name, exp_unix)
            if room_data:
                room_url = room_data.get("url")

        vc = VideoClass(
            teacher_id=current_user.id,
            title=title,
            description=description,
            scheduled_at=sched_dt,
            duration_minutes=duration,
            room_url=room_url,
            room_name=room_name,
        )
        db.session.add(vc)
        db.session.commit()
        flash(f"Class '{title}' scheduled successfully!", "success")
        return redirect(url_for("video_classes"))

    return render_template("schedule_class.html")


@app.route("/classes/<int:class_id>/join")
@login_required
def join_class(class_id):
    """Teacher joins: generate owner token and embed Daily.co."""
    from datetime import datetime as dt
    vc = db.session.get(VideoClass, class_id)
    if not vc or vc.teacher_id != current_user.id:
        flash("Class not found", "error")
        return redirect(url_for("video_classes"))

    token = None
    if DAILY_API_KEY and vc.room_name:
        import time
        exp = int(time.time()) + vc.duration_minutes * 60 + 3600
        token = _create_daily_token(vc.room_name, is_owner=True, exp_unix=exp)

    return render_template("class_room.html", vc=vc, token=token, is_teacher=True)


@app.route("/classes/<int:class_id>/student-join")
def student_join_class(class_id):
    """Students join a class (no login required — link shared by teacher)."""
    from datetime import datetime as dt
    vc = db.session.get(VideoClass, class_id)
    if not vc:
        flash("Class not found", "error")
        return redirect(url_for("student_login"))

    token = None
    if DAILY_API_KEY and vc.room_name:
        import time
        exp = int(time.time()) + vc.duration_minutes * 60 + 3600
        token = _create_daily_token(vc.room_name, is_owner=False, exp_unix=exp)

    return render_template("class_room.html", vc=vc, token=token, is_teacher=False)


@app.route("/classes/<int:class_id>/delete", methods=["POST"])
@login_required
def delete_class(class_id):
    vc = db.session.get(VideoClass, class_id)
    if vc and vc.teacher_id == current_user.id:
        # Optionally delete the Daily.co room
        if DAILY_API_KEY and vc.room_name:
            try:
                http_requests.delete(f"{DAILY_BASE}/rooms/{vc.room_name}", headers=_daily_headers(), timeout=5)
            except Exception:
                pass
        db.session.delete(vc)
        db.session.commit()
        flash("Class deleted", "success")
    return redirect(url_for("video_classes"))


# Student portal: list upcoming classes from their teacher
@app.route("/portal/classes")
def student_classes():
    redir = require_student_login()
    if redir:
        return redir
    from datetime import datetime as dt
    student = current_user.student
    stmt = (
        select(VideoClass)
        .where(VideoClass.teacher_id == student.teacher_id)
        .order_by(VideoClass.scheduled_at.desc())
    )
    classes = db.session.execute(stmt).scalars().all()
    now = dt.utcnow()
    return render_template("student_classes.html", classes=classes, now=now)


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 5: AI STUDY NOTES GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/student/<int:student_id>/study-notes")
@login_required
def study_notes(student_id):
    stmt = select(Student).where(Student.id == student_id, Student.teacher_id == current_user.id)
    student = db.session.execute(stmt).scalar_one_or_none()
    if not student:
        flash("Student not found", "error")
        return redirect(url_for("dashboard"))

    # Get all existing notes for this student
    notes = db.session.execute(
        select(StudyNote)
        .where(StudyNote.student_id == student_id, StudyNote.teacher_id == current_user.id)
        .order_by(StudyNote.created_at.desc())
    ).scalars().all()

    # Get subject list from subject_marks
    subjects = []
    if student.subject_marks:
        try:
            sm = json.loads(student.subject_marks)
            subjects = list(sm.keys())
        except Exception:
            pass
    if not subjects:
        subjects = ["Mathematics", "Science", "English", "Social Studies", "Hindi"]

    return render_template("study_notes.html", student=student, notes=notes, subjects=subjects)


@app.route("/student/<int:student_id>/study-notes/generate", methods=["POST"])
@login_required
def generate_study_note(student_id):
    stmt = select(Student).where(Student.id == student_id, Student.teacher_id == current_user.id)
    student = db.session.execute(stmt).scalar_one_or_none()
    if not student:
        flash("Student not found", "error")
        return redirect(url_for("dashboard"))

    subject = request.form.get("subject", "").strip()
    if not subject:
        flash("Please select a subject.", "error")
        return redirect(url_for("study_notes", student_id=student_id))

    # Get subject score if available
    subject_score = None
    if student.subject_marks:
        try:
            sm = json.loads(student.subject_marks)
            subject_score = sm.get(subject)
        except Exception:
            pass

    content = generate_study_notes(
        student.name, subject, student.category or "Average",
        student.marks, subject_score
    )

    # Replace existing note for same subject or create new
    existing = db.session.execute(
        select(StudyNote).where(
            StudyNote.student_id == student_id,
            StudyNote.teacher_id == current_user.id,
            StudyNote.subject == subject,
        )
    ).scalar_one_or_none()

    if existing:
        existing.notes_content = content
        existing.category = student.category
        from datetime import datetime as dt
        existing.created_at = dt.utcnow()
    else:
        note = StudyNote(
            student_id=student_id,
            teacher_id=current_user.id,
            subject=subject,
            category=student.category,
            notes_content=content,
        )
        db.session.add(note)

    db.session.commit()
    flash(f"Study notes generated for {subject}!", "success")
    return redirect(url_for("study_notes", student_id=student_id))


@app.route("/student/<int:student_id>/study-notes/<int:note_id>/delete", methods=["POST"])
@login_required
def delete_study_note(student_id, note_id):
    note = db.session.get(StudyNote, note_id)
    if note and note.teacher_id == current_user.id:
        db.session.delete(note)
        db.session.commit()
        flash("Study note deleted.", "success")
    return redirect(url_for("study_notes", student_id=student_id))


# Student portal: view own study notes
@app.route("/portal/study-notes")
def portal_study_notes():
    redir = require_student_login()
    if redir:
        return redir
    student = current_user.student
    notes = db.session.execute(
        select(StudyNote)
        .where(StudyNote.student_id == student.id)
        .order_by(StudyNote.created_at.desc())
    ).scalars().all()
    return render_template("portal_study_notes.html", student=student, notes=notes)


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE 6: RESOURCE FEEDBACK & SMART RE-RECOMMENDATION
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/student/<int:student_id>/resources/feedback", methods=["GET", "POST"])
@login_required
def resource_feedback(student_id):
    stmt = select(Student).where(Student.id == student_id, Student.teacher_id == current_user.id)
    student = db.session.execute(stmt).scalar_one_or_none()
    if not student:
        flash("Student not found", "error")
        return redirect(url_for("dashboard"))

    # Get latest recommendation
    rec = db.session.execute(
        select(ResourceRecommendation)
        .where(ResourceRecommendation.student_id == student_id,
               ResourceRecommendation.teacher_id == current_user.id)
        .order_by(ResourceRecommendation.created_at.desc())
    ).scalars().first()

    if not rec:
        flash("No recommendations found. Generate resources first.", "error")
        return redirect(url_for("student_resources", student_id=student_id))

    recommendations = []
    try:
        recommendations = json.loads(rec.recommendations)
    except Exception:
        pass

    # Load existing feedback if any
    existing_feedback = {}
    fb_row = db.session.execute(
        select(ResourceFeedback)
        .where(ResourceFeedback.recommendation_id == rec.id,
               ResourceFeedback.teacher_id == current_user.id)
    ).scalar_one_or_none()
    if fb_row:
        try:
            for item in json.loads(fb_row.feedback_json):
                key = f"{item['subject']}|{item['type']}|{item['title']}"
                existing_feedback[key] = item.get("worked", None)
        except Exception:
            pass

    if request.method == "POST":
        # Save feedback
        fb_list = []
        for r in recommendations:
            key = f"{r.get('subject')}|{r.get('type')}|{r.get('title')}"
            val = request.form.get(key)
            if val is not None:
                fb_list.append({
                    "subject": r.get("subject"),
                    "type": r.get("type"),
                    "title": r.get("title"),
                    "worked": val == "yes",
                })

        if fb_row:
            fb_row.feedback_json = json.dumps(fb_list)
            from datetime import datetime as dt
            fb_row.updated_at = dt.utcnow()
        else:
            fb_row = ResourceFeedback(
                recommendation_id=rec.id,
                teacher_id=current_user.id,
                student_id=student_id,
                feedback_json=json.dumps(fb_list),
            )
            db.session.add(fb_row)
        db.session.commit()

        # If user clicked "Save & Regenerate"
        if request.form.get("action") == "regenerate":
            raw = recommend_resources_with_feedback(
                student.name, student.weak_areas, student.category,
                student.marks, student.attendance, student.assignments,
                subject_marks=student.subject_marks,
                feedback=fb_list,
            )
            try:
                recs_new = json.loads(raw)
            except Exception:
                recs_new = []

            new_rec = ResourceRecommendation(
                student_id=student_id,
                teacher_id=current_user.id,
                recommendations=json.dumps(recs_new),
            )
            db.session.add(new_rec)
            db.session.commit()
            flash("Feedback saved and new resources regenerated based on what worked!", "success")
            return redirect(url_for("student_resources", student_id=student_id))

        flash("Feedback saved!", "success")
        return redirect(url_for("resource_feedback", student_id=student_id))

    return render_template("resource_feedback.html",
                           student=student, recommendations=recommendations,
                           existing_feedback=existing_feedback, rec=rec)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
