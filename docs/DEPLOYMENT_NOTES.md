# Production Deployment Notes & Pre-Release Checklist

This document details production settings, static asset configuration, role provisioning, and release procedures for the Vessel Intelligence web application.

---

## 1. Production Environment Variables

Configure the following environment variables in your production environment (e.g. systemd service, container environment, or secrets vault). **Never commit secret values to version control.**

| Variable Name | Production Recommendation | Purpose |
| :--- | :--- | :--- |
| `DEBUG` | `False` | Disables debug mode and diagnostic traces. |
| `SECRET_KEY` | Long random secret string | Cryptographic signing key for sessions and CSRF tokens. |
| `ALLOWED_HOSTS` | Comma-delimited domain names | Allowed host headers (e.g. `intel.splendour.com,10.0.0.5`). |
| `STATIC_HASHING` | `1` or `True` | Activates `AggregatedManifestStaticFilesStorage` for hashed JS/CSS assets. |
| `SESSION_COOKIE_SECURE` | `True` | Ensures session cookies are transmitted only over HTTPS connections. |
| `CSRF_COOKIE_SECURE` | `True` | Ensures CSRF cookies are transmitted only over HTTPS connections. |
| `SECURE_SSL_REDIRECT` | `True` | Automatically redirects all plain HTTP requests to HTTPS. |
| `SECURE_HSTS_SECONDS` | `31536000` (1 year) | Enforces HTTP Strict Transport Security (HSTS) in client browsers. |
| `WEB_CSP_MODE` | `enforce` | Activates strict Content Security Policy headers (or `report-only` during rollout). |

---

## 2. Serving Static Files in Production

In production, JavaScript modules import each other via relative specifiers. To guarantee browsers never run outdated cached files alongside new code, hashed static assets must be collected prior to process startup.

### Deploy Commands
Run these commands during every deployment:
```bash
# 1. Enable manifest hashing
export STATIC_HASHING=1

# 2. Collect and aggregate module dependencies into STATIC_ROOT
python manage.py collectstatic --noinput

# 3. Restart the WSGI/ASGI application server (e.g. gunicorn / uvicorn)
systemctl restart vessel-intel
```

### Static Asset Delivery Options
The application does not bundle third-party Python static file servers like WhiteNoise by default. Choose one of the following production serving architectures:
1. **Web Server Alias (Recommended)**: Configure your edge reverse proxy (Nginx, Caddy, or Apache) with an alias directive pointing `/static/` directly to the filesystem path defined by `STATIC_ROOT`. Configure aggressive caching headers (`Cache-Control: public, max-age=31536000, immutable`) because all filenames include unique content hashes.
2. **WhiteNoise (Optional Future Dependency)**: If deploying to a containerized platform without direct filesystem reverse proxying, WhiteNoise can be installed as a Python dependency and added to `MIDDLEWARE` immediately following `SecurityMiddleware`.

---

## 3. Provisioning Roles & Initial Users

The application enforces role-based access control (Admin and BD Manager).

1. **Create the Role Groups**:
   ```bash
   python manage.py setup_roles
   ```
   This idempotent command creates the `Admin` and `BD Manager` groups if they do not already exist.

2. **Assign a User to a Role**:
   Users can be assigned to roles via the Django Admin interface (`/admin/auth/user/`) or using the Django management shell:
   ```bash
   python manage.py shell -c "
   from django.contrib.auth import get_user_model
   from django.contrib.auth.models import Group
   User = get_user_model()
   u = User.objects.get(username='john_bd')
   g = Group.objects.get(name='BD Manager')
   u.groups.add(g)
   "
   ```

---

## 4. Pre-Release Checklist

Execute these verification steps before cutting any release to staging or production:

1. **Deployment Security Audit**:
   ```bash
   python manage.py check --deploy
   ```
   Verify that all security warnings (HSTS, SSL redirect, secure cookies, DEBUG) are resolved under production environment variables.

2. **Verify Database Migrations**:
   ```bash
   python manage.py makemigrations --check --dry-run
   ```
   Must output `No changes detected`. If changes exist, apply them with `python manage.py migrate`.

3. **Run Test Suites**:
   ```bash
   # Node.js pure unit tests
   node --test apps/web/static/web/js/tests/*.test.mjs

   # Full Django regression and integration suite
   python manage.py test
   ```

4. **Database Backup**:
   Take a snapshot or `pg_dump` of the PostgreSQL production database prior to migrating or updating code.

