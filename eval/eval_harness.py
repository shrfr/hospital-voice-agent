import os
import json
import time
import requests
from datetime import datetime, timedelta
from supabase import create_client
from dotenv import load_dotenv

load_dotenv("../backend/.env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
BASE_URL = "http://127.0.0.1:8000"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TOMORROW = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
DAY_AFTER = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def post(endpoint, data):
    start = time.time()
    try:
        r = requests.post(
            f"{BASE_URL}/{endpoint}", 
            json=data, 
            timeout=30,
            headers={"Content-Type": "application/json"}
        )
        latency = round((time.time() - start) * 1000, 1)
        return r, latency
    except Exception as e:
        raise Exception(f"Connection error: {e}")
    
def check_db_appointment(appointment_id, expected_status):
    result = supabase.table("appointments")\
        .select("status")\
        .eq("id", appointment_id)\
        .execute()
    if not result.data:
        return False
    return result.data[0]["status"] == expected_status

def print_result(tc_id, name, passed, latency, notes=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} | {tc_id} | {name:<35} | {latency:>7.1f}ms | {notes}")

# ─────────────────────────────────────────
# TEST CASES
# ─────────────────────────────────────────

def tc001_basic_booking():
    """Book an appointment and verify it exists in DB."""
    r, latency = post("book-appointment", {
        "patient_name": "Rahul Sharma",
        "patient_phone": "9800000001",
        "doctor_name": "Debasis Mohanty",
        "appointment_date": TOMORROW,
        "preferred_time": "morning"
    })

    if r.status_code != 200:
        print_result("TC001", "Basic Booking", False, latency, f"HTTP {r.status_code}")
        return None

    data = r.json()
    appt_id = data.get("appointment_id")

    # Verify in DB
    in_db = check_db_appointment(appt_id, "confirmed")
    correct_doctor = "Mohanty" in data.get("doctor_name", "")
    correct_date = data.get("date") == TOMORROW

    passed = in_db and correct_doctor and correct_date
    notes = f"Dr: {data.get('doctor_name','?')} | Date: {data.get('date','?')} | DB: {in_db}"
    print_result("TC001", "Basic Booking", passed, latency, notes)
    return appt_id

def tc002_check_slots():
    """Check slots returns available morning and evening slots."""
    r, latency = post("check-slots", {
        "doctor_name": "Lipsa Pattnaik",
        "appointment_date": TOMORROW
    })

    if r.status_code != 200:
        print_result("TC002", "Check Slots", False, latency, f"HTTP {r.status_code}")
        return

    data = r.json()
    has_morning = len(data.get("morning_slots", [])) > 0
    has_evening = len(data.get("evening_slots", [])) > 0
    is_available = data.get("available") == True

    passed = is_available and (has_morning or has_evening)
    notes = f"Morning: {len(data.get('morning_slots',[]))} | Evening: {len(data.get('evening_slots',[]))} slots"
    print_result("TC002", "Check Slots", passed, latency, notes)

def tc003_book_and_cancel():
    """Book an appointment then cancel it — verify status changes in DB."""
    # Book
    r, latency = post("book-appointment", {
        "patient_name": "Cancel Test",
        "patient_phone": "9800000002",
        "doctor_name": "Prasanta Senapati",
        "appointment_date": TOMORROW,
        "preferred_time": "evening"
    })

    if r.status_code != 200:
        print_result("TC003", "Book and Cancel", False, latency, f"Booking failed HTTP {r.status_code}")
        return

    appt_id = r.json().get("appointment_id")

    # Cancel
    r2, latency2 = post("cancel-appointment", {"appointment_id": appt_id})
    total_latency = latency + latency2

    if r2.status_code != 200:
        print_result("TC003", "Book and Cancel", False, total_latency, f"Cancel failed HTTP {r2.status_code}")
        return

    in_db_cancelled = check_db_appointment(appt_id, "cancelled")
    passed = in_db_cancelled
    notes = f"Booked then cancelled | DB status=cancelled: {in_db_cancelled}"
    print_result("TC003", "Book and Cancel", passed, total_latency, notes)

def tc004_book_and_reschedule():
    """Book an appointment then reschedule it to a new date."""
    # Book
    r, latency = post("book-appointment", {
        "patient_name": "Reschedule Test",
        "patient_phone": "9800000004",
        "doctor_name": "Debasis Mohanty",
        "appointment_date": TOMORROW,
        "preferred_time": "morning"
    })

    if r.status_code != 200:
        print_result("TC004", "Book and Reschedule", False, latency, f"Booking failed HTTP {r.status_code}")
        return

    appt_id = r.json().get("appointment_id")

    # Reschedule
    r2, latency2 = post("reschedule-appointment", {
        "appointment_id": appt_id,
        "new_date": DAY_AFTER,
        "preferred_time": "evening"
    })
    total_latency = latency + latency2

    if r2.status_code != 200:
        print_result("TC004", "Book and Reschedule", False, total_latency, f"Reschedule failed HTTP {r2.status_code}")
        return

    data = r2.json()
    correct_date = data.get("new_date") == DAY_AFTER
    in_db = check_db_appointment(appt_id, "confirmed")

    passed = correct_date and in_db
    notes = f"New date: {data.get('new_date')} | New time: {data.get('new_time')}"
    print_result("TC004", "Book and Reschedule", passed, total_latency, notes)

def tc005_invalid_doctor():
    """Error recovery — agent should return 404 for unknown doctor."""
    r, latency = post("check-slots", {
        "doctor_name": "Dr. Nonexistent Person XYZ",
        "appointment_date": TOMORROW
    })

    passed = r.status_code == 404
    notes = f"Got HTTP {r.status_code} (expected 404)"
    print_result("TC005", "Invalid Doctor (Error Recovery)", passed, latency, notes)

# ─────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────

def run_eval():
    print("\n" + "="*90)
    print("HOSPITAL VOICE AGENT — EVAL HARNESS")
    print(f"Backend: {BASE_URL}")
    print(f"Run at:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*90)
    print(f"{'Status':<10} | {'ID':<5} | {'Test Name':<35} | {'Latency':>10} | Notes")
    print("-"*90)

    results = []

    tests = [tc001_basic_booking, tc002_check_slots, tc003_book_and_cancel,
             tc004_book_and_reschedule, tc005_invalid_doctor]

    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"❌ FAIL | {'ERR':<5} | {test.__name__:<35} | {'N/A':>10} | Exception: {e}")

    print("="*90)
    print("\nEval complete. Check Supabase appointments table to verify DB state.")

if __name__ == "__main__":
    run_eval()