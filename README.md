# Connect

Ein kleines soziales Netzwerk, das ich zum Lernen gebaut habe: Account anlegen,
Beiträge schreiben, liken, kommentieren, anderen Leuten folgen.

**Demo:** https://amirmammadli13-sys.github.io/Connect/ — Zugang `demo` / `connect-demo`.
Der erste Aufruf kann eine Minute dauern: die API läuft auf einem kostenlosen
Server, der bei Inaktivität einschläft. Wie das aufgebaut ist, steht unter
[Deployen](#deployen).

## Screenshots

<!-- Nach dem ersten Lauf zwei Bilder in docs/ legen und hier einbinden:
![Feed](docs/feed.png)
![Profil](docs/profil.png)
-->

Lokal läuft alles in Docker, drei Container plus Datenbank:

- **nginx** liefert das Frontend aus und schickt `/api/` ans Backend
- **backend** – FastAPI mit SQLAlchemy, kümmert sich um Nutzer, Beiträge, Likes, Kommentare, Follows
- **ai-service** – sortiert den Feed für jeden Nutzer
- **db** – Postgres 16

## Starten

```bash
cp .env.example .env      # einmalig, Passwort in der Datei ändern
docker compose up -d --build
```

Danach läuft die Seite auf http://localhost. Die Datenbank ist beim ersten Start
leer, also erst registrieren, dann anmelden.

Die `.env` bleibt lokal (steht in `.gitignore`), im Repo liegt nur `.env.example`.
Wer die Instanz erreichbar betreibt, sollte das Passwort daraus nicht übernehmen.

## Struktur

```
html/           index.html (die ganze App) und impressum.html
backend/        main.py (API), database.py (Modelle), seed_demo.py (Demo-Inhalt)
ai/             recommendation_service.py (Feed-Sortierung)
deployment/     nginx.conf
render.yaml     Blueprint für die Demo-API bei Render
.github/        Pages-Workflow für html/
```

## Anmeldung

Beim ersten Besuch fragt die Seite, ob sie ein Cookie benutzen darf. Die Antwort
landet im Browser-Speicher, nicht auf dem Server.

**Mit Cookie** (Standard, wenn die Seite über nginx läuft): Nach dem Login setzt
das Backend `connect_session` – `HttpOnly`, `SameSite=Lax`, 30 Tage gültig. Der
Token ist für JavaScript nicht lesbar, jede Anfrage schickt ihn automatisch mit.
Weil der Browser das Cookie von allein mitschickt, verlangt das Backend bei
schreibenden Anfragen zusätzlich den Header `X-Connect: 1`. Ein fremdes Formular
kann den nicht setzen, ohne dass der Browser vorher einen Preflight macht.

**Ohne Cookie**: Der Login liefert den Token im Antwort-Body, das Frontend legt
ihn im `localStorage` ab und schickt ihn als `Authorization: Bearer <token>`.
Das ist der Weg, wenn `html/index.html` direkt als Datei geöffnet wird – dort
gibt es keine Domain, unter der ein Cookie liegen könnte.

Läuft das Frontend auf einer anderen Domain als die API (GitHub Pages),
funktioniert nur der Weg ohne Cookie: ein Cookie gilt immer für die Domain des
Backends. Die Seite merkt das und schickt den Token als Header.

In beiden Fällen gilt:

- Der Token ist ein Zufallswert, in der Tabelle `sessions` liegt nur sein
  SHA-256-Hash, dazu Ablaufdatum und Nutzer.
- Abgelaufene Sessions werden beim Login weggeräumt, `/logout` löscht die Session
  sofort und entfernt das Cookie.
- Wer angemeldet ist, entscheidet der Server. Im Request-Body steht keine User-ID.

Umstellen lässt sich das jederzeit im Impressum („Keks-Entscheidung zurücksetzen“),
danach meldet man sich einmal neu an.

## API

Alles läuft unter `/api`, beim Start ohne Docker auch direkt auf Port 8000.
„Token“ heißt: entweder Session-Cookie oder `Authorization: Bearer <token>`.

| Methode | Pfad | Anmeldung | Zweck |
| --- | --- | --- | --- |
| POST | `/register` | – | Account anlegen (Username, E-Mail, Passwort) |
| POST | `/login` | – | Anmelden; `use_cookie: false` für den Token im Body |
| POST | `/logout` | Token | Session beenden, Cookie löschen |
| GET | `/me` | Token | Wer gehört zu diesem Token |
| POST | `/posts` | Token | Beitrag schreiben |
| GET | `/feed?limit=50` | optional | Feed, für angemeldete Nutzer sortiert |
| POST | `/posts/{id}/like` | Token | Like setzen oder wieder wegnehmen |
| GET | `/posts/{id}/comments` | – | Kommentare eines Beitrags |
| POST | `/posts/{id}/comments` | Token | Kommentar schreiben |
| GET | `/users/{username}` | optional | Profil mit Beiträgen, Follower-Zahlen |
| POST | `/users/{username}/follow` | Token | Folgen bzw. entfolgen |

Mit Cookie:

```bash
curl -s -c kekse.txt -X POST localhost/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"amir","password":"geheim123"}'

curl -s -b kekse.txt -X POST localhost/api/posts \
  -H 'X-Connect: 1' -H 'Content-Type: application/json' \
  -d '{"content":"Hallo"}'
```

Ohne Cookie:

```bash
TOKEN=$(curl -s -X POST localhost/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"amir","password":"geheim123","use_cookie":false}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')

curl -s -X POST localhost/api/posts \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"content":"Hallo"}'
```

## Wie der Feed sortiert wird

Der `ai-service` bekommt die Kandidaten-Beiträge und rechnet für jeden einen Score
aus drei Teilen:

- 40 %: folgt man dem Autor?
- 35 %: wie viele Likes und Kommentare hat der Beitrag (im Vergleich zum Rest)
- 25 %: wie alt ist er (Halbwertszeit ein Tag)

Ist der Service nicht erreichbar, liefert das Backend den Feed einfach
chronologisch aus, statt einen Fehler zu werfen.

Anfangs wollte ich hier ein TensorFlow-Modell einsetzen. Das habe ich wieder
verworfen: ohne echte Interaktionsdaten hätte das Modell nur geraten, und die
Heuristik oben tut genau das, was ich wollte, ohne den Ballast.

## Einstellungen

Alles über Umgebungsvariablen, beim Docker-Start aus der `.env`:

| Variable | Standard | Zweck |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | `connect_password` | Passwort der Datenbank |
| `SESSION_DAYS` | `30` | Wie lange eine Anmeldung gilt |
| `COOKIE_SECURE` | `0` | `1` setzen, sobald die Seite über HTTPS läuft |
| `CORS_ORIGINS` | localhost + `null` | zusätzliche Origins, falls das Frontend woanders liegt |

## Lokal ohne Docker

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Ohne `DATABASE_URL` landet alles in einer SQLite-Datei `connect.db` neben dem Code.
Für den sortierten Feed muss der Ranking-Service zusätzlich laufen:

```bash
cd ai
uvicorn recommendation_service:app --port 8001
```

Danach `html/index.html` direkt im Browser öffnen – das Frontend merkt, dass es
nicht über nginx läuft, und spricht `localhost:8000` direkt an.

## Deployen

Für die Demo wird der Stack geteilt: Oberfläche auf GitHub Pages (kostenlos,
statisch), API auf Render (kostenlos, schläft bei Inaktivität ein), Datenbank bei
Neon (kostenlos, läuft nicht nach 30 Tagen ab). Der Ranking-Service bleibt weg,
deshalb ist der Feed online chronologisch sortiert.

1. **Datenbank bei Neon** anlegen (<https://neon.com>, Free Plan, kein Kartenzwang)
   und den Verbindungsstring kopieren. Er lässt sich unverändert einfügen, das
   Backend ergänzt den Treiber selbst (`postgresql://` → `postgresql+psycopg://`).
2. **API bei Render**: New → Blueprint → dieses Repo auswählen. Render liest
   `render.yaml` und fragt nach `DATABASE_URL` – dort den Neon-String einfügen.
   Die API läuft danach unter `https://connect-api.onrender.com`.
3. **Demo-Inhalt anlegen**, einmalig von lokal aus:

   ```bash
   cd backend
   pip install -r requirements.txt
   DATABASE_URL='postgresql://...' python seed_demo.py
   ```

   Das legt `demo` / `connect-demo` an, dazu zwei weitere Nutzer, Beiträge,
   Likes und Kommentare, damit der Feed nicht leer wirkt. Mehrfaches Ausführen
   ändert nichts.
4. **Frontend-Adresse eintragen**: in `html/index.html` oben `DEMO_API` auf die
   Render-Adresse setzen, ohne Schrägstrich am Ende:

   ```js
   const DEMO_API = 'https://connect-api.onrender.com';
   ```

5. **CORS prüfen**: in `render.yaml` steht die Pages-Herkunft bereits drin
   (`https://amirmammadli13-sys.github.io`). Bei anderem Nutzernamen anpassen,
   sonst blockt der Browser jede Anfrage.
6. **Pages einschalten**: Repo → Settings → Pages → Source „GitHub Actions“.
   Der Workflow `.github/workflows/pages.yml` veröffentlicht bei jedem Push auf
   `main` den Ordner `html/`. Die Seite liegt dann unter
   `https://amirmammadli13-sys.github.io/Connect/`.

Kaltstart: nach 15 Minuten ohne Zugriff schläft der kostenlose Dienst ein, die
nächste Anfrage braucht etwa eine Minute. Das ist der Preis dafür, dass die Demo
nichts kostet.

## Wenn die Anmeldung nicht klappt

Drei Ursachen decken fast alles ab, in dieser Reihenfolge prüfen:

1. **Die Seite fragt `…github.io/api/login` an.** Dann ist in der ausgelieferten
   `index.html` `DEMO_API` leer, die Anfrage geht ins Leere und der Browser
   meldet einen Netzwerkfehler. Die Adresse steht im Repo, also wurde die Seite
   nur nicht neu gebaut: Repo → Actions → „Pages“ muss nach dem Push einmal
   grün durchlaufen. Passiert das nie, fehlt der Workflow
   `.github/workflows/pages.yml`.
2. **`401 Username oder Passwort falsch`.** Dann existiert der Demo-Account in
   dieser Datenbank nicht. `python seed_demo.py` mit demselben `DATABASE_URL`
   ausführen, das auch Render benutzt — nicht mit einem anderen Neon-Branch.
3. **`CORS`-Fehler in der Browser-Konsole.** Die Herkunft der Seite fehlt in
   `CORS_ORIGINS` (`render.yaml`), der Browser blockt die Antwort dann ab.

Prüfen, ob die API selbst tut, was sie soll — ohne Browser:

```bash
curl -s https://connect-api-ywhs.onrender.com/feed | head -c 200

curl -s -X POST https://connect-api-ywhs.onrender.com/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"connect-demo","use_cookie":false}'
```

Kommt beim ersten Befehl eine Liste von Beiträgen und beim zweiten ein `token`,
liegt es nur an der Seite — nicht an Datenbank oder API.

## Was noch fehlt

- Kein Rate-Limit beim Login, keine Zwei-Faktor-Anmeldung, kein „Passwort vergessen“.
- Beiträge lassen sich nicht bearbeiten oder löschen.
- Kein Bild-Upload, keine Benachrichtigungen, keine Suche.
- Keine automatischen Tests, ich habe alles von Hand durchgeklickt.
- Online fehlt der Ranking-Service (siehe [Deployen](#deployen)), der Feed ist
dort chronologisch.
- Wer kein Cookie will, dessen Token liegt im `localStorage` und ist damit für
  JavaScript lesbar. Das ist der Preis dafür, dass der Datei-Modus funktioniert.

## Datenschutz

Passwörter liegen gehasht in der Datenbank (bcrypt), Session-Tokens nur als Hash.
Kein Tracking, keine Werbung, keine Weitergabe an Dritte. Trotzdem: das ist ein
Lernprojekt, keine Plattform für echte persönliche Daten.
