# Stacks

A small, private, self-hosted catalog for the **physical books you own**. Add a
book by ISBN, see it filled in from Open Library (with Google Books as a
fallback), note where it lives on your shelves, and search and sort the whole
collection from your phone or laptop.

It is deliberately not a reading tracker or a social network. It answers
questions like *"do I already own this?"* and *"which shelf is it on?"*

## Features

- Add by ISBN (ISBN-10 or ISBN-13, hyphens fine) or manually for books without one
- Metadata and cover lookup from Open Library, falling back to Google Books;
  covers are downloaded and stored locally, never hot-linked
- A **sticky shelf location**, so you can work through one shelf at a time
- Duplicate detection: adding a book you own asks before creating a second copy
- Edition/copy split: one record per edition, one row per physical copy
- Search (accent- and case-insensitive, including Cyrillic) plus sorting by title,
  author (by surname), year, date added, location, publisher, pages, format,
  condition, price and date acquired
- Filters for location, format, condition and tags; list or cover-grid view
- Review queue for books whose details couldn't be found automatically
- CSV export (respects your current filters)
- Private by default: every page requires login, there is no signup, and covers
  are served through the login too
- Works with a USB/Bluetooth barcode scanner (it just types the ISBN and presses Enter)

## Quick start

```sh
git clone <this repo> stacks && cd stacks
cp .env.example .env        # set STACKS_ADMIN_USER and STACKS_ADMIN_PASSWORD
docker compose up -d --build
```

Open <http://localhost:8000> and sign in with the credentials from `.env`.
The admin account is created on first start only, when no users exist yet.
Alternatively, leave those two variables unset and run:

```sh
docker compose exec stacks python manage.py createsuperuser
```

All state (the SQLite database, covers, and a generated secret key) lives in the
`/data` volume. The container runs as an unprivileged user (UID 10001); if you
swap the named volume for a bind mount, make that directory writable by it
(`chown 10001 ./data`).

## Behind a reverse proxy (HTTPS)

Secure cookies (and, later, camera access) need HTTPS, so in practice you'll put
Stacks behind a proxy. See `docker-compose.proxy.example.yml`. With Caddy:

```
books.example.com {
    reverse_proxy stacks:8000
}
```

and in `.env`:

```
STACKS_ALLOWED_HOSTS=books.example.com
STACKS_CSRF_TRUSTED_ORIGINS=https://books.example.com
STACKS_HTTPS=true
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `STACKS_ADMIN_USER`, `STACKS_ADMIN_PASSWORD` | unset | Create the first user on first start (password ≥ 8 chars) |
| `STACKS_ALLOWED_HOSTS` | `localhost` | Comma-separated hostnames |
| `STACKS_CSRF_TRUSTED_ORIGINS` | unset | Needed for HTTPS behind a proxy |
| `STACKS_HTTPS` | `false` | Secure cookies and HSTS when a proxy terminates TLS |
| `STACKS_SECRET_KEY` | generated | Fixed key; otherwise one is generated and kept in `/data` |
| `STACKS_TIME_ZONE` | `UTC` | IANA zone, e.g. `America/New_York` |
| `STACKS_CONTACT` | unset | Email or URL sent in the User-Agent to Open Library |
| `STACKS_PORT` | `8000` | Host port in the bundled compose file |
| `STACKS_DEBUG` | `false` | Django debug mode; never enable on a public host |

## Backups

Everything is in the `/data` volume. For a consistent copy of the database while
the app is running, use SQLite's backup API, then copy the covers:

```sh
docker compose exec stacks python -c "import sqlite3; s=sqlite3.connect('/data/db.sqlite3'); d=sqlite3.connect('/data/backup.sqlite3'); s.backup(d)"
docker compose cp stacks:/data/backup.sqlite3 ./stacks-backup.sqlite3
docker compose cp stacks:/data/covers ./stacks-covers
```

Store the copies somewhere other than the machine running Stacks. Covers can
always be re-downloaded, so the database is the part that matters. The CSV export
is a second, portable backup.

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export STACKS_DEBUG=true
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
python manage.py test
```

## Known limitations

- **Single library.** Every account sees the same collection; there are no per-user libraries.
- Search is substring matching, which is plenty for personal-sized libraries
  (thousands of books) but isn't ranked full-text search.
- No camera scanning, bulk CSV import, or wishlist/lending tracking yet.
- Metadata quality is whatever Open Library and Google Books return. Pre-1970 books
  and small presses often have gaps, which is what the review queue and manual
  editing are for.

## License

MIT, see `LICENSE`.
