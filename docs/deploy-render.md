# Deploying the Doorstep backend on Render + MongoDB Atlas (free)

> DOORSTEP DEMO: synthetic data only. The public backend exists so the ASI:One route-map image has a public `https://` address (plan rev 6 §000.7). Never put real people's data in it.

**What you get:** the backend at a public address like `https://doorstep-backend.onrender.com`, with its data in a free MongoDB Atlas database. Takes about 15 minutes.

## 1. MongoDB Atlas (the database)
1. Sign up at **cloud.mongodb.com** and create a **free (M0) cluster**. Any region near Oregon or Ohio is fine.
2. **Database Access** → *Add New Database User* → username `doorstep`, auto-generate a password, and copy it.
3. **Network Access** → *Add IP Address* → **Allow access from anywhere** (`0.0.0.0/0`). Render's free plan has no fixed IP. The database password still protects it.
4. **Connect** → *Drivers* → copy the connection string. It looks like
   `mongodb+srv://doorstep:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority`.
   Put the password in place of `<password>`. **Never commit this string or paste it in chat.**

## 2. Render (the server)
1. Sign up at **render.com** with GitHub and give it access to the Doorstep repo.
2. *New* → **Blueprint** → pick the repo and the branch (`feat/backend-geodata` for now, `main` after the freeze). Render reads `render.yaml` from the repo.
3. When it asks for **`MONGODB_URI`**, paste the Atlas connection string from step 1.4.
4. Click *Apply*. The first build takes a few minutes, because it installs the dependencies.
5. Open `https://<your-service>.onrender.com/health`. You should see `"status": "ok"` and `"simulation_mode": true`. The backend seeds the synthetic demo data the first time it starts with an empty database.

## 3. Give the tokens to Developer A
Render generated random values for `DEMO_AUTH_TOKEN`, `NETWORK_AGENT_TOKEN`, `DOORSTEP_AGENT_TOKEN`, `ROUTE_AGENT_TOKEN` and `CALAMITY_AGENT_TOKEN` (service → *Environment*).
- Send them to A **privately** (not in the repo or a public channel). A puts them in the agents' `.env`, along with `DOORSTEP_API_URL=https://<your-service>.onrender.com`.
- The tokens must match on both sides, or the agents get 401s.

## 4. Before the demo
- The free plan **sleeps after about 15 idle minutes**, and the first request then takes about 30 s. Open `/health` a minute before you start.
- Reset the demo data: `curl -X POST https://<your-service>.onrender.com/demo/reset -H "Authorization: Bearer <DEMO_AUTH_TOKEN>"`.
- Map links use Render's `RENDER_EXTERNAL_URL` automatically. Set `PUBLIC_BASE_URL` only if you add a custom domain.

## Troubleshooting
| Symptom | Fix |
|---|---|
| Build fails on the Python version | `PYTHON_VERSION` must be 3.11 or 3.12 (the project needs `<3.13`). |
| `/health` shows a database error | Check `MONGODB_URI` (password in place, no `<>`) and the Atlas network access rule. |
| Agents get 401 | A token in the agents' `.env` doesn't match Render's *Environment* tab. |
| Map image doesn't show in ASI:One | The URL must be `https://…onrender.com/maps/<id>.png`. Open it in a private browser window to check. |
