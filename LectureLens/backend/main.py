import os, sqlite3, hashlib, secrets, json, math
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Header
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
import nlp
BASE = os.path.dirname(os.path.abspath(__file__)); UP = os.path.join(BASE, "uploads")
DB = os.path.join(BASE, "..", "database", "lecturelens.db")
ALLOWED = {".mp3", ".wav", ".m4a", ".webm"}; MAX_MB = 100
app = FastAPI(title="LectureLens")

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c
with db() as c:
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, password_hash TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INT);
    CREATE TABLE IF NOT EXISTS lectures(id INTEGER PRIMARY KEY, user_id INT, title TEXT, subject TEXT, audio_path TEXT, duration REAL DEFAULT 0, status TEXT, mode TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS transcripts(id INTEGER PRIMARY KEY, lecture_id INT UNIQUE, text TEXT, language TEXT, segments TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS topics(id INTEGER PRIMARY KEY, lecture_id INT, topic_name TEXT, importance_score REAL);
    CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, lecture_id INT UNIQUE, content TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, lecture_id INT, question TEXT, answer TEXT, question_type TEXT, extra TEXT);
    CREATE TABLE IF NOT EXISTS flashcards(id INTEGER PRIMARY KEY, lecture_id INT, front TEXT, back TEXT);
    CREATE TABLE IF NOT EXISTS summaries(lecture_id INT PRIMARY KEY, data TEXT);""")

def hp(pw, salt=None):
    salt = salt or secrets.token_hex(8); return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120000).hex()
def user(authorization: str = Header(None)):
    r = db().execute("SELECT user_id FROM sessions WHERE token=?", ((authorization or "").replace("Bearer ", ""),)).fetchone()
    if not r: raise HTTPException(401, "Please log in to continue.")
    return r[0]
def own(lid, uid):
    r = db().execute("SELECT * FROM lectures WHERE id=? AND user_id=?", (lid, uid)).fetchone()
    if not r: raise HTTPException(404, "Lecture not found.")
    return r

class Reg(BaseModel): name: str; email: EmailStr; password: str
class Log(BaseModel): email: EmailStr; password: str
class Edit(BaseModel): title: str | None = None; subject: str | None = None; transcript: str | None = None

@app.post("/api/auth/register")
def register(b: Reg):
    if len(b.password) < 8: raise HTTPException(400, "Password must be at least 8 characters.")
    try:
        with db() as c: c.execute("INSERT INTO users(name,email,password_hash) VALUES(?,?,?)", (b.name.strip(), b.email.lower(), hp(b.password)))
    except sqlite3.IntegrityError: raise HTTPException(400, "An account with this email already exists.")
    return {"ok": True}
@app.post("/api/auth/login")
def login(b: Log):
    r = db().execute("SELECT * FROM users WHERE email=?", (b.email.lower(),)).fetchone()
    if not r or hp(b.password, r["password_hash"].split("$")[0]) != r["password_hash"]: raise HTTPException(401, "Incorrect email or password.")
    t = secrets.token_urlsafe(32)
    with db() as c: c.execute("INSERT INTO sessions VALUES(?,?)", (t, r["id"]))
    return {"token": t, "name": r["name"], "email": r["email"]}
@app.post("/api/auth/logout")
def logout(authorization: str = Header(None)):
    with db() as c: c.execute("DELETE FROM sessions WHERE token=?", ((authorization or "").replace("Bearer ", ""),))
    return {"ok": True}

# ---- Speech: REAL (faster-whisper if installed) or DEMO fallback, always labelled in the UI ----
DEMO = ("Today we are going to discuss machine learning. Machine learning is a subset of artificial intelligence that enables systems to learn from data. "
 "There are three major types of machine learning. Supervised learning uses labeled training data to learn input-output pairs. "
 "Classification is a task that predicts a category for each input. Regression is a task that predicts a continuous value such as a price. "
 "Unsupervised learning finds hidden patterns in unlabeled data. Clustering is a technique that groups similar data points together. "
 "A neural network is a model made of connected layers of neurons. Neural networks are trained with gradient descent to reduce error. "
 "Overfitting happens when a model memorizes training data and performs poorly on new data. Machine learning models should be validated on test data.")
def transcribe(path):
    try: from faster_whisper import WhisperModel
    except ImportError:
        return [(i * 14.0, s, None) for i, s in enumerate(nlp.sentences(DEMO))], "en", "demo"
    segs, info = WhisperModel("base", compute_type="int8").transcribe(path)
    segs = [(s.start, s.text.strip(), round(math.exp(s.avg_logprob), 2)) for s in segs]
    if not segs: raise ValueError("no speech")
    return segs, info.language, "real"

def analyze(lid, text, duration):
    text = nlp.clean(text)
    with db() as c:
        for t in ("topics", "questions", "flashcards"): c.execute(f"DELETE FROM {t} WHERE lecture_id=?", (lid,))
        c.executemany("INSERT INTO topics(lecture_id,topic_name,importance_score) VALUES(?,?,?)", [(lid, n, s) for n, s in nlp.topics(text)])
        for q in nlp.questions(text):
            c.execute("INSERT INTO questions(lecture_id,question,answer,question_type,extra) VALUES(?,?,?,?,?)",
                      (lid, q["question"], q["answer"], q["type"], json.dumps({"options": q.get("options"), "explanation": q.get("explanation")})))
        c.executemany("INSERT INTO flashcards(lecture_id,front,back) VALUES(?,?,?)", [(lid, f, b) for f, b in nlp.flashcards(text)])
        c.execute("REPLACE INTO notes(lecture_id,content) VALUES(?,?)", (lid, nlp.notes(text)))
        c.execute("REPLACE INTO summaries VALUES(?,?)", (lid, json.dumps({**nlp.summarize(text), "key_points": nlp.key_points(text),
            "keywords": nlp.keywords(text, 25), "definitions": nlp.definitions(text), "stats": nlp.stats(text, duration)})))
        c.execute("UPDATE lectures SET status='Completed' WHERE id=?", (lid,))

@app.post("/api/lectures/upload")
async def upload(file: UploadFile = File(...), title: str = Form(""), subject: str = Form("General"), duration: float = Form(0), uid: int = Depends(user)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED: raise HTTPException(400, "Unable to process the audio file. Please upload MP3, WAV, M4A or WEBM.")
    data = await file.read()
    if not data: raise HTTPException(400, "The audio file is empty.")
    if len(data) > MAX_MB * 1048576: raise HTTPException(400, f"File is too large (max {MAX_MB} MB).")
    path = os.path.join(UP, secrets.token_hex(8) + ext); open(path, "wb").write(data)
    with db() as c:
        lid = c.execute("INSERT INTO lectures(user_id,title,subject,audio_path,duration,status) VALUES(?,?,?,?,?,'Transcribing')",
                        (uid, (title or file.filename)[:200], subject[:100], path, duration)).lastrowid
    try:
        segs, lang, mode = transcribe(path); text = " ".join(s[1] for s in segs); dur = duration or segs[-1][0] + 10
        with db() as c:
            c.execute("UPDATE lectures SET status='Analyzing', mode=?, duration=? WHERE id=?", (mode, dur, lid))
            c.execute("REPLACE INTO transcripts(lecture_id,text,language,segments) VALUES(?,?,?,?)", (lid, text, lang, json.dumps(segs)))
        analyze(lid, text, dur)
    except Exception:
        with db() as c: c.execute("UPDATE lectures SET status='Failed' WHERE id=?", (lid,))
        raise HTTPException(500, "Speech could not be detected clearly. Please try a recording with better audio quality.")
    return {"id": lid, "mode": mode}

@app.get("/api/lectures")
def lectures(uid: int = Depends(user)):
    return [dict(r) for r in db().execute("SELECT id,title,subject,duration,status,mode,created_at FROM lectures WHERE user_id=? ORDER BY id DESC", (uid,))]
@app.get("/api/lectures/{lid}")
def detail(lid: int, uid: int = Depends(user)):
    l = dict(own(lid, uid)); l.pop("audio_path"); c = db()
    t = c.execute("SELECT * FROM transcripts WHERE lecture_id=?", (lid,)).fetchone()
    s = c.execute("SELECT data FROM summaries WHERE lecture_id=?", (lid,)).fetchone()
    n = c.execute("SELECT content FROM notes WHERE lecture_id=?", (lid,)).fetchone()
    return {"lecture": l, "transcript": t and {"text": t["text"], "language": t["language"], "segments": json.loads(t["segments"])},
            "analysis": s and json.loads(s["data"]), "notes": n[0] if n else "",
            "topics": [dict(r) for r in c.execute("SELECT topic_name,importance_score FROM topics WHERE lecture_id=?", (lid,))],
            "questions": [{**{k: r[k] for k in ("question", "answer", "question_type")}, **json.loads(r["extra"])} for r in c.execute("SELECT * FROM questions WHERE lecture_id=?", (lid,))],
            "flashcards": [dict(r) for r in c.execute("SELECT front,back FROM flashcards WHERE lecture_id=?", (lid,))]}
@app.put("/api/lectures/{lid}")
def edit(lid: int, b: Edit, uid: int = Depends(user)):
    l = own(lid, uid)
    with db() as c:
        if b.title: c.execute("UPDATE lectures SET title=? WHERE id=?", (b.title[:200], lid))
        if b.subject: c.execute("UPDATE lectures SET subject=? WHERE id=?", (b.subject[:100], lid))
        if b.transcript:
            c.execute("UPDATE transcripts SET text=? WHERE lecture_id=?", (b.transcript, lid))
    if b.transcript: analyze(lid, b.transcript, l["duration"])
    return {"ok": True}
@app.delete("/api/lectures/{lid}")
def delete(lid: int, uid: int = Depends(user)):
    l = own(lid, uid)
    with db() as c:
        for t in ("transcripts", "topics", "notes", "questions", "flashcards", "summaries"): c.execute(f"DELETE FROM {t} WHERE lecture_id=?", (lid,))
        c.execute("DELETE FROM lectures WHERE id=?", (lid,))
    try: os.remove(l["audio_path"])
    except OSError: pass
    return {"ok": True}
@app.get("/api/lectures/{lid}/search")
def search(lid: int, q: str, uid: int = Depends(user)):
    own(lid, uid); t = db().execute("SELECT segments FROM transcripts WHERE lecture_id=?", (lid,)).fetchone()
    return [{"time": s[0], "text": s[1]} for s in json.loads(t[0]) if q.lower() in s[1].lower()] if t else []

app.mount("/", StaticFiles(directory=os.path.join(BASE, "..", "frontend"), html=True))
