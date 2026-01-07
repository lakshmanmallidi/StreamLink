# Configuration Quick Reference

## Where Things Live

### 🔐 Secrets → `.env`
```bash
POSTGRES_PASSWORD=...
KC_DB_PASSWORD=...
KEYCLOAK_ADMIN_PASSWORD=...
KEYCLOAK_CLIENT_SECRET=...
ENCRYPTION_KEY=...
```

### 🐳 Docker Config → `docker-compose.yml`
- Service definitions (postgres, keycloak)
- Image versions (postgres:15-alpine, keycloak:23.0)
- Port mappings (5432, 8080)
- Volume mounts
- Database names (streamlink, keycloak)
- Usernames (streamlink, keycloak, admin)

### ⚙️ Backend Config → `backend/src/config.py`
- Application settings (name, version, debug)
- Database connection (host, port, database, user)
- Keycloak URLs (url, realm, client_id, redirect_uri)
- JWT settings (algorithm, token expiry)
- CORS origins
- Feature flags

---

## Quick Commands

### First Time Setup
```bash
# 1. Copy template
cp .env.example .env

# 2. Generate encryption key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 3. Edit .env with your secrets
nano .env

# 4. Start infrastructure
docker-compose up -d

# 5. Run backend
cd backend && bash dev.sh
```

### Change Configuration
```bash
# Change backend config (URLs, ports, settings)
nano backend/src/config.py
cd backend && bash dev.sh  # Restart backend

# Change Docker config (images, ports, volumes)
nano docker-compose.yml
docker-compose restart

# Change secrets
nano .env
docker-compose restart  # For Docker services
cd backend && bash dev.sh  # For backend
```

### Verify Setup
```bash
# Check .env is clean (only secrets)
grep -E "^[A-Z_]+=" .env | grep -v "PASSWORD\|SECRET\|KEY"
# Should output nothing

# Check Docker services
docker-compose ps
# Should show postgres and keycloak healthy

# Test database connection
psql -h localhost -U streamlink -d streamlink
# Use password from .env

# Check backend config
cd backend && python3 -c "from src.config import settings; print(settings.DATABASE_URL)"
# Should show URL with password from .env
```

---

## What Goes Where?

### It's a SECRET if... → `.env`
- ✅ Password, API key, token
- ✅ Encryption key, signing key
- ✅ OAuth client secret
- ✅ Anything that authenticates or encrypts

### It's DOCKER CONFIG if... → `docker-compose.yml`
- ✅ Service name, image version
- ✅ Port mapping, volume mount
- ✅ Database name, username (non-sensitive)
- ✅ Infrastructure topology

### It's BACKEND CONFIG if... → `config.py`
- ✅ Application URL, port, mode
- ✅ Feature flag, timeout, limit
- ✅ CORS origin, allowed host
- ✅ Non-sensitive application settings

---

## Priority Order

When the same variable is defined multiple times:

1. **Shell environment** (highest)
2. **`.env` file**
3. **`config.py` defaults** (lowest)

Example:
```bash
# Shell wins
export KEYCLOAK_URL=http://prod:8080
python -m uvicorn src.main:create_app

# .env wins over config.py
echo "KEYCLOAK_URL=http://staging:8080" >> .env

# config.py default (if not in shell or .env)
KEYCLOAK_URL: str = "http://localhost:8080"
```

---

## Common Tasks

### Add New Secret
1. Add to `.env`: `NEW_SECRET=value`
2. Add to `.env.example`: `NEW_SECRET=placeholder`
3. Add to `config.py`: `NEW_SECRET: str = ""`
4. Document in `CONFIGURATION.md`

### Add New Config
1. Add to `config.py` with sensible default
2. Document what it does
3. No need to touch `.env`

### Change Environment
```bash
# Development (use defaults)
cp .env.dev .env
docker-compose up -d
cd backend && bash dev.sh

# Staging (override some configs)
export KEYCLOAK_URL=https://staging-keycloak.example.com
export DEBUG=False

# Production (all from environment/secrets manager)
export POSTGRES_PASSWORD=$(vault read -field=password secret/postgres)
export KEYCLOAK_CLIENT_SECRET=$(vault read -field=secret secret/keycloak)
```

---

## Troubleshooting

### "Missing ENCRYPTION_KEY"
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Add output to .env
```

### "Database connection failed"
```bash
# Check password in .env matches docker-compose
cat .env | grep POSTGRES_PASSWORD
docker-compose exec postgres env | grep POSTGRES_PASSWORD

# Test connection
psql -h localhost -U streamlink -d streamlink
```

### "Config not updating"
```bash
# Backend config changes
cd backend && bash dev.sh  # Must restart

# Docker config changes
docker-compose restart

# .env changes
# Restart both Docker AND backend
```

---

## Security Checklist

Before committing:
- [ ] `.env` contains only secrets
- [ ] No passwords in `config.py`
- [ ] No secrets in `docker-compose.yml`
- [ ] `.env.example` has placeholders only
- [ ] `.env` is in `.gitignore`

---

## Files Summary

| File | Purpose | Committed to Git? |
|------|---------|-------------------|
| `.env` | Secrets only | ❌ No (gitignored) |
| `.env.example` | Template with placeholders | ✅ Yes |
| `config.py` | Backend configuration | ✅ Yes |
| `docker-compose.yml` | Infrastructure config | ✅ Yes |
| `CONFIGURATION.md` | Full documentation | ✅ Yes |

---

## Need Help?

See [CONFIGURATION.md](../CONFIGURATION.md) for detailed documentation.
