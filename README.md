**English** · [Deutsch](README.de.md)

# Connect

A small social network I built to learn: create an account, write posts, like and
comment, follow other people.

**Demo:** https://amirmammadli13-sys.github.io/Connect/ — sign in with `demo` / `connect-demo`.
The first request can take a minute: the API runs on a free server that falls
asleep when idle. How it is put together is described under
[Deploying](#deploying).

## Screenshots

<!-- After the first run, put two images into docs/ and include them here:
![Feed](docs/feed.png)
![Profile](docs/profile.png)
-->

Locally everything runs in Docker: three containers plus a database.

- **nginx** serves the frontend and forwards `/api/` to the backend
- **backend** – FastAPI with SQLAlchemy, handles users, posts, likes, comments, follows
- **ai-service** – sorts the feed for each user
- **db** – Postgres 16

## Running it

```bash
cp .env.example .env      # once, change the password in the file
docker compose up -d --build
```

The site then runs on http://localhost. The database is empty on the first start,
so register first, then sign in.

The `.env` stays local (it is in `.gitignore`); only `.env.example` is in the repo.
Anyone running an instance that is reachable from the internet should not reuse
that password.

## Layout

```
html/           index.html (the whole app) and impressum.html
backend/        main.py (API), database.py (models), seed_demo.py (demo content)
ai/             recommendation_service.py (feed ranking)
deployment/     nginx.conf
render.yaml     blueprint for the demo API on Render
.github/        Pages workflow for html/
```

## Signing in

On the first visit the page asks whether it may use a cookie. The answer is kept
in browser storage, not on the server.

**With a cookie** (the default when the site runs behind nginx): after login the
backend sets `connect_session` – `HttpOnly`, `SameSite=Lax`, valid for 30 days.
JavaScript cannot read the token, and every request carries it automatically.
Because the browser sends the cookie on its own, the backend also demands the
header `X-Connect: 1` on writing requests. A third-party form cannot set that
without the browser performing a preflight first.

**Without a cookie**: the login returns the token in the response body, the
frontend stores it in `localStorage` and sends it as
`Authorization: Bearer <token>`. That is the way when `html/index.html` is opened
directly as a file – there is no domain there that a cookie could belong to.

If the frontend runs on a different domain than the API (GitHub Pages), only the
cookie-less way works: a cookie always belongs to the backend's domain. The page
notices that and sends the token as a header.

In both cases:

- The token is a random value; the `sessions` table only holds its SHA-256 hash,
  plus an expiry date and the user.
- Expired sessions are cleaned up on login; `/logout` deletes the session
  immediately and removes the cookie.
- The server decides who is signed in. No user ID is taken from the request body.

You can switch at any time in the imprint page ("Keks-Entscheidung
zurücksetzen"); afterwards you sign in once more.

## API

Everything lives under `/api`; without Docker it also runs directly on port 8000.
"Token" means either the session cookie or `Authorization: Bearer <token>`.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/register` | – | Create an account (username, e-mail, password) |
| POST | `/login` | – | Sign in; `use_cookie: false` returns the token in the body |
| POST | `/logout` | Token | End the session, delete the cookie |
| GET | `/me` | Token | Which user belongs to this token |
| POST | `/posts` | Token | Write a post |
| GET | `/feed?limit=50` | optional | Feed, ranked for signed-in users |
| POST | `/posts/{id}/like` | Token | Add or remove a like |
| GET | `/posts/{id}/comments` | – | Comments of a post |
| POST | `/posts/{id}/comments` | Token | Write a comment |
| GET | `/users/{username}` | optional | Profile with posts and follower counts |
| POST | `/users/{username}/follow` | Token | Follow or unfollow |

With a cookie:

```bash
curl -s -c cookies.txt -X POST localhost/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"amir","password":"geheim123"}'

curl -s -b cookies.txt -X POST localhost/api/posts \
  -H 'X-Connect: 1' -H 'Content-Type: application/json' \
  -d '{"content":"Hello"}'
```

Without a cookie:

```bash
TOKEN=$(curl -s -X POST localhost/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"amir","password":"geheim123","use_cookie":false}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')

curl -s -X POST localhost/api/posts \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"content":"Hello"}'
```

## How the feed is ranked

The `ai-service` receives the candidate posts and computes a score for each of
them out of three parts:

- 40 %: do you follow the author?
- 35 %: how many likes and comments does the post have (compared to the rest)
- 25 %: how old is it (half-life of one day)

If the service is unreachable, the backend simply returns the feed in
chronological order instead of raising an error.

At first I wanted to train a TensorFlow model here. I dropped that idea: without
real interaction data the model would only be guessing, while the heuristic above
does exactly what I wanted without the baggage.

## Settings

Everything goes through environment variables, read from `.env` when Docker
starts:

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | `connect_password` | Database password |
| `SESSION_DAYS` | `30` | How long a login stays valid |
| `COOKIE_SECURE` | `0` | Set to `1` once the site runs over HTTPS |
| `CORS_ORIGINS` | localhost + `null` | Extra origins if the frontend lives elsewhere |

## Running without Docker

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Without `DATABASE_URL` everything lands in an SQLite file `connect.db` next to the
code. For the ranked feed the ranking service has to run as well:

```bash
cd ai
uvicorn recommendation_service:app --port 8001
```

After that, open `html/index.html` directly in the browser – the frontend notices
that it is not served by nginx and talks to `localhost:8000` directly.

## Deploying

For the demo the stack is split: frontend on GitHub Pages (free, static), API on
Render (free, sleeps when idle), database on Neon (free, does not expire after 30
days). The ranking service is left out, which is why the online feed is in
chronological order.

1. **Create the database on Neon** (<https://neon.com>, free plan, no credit card)
   and copy the connection string. It can be pasted unchanged; the backend adds
   the driver itself (`postgresql://` → `postgresql+psycopg://`).
2. **API on Render**: New → Blueprint → pick this repository. Render reads
   `render.yaml` and asks for `DATABASE_URL` – paste the Neon string there.
   The API then runs at `https://connect-api-ywhs.onrender.com`.
3. **Create the demo content**, once, from your machine:

   ```bash
   cd backend
   pip install -r requirements.txt
   DATABASE_URL='postgresql://...' python seed_demo.py
   ```

   This creates `demo` / `connect-demo` plus two more users, posts, likes and
   comments, so the feed is not empty. Running it again changes nothing.
4. **Point the frontend at the API**: in `html/index.html`, at the top, set
   `DEMO_API` to the Render address without a trailing slash:

   ```js
   const DEMO_API = 'https://connect-api-ywhs.onrender.com';
   ```

5. **Check CORS**: `render.yaml` already contains the Pages origin
   (`https://amirmammadli13-sys.github.io`). Adjust it for a different username,
   otherwise the browser blocks every request.
6. **Enable Pages**: repo → Settings → Pages → Source "GitHub Actions".
   The workflow `.github/workflows/pages.yml` publishes the `html/` folder on every
   push to `main`. The site then lives at
   `https://amirmammadli13-sys.github.io/Connect/`.

Cold start: after 15 minutes without traffic the free service falls asleep; the
next request takes about a minute. That is the price of a demo that costs nothing.

## If signing in does not work

Three causes cover almost everything; check them in this order:

1. **The page requests `…github.io/api/login`.** Then `DEMO_API` is empty in the
   deployed `index.html`, the request goes nowhere and the browser reports a
   network error. The address is in the repository, so the page was simply not
   rebuilt: repo → Actions → "Pages" has to run green once after the push. If that
   never happens, the workflow `.github/workflows/pages.yml` is missing.
2. **`401 Username oder Passwort falsch`.** The demo account does not exist in
   this database. Run `python seed_demo.py` with the same `DATABASE_URL` that
   Render uses – not against a different Neon branch.
3. **`CORS` error in the browser console.** The page's origin is missing in
   `CORS_ORIGINS` (`render.yaml`), so the browser discards the response.

To check whether the API itself does what it should, without a browser:

```bash
curl -s https://connect-api-ywhs.onrender.com/feed | head -c 200

curl -s -X POST https://connect-api-ywhs.onrender.com/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"connect-demo","use_cookie":false}'
```

If the first command returns a list of posts and the second one a `token`, the
problem is only in the page – not in the database or the API.

## What is still missing

- No rate limit on login, no two-factor authentication, no "forgot password".
- Posts cannot be edited or deleted.
- No image upload, no notifications, no search.
- No automated tests; I clicked through everything by hand.
- The ranking service is missing online (see [Deploying](#deploying)), so the feed
  there is chronological.
- If you decline the cookie, your token sits in `localStorage` and is therefore
  readable by JavaScript. That is the price for the file mode to work.

## Privacy

Passwords are stored hashed (bcrypt), session tokens only as hashes. No tracking,
no ads, no sharing with third parties. Still: this is a learning project, not a
platform for real personal data.

## Languages

The interface speaks German, English and Spanish; pick the language in the top
right corner. The choice is stored in the browser and survives a reload.
