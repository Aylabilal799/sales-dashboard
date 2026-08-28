# Sales Dashboard

FastAPI sales dashboard for pharmaceutical / product sales teams.

- Upload daily PDF sales reports
- Value-based calculations (qty × TP)
- Monthly targets and achievement %
- Multi-user login by **mobile number + PIN** (each user has isolated data)
- New users auto-copy the template account's products & monthly setup
- Cloudflare Tunnel friendly (`https://your-domain`)

Live example: `https://sales.zyvion.qzz.io`

---

## Features

| Area | Details |
|------|---------|
| **Auth** | Register / login with mobile + 4–6 digit PIN |
| **Upload** | Parse sales PDF, match products, edit TP & other-city qty |
| **Calculations** | Today sale, MTD sale, targets and achievement on **value** (qty × TP) |
| **Monthly setup** | PSP name, town, working days, product-wise target qty |
| **Products** | PDF identifier, display name, code, default monthly target |
| **History** | Saved reports and generated WhatsApp-style messages |
| **Multi-user** | Data scoped by `user_id`; template mobile seeds new accounts |

---

## Requirements

- Python 3.11+ (tested on 3.13)
- Linux server (or local) with port free for uvicorn (e.g. `3304`)

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## Run locally

```bash
uvicorn app:app --host 127.0.0.1 --port 3304
```

Open: http://127.0.0.1:3304

First visit → **Register** with mobile + PIN.  
Later users get a **copy of the template account's products + monthly config**.

### Environment (optional)

| Variable | Purpose |
|----------|---------|
| `SALES_SESSION_SECRET` | Session cookie secret (set a long random string in production) |

Template account mobile is set in `auth.py` as `TEMPLATE_MOBILE` (default `03368382799`).

---

## Production (systemd)

```ini
[Unit]
Description=Sales Dashboard FastAPI
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/sales-dashboard
Environment=SALES_SESSION_SECRET=change-me-to-a-long-random-string
Environment=PATH=/root/sales-dashboard/venv/bin
ExecStart=/root/sales-dashboard/venv/bin/uvicorn app:app --host 127.0.0.1 --port 3304
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now sales-dashboard
```

### Domain with Cloudflare Tunnel

Point a public hostname (e.g. `sales.yourdomain.com`) to `http://127.0.0.1:3304`.
Users open **https://sales.yourdomain.com** (HTTPS via Cloudflare).

---

## Multi-user & template copy

1. **Template user** = mobile in `TEMPLATE_MOBILE` (`auth.py`).
2. On register / login / app startup, any user with **0 products** receives a copy of products + latest monthly setup.
3. Reports and other-city figures are **not** copied (personal).

### One-time sync for already-empty users

```bash
cd /path/to/sales-dashboard
source venv/bin/activate
python sync_bilal_to_all.py
systemctl restart sales-dashboard
```

---

## Project layout

```
sales-dashboard/
├── app.py
├── auth.py
├── models.py
├── database.py
├── calculations.py
├── pdf_parser.py
├── sync_bilal_to_all.py
├── requirements.txt
├── templates/
├── static/css|js/
└── uploads/
```

SQLite file: `sales_dashboard.db` (created on first run, not in git).

---

## Calculations (summary)

- **Today sale value** = Σ (today_qty × TP)
- **MTD / current sale value** = Σ (current_sale × TP) where `current_sale = mtd_qty − other_city`
- **Monthly target value** = Σ (monthly_target_qty × TP)
- Message “Till Date” shows **qty / qty** (target qty / current sale qty)

---

## Security notes

- Do **not** commit `sales_dashboard.db` or real PDFs.
- Set `SALES_SESSION_SECRET` in production.
- Prefer binding uvicorn to `127.0.0.1` and exposing only via Cloudflare Tunnel.
- PINs are stored with PBKDF2-HMAC-SHA256 (salted).

---

## License

Private / internal use unless you state otherwise.
