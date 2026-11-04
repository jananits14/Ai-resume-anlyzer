# AI Resume Analyzer / Career Hub

This project is a beginner-friendly Streamlit app for resume analysis, skill-based learning, interview practice, and job search.

## Quick start on Windows (VS Code)

1. Open the project folder in VS Code.
2. Open a terminal in the project root.
3. Run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

4. Create a local `.env` file from the example:

```powershell
Copy-Item .env.example .env
```

5. Edit `.env` and add your real keys:

```env
GEMINI_API_KEY=your_gemini_key_here
RAPIDAPI_KEY=your_rapidapi_key_here
GEMINI_MODEL=gemini-2.5-flash
```

6. Start the app:

```powershell
streamlit run app.py
```

## Required API setup

### Gemini
- Create a key from Google AI Studio / Gemini Developer API.
- Store it in `GEMINI_API_KEY`.
- If the key is missing, the app shows a helpful configuration message instead of pretending to use live AI.

### RapidAPI / JSearch
- Create a JSearch key at: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
- Store it in `RAPIDAPI_KEY`.
- This app uses the official JSearch endpoint and validates errors such as invalid keys, quota exhaustion, and empty results.

## Shared video storage

- Uploaded learning videos are stored in a local persistent folder inside the project: `shared_media/videos`.
- A video saved by one user remains visible to other signed-in users on the same app when its visibility is set to `shared` or `public`.
- For cross-device or cross-computer sharing, a persistent shared disk or external object storage is required.
- The app does not download YouTube videos automatically. Users should upload only content they own or are authorized to share.

## Security and privacy notes

- Never commit real API keys to Git.
- The `.env` file is excluded by `.gitignore`.
- Passwords are hashed with PBKDF2 before being stored in SQLite.
- Local data is stored in `career_platform.db` and local video storage in the project folder.

## Troubleshooting

- If the app says a key is missing, create the `.env` file and set the correct value.
- If the job search page returns an API error, check your RapidAPI key, quota, and JSearch access.
- If the AI page shows a message instead of a live answer, the key is not configured or the service is unavailable.
