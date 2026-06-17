# Hospital Voice Agent — Apollo Clinic Bhubaneswar

A production-grade voice AI receptionist that handles the full appointment lifecycle for Apollo Clinic, Bhubaneswar. Patients call a real phone number, speak naturally, and walk away with an appointment booked, rescheduled, or cancelled — no human involved.

**Live phone number: +1 (864) 514 7592**  
**Backend API: https://hospital-voice-agent-production-61a1.up.railway.app/docs**

---

## What I Built

A fully deployed voice AI agent with:
- A real phone number patients can call
- A voice agent (Priya) that handles booking, rescheduling, and cancellation
- A FastAPI backend connected to a real PostgreSQL database
- Real doctor data scraped from Apollo Clinic Bhubaneswar
- 4,000+ appointment slots seeded for 10 real doctors across 10 departments
- An automated eval harness that tests 5 end-to-end scenarios

---

## Architecture

Patient calls +1 (864) 514 7592

↓

Vapi (voice platform)

- Speech-to-text: Deepgram

- LLM: Claude Haiku 4.5 (Anthropic)

- Text-to-speech: Vapi Elliot

↓

Agent decides to call a tool

↓

FastAPI backend (Railway, US West)

↓

Supabase PostgreSQL (Mumbai region)

↓

Result spoken back to patient

---

## Stack & Key Decisions

### Voice Platform — Vapi
Chose Vapi over Retell, Bolna, LiveKit, and Pipecat for three reasons:
1. Native phone number provisioning with zero additional setup
2. Best-in-class tool calling support — tools map directly to HTTP endpoints
3. Streaming responses reduce perceived latency significantly

### LLM — Claude Haiku 4.5
Chose Haiku over GPT-4o for this use case because:
- 800ms average LLM latency vs ~1.4s for GPT-4o
- Tool calling reliability is equivalent for structured tasks
- Lower cost per call matters at scale for a clinic

### Backend — FastAPI + Supabase
- FastAPI chosen for Python familiarity and automatic OpenAPI docs
- Supabase (PostgreSQL) over Firebase because relational data is the right model for appointments — slot conflicts, foreign keys, and joins matter
- Mumbai region for Supabase minimizes latency from India

### Deployment — Railway
- Sub-5-minute deploys from GitHub push
- US West region chosen to minimize latency to Vapi's infrastructure

---

## Latency Story

End-to-end latency breakdown for a typical booking call:

| Component | Latency |
|---|---|
| Speech-to-text (Deepgram) | ~100ms |
| LLM first token (Claude Haiku) | ~800ms |
| Tool call to Railway backend | ~150ms |
| Database query (Supabase) | ~50ms |
| Text-to-speech (Vapi Elliot) | ~250ms |
| **Total end-to-end** | **~1.35 seconds** |

Latency optimisations made:
- Kept system prompt under 400 tokens — every extra token adds to TTFT
- Indexed slots table on `(doctor_id, slot_date, is_booked)` for fast availability queries
- Supabase Mumbai region co-located with likely caller geography

---

## Real Data

Doctors sourced from Apollo Clinic Bhubaneswar public listings:

| Doctor | Department | Days |
|---|---|---|
| Dr. Satyajit Mohapatra | Cardiology | Mon–Sat |
| Dr. Priyanka Dash | Gynaecology | Mon, Tue, Wed, Fri, Sat |
| Dr. Rakesh Kumar Panda | Orthopaedics | Mon, Wed, Thu, Fri, Sat |
| Dr. Subhashree Mishra | Dermatology | Tue–Sat |
| Dr. Amitabh Nanda | Neurology | Mon, Tue, Thu, Fri |
| Dr. Lipsa Pattnaik | Paediatrics | Mon–Sat |
| Dr. Debasis Mohanty | General Medicine | Mon–Sat |
| Dr. Sanjukta Rath | Ophthalmology | Mon, Wed, Fri, Sat |
| Dr. Prasanta Senapati | ENT | Tue, Thu, Fri, Sat |
| Dr. Monalisa Kar | Endocrinology | Mon, Wed, Thu, Sat |

Slot structure: 15-minute slots, morning (9am–1pm) and evening (5pm–8pm), generated for 30 days.

---

## Eval Harness

Located in `/eval/eval_harness.py`. Tests 5 end-to-end scenarios against the live backend and verifies outcomes in the database.

### Running it

```bash
# Terminal 1 — start the backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# Terminal 2 — run the eval
cd eval
pip install requests supabase python-dotenv
python eval_harness.py
```

### Results (latest run)

✅ TC001 | Basic Booking           | 1213.1ms | Dr. Debasis Mohanty | Date: 2026-06-18 | DB: True

✅ TC002 | Check Slots             |  147.2ms | Morning: 5 | Evening: 5 slots

✅ TC003 | Book and Cancel         |  533.9ms | Booked then cancelled | DB status=cancelled: True

✅ TC004 | Book and Reschedule     |  709.5ms | New date: 2026-06-19 | New time: 17:15:00

✅ TC005 | Invalid Doctor          |   96.0ms | Got HTTP 404 (expected 404)


**5/5 passing. 0 failures.**

### What the metrics measure

| Metric | Why it matters |
|---|---|
| Task completion | Did the action actually happen in the DB? |
| Correct doctor/date | Did the agent book what the patient asked for? |
| Latency | Is the backend fast enough for real-time voice? |
| Error recovery | Does the system fail gracefully on bad input? |
| Lifecycle testing | Does book→cancel and book→reschedule work end to end? |

### Known harness limitations
- Tests hit the backend API directly, not the voice layer — Vapi call quality and STT accuracy are not measured
- Slot availability depends on prior test runs not having exhausted slots — re-running may hit 409 conflicts on busy dates
- No concurrency testing — simultaneous bookings for the same slot are not tested
- Latency numbers are from a local network and will differ in production

---

## Project Structure

hospital-voice-agent/

├── backend/

│   ├── main.py              # FastAPI app — all endpoints

│   ├── requirements.txt     # Pinned dependencies

│   ├── Procfile             # Railway start command

│   └── .python-version      # Pins Python 3.12

├── eval/

│   └── eval_harness.py      # Automated test suite

└── README.md

---

## Setup Instructions

### Prerequisites
- Python 3.12
- Supabase account
- Railway account
- Vapi account

### 1. Clone and configure

```bash
git clone https://github.com/shrfr/hospital-voice-agent
cd hospital-voice-agent/backend
```

Create `.env`:

SUPABASE_URL=your_supabase_url

SUPABASE_SERVICE_KEY=your_service_role_key

### 2. Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Visit `http://localhost:8000/docs`

### 3. Seed the database

Run the SQL scripts in order from `/backend/seed.sql` in Supabase SQL Editor (doctors → slots).

### 4. Run eval

```bash
cd eval
python eval_harness.py
```

---

## Known Limitations

- **Phone number is US-only** — Vapi free tier provides US numbers only. International callers need VoIP (Skype, Google Voice).
- **Slots expire** — slots are seeded for 30 days from setup date. Re-run the slot generation SQL after 30 days.
- **No patient authentication** — patients are identified by phone number only, no OTP or verification.
- **Appointment ID recall** — for rescheduling/cancellation, patients need their appointment ID. A real system would look up by phone number instead.
- **English only** — the agent does not handle Hindi or Odia.

