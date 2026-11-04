import os
import re
import io
import json
import sqlite3
import hashlib
import secrets
import time
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st
import pandas as pd
import requests
from dotenv import load_dotenv

try:
    import fitz
except Exception:
    fitz = None
try:
    from docx import Document
except Exception:
    Document = None
try:
    from google import genai
except Exception:
    genai = None

load_dotenv(override=False)

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "career_platform.db"
VIDEO_STORAGE_DIR = APP_DIR / "shared_media" / "videos"

st.set_page_config(page_title="AI Career & Skill Learning Platform", page_icon="🎯", layout="wide")


def ensure_video_storage():
    VIDEO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return VIDEO_STORAGE_DIR


def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
                salt TEXT NOT NULL, password_hash TEXT NOT NULL, created_at TEXT NOT NULL)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS resumes(
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                filename TEXT NOT NULL, text_content TEXT NOT NULL, uploaded_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id))"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS progress(
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                skill TEXT NOT NULL, item TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL, UNIQUE(user_id, skill, item))"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS quiz_results(
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                topic TEXT NOT NULL, score INTEGER NOT NULL, total INTEGER NOT NULL,
                weak_topics TEXT NOT NULL, created_at TEXT NOT NULL)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS interview_results(
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                question TEXT NOT NULL, answer TEXT NOT NULL, feedback TEXT NOT NULL,
                created_at TEXT NOT NULL)"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS learning_videos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uploader_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                skill TEXT NOT NULL,
                description TEXT DEFAULT '',
                file_name TEXT,
                file_hash TEXT UNIQUE,
                file_path TEXT,
                video_url TEXT,
                file_size INTEGER DEFAULT 0,
                visibility TEXT NOT NULL DEFAULT 'shared',
                created_at TEXT NOT NULL,
                uploader_name TEXT NOT NULL,
                FOREIGN KEY(uploader_id) REFERENCES users(id))"""
        )

    with db() as conn:
        existing = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='learning_videos'").fetchone()
        if existing:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(learning_videos)").fetchall()]
            required = {
                "uploader_id": "INTEGER NOT NULL DEFAULT 0",
                "title": "TEXT NOT NULL DEFAULT ''",
                "skill": "TEXT NOT NULL DEFAULT ''",
                "description": "TEXT DEFAULT ''",
                "file_name": "TEXT",
                "file_hash": "TEXT UNIQUE",
                "file_path": "TEXT",
                "video_url": "TEXT",
                "file_size": "INTEGER DEFAULT 0",
                "visibility": "TEXT NOT NULL DEFAULT 'shared'",
                "created_at": "TEXT NOT NULL DEFAULT '1970-01-01T00:00:00'",
                "uploader_name": "TEXT NOT NULL DEFAULT ''",
            }
            for column_name, column_sql in required.items():
                if column_name not in columns:
                    try:
                        conn.execute(f"ALTER TABLE learning_videos ADD COLUMN {column_name} {column_sql}")
                    except sqlite3.OperationalError:
                        pass

    ensure_video_storage()


init_db()


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180000).hex()
    return salt, digest


def register_user(username, password):
    salt, digest = hash_password(password)
    try:
        with db() as c:
            c.execute(
                "INSERT INTO users(username,salt,password_hash,created_at) VALUES(?,?,?,?)",
                (username.strip(), salt, digest, datetime.now().isoformat(timespec="seconds")),
            )
        return True, "Account created. Please sign in."
    except sqlite3.IntegrityError:
        return False, "That username already exists."


def authenticate(username, password):
    with db() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
    if not row:
        return None
    _, digest = hash_password(password, row["salt"])
    return dict(row) if secrets.compare_digest(digest, row["password_hash"]) else None


def get_gemini_client():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key or genai is None:
        return None
    try:
        return genai.Client(api_key=key)
    except Exception:
        return None


def ai_text(prompt, system="You are a careful, supportive career and learning coach."):
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    if genai is None:
        return None
    try:
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=system + "\n\n" + prompt,
        )
        text = getattr(response, "text", "") or ""
        return text.strip() if isinstance(text, str) else str(text).strip()
    except Exception as exc:
        return f"Gemini error: {exc}"


def extract_resume(uploaded):
    name = uploaded.name.lower()
    raw = uploaded.getvalue()
    try:
        if name.endswith(".pdf") and fitz:
            doc = fitz.open(stream=raw, filetype="pdf")
            return "\n".join(page.get_text() for page in doc).strip()
        if name.endswith(".docx") and Document:
            doc = Document(io.BytesIO(raw))
            return "\n".join(p.text for p in doc.paragraphs).strip()
        if name.endswith(".txt"):
            return raw.decode("utf-8", errors="ignore").strip()
    except Exception as exc:
        return "Could not read file: " + str(exc)
    return ""


SKILLS = [
    "Python", "Java", "C", "C++", "SQL", "Excel", "Power BI", "Tableau", "HTML", "CSS", "JavaScript",
    "React", "Node.js", "Flask", "FastAPI", "Streamlit", "Machine Learning", "Deep Learning", "NLP",
    "Data Analysis", "Pandas", "NumPy", "Scikit-learn", "TensorFlow", "PyTorch", "Git", "GitHub",
    "Docker", "AWS", "Azure", "Communication", "Problem Solving", "Data Structures", "Algorithms",
    "REST API", "MongoDB", "MySQL", "PostgreSQL", "Linux", "Statistics", "Generative AI", "Prompt Engineering",
]
JOB_PROFILES = {
    "Python Developer": ["Python", "SQL", "Git", "REST API", "Flask", "Problem Solving"],
    "Data Analyst": ["SQL", "Excel", "Python", "Pandas", "Power BI", "Statistics", "Data Analysis"],
    "Machine Learning Intern": ["Python", "Pandas", "NumPy", "Machine Learning", "Scikit-learn", "Statistics"],
    "AI Engineer Intern": ["Python", "Machine Learning", "NLP", "Generative AI", "REST API", "Git"],
    "Frontend Developer": ["HTML", "CSS", "JavaScript", "React", "Git"],
    "Backend Developer": ["Python", "Java", "SQL", "REST API", "Flask", "Git"],
}
LESSONS = {
    "Python": {
        "en": "## Python basics\n1. Variables and data types\n2. if/else and loops\n3. Functions\n4. Lists, dictionaries and sets\n5. Files and exceptions\n\n**Practice:** Write a function that returns the largest number in a list.",
        "ta": "## Python அடிப்படைகள்\n1. Variables மற்றும் data types\n2. if/else, loops\n3. Functions\n4. List, dictionary, set\n5. File handling, errors\n\n**பயிற்சி:** ஒரு list-ல் உள்ள பெரிய எண்ணை return செய்யும் function எழுதுங்கள்.",
    },
    "SQL": {
        "en": "## SQL learning path\n1. SELECT and WHERE\n2. ORDER BY and LIMIT\n3. GROUP BY and aggregate functions\n4. JOINs\n5. Subqueries\n\n**Practice:** Find the average salary per department.",
        "ta": "## SQL கற்றல் பாதை\n1. SELECT, WHERE\n2. ORDER BY, LIMIT\n3. GROUP BY மற்றும் aggregate functions\n4. JOIN வகைகள்\n5. Subquery\n\n**பயிற்சி:** ஒவ்வொரு department-ன் average salary-ஐ கண்டுபிடிக்கவும்.",
    },
    "Machine Learning": {
        "en": "## Machine Learning basics\n1. Supervised vs unsupervised learning\n2. Train/test split\n3. Regression and classification\n4. Evaluation metrics\n5. Overfitting and regularization\n\n**Practice:** Explain why a test set must be kept separate.",
        "ta": "## Machine Learning அடிப்படைகள்\n1. Supervised / unsupervised learning\n2. Train/test split\n3. Regression, classification\n4. Evaluation metrics\n5. Overfitting\n\n**பயிற்சி:** Test data-ஐ training data-இலிருந்து ஏன் பிரிக்க வேண்டும் என்று விளக்குங்கள்.",
    },
}


def detect_skills(text):
    low = text.lower()
    found = []
    for skill in SKILLS:
        pattern = re.escape(skill.lower())
        if re.search(r"(?<!\w)" + pattern + r"(?!\w)", low):
            found.append(skill)
    return found


def resume_id_for_user(uid):
    with db() as c:
        row = c.execute("SELECT * FROM resumes WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
    return dict(row) if row else None


def save_resume(uid, filename, text):
    with db() as c:
        c.execute(
            "INSERT INTO resumes(user_id,filename,text_content,uploaded_at) VALUES(?,?,?,?)",
            (uid, filename, text, datetime.now().isoformat(timespec="seconds")),
        )


def get_resume(uid):
    return resume_id_for_user(uid)


def save_progress(uid, skill, item, completed):
    with db() as c:
        c.execute(
            """INSERT INTO progress(user_id,skill,item,completed,updated_at) VALUES(?,?,?,?,?)
            ON CONFLICT(user_id,skill,item) DO UPDATE SET completed=excluded.completed, updated_at=excluded.updated_at""",
            (uid, skill, item, int(completed), datetime.now().isoformat(timespec="seconds")),
        )


def get_progress(uid, skill):
    with db() as c:
        rows = c.execute("SELECT item,completed FROM progress WHERE user_id=? AND skill=?", (uid, skill)).fetchall()
    return {row["item"]: bool(row["completed"]) for row in rows}


def add_quiz_result(uid, topic, score, total, weak):
    with db() as c:
        c.execute(
            "INSERT INTO quiz_results(user_id,topic,score,total,weak_topics,created_at) VALUES(?,?,?,?,?,?)",
            (uid, topic, score, total, json.dumps(weak), datetime.now().isoformat(timespec="seconds")),
        )


def load_quiz_history(uid):
    with db() as c:
        return pd.read_sql_query(
            "SELECT topic,score,total,weak_topics,created_at FROM quiz_results WHERE user_id=? ORDER BY id DESC",
            c,
            params=(uid,),
        )


def search_jobs_jsearch(query, location, remote_only, date_posted, page=1):
    api_key = os.getenv("RAPIDAPI_KEY", "").strip()
    if not api_key:
        return {"jobs": [], "error": "RAPIDAPI_KEY is not configured. Create a JSearch RapidAPI key and set it before starting the app."}

    query_text = (query or "").strip() or "software engineer"
    location_text = (location or "").strip()
    params = {
        "query": f"{query_text} in {location_text}" if location_text else query_text,
        "page": str(page),
        "num_pages": "1",
        "country": "in" if any(keyword in (location_text + " " + query_text).lower() for keyword in ["india", "chennai", "mumbai", "pune", "bangalore", "hyderabad", "delhi", "kochi"]) else "us",
    }
    if location_text:
        params["location"] = location_text
    if remote_only:
        params["remote_jobs_only"] = "true"
        params["work_from_home"] = "true"
    if date_posted and date_posted != "all":
        params["date_posted"] = date_posted

    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    try:
        response = requests.get(
            "https://jsearch.p.rapidapi.com/search",
            headers=headers,
            params=params,
            timeout=25,
        )
    except requests.exceptions.Timeout:
        return {"jobs": [], "error": "The JSearch API timed out. Please try again with a broader search or a shorter query."}
    except requests.exceptions.RequestException as exc:
        return {"jobs": [], "error": f"A network error occurred while contacting JSearch: {exc}"}

    if response.status_code in (401, 403):
        return {"jobs": [], "error": "The RapidAPI key is invalid, expired, or missing JSearch access. Please check the key and subscription."}
    if response.status_code == 429:
        return {"jobs": [], "error": "RapidAPI quota has been exhausted for this key. Please wait or update your plan."}
    if response.status_code >= 400:
        msg = response.text[:250]
        return {"jobs": [], "error": f"The job API returned an error ({response.status_code}). {msg}"}

    try:
        payload = response.json()
    except ValueError:
        return {"jobs": [], "error": "The job API returned a non-JSON response. Please try again later."}

    if not isinstance(payload, dict):
        return {"jobs": [], "error": "The JSearch API returned an unexpected response format."}

    message = payload.get("message")
    if message and not payload.get("data"):
        return {"jobs": [], "error": message}

    raw_jobs = payload.get("data") or []
    if isinstance(raw_jobs, dict):
        raw_jobs = raw_jobs.get("jobs") or raw_jobs.get("results") or []
    if not isinstance(raw_jobs, list):
        return {"jobs": [], "error": "The JSearch result payload is missing the expected job list."}

    jobs = []
    for job in raw_jobs:
        if not isinstance(job, dict):
            continue
        title = str(job.get("job_title") or job.get("title") or "Not listed").strip()
        company = str(job.get("employer_name") or job.get("company") or "Not listed").strip()
        location_value = ", ".join(
            part for part in [job.get("job_city"), job.get("job_state"), job.get("job_country")] if part
        ) or (location_text or "Remote / unspecified")
        apply_link = job.get("job_apply_link") or job.get("job_google_link") or job.get("link") or ""
        description = job.get("job_description") or job.get("description") or "No description returned by the provider."
        posted = job.get("job_posted_at_datetime_utc") or job.get("job_posted_at") or job.get("date") or "Not listed"
        salary = "Not listed"
        min_salary = job.get("job_min_salary")
        max_salary = job.get("job_max_salary")
        if min_salary or max_salary:
            salary = f"{min_salary} - {max_salary}" if min_salary and max_salary else str(min_salary or max_salary)
        jobs.append(
            {
                "Title": title,
                "Company": company,
                "Location": location_value,
                "Posted": posted,
                "Type": job.get("job_employment_type") or job.get("employment_type") or "Not listed",
                "Salary": salary,
                "Description": description,
                "Apply link": apply_link,
                "Source": job.get("job_publisher") or "Job aggregator",
            }
        )

    return {"jobs": jobs, "error": None}


def get_user_videos(uid):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM learning_videos
            WHERE uploader_id=? OR visibility IN ('shared', 'public')
            ORDER BY created_at DESC
            """,
            (uid,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_uploaded_video(uid, username, title, skill, upload, visibility):
    if upload is None:
        return {"saved": False, "message": "No video file was provided."}
    allowed_types = {"video/mp4", "video/quicktime", "video/webm", "video/x-matroska"}
    file_type = (upload.type or "").lower()
    if file_type not in allowed_types and not upload.name.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
        return {"saved": False, "message": "Unsupported video format. Please upload MP4, MOV, WEBM, or MKV."}
    if upload.size > 200 * 1024 * 1024:
        return {"saved": False, "message": "Video is too large. Please choose a file under 200 MB."}

    ensure_video_storage()
    original_name = Path(upload.name).name
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", original_name)
    file_hash = hashlib.sha256(upload.getvalue()).hexdigest()
    with db() as conn:
        existing = conn.execute("SELECT * FROM learning_videos WHERE file_hash=? LIMIT 1", (file_hash,)).fetchone()
        if existing:
            return {"saved": True, "message": "This video was already uploaded and is now available to shared viewers.", "video_id": existing["id"]}

    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    target_path = VIDEO_STORAGE_DIR / unique_name
    target_path.write_bytes(upload.getvalue())
    created_at = datetime.now().isoformat(timespec="seconds")

    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO learning_videos(
                uploader_id, title, skill, description, file_name, file_hash,
                file_path, video_url, file_size, visibility, created_at, uploader_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                title.strip() or original_name,
                skill.strip() or "General",
                "",
                safe_name,
                file_hash,
                str(target_path),
                "",
                upload.size,
                visibility,
                created_at,
                username,
            ),
        )
        video_id = cursor.lastrowid
    return {"saved": True, "message": "Video uploaded and saved to the shared app storage.", "video_id": video_id}


def save_url_video(uid, username, title, skill, video_url, visibility):
    if not video_url or not video_url.strip():
        return {"saved": False, "message": "Please enter a valid video URL."}
    url = video_url.strip()
    if not url.startswith(("http://", "https://")):
        return {"saved": False, "message": "Only direct HTTP/HTTPS video URLs are supported."}
    created_at = datetime.now().isoformat(timespec="seconds")
    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO learning_videos(
                uploader_id, title, skill, description, file_name, file_hash,
                file_path, video_url, file_size, visibility, created_at, uploader_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                title.strip() or "Shared video",
                skill.strip() or "General",
                "",
                "",
                hashlib.sha256(url.encode("utf-8")).hexdigest(),
                "",
                url,
                0,
                visibility,
                created_at,
                username,
            ),
        )
        video_id = cursor.lastrowid
    return {"saved": True, "message": "Video link saved to the shared library.", "video_id": video_id}


def delete_video(uid, video_id):
    with db() as conn:
        row = conn.execute("SELECT * FROM learning_videos WHERE id=?", (video_id,)).fetchone()
        if not row:
            return False
        if row["uploader_id"] != uid:
            return False
        if row["file_path"]:
            try:
                target = Path(row["file_path"])
                if target.exists():
                    target.unlink()
            except Exception:
                pass
        conn.execute("DELETE FROM learning_videos WHERE id=?", (video_id,))
    return True


def render_video_card(video, current_user_id):
    title = video.get("title") or "Untitled video"
    skill = video.get("skill") or "General"
    uploader = video.get("uploader_name") or "Unknown user"
    visibility = video.get("visibility") or "shared"
    created = video.get("created_at") or "unknown"
    st.subheader(title)
    st.caption(f"Skill: {skill} • Uploaded by: {uploader} • {visibility} • {created}")

    file_path = video.get("file_path")
    video_url = (video.get("video_url") or "").strip()
    if video_url:
        st.video(video_url)
    elif file_path and Path(file_path).exists():
        st.video(str(file_path))
    else:
        st.warning("This saved video file is missing. The record is still visible, but the file cannot be played right now.")

    if int(video.get("uploader_id") or 0) == current_user_id:
        if st.button("Delete this video", key=f"delete_video_{video.get('id')}"):
            delete_video(current_user_id, video.get("id"))
            st.rerun()

    st.divider()


def render_page():
    if "user" not in st.session_state:
        st.session_state.user = None

    if not st.session_state.user:
        st.title("🎯 AI Resume Analyzer & Skill Learning Platform")
        st.write("Resume matching, personalized quizzes, interview practice, learning lessons and saved progress.")
        tab1, tab2 = st.tabs(["Sign in", "Create account"])
        with tab1:
            with st.form("login"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign in", use_container_width=True)
            if submitted:
                user = authenticate(u, p)
                if user:
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("Username or password is incorrect.")
        with tab2:
            with st.form("register"):
                nu = st.text_input("Choose username")
                np = st.text_input("Choose password", type="password")
                cp = st.text_input("Confirm password", type="password")
                ok = st.form_submit_button("Create account", use_container_width=True)
            if ok:
                if len(nu.strip()) < 3:
                    st.error("Username must contain at least 3 characters.")
                elif len(np) < 8:
                    st.error("Use a password with at least 8 characters.")
                elif np != cp:
                    st.error("Passwords do not match.")
                else:
                    good, msg = register_user(nu, np)
                    (st.success if good else st.error)(msg)
        st.info("Use a sample resume while testing. The app stores your uploaded resume text locally in the SQLite database until you delete it.")
        st.stop()

    user = st.session_state.user
    uid = user["id"]
    with st.sidebar:
        st.title("🎯 Career Hub")
        st.caption("Signed in as " + user["username"])
        page = st.radio(
            "Navigate",
            [
                "Dashboard",
                "Resume Analyzer",
                "Resume Quiz",
                "Mock Interview",
                "AI Skill Tutor",
                "Lessons & Practice",
                "Learning Videos",
                "Job Listings API",
                "My Progress & Privacy",
            ],
        )
        if st.button("Sign out", use_container_width=True):
            st.session_state.user = None
            st.rerun()

    resume = get_resume(uid)
    resume_text = resume["text_content"] if resume else ""
    skills = detect_skills(resume_text)

    if page == "Dashboard":
        st.title("Welcome to your AI Career Hub")
        a, b, c, d = st.columns(4)
        a.metric("Resume uploaded", "Yes" if resume else "No")
        b.metric("Skills detected", len(skills))
        hist = load_quiz_history(uid)
        c.metric("Quiz attempts", len(hist))
        with db() as conn:
            completed = conn.execute("SELECT COUNT(*) n FROM progress WHERE user_id=? AND completed=1", (uid,)).fetchone()["n"]
        d.metric("Learning items done", completed)
        st.subheader("Your next steps")
        st.markdown("1. Upload your latest resume in **Resume Analyzer**.\n2. Try the resume-based quiz and review weak topics.\n3. Practise interview answers and use the bilingual skill lessons.\n4. Save progress and delete your resume whenever you want.")
        if skills:
            st.write("Detected skills:", ", ".join(skills))
        if not os.getenv("GEMINI_API_KEY"):
            st.warning("Gemini API key is not configured. AI-specific evaluation will use a basic fallback until you add GEMINI_API_KEY.")
    elif page == "Resume Analyzer":
        st.title("📄 Resume Analyzer")
        up = st.file_uploader("Upload resume (PDF, DOCX or TXT)", type=["pdf", "docx", "txt"])
        if up:
            txt = extract_resume(up)
            if txt:
                save_resume(uid, up.name, txt)
                st.success("Resume text extracted and saved.")
                st.rerun()
            else:
                st.error("No readable text found. For scanned PDFs, add OCR support or upload a text-based PDF.")
        if resume:
            st.subheader("Current resume")
            st.caption(f"{resume['filename']} · uploaded {resume['uploaded_at']}")
            st.text_area("Extracted text preview", resume_text[:10000], height=220, disabled=True)
            st.subheader("Detected skills")
            st.write(", ".join(skills) if skills else "No listed skills detected yet. Add skills in a clearly labeled Skills section.")
            target = st.selectbox("Target role", list(JOB_PROFILES.keys()))
            needed = JOB_PROFILES[target]
            matched = [x for x in needed if x.lower() in [skill.lower() for skill in skills]]
            missing = [x for x in needed if x not in matched]
            score = round(100 * len(matched) / max(1, len(needed)))
            x, y, z = st.columns(3)
            x.metric("Role skill coverage", f"{score}%")
            y.metric("Matched skills", len(matched))
            z.metric("Skills to learn", len(missing))
            st.progress(score / 100)
            st.write("**Matched:**", ", ".join(matched) if matched else "None detected")
            st.write("**Potential gaps:**", ", ".join(missing) if missing else "No gaps in this small checklist")
            st.caption("This is a simple checklist, not a hiring probability. Job requirements differ by employer.")
            if st.button("Generate resume improvement tips"):
                result = ai_text("Review this resume text. Give 5 specific, honest improvements and a stronger project-bullet example. Do not invent experience.\n\n" + resume_text[:12000])
                if result is None:
                    st.warning("GEMINI_API_KEY is not configured. Add your key to enable Gemini-backed resume feedback.")
                    st.write("Add measurable project outcomes, list tools used, tailor the summary to the target role, and keep formatting consistent.")
                elif result.startswith("Gemini error:"):
                    st.warning(result)
                    st.write("Add measurable project outcomes, list tools used, tailor the summary to the target role, and keep formatting consistent.")
                else:
                    st.write(result)
        else:
            st.info("Upload a resume to unlock skill matching and personalized quiz/interview practice.")
    elif page == "Resume Quiz":
        st.title("🧠 Resume & Project Quiz")
        if not resume_text:
            st.warning("Upload a resume first so quiz prompts can be personalized.")
        else:
            topic = st.selectbox("Quiz topic", ["Resume projects"] + (skills or ["Python", "SQL", "Machine Learning"]))
            count = st.slider("Number of questions", 3, 10, 5)
            if st.button("Generate personalized quiz", type="primary"):
                prompt = f"""Create {count} short multiple-choice questions using only the resume details below, focusing on the user's projects and the topic '{topic}'. If resume details do not support a specific claim, ask general questions about the selected skill instead. Return STRICT JSON array, each item: {{question, options:[four strings], answer_index:0-3, explanation, topic}}. Avoid guessing facts about the user. Resume:\n{resume_text[:9000]}"""
                generated = ai_text(prompt, "You generate fair educational quiz questions. Output valid JSON only.")
                quiz = None
                if generated is not None and not generated.startswith("Gemini error:"):
                    try:
                        cleaned = re.sub(r"^```(?:json)?|```$", "", generated.strip(), flags=re.M).strip()
                        quiz = json.loads(cleaned)
                    except Exception:
                        st.warning("AI response could not be parsed. Using a fallback quiz.")
                if generated is None:
                    st.info("Gemini is not configured. A built-in offline quiz will be used instead.")
                elif generated.startswith("Gemini error:"):
                    st.warning(generated)
                base_topic = topic if topic != "Resume projects" else (skills[0] if skills else "Python")
                if not isinstance(quiz, list):
                    quiz = []
                cleaned_quiz = []
                seen_questions = set()
                for item in quiz:
                    if not isinstance(item, dict):
                        continue
                    question_text = str(item.get("question", "")).strip()
                    options = item.get("options", [])
                    try:
                        answer_index = int(item.get("answer_index", -1))
                    except (TypeError, ValueError):
                        answer_index = -1
                    normalized = re.sub(r"\W+", " ", question_text.lower()).strip()
                    if (
                        not question_text
                        or normalized in seen_questions
                        or not isinstance(options, list)
                        or len(options) != 4
                        or answer_index not in range(4)
                    ):
                        continue
                    seen_questions.add(normalized)
                    item["question"] = question_text
                    item["options"] = [str(x) for x in options]
                    item["answer_index"] = answer_index
                    cleaned_quiz.append(item)
                quiz = cleaned_quiz
                fallback_items = [
                    (f"What should you explain first about your {base_topic} project?", ["The problem it solves", "Only the project title", "Only the colour of the UI", "Unrelated personal details"], 0, "Start with the problem and why the project is useful."),
                    (f"When describing your work on a {base_topic} project, what should you include?", ["Your actual contribution", "Work done by others as your own", "Only the project name", "No technical details at all"], 0, "Clearly describe the parts you personally completed."),
                    (f"How can you show that your {base_topic} project works?", ["Explain testing and a real result", "Make up performance numbers", "Avoid showing the output", "Say it works without evidence"], 0, "Testing and honest results help demonstrate that a project works."),
                    (f"If you faced a bug in your {base_topic} project, what is the best response?", ["Explain how you investigated and fixed it", "Hide the issue and claim there were no bugs", "Blame someone without checking", "Remove all project details"], 0, "Explain the debugging steps and what you learned."),
                    (f"Which detail helps an interviewer understand your {base_topic} project?", ["Tools used and why you chose them", "A list of unrelated tools", "Features you never built", "An answer with no examples"], 0, "Connect each important tool to the task it helped you perform."),
                    (f"What is a useful way to improve a {base_topic} project after feedback?", ["Prioritize a specific improvement and test it", "Ignore all feedback", "Change everything without a plan", "Claim the project is perfect"], 0, "Use feedback to make a focused change and check the result."),
                    (f"How should you describe a limitation in your {base_topic} project?", ["State it honestly and explain possible improvements", "Pretend the limitation does not exist", "Invent a feature to cover it", "Avoid answering"], 0, "Honesty about limitations plus a plan shows understanding."),
                    (f"What should a good project demo for {base_topic} include?", ["A clear workflow and example output", "Only a blank screen", "Unrelated screenshots", "A feature that is not implemented"], 0, "Show a realistic workflow and the output produced."),
                    (f"Why should you mention your project’s result when discussing {base_topic}?", ["It shows what the work achieved", "It replaces the need to explain your work", "It lets you invent achievements", "It hides the project purpose"], 0, "A truthful result helps the interviewer understand the project's value."),
                    (f"If asked why you selected a tool for {base_topic}, what should you do?", ["Give a reason related to the project requirements", "Say you chose it randomly", "Name many tools without context", "Avoid explaining the choice"], 0, "Explain how the tool fits the requirements or task."),
                ]
                for question_text, options, answer_index, explanation in fallback_items:
                    normalized = re.sub(r"\W+", " ", question_text.lower()).strip()
                    if normalized not in seen_questions and len(quiz) < count:
                        quiz.append({"question": question_text, "options": options, "answer_index": answer_index, "explanation": explanation, "topic": base_topic})
                        seen_questions.add(normalized)
                st.session_state.quiz = quiz[:count]
                st.session_state.quiz_topic = topic
                st.session_state.quiz_submitted = False
            if st.session_state.get("quiz"):
                quiz = st.session_state.quiz
                with st.form("quiz_form"):
                    answers = []
                    for i, q in enumerate(quiz):
                        st.markdown(f"**Q{i+1}. {q.get('question','')}**")
                        opts = q.get("options", [])
                        answers.append(st.radio("Choose one", opts, key=f"q_{i}", index=None, label_visibility="collapsed"))
                    submit = st.form_submit_button("Submit answers")
                if submit:
                    correct = 0
                    weak = []
                    for i, (q, ans) in enumerate(zip(quiz, answers)):
                        opts = q.get("options", [])
                        idx = opts.index(ans) if ans in opts else -1
                        good = idx == int(q.get("answer_index", -99))
                        correct += int(good)
                        if not good:
                            weak.append(q.get("topic", st.session_state.get("quiz_topic", "General")))
                        st.markdown(f"**Q{i+1}: {'Correct' if good else 'Review this'}**")
                        if not good:
                            suggested_index = int(q.get("answer_index", 0))
                            suggested = opts[suggested_index] if opts and 0 <= suggested_index < len(opts) else "Review"
                            st.write("Suggested answer:", suggested)
                        st.write(q.get("explanation", "Review the concept and explain it in your own words."))
                    add_quiz_result(uid, st.session_state.get("quiz_topic", "General"), correct, len(quiz), sorted(set(weak)))
                    st.success(f"Score: {correct}/{len(quiz)} ({round(correct/len(quiz)*100)}%)")
                    if weak:
                        st.warning("Weak topics to revise: " + ", ".join(sorted(set(weak))))
                    else:
                        st.success("Great work. Keep practising with new examples.")
                    st.session_state.quiz = None
        st.caption("Dynamic generation uses Gemini when configured; the offline fallback is intentionally basic.")
    elif page == "Mock Interview":
        st.title("🎤 Real-time AI HR Interview")
        st.caption("ஒரு real interview போல: ஒரு கேள்விக்கு பதில் சொல்லுங்கள்; உங்கள் பதிலின் அடிப்படையில் அடுத்த கேள்வி வரும்.")
        if not resume_text:
            st.warning("முதலில் Resume Analyzer பகுதியில் உங்கள் resume upload செய்யுங்கள்.")
        else:
            target = st.selectbox("Interview role", list(JOB_PROFILES.keys()), key="hr_role")
            mode = st.radio("Interview mode", ["HR + Technical", "HR only", "Technical only"], horizontal=True)
            if "hr_interview" not in st.session_state or st.session_state.get("hr_role_saved") != target:
                st.session_state.hr_interview = []
                st.session_state.hr_role_saved = target
                st.session_state.hr_q = f"Tell me about yourself and explain why you are interested in the {target} role."
                st.session_state.hr_started = False
                st.session_state.hr_done = False

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Start / Restart interview", type="primary"):
                    st.session_state.hr_interview = []
                    st.session_state.hr_q = f"Tell me about yourself and explain why you are interested in the {target} role."
                    st.session_state.hr_started = True
                    st.session_state.hr_done = False
                    st.rerun()
            with col2:
                if st.button("End interview"):
                    st.session_state.hr_done = True
                    st.rerun()

            if not st.session_state.hr_started:
                st.info("Start / Restart interview அழுத்தினால் interview தொடங்கும். Resume-ல் உள்ள project மற்றும் skills பற்றி follow-up கேள்விகள் வரும்.")
            else:
                for i, turn in enumerate(st.session_state.hr_interview, 1):
                    with st.chat_message("assistant"):
                        st.markdown(f"**Question {i}:** {turn['question']}")
                    with st.chat_message("user"):
                        st.write(turn["answer"])
                    with st.expander(f"Feedback for answer {i}"):
                        st.markdown(turn.get("feedback", ""))
                if not st.session_state.hr_done:
                    qnum = len(st.session_state.hr_interview) + 1
                    st.markdown(f"### HR Interviewer · Question {qnum}")
                    st.info(st.session_state.hr_q)
                    answer = st.text_area("Your answer", key=f"hr_answer_{qnum}", height=150, placeholder="Answer as you would speak to a real interviewer. Be honest and specific.")
                    audio = None
                    try:
                        audio = st.audio_input("Or record your answer (if your browser supports microphone recording)")
                    except Exception:
                        pass
                    if st.button("Submit answer & get follow-up", type="primary", key=f"hr_submit_{qnum}"):
                        spoken_answer = answer.strip()
                        if audio is not None and not spoken_answer:
                            try:
                                if genai and os.getenv("GEMINI_API_KEY"):
                                    audio_bytes = audio.getvalue()
                                    response = genai.Client(api_key=os.getenv("GEMINI_API_KEY")).models.generate_content(
                                        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                                        contents=[
                                            "Transcribe the candidate's recorded interview answer verbatim. Return only the transcription.",
                                            {"mime_type": audio.type or "audio/wav", "data": audio_bytes},
                                        ],
                                    )
                                    spoken_answer = (getattr(response, "text", "") or "").strip()
                            except Exception:
                                spoken_answer = ""
                        if len(spoken_answer) < 20:
                            st.error("கொஞ்சம் விரிவாக answer type செய்யுங்கள் அல்லது clear audio record செய்யுங்கள். குறைந்தது 20 characters தேவை.")
                        else:
                            history = st.session_state.hr_interview
                            history_text = "\\n".join([f"Q: {t['question']}\\nA: {t['answer']}" for t in history[-6:]])
                            eval_prompt = f"""Act as a fair, professional human-style interviewer for a {target} position. Interview mode: {mode}. Evaluate the candidate's answer to the CURRENT question. Return concise headings:
- Score: X/10
- What was strong
- What was missing / follow-up concerns
- Specific improvement tip
- Integrity / authenticity check: flag only concrete concerns such as claims unsupported by the supplied resume, contradictions, or generic answers that do not answer the question. Do NOT claim you can reliably detect cheating or AI use. Do not accuse based on writing style alone.
- Next interviewer question: exactly ONE natural follow-up question, based on the answer. If the answer is adequate, move to a different relevant HR/technical topic. Never invent resume facts.
Resume context: {resume_text[:6500]}
Previous interview:
{history_text}
Current question: {st.session_state.hr_q}
Candidate answer: {spoken_answer}
Give constructive feedback, not a hiring decision."""
                            feedback = ai_text(eval_prompt)
                            if feedback is None:
                                feedback = ("**Basic feedback (Gemini API not configured):**\n"
                                            f"- Your answer has {len(spoken_answer.split())} words.\n"
                                            "- Use Situation → Task → Action → Result for project examples.\n"
                                            "- Give specific details you can honestly explain; do not claim work you did not do.\n"
                                            "- Next question: What was the biggest challenge in this project, and how did you solve it?")
                            elif feedback.startswith("Gemini error:"):
                                st.warning(feedback)
                            next_prompt = f"""You are a professional {target} interviewer conducting a live {mode} interview. Based on the candidate's latest answer, ask exactly ONE short, natural next question. Use resume details only when supported. Ask a follow-up if the answer is vague, otherwise move to another relevant topic. No answer, no explanation, no numbering.
Resume: {resume_text[:5000]}
Previous Q&A: {history_text}
Latest question: {st.session_state.hr_q}
Latest answer: {spoken_answer}"""
                            next_q = ai_text(next_prompt)
                            if next_q is None:
                                next_q = "Can you describe one specific challenge you faced and the steps you personally took to solve it?"
                            elif next_q.startswith("Gemini error:"):
                                st.warning(next_q)
                                next_q = "Can you describe one specific challenge you faced and the steps you personally took to solve it?"
                            next_q = re.sub(r"^\s*(Next interviewer question:|Question\s*\d*[:.]?)\s*", "", next_q, flags=re.I).strip()
                            history.append({"question": st.session_state.hr_q, "answer": spoken_answer, "feedback": feedback})
                            st.session_state.hr_interview = history
                            st.session_state.hr_q = next_q
                            with db() as conn:
                                conn.execute(
                                    "INSERT INTO interview_results(user_id,question,answer,feedback,created_at) VALUES(?,?,?,?,?)",
                                    (uid, st.session_state.hr_interview[-1]["question"], spoken_answer, feedback, datetime.now().isoformat(timespec="seconds")),
                                )
                            st.rerun()
                else:
                    st.success("Interview ended. Review the feedback above.")
                    if st.session_state.hr_interview:
                        turns = st.session_state.hr_interview
                        st.markdown("### Interview performance report")
                        scores = []
                        for turn in turns:
                            match = re.search(r"Score\s*:\s*(\d{1,2})\s*/\s*10", turn.get("feedback", ""), re.I)
                            if match:
                                scores.append(min(10, int(match.group(1))))
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Questions answered", len(turns))
                        c2.metric("Average AI score", f"{sum(scores)/len(scores):.1f}/10" if scores else "Not available")
                        c3.metric("Scored answers", f"{len(scores)}/{len(turns)}")
                        st.write("Use the feedback to practise weak topics. Scores are AI-generated coaching estimates, not an actual hiring decision.")
                        report_lines = [f"AI MOCK INTERVIEW REPORT\nRole: {target}\nMode: {mode}\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
                        for idx, turn in enumerate(turns, 1):
                            report_lines.extend([f"\nQUESTION {idx}\n{turn['question']}\n", f"ANSWER\n{turn['answer']}\n", f"FEEDBACK\n{turn.get('feedback','')}\n", "-"*60])
                        report_lines.append("\nNote: AI feedback may be inaccurate. This is practice feedback, not a real employer assessment.")
                        report_text = "\n".join(report_lines)
                        st.download_button("Download full interview report (.txt)", report_text, file_name="ai_mock_interview_report.txt", mime="text/plain")
                        st.download_button("Download interview data (.json)", json.dumps({"role": target, "mode": mode, "turns": turns}, ensure_ascii=False, indent=2), file_name="ai_mock_interview_report.json", mime="application/json")
                        if st.button("Start a new interview"):
                            st.session_state.hr_started = False
                            st.session_state.hr_done = False
                            st.session_state.hr_interview = []
                            st.rerun()
    elif page == "AI Skill Tutor":
        st.title("🤖 AI Skill Tutor")
        if not skills:
            st.info("Upload a resume to personalize learning suggestions, or choose a skill manually.")
        skill = st.selectbox("Skill to learn", sorted(set(skills + SKILLS)))
        language = st.radio("Response language", ["English", "Tamil", "Tamil + English"], horizontal=True)
        question = st.text_area("Ask your tutor", placeholder="Example: Explain SQL JOIN with a simple example")
        if st.button("Ask AI tutor", type="primary"):
            lang_prompt = {"English": "Answer in simple English.", "Tamil": "Answer in simple Tamil.", "Tamil + English": "Explain in easy Tamil-English mix."}[language]
            prompt = f"{lang_prompt} Teach the skill {skill} to a beginner. Include a simple explanation, example, a short practice task and answer key. User question: {question or 'Give me a beginner lesson.'}"
            answer = ai_text(prompt)
            if answer is None:
                st.warning("GEMINI_API_KEY is not configured. This is an offline learning starter, not a live AI response.")
                offline = LESSONS.get(skill, {}).get("ta" if language == "Tamil" else "en", f"Start with {skill} basics, learn one concept at a time, practise a small example, and explain it without looking at notes.")
                st.markdown(offline)
            elif answer.startswith("Gemini error:"):
                st.warning(answer)
                offline = LESSONS.get(skill, {}).get("ta" if language == "Tamil" else "en", f"Start with {skill} basics, learn one concept at a time, practise a small example, and explain it without looking at notes.")
                st.markdown(offline)
            else:
                st.markdown(answer)
    elif page == "Lessons & Practice":
        st.title("📚 Tamil + English Lessons, Notes & Coding Practice")
        skill = st.selectbox("Choose skill", sorted(set(skills + list(LESSONS.keys()) + SKILLS)))
        language = st.segmented_control("Language", ["English", "Tamil", "Tamil + English"], default="Tamil + English")
        lesson_items = ["Read beginner lesson", "Write summary notes", "Complete coding/practice task", "Explain concept aloud"]
        progress = get_progress(uid, skill)
        st.subheader(skill + " learning checklist")
        for item in lesson_items:
            checked = st.checkbox(item, value=progress.get(item, False), key=f"progress_{skill}_{item}")
            save_progress(uid, skill, item, checked)
        st.divider()
        if skill in LESSONS:
            if language == "Tamil":
                st.markdown(LESSONS[skill]["ta"])
            elif language == "English":
                st.markdown(LESSONS[skill]["en"])
            else:
                st.markdown(LESSONS[skill]["en"])
                st.markdown(LESSONS[skill]["ta"])
        else:
            if language != "Tamil":
                st.markdown(f"## {skill}: beginner plan\n1. Learn the core terms.\n2. Follow one small worked example.\n3. Practise independently.\n4. Build a mini-project and add it to your portfolio.")
            if language != "English":
                st.markdown(f"## {skill}: தமிழ் வழிகாட்டி\n1. அடிப்படை சொற்களை கற்றுக்கொள்ளுங்கள்.\n2. ஒரு சிறிய example-ஐ புரிந்துகொள்ளுங்கள்.\n3. நீங்களே practice செய்யுங்கள்.\n4. ஒரு mini-project செய்து portfolio-வில் சேர்க்கவும்.")
        custom = st.text_input("Ask for a lesson / code example")
        if st.button("Create lesson or coding example"):
            result = ai_text(f"Teach {skill} in {language}. User request: {custom}. Include a beginner explanation, code only if relevant, expected output, and one practice task.")
            if result is None:
                st.warning("GEMINI_API_KEY is not configured. Use the built-in offline lesson checklist for now.")
                st.markdown("Offline practice prompt: write one short explanation, one example, and one troubleshooting note using your own words.")
            elif result.startswith("Gemini error:"):
                st.warning(result)
                st.markdown("Offline practice prompt: write one short explanation, one example, and one troubleshooting note using your own words.")
            else:
                st.markdown(result)
    elif page == "Learning Videos":
        st.title("🎬 Shared Learning Videos")
        skill = st.selectbox("Skill", sorted(set(skills + SKILLS)))
        video_filter = st.selectbox("View videos for", ["All shared videos", "My videos only"])
        with st.form("video_upload_form"):
            title = st.text_input("Video title", value="My learning video")
            selected_skill = st.selectbox("Skill / category", sorted(set(skills + SKILLS)), index=0 if skill in set(skills + SKILLS) else 0)
            visibility = st.radio("Visibility", ["shared", "private"], horizontal=True, help="Shared videos are visible to all signed-in users on the same app. Private videos remain visible only to you.")
            source_url = st.text_input("YouTube / public video URL (optional)")
            uploaded_file = st.file_uploader("Upload a local video file (MP4, MOV, WEBM, MKV)", type=["mp4", "mov", "webm", "mkv"])
            save_video = st.form_submit_button("Save video")

        if save_video:
            if uploaded_file is not None:
                result = save_uploaded_video(uid, user["username"], title, selected_skill, uploaded_file, visibility)
                st.success(result["message"])
            elif source_url.strip():
                result = save_url_video(uid, user["username"], title, selected_skill, source_url.strip(), visibility)
                st.success(result["message"])
            else:
                st.warning("Please upload a file or paste a public video URL.")
            st.rerun()

        videos = get_user_videos(uid)
        if video_filter == "My videos only":
            videos = [video for video in videos if int(video.get("uploader_id") or 0) == uid]
        if skill and skill != "All":
            videos = [video for video in videos if (video.get("skill") or "").lower() == skill.lower()]

        if not videos:
            st.info("No shared videos yet. Upload a video or add a valid URL so other users can view it after sign-in.")
        else:
            for video in videos:
                render_video_card(video, uid)

        st.info("For copyright and reliability, upload only videos you own or have permission to share. This app stores local files in a persistent project folder so other users can view the same shared video on the same computer or deployment.")
    elif page == "Job Listings API":
        st.title("💼 Multi-Source Job Search")
        st.write("Search public job listings aggregated from multiple job sites using JSearch through RapidAPI.")
        st.info("One key powers this aggregator; it does not provide private access to every job board. Results depend on the API plan, location, and provider availability.")
        query = st.text_input("Job title / keyword", "Python Developer")
        location = st.text_input("Location", "Chennai, India")
        col1, col2 = st.columns(2)
        with col1:
            remote_only = st.checkbox("Remote jobs only", value=False)
        with col2:
            date_posted = st.selectbox("Posted", ["all", "today", "3days", "week", "month"], index=3)
        if st.button("Search live jobs", type="primary"):
            result = search_jobs_jsearch(query, location, remote_only, date_posted)
            if result["error"]:
                st.error(result["error"])
                st.markdown("Get a key: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch")
                st.caption("No fake or sample job postings are shown as live results.")
            else:
                jobs = result["jobs"]
                if not jobs:
                    st.warning("The API returned no jobs for this search. Try a broader keyword, a different city, or lower filters.")
                else:
                    st.success(f"Found {len(jobs)} live listing(s). Check the employer and original posting before applying.")
                    jobs_df = pd.DataFrame(
                        [
                            {
                                "Title": job["Title"],
                                "Company": job["Company"],
                                "Location": job["Location"],
                                "Posted": job["Posted"],
                                "Type": job["Type"],
                                "Salary": job["Salary"],
                                "Source": job["Source"],
                            }
                            for job in jobs
                        ]
                    )
                    st.dataframe(jobs_df, use_container_width=True, hide_index=True)
                    for job in jobs:
                        description = (job["Description"] or "No description returned by the provider.").strip()
                        if job["Apply link"]:
                            st.markdown(f"- [{job['Title']} — {job['Company']}]({job['Apply link']}) · {job['Location']} · {job['Source']}")
                        else:
                            st.write(f"- {job['Title']} — {job['Company']} · {job['Location']} · {job['Source']}")
                        if description:
                            st.caption(description[:400] + ("..." if len(description) > 400 else ""))
        st.caption("JSearch aggregates public job postings from sources such as LinkedIn, Indeed, Glassdoor and other job sites where available. Availability, freshness, and application links are controlled by the provider.")
    elif page == "My Progress & Privacy":
        st.title("🔐 My Progress & Privacy")
        with db() as conn:
            prog = pd.read_sql_query("SELECT skill,item,completed,updated_at FROM progress WHERE user_id=? ORDER BY skill,item", conn, params=(uid,))
            quiz_hist = load_quiz_history(uid)
            interviews = pd.read_sql_query("SELECT question,feedback,created_at FROM interview_results WHERE user_id=? ORDER BY id DESC", conn, params=(uid,))
        st.subheader("Saved learning progress")
        st.dataframe(prog, use_container_width=True, hide_index=True) if not prog.empty else st.write("No progress saved yet.")
        st.subheader("Quiz history")
        st.dataframe(quiz_hist, use_container_width=True, hide_index=True) if not quiz_hist.empty else st.write("No quiz attempts yet.")
        st.subheader("Interview practice history")
        st.dataframe(interviews, use_container_width=True, hide_index=True) if not interviews.empty else st.write("No interview evaluations saved yet.")
        st.divider()
        st.subheader("Resume data deletion")
        st.write("Deleting your resume removes the saved resume text. Quiz and learning progress remain unless you delete your account.")
        if resume and st.button("Delete my saved resume", type="primary"):
            with db() as conn:
                conn.execute("DELETE FROM resumes WHERE user_id=?", (uid,))
            st.success("Saved resume deleted.")
            st.rerun()
        st.warning("This starter app stores data in a local SQLite file. For public deployment, add HTTPS, secure session handling, rate limits, backups, access controls, and a reviewed privacy policy.")


def main():
    render_page()


if __name__ == "__main__":
    main()
