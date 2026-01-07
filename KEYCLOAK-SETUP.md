# Keycloak Setup Guide

> **📚 This guide has been consolidated into the main README**

For complete Keycloak setup instructions, see [README.md](README.md#4-configure-keycloak) - Section "4. Configure Keycloak"

---

## Quick Reference

### Access Keycloak Admin Console
- URL: http://localhost:8080/admin
- Username: `admin`
- Password: `admin123` (from your `.env` file)

### Setup Checklist
- [ ] Create `streamlink` realm
- [ ] Create `streamlink-api` client (with client authentication ON)
- [ ] Set redirect URI: `http://localhost:3001/auth/callback`
- [ ] Copy client secret to `.env` as `KEYCLOAK_CLIENT_SECRET`
- [ ] Create test user (username: `testuser`, password: `password123`)
- [ ] Ensure password is NOT temporary

### Troubleshooting
- **Can't access admin console?** Check `docker-compose ps` - Keycloak should be "healthy"
- **Invalid client credentials?** Verify `KEYCLOAK_CLIENT_SECRET` in `.env` matches Keycloak
- **Stuck as admin?** Clear browser cookies/localStorage (F12 → Application → Storage)
- **Wrong realm?** Check top-left shows "streamlink" not "Master"

---

For detailed step-by-step instructions, see the [Development Guide in README.md](README.md#development-guide)
