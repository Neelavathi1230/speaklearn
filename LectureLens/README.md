# LectureLens – Lecture Speech Analysis & Study Assistant
Text and Speech Analysis project: lecture audio → transcript → summary, key points, notes, Q&A, flashcards, analytics.

## Run
```bash
pip install -r requirements.txt
cd backend && uvicorn main:app --reload
# open http://127.0.0.1:8000  (API docs: /docs)
```
Frontend is served by FastAPI from `frontend/`. SQLite DB is created at `database/lecturelens.db`.

## Real vs demo processing
- **Real speech-to-text**: `pip install faster-whisper` (Whisper "base" model, runs locally; ffmpeg needed for some formats).
- **Demo fallback**: without faster-whisper, a built-in sample transcript is used. The UI labels such lectures **demo**.
- **NLP is always real and local** (`backend/nlp.py`): frequency/bigram keywords, sentence-scored summaries, regex definition detection, cloze MCQs, flashcards, notes. Edit a transcript and it is re-analyzed.

## Structure
`backend/main.py` (auth, lectures, search, pipeline) · `backend/nlp.py` (replaceable NLP functions) · `frontend/index.html` (SPA: dashboard, upload, record, history, lecture tabs).

## API
`POST /api/auth/{register,login,logout}` · `POST /api/lectures/upload` · `GET /api/lectures` · `GET|PUT|DELETE /api/lectures/{id}` · `GET /api/lectures/{id}/search?q=`
Passwords are PBKDF2-hashed; every lecture query is scoped to the logged-in user; file type/size are validated.

## Not yet included
Per-route files from the spec, PDF/DOCX export (TXT only), separate pages/URLs, profile/settings, charts library, spaCy/transformer models, password reset. Good next steps.
