from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import date, time, datetime, timedelta
import os

load_dotenv()

app = FastAPI(title="Hospital Voice Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

# ─────────────────────────────────────────
# REQUEST MODELS
# ─────────────────────────────────────────

class BookAppointmentRequest(BaseModel):
    patient_name: str
    patient_phone: str
    doctor_name: str
    appointment_date: str   # "YYYY-MM-DD"
    preferred_time: str     # "HH:MM" or "morning" / "evening"

class RescheduleRequest(BaseModel):
    appointment_id: str
    new_date: str
    preferred_time: str

class CancelRequest(BaseModel):
    appointment_id: str

class CheckSlotsRequest(BaseModel):
    doctor_name: str
    appointment_date: str

# ─────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────

def find_doctor(name: str):
    """Fuzzy doctor lookup — handles partial names."""
    name_parts = name.lower().split()
    all_doctors = supabase.table("doctors").select("*").eq("is_active", True).execute()
    
    for doc in all_doctors.data:
        doc_name_lower = doc["name"].lower()
        if any(part in doc_name_lower for part in name_parts if len(part) > 3):
            return doc
    return None

def find_or_create_patient(name: str, phone: str):
    """Get existing patient or create new one."""
    existing = supabase.table("patients").select("*").eq("phone", phone).execute()
    if existing.data:
        return existing.data[0]
    
    new_patient = supabase.table("patients").insert({
        "name": name,
        "phone": phone
    }).execute()
    return new_patient.data[0]

def parse_preferred_time(preferred_time: str, slots: list):
    """Match a time preference like 'morning', 'evening', or '14:00' to a slot."""
    preferred_time = preferred_time.lower().strip()
    
    if preferred_time == "morning":
        for slot in slots:
            if slot["start_time"] < "13:00":
                return slot
    elif preferred_time == "evening" or preferred_time == "afternoon":
        for slot in slots:
            if slot["start_time"] >= "13:00":
                return slot
    else:
        # Try to match exact or nearest time
        for slot in slots:
            if slot["start_time"].startswith(preferred_time[:5]):
                return slot
        # Return first available if no exact match
        if slots:
            return slots[0]
    return None

# ─────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "Hospital Voice Agent API is running"}

@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.post("/check-slots")
def check_slots(req: CheckSlotsRequest):
    """Check available slots for a doctor on a given date."""
    doctor = find_doctor(req.doctor_name)
    if not doctor:
        raise HTTPException(status_code=404, detail=f"Doctor '{req.doctor_name}' not found")
    
    slots = supabase.table("slots")\
        .select("*")\
        .eq("doctor_id", doctor["id"])\
        .eq("slot_date", req.appointment_date)\
        .eq("is_booked", False)\
        .order("start_time")\
        .execute()
    
    if not slots.data:
        # Find next available date
        for i in range(1, 8):
            next_date = (datetime.strptime(req.appointment_date, "%Y-%m-%d") + timedelta(days=i)).strftime("%Y-%m-%d")
            next_slots = supabase.table("slots")\
                .select("*")\
                .eq("doctor_id", doctor["id"])\
                .eq("slot_date", next_date)\
                .eq("is_booked", False)\
                .limit(5)\
                .execute()
            if next_slots.data:
                return {
                    "available": False,
                    "doctor": doctor["name"],
                    "department": doctor["department"],
                    "requested_date": req.appointment_date,
                    "message": f"No slots on {req.appointment_date}. Next available: {next_date}",
                    "next_available_date": next_date,
                    "next_available_slots": [
                        {"time": s["start_time"], "slot_id": s["id"]} 
                        for s in next_slots.data[:5]
                    ]
                }
        return {"available": False, "doctor": doctor["name"], "message": "No slots in next 7 days"}
    
    morning = [s for s in slots.data if s["start_time"] < "13:00"]
    evening = [s for s in slots.data if s["start_time"] >= "13:00"]
    
    return {
        "available": True,
        "doctor": doctor["name"],
        "department": doctor["department"],
        "consultation_fee": doctor["consultation_fee"],
        "date": req.appointment_date,
        "morning_slots": [{"time": s["start_time"], "slot_id": s["id"]} for s in morning[:5]],
        "evening_slots": [{"time": s["start_time"], "slot_id": s["id"]} for s in evening[:5]],
        "total_available": len(slots.data)
    }


@app.post("/book-appointment")
def book_appointment(req: BookAppointmentRequest):
    """Book an appointment for a patient."""
    # 1. Find doctor
    doctor = find_doctor(req.doctor_name)
    if not doctor:
        raise HTTPException(status_code=404, detail=f"Doctor '{req.doctor_name}' not found")
    
    # 2. Get available slots
    slots = supabase.table("slots")\
        .select("*")\
        .eq("doctor_id", doctor["id"])\
        .eq("slot_date", req.appointment_date)\
        .eq("is_booked", False)\
        .order("start_time")\
        .execute()
    
    if not slots.data:
        raise HTTPException(status_code=409, detail=f"No available slots for {doctor['name']} on {req.appointment_date}")
    
    # 3. Pick best matching slot
    chosen_slot = parse_preferred_time(req.preferred_time, slots.data)
    if not chosen_slot:
        chosen_slot = slots.data[0]
    
    # 4. Find or create patient
    patient = find_or_create_patient(req.patient_name, req.patient_phone)
    
    # 5. Mark slot as booked
    supabase.table("slots").update({"is_booked": True}).eq("id", chosen_slot["id"]).execute()
    
    # 6. Create appointment record
    appointment = supabase.table("appointments").insert({
        "patient_id": patient["id"],
        "doctor_id": doctor["id"],
        "slot_id": chosen_slot["id"],
        "appointment_date": req.appointment_date,
        "start_time": chosen_slot["start_time"],
        "status": "confirmed"
    }).execute()
    
    return {
        "success": True,
        "appointment_id": appointment.data[0]["id"],
        "patient_name": patient["name"],
        "doctor_name": doctor["name"],
        "department": doctor["department"],
        "date": req.appointment_date,
        "time": chosen_slot["start_time"],
        "consultation_fee": doctor["consultation_fee"],
        "message": f"Appointment confirmed with {doctor['name']} on {req.appointment_date} at {chosen_slot['start_time']}"
    }


@app.post("/reschedule-appointment")
def reschedule_appointment(req: RescheduleRequest):
    """Reschedule an existing appointment."""
    # 1. Get existing appointment
    existing = supabase.table("appointments")\
        .select("*, doctors(*), patients(*)")\
        .eq("id", req.appointment_id)\
        .eq("status", "confirmed")\
        .execute()
    
    if not existing.data:
        raise HTTPException(status_code=404, detail="Appointment not found or already cancelled")
    
    appt = existing.data[0]
    doctor = appt["doctors"]
    
    # 2. Find new slot
    new_slots = supabase.table("slots")\
        .select("*")\
        .eq("doctor_id", doctor["id"])\
        .eq("slot_date", req.new_date)\
        .eq("is_booked", False)\
        .order("start_time")\
        .execute()
    
    if not new_slots.data:
        raise HTTPException(status_code=409, detail=f"No available slots on {req.new_date}")
    
    chosen_slot = parse_preferred_time(req.preferred_time, new_slots.data)
    if not chosen_slot:
        chosen_slot = new_slots.data[0]
    
    # 3. Free old slot
    supabase.table("slots").update({"is_booked": False}).eq("id", appt["slot_id"]).execute()
    
    # 4. Book new slot
    supabase.table("slots").update({"is_booked": True}).eq("id", chosen_slot["id"]).execute()
    
    # 5. Update appointment
    supabase.table("appointments").update({
        "slot_id": chosen_slot["id"],
        "appointment_date": req.new_date,
        "start_time": chosen_slot["start_time"]
    }).eq("id", req.appointment_id).execute()
    
    return {
        "success": True,
        "appointment_id": req.appointment_id,
        "doctor_name": doctor["name"],
        "new_date": req.new_date,
        "new_time": chosen_slot["start_time"],
        "message": f"Rescheduled to {req.new_date} at {chosen_slot['start_time']}"
    }


@app.post("/cancel-appointment")
def cancel_appointment(req: CancelRequest):
    """Cancel an appointment and free the slot."""
    existing = supabase.table("appointments")\
        .select("*, doctors(*), patients(*)")\
        .eq("id", req.appointment_id)\
        .eq("status", "confirmed")\
        .execute()
    
    if not existing.data:
        raise HTTPException(status_code=404, detail="Appointment not found or already cancelled")
    
    appt = existing.data[0]
    
    # Free the slot
    supabase.table("slots").update({"is_booked": False}).eq("id", appt["slot_id"]).execute()
    
    # Cancel the appointment
    supabase.table("appointments").update({"status": "cancelled"}).eq("id", req.appointment_id).execute()
    
    return {
        "success": True,
        "message": f"Appointment with {appt['doctors']['name']} on {appt['appointment_date']} at {appt['start_time']} has been cancelled",
        "patient_name": appt["patients"]["name"]
    }


@app.get("/appointment/{appointment_id}")
def get_appointment(appointment_id: str):
    """Look up an appointment by ID."""
    result = supabase.table("appointments")\
        .select("*, doctors(*), patients(*)")\
        .eq("id", appointment_id)\
        .execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    appt = result.data[0]
    return {
        "appointment_id": appt["id"],
        "patient_name": appt["patients"]["name"],
        "doctor_name": appt["doctors"]["name"],
        "department": appt["doctors"]["department"],
        "date": appt["appointment_date"],
        "time": appt["start_time"],
        "status": appt["status"]
    }


@app.get("/doctors")
def list_doctors():
    """List all active doctors."""
    result = supabase.table("doctors").select("name, department, consultation_fee, available_days").eq("is_active", True).execute()
    return {"doctors": result.data}