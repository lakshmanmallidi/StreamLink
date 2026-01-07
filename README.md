# StreamLink

> **⚠️ IN PROGRESS**: This project is under active development. Features and documentation may change frequently.

A unified open-source tool for end-to-end event orchestration and Kubernetes service management. StreamLink provides a single control plane for managing Kafka, Schema Registry, and other event streaming infrastructure with integrated authentication, encryption, and monitoring.

## Features

- 🔐 **OAuth2 Authentication** - Keycloak integration with PKCE flow
- ☸️ **Kubernetes Management** - Single-cluster connection with encrypted kubeconfig storage
- 🚀 **Service Deployment** - One-click deployment of Kafka and Schema Registry to Kubernetes
- 📊 **Health Monitoring** - Real-time service status and pod health tracking
- 🔒 **Security First** - Fernet encryption for sensitive data, secrets isolated from configuration
- 💻 **Modern UI** - React-based dashboard with collapsible sidebar and auto-refresh

## Tech Stack

**Backend**:
- FastAPI 0.104.0 (Python async web framework)
- SQLAlchemy 2.0 + asyncpg (PostgreSQL ORM)
- Kubernetes Python client 28.1.0
- Cryptography 41.0.7 (Fernet encryption)

**Frontend**:
- React 18.2.0 + React Router 6.20.0
- Parcel 2.10.3 (bundler)

**Infrastructure**:
- PostgreSQL 15 (application database)
- Keycloak 23 (identity provider)
- Docker Compose (local development)

---

# Development Guide

## Prerequisites

- **Docker & Docker Compose** - For PostgreSQL and Keycloak
- **Python 3.11+** - Backend runtime
- **Node.js 18+** - Frontend runtime
- **kubectl** - (Optional) For Kubernetes cluster management

## Quick Start

### 1. Clone Repository

```bash
git clone <repository-url>
cd StreamLink
```

### 2. Setup Environment Variables

Copy the template and configure your secrets:

```bash
cp .env.example .env
```

Edit `.env` and set the following secrets:

```bash
# PostgreSQL Passwords
POSTGRES_PASSWORD=streamlink123
KC_DB_PASSWORD=keycloak123

# Keycloak Admin Password
KEYCLOAK_ADMIN_PASSWORD=admin123

# OAuth2 Client Secret (will get from Keycloak setup below)
KEYCLOAK_CLIENT_SECRET=<placeholder-for-now>

# Generate Encryption Key
# Run: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=<generated-key-here>
```

**Generate Encryption Key**:
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output and paste it as `ENCRYPTION_KEY` in `.env`.

### 3. Start Infrastructure (PostgreSQL + Keycloak)

```bash
docker-compose up -d
```

This will start:
- **PostgreSQL** on port `5432` (database for StreamLink and Keycloak)
- **Keycloak** on port `8080` (identity provider)

Wait for services to be healthy:
```bash
docker-compose ps
# Both should show "healthy" status
```

Check logs if needed:
```bash
docker-compose logs -f postgres
docker-compose logs -f keycloak
```

### 4. Configure Keycloak

Keycloak needs one-time setup to create the realm, client, and test user.

#### 4.1 Access Keycloak Admin Console

Open http://localhost:8080/admin in your browser.

**Login**:
- Username: `admin`
- Password: `admin123` (from your `.env` file)

#### 4.2 Create StreamLink Realm

> **Why?** The `master` realm is for Keycloak administration only. Your application needs its own realm.

1. Click the **"Master"** dropdown in the top-left corner
2. Click **"Create realm"**
3. **Realm name**: `streamlink`
4. Click **"Create"**

You should now see "streamlink" in the top-left (not "Master").

#### 4.3 Create OAuth2 Client

1. In the left sidebar, click **"Clients"**
2. Click **"Create client"** button
3. **Client ID**: `streamlink-api`
4. Click **"Next"**
5. **Client authentication**: Turn **ON**
6. Click **"Next"**
7. **Valid redirect URIs**: `http://localhost:3001/auth/callback`
8. Click **"Save"**

#### 4.4 Get Client Secret

1. Go to the **"Credentials"** tab
2. Copy the **"Client secret"** value
3. Update your `.env` file:
   ```bash
   KEYCLOAK_CLIENT_SECRET=<paste-the-secret-here>
   ```

#### 4.5 Create Test User

1. In the left sidebar, click **"Users"**
2. Click **"Create new user"** button
3. Fill in:
   - **Username**: `testuser`
   - **Email**: `test@example.com`
   - **First name**: `Test`
   - **Last name**: `User`
4. Click **"Create"**
5. Go to the **"Credentials"** tab
6. Click **"Set password"**
7. Enter password: `password123`
8. **Temporary**: Turn **OFF** (important!)
9. Click **"Save"**
10. Confirm by clicking **"Save password"**

### 5. Run Backend

```bash
cd backend
bash dev.sh
```

This script will:
- Create a Python virtual environment (if needed)
- Install dependencies from `requirements.txt`
- Load environment variables from `.env`
- Run database migrations
- Start FastAPI server on http://localhost:3000 with hot-reload

**Backend will be available at**: http://localhost:3000

**API Documentation**: http://localhost:3000/docs (Swagger UI)

**Backend Logs**: Watch the terminal for logs

### 6. Run Frontend (New Terminal)

Open a new terminal window/tab:

```bash
cd frontend
bash dev.sh
```

This script will:
- Install Node.js dependencies (if needed)
- Start Parcel dev server with hot-reload

**Frontend will be available at**: http://localhost:3001

**Note**: The first build may take a minute. Subsequent builds are instant.

### 7. Test the Application

1. Open http://localhost:3001 in your browser
2. Click **"Login"** button
3. You'll be redirected to Keycloak
4. Login with:
   - Username: `testuser`
   - Password: `password123`
5. After successful login, you'll be redirected to the dashboard
6. You should see:
   - User info in the sidebar (testuser)
   - Dashboard home page
   - Kubernetes menu (if you add a cluster)
   - Services menu (after cluster is connected)

---

## Configuration Management

StreamLink separates **secrets** from **configuration** for security:

### Configuration Files

| File | Purpose | In Git? |
|------|---------|---------|
| `.env` | **Secrets only** (passwords, keys) | ❌ No (gitignored) |
| `.env.example` | Template with placeholders | ✅ Yes |
| `backend/src/config.py` | Backend configuration | ✅ Yes |
| `docker-compose.yml` | Infrastructure config | ✅ Yes |

### What Goes Where?

**`.env` - Secrets Only** (5 variables):
```bash
POSTGRES_PASSWORD           # PostgreSQL password
KC_DB_PASSWORD             # Keycloak database password
KEYCLOAK_ADMIN_PASSWORD    # Keycloak admin password
KEYCLOAK_CLIENT_SECRET     # OAuth2 client secret (from Keycloak)
ENCRYPTION_KEY             # Fernet encryption key
```

**`backend/src/config.py` - Application Settings**:
- Database host, port, name, username
- Keycloak URL, realm, client ID, redirect URI
- JWT algorithm, token expiry times
- CORS origins, debug mode, log level

**`docker-compose.yml` - Infrastructure**:
- Service definitions (postgres, keycloak)
- Image versions, port mappings
- Volume mounts, health checks
- Database names, usernames (non-sensitive)

### Priority Order

When the same variable is defined multiple times:

1. **Shell environment** (highest priority)
2. **`.env` file**
3. **`config.py` defaults** (lowest priority)

**Example**: Set `DEBUG=False` in `.env` to override the `DEBUG=True` default in `config.py`.

---

## Project Structure

```
StreamLink/
├── .env                       # Secrets (gitignored)
├── .env.example              # Template
├── docker-compose.yml        # PostgreSQL + Keycloak
├── README.md                 # This file
│
├── backend/
│   ├── dev.sh               # Backend development script
│   ├── requirements.txt     # Python dependencies
│   ├── alembic/             # Database migrations
│   ├── deployments/         # Kubernetes YAML manifests
│   │   ├── kafka.yaml
│   │   └── schema-registry.yaml
│   └── src/
│       ├── main.py          # FastAPI application
│       ├── config.py        # Configuration
│       ├── database.py      # Database connection
│       ├── models/          # SQLAlchemy models
│       │   ├── user.py
│       │   ├── cluster.py
│       │   └── service.py
│       ├── api/             # API endpoints
│       │   ├── auth_simple.py
│       │   ├── clusters.py
│       │   └── services.py
│       └── utils/
│           └── crypto.py    # Encryption utilities
│
├── frontend/
│   ├── dev.sh               # Frontend development script
│   ├── package.json         # Node.js dependencies
│   ├── index.html           # Entry point
│   └── src/
│       ├── App.jsx          # React router
│       ├── pages/
│       │   ├── Login.jsx
│       │   ├── DashboardSimple.jsx
│       │   ├── Kubernetes.jsx
│       │   └── Services.jsx
│       └── components/      # Reusable components
│
└── scripts/
    └── init-db.sh           # Database initialization
```

---

## Development Workflow

### Starting Development

```bash
# Terminal 1: Infrastructure
docker-compose up -d

# Terminal 2: Backend
cd backend && bash dev.sh

# Terminal 3: Frontend
cd frontend && bash dev.sh
```

### Making Changes

**Backend Changes**:
- Edit files in `backend/src/`
- FastAPI auto-reloads on file changes
- Check terminal for errors

**Frontend Changes**:
- Edit files in `frontend/src/`
- Parcel auto-reloads on file changes
- Browser will refresh automatically

**Database Schema Changes**:
```bash
cd backend
source venv/bin/activate
alembic revision --autogenerate -m "description"
alembic upgrade head
```

### Stopping Services

```bash
# Stop backend: Ctrl+C in backend terminal

# Stop frontend: Ctrl+C in frontend terminal

# Stop infrastructure
docker-compose down

# Stop and remove volumes (clean slate)
docker-compose down -v
```

---

## Common Development Tasks

### Add a Kubernetes Cluster

1. Log in to the application
2. Go to **"Kubernetes"** page
3. Click **"Add Cluster"**
4. Fill in:
   - **Cluster Name**: `my-cluster`
   - **API Server**: Your K8s API endpoint
   - **Kubeconfig**: Paste your kubeconfig content
5. Click **"Add Cluster"**

The kubeconfig is encrypted with Fernet before storing in the database.

### Deploy a Service

1. Ensure a cluster is connected
2. Go to **"Services"** page
3. Click **"Deploy"** on Kafka or Schema Registry
4. Service status updates every 5 seconds
5. Watch for status to change: deploying → running

### Check Logs

**Backend Logs**: Check the terminal where `dev.sh` is running

**Frontend Logs**: Check browser console (F12 → Console)

**Database Logs**:
```bash
docker-compose logs -f postgres
```

**Keycloak Logs**:
```bash
docker-compose logs -f keycloak
```

**Docker Container Logs**:
```bash
docker-compose logs -f
```

### Database Access

**Connect to PostgreSQL**:
```bash
psql -h localhost -U streamlink -d streamlink
# Password from .env (POSTGRES_PASSWORD)
```

**Useful Queries**:
```sql
-- Check users
SELECT * FROM users;

-- Check clusters
SELECT id, name, api_server, status FROM clusters;

-- Check services
SELECT id, name, namespace, status, replicas FROM services;
```

### Reset Keycloak Session

If you're stuck with wrong user or session issues:

```bash
# Clear browser data
# Press F12 → Application → Storage → Clear site data

# Or restart Keycloak
docker-compose restart keycloak
```

---

## Troubleshooting

### Backend won't start

**Error: "Missing ENCRYPTION_KEY"**
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Add output to .env as ENCRYPTION_KEY
```

**Error: "Connection refused" (PostgreSQL)**
```bash
docker-compose ps          # Check postgres is running
docker-compose up -d       # Start if not running
docker-compose logs postgres  # Check logs
```

**Error: "Module not found"**
```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
```

### Frontend won't start

**Error: "Command not found: npm"**
- Install Node.js 18+ from https://nodejs.org

**Error: "Port 3001 already in use"**
```bash
lsof -ti:3001 | xargs kill -9  # Kill process on port 3001
```

**Error: Dependencies not installing**
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
```

### Keycloak issues

**Can't access admin console**
- Verify Keycloak is running: `docker-compose ps`
- Check logs: `docker-compose logs keycloak`
- Wait for "Keycloak started" message

**"Invalid client credentials"**
- Verify `KEYCLOAK_CLIENT_SECRET` in `.env` matches Keycloak credentials tab
- Ensure you're in the `streamlink` realm (not master)
- Restart backend after updating `.env`

**Stuck logging in as admin**
- Clear browser cookies and localStorage (F12 → Application → Storage)
- Ensure test user was created in the `streamlink` realm
- Verify test user password is set and not temporary

### Kubernetes connection fails

**"Invalid kubeconfig"**
- Verify kubeconfig syntax (test with `kubectl --kubeconfig=file.yaml get nodes`)
- Check API server URL is accessible
- Ensure kubeconfig contains certificates/tokens

**"Status check failed"**
- Verify cluster API is reachable from your machine
- Check kubeconfig has valid credentials
- Look at backend logs for detailed error

---

## API Documentation

Once the backend is running, interactive API docs are available:

- **Swagger UI**: http://localhost:3000/docs
- **ReDoc**: http://localhost:3000/redoc

**Key Endpoints**:

```
POST   /v1/auth/login              - Initiate OAuth2 login
GET    /v1/auth/callback           - OAuth2 callback
GET    /v1/auth/user               - Get current user

GET    /v1/clusters                - List clusters
POST   /v1/clusters                - Add cluster
DELETE /v1/clusters/{id}           - Delete cluster

GET    /v1/services                - List services
POST   /v1/services                - Deploy service
DELETE /v1/services/{id}           - Delete service
POST   /v1/services/{id}/check-status - Check service health
```

---

## Security Notes

### Secrets Management

- ✅ `.env` is in `.gitignore` - never commit it
- ✅ All sensitive data (passwords, keys) goes in `.env` only
- ✅ Use `.env.example` as template with placeholders
- ✅ Kubeconfig is encrypted with Fernet before database storage
- ✅ JWT tokens are validated on every request

### Development vs Production

**This guide is for DEVELOPMENT only**. Do not use these configurations in production:

- ❌ Default passwords are weak
- ❌ No HTTPS/TLS
- ❌ Debug mode enabled
- ❌ Permissive CORS
- ❌ Local storage only

**Production deployment guide will be added when the project is ready for production.**

---

## Contributing

This project is in active development. Contribution guidelines will be added soon.

---

## License

See [LICENSE](LICENSE) file for details.

---

## Support

For issues or questions:
1. Check this README and troubleshooting section
2. Check application logs (backend terminal, browser console)
3. Check Docker logs: `docker-compose logs`

---

## What's Next?

Current development priorities:
- [ ] Database migration for services table
- [ ] Service credentials storage
- [ ] Multi-service configuration UI
- [ ] Enhanced monitoring and alerting
- [ ] Cluster edit functionality
- [ ] Role-based access control (RBAC)
