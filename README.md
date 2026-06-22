# linkedin-automation-backend

Give it a LinkedIn profile URL, get back a clean JSON file with that person's info: name, headline, location, about, experience, education, skills, and profile photo.

It drives a real Chrome browser under the hood, because LinkedIn has killed off every easier way of doing this. The next section explains why, since it shapes how you use the tool.

## Why it works this way

A few facts worth knowing up front, they explain the parts that look odd:

- LinkedIn's old API is gone. The popular `linkedin-api` Python library no longer works, every endpoint it relies on returns a 410 now.
- They run PerimeterX bot detection. Plain HTTP requests get blocked after a call or two even when you pass valid cookies. Libraries that fake a browser's network fingerprint run into a JavaScript challenge they can't pass.
- So the only thing that holds up is an actual logged-in browser. This project uses Playwright to open Chromium, visit the profile page the way a person would, scroll to load everything, and read the data off the rendered page.

One consequence: the browser window has to be visible. Running it headless gets detected and you get the "Join LinkedIn" wall instead of real data.

## What you need

- Python 3.11 (3.12 is fine too). Avoid 3.14, one of the dependencies won't build on it.
- A display. The browser opens a real window, so a normal desktop works out of the box. Over SSH you'd need X forwarding or something like xvfb.
- A LinkedIn account. Either one you're already signed into in Firefox, or one you log into when the tool asks.

## Setup

```bash
git clone https://github.com/Wahid7852/linkedin-automation-backend.git
cd linkedin-automation-backend

python3.11 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

If you want to change the port or file paths, copy the example env file (optional, defaults are fine):

```bash
cp .env.example .env
```

## Log in once

The tool keeps a logged-in session on disk and reuses it. You set that up once, two ways to choose from.

Reuse your Firefox login. If you're already signed into LinkedIn in Firefox, this lifts that session, no typing:

```bash
python -m linkedin_backend.cli import-firefox
```

Or log in yourself. This opens a browser window, you sign in (2FA and all), and it saves the session:

```bash
python -m linkedin_backend.cli login
```

Either way the session lands in `.pw-profile/`. It lasts a few days. When it expires you just run one of these again.

## Fetch a profile from the command line

```bash
python -m linkedin_backend.cli fetch https://www.linkedin.com/in/wahidkhan7852/
```

That writes `wahidkhan7852.json` in the current folder.

Choose your own filename:

```bash
python -m linkedin_backend.cli fetch https://www.linkedin.com/in/wahidkhan7852/ -o wahid.json
```

Include the raw captured data as well (much bigger, handy for debugging):

```bash
python -m linkedin_backend.cli fetch https://www.linkedin.com/in/wahidkhan7852/ --raw
```

## Run it as a server and use curl

Start the server:

```bash
python run_server.py
```

It listens on port 8000 by default.

Health check:

```bash
curl http://localhost:8000/health
```

Fetch a profile:

```bash
curl -X POST http://localhost:8000/profile \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.linkedin.com/in/wahidkhan7852/"}'
```

Save the response straight to a file:

```bash
curl -s -X POST http://localhost:8000/profile \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.linkedin.com/in/wahidkhan7852/"}' \
  -o wahid.json
```

Pretty-print it with jq:

```bash
curl -s -X POST http://localhost:8000/profile \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.linkedin.com/in/wahidkhan7852/"}' | jq
```

Worth knowing: every request opens the browser and takes roughly 20 to 40 seconds, and requests run one at a time. This is meant for low volume, single person use, not as a public API.

## What you get back

```json
{
  "url": "https://www.linkedin.com/in/wahidkhan7852/",
  "username": "wahidkhan7852",
  "name": "Abdul Wahid Khan",
  "headline": "Breaking Things to Build Them Safer | DevSecOps and Red Team ...",
  "location": "Kalyan, Maharashtra, India",
  "summary": "Full text of the About section ...",
  "current_company": "Lixta Network",
  "current_title": "DevOps Team Lead",
  "education": [
    { "school": "National Forensic Sciences University (NFSU)", "degree": "Master of Science - MS, Cybersecurity", "duration": "Aug 2025 - Present" }
  ],
  "skills": ["Python (Programming Language)", "Linux System Administration"],
  "experience": [
    { "title": "DevOps Team Lead", "company": "Lixta Network", "duration": "Jan 2025 - Present", "location": "Mumbai, Maharashtra, India" }
  ],
  "profile_pic_url": "https://media.licdn.com/...",
  "sections_text": { "about": "...", "experience": "...", "education": "..." },
  "fetched_at": "2026-06-22T08:55:40Z"
}
```

The `sections_text` field keeps the raw text of each section exactly as it showed up on the page. It is there as a fallback if the structured parsing ever misses a field, and it makes a good input if you later want to generate a written summary.

## Endpoints

- `GET /health` returns the status and whether a logged-in session exists.
- `POST /profile` takes `{"url": "..."}` and returns the JSON shown above. You can also pass `"raw": true` to include the raw capture.

## Checking it yourself

A quick way to confirm everything works, from a fresh clone:

```bash
# 1. session check, should say a session exists after you logged in
python -c "from linkedin_backend import auth; print('session:', auth.profile_exists())"

# 2. fetch your own profile and look at it
python -m linkedin_backend.cli fetch https://www.linkedin.com/in/wahidkhan7852/
cat wahidkhan7852.json | jq '{name, headline, location, current_title, education, skills}'

# 3. same thing through the server
python run_server.py &
sleep 5
curl -s http://localhost:8000/health
curl -s -X POST http://localhost:8000/profile \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.linkedin.com/in/wahidkhan7852/"}' | jq '.name, .current_title'
```

## When something breaks

- You get "Join LinkedIn" or empty data: your session expired, run `import-firefox` or `login` again.
- The browser won't open, or you see a display error: you need a visible screen, this does not run headless.
- The server returns 401: same cause, no valid session, log in again.
- A single section comes back empty: LinkedIn may have shuffled its layout. The raw text for that section is still in `sections_text`.

## Fair warning

This automates a logged-in browser to read LinkedIn pages, which goes against their terms of service. Your account can get limited or banned. Use a spare account if you have one, do not hammer it, and keep the volume low. The fetcher already scrolls slowly and adds random delays so it looks less robotic, but that is not a guarantee.

## Notes

- X and Twitter support is stubbed out but not built yet. Only LinkedIn works right now.
- `.pw-profile/`, `cookies.json` and `.env` are gitignored on purpose. They hold your session, keep them out of version control.
