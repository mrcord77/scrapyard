"""
buffer_calculator — Computes and applies time buffers before and after scheduled slots to improve scheduling robustness and flexibility. It ensures slots are padded with buffer time for unexpected delays or early completion of the preceding booking.

### PART-META-JSON
{
  "name": "buffer_calculator",
  "layer": "scheduling",
  "purpose": "Computes and applies time buffers before and after scheduled slots to improve scheduling robustness and flexibility. It ensures slots are padded with buffer time for unexpected delays or early completion of the preceding booking. Uses the canonical Slot model owned by scrapyard.scheduling.slot_manager (no model of its own).",
  "addition": true,
  "status": "core",
  "dependencies": ["scrapyard.scheduling.slot_manager"],
  "inputs": "A slot_manager.Slot instance and a non-negative integer buffer in minutes.",
  "outputs": "A new transient Slot padded on both ends; integer buffered duration in minutes.",
  "files_created": [],
  "security_notes": "Pure in-memory computation, no persistence and no authorization checks. apply_buffer returns a transient Slot that is NOT saved; if the caller persists it, the caller is responsible for overlap validation via slot_manager.",
  "ai_usage": "Import what you need from `scrapyard.scheduling.buffer_calculator`.",
  "example": "from scrapyard.scheduling.buffer_calculator import apply_buffer, calculate_buffered_duration",
  "import_path": "scrapyard.scheduling.buffer_calculator"
}
### END-PART-META
"""

from datetime import datetime, timezone, timedelta

# Canonical-owner pattern: slot_manager owns the Slot model for the
# scheduling layer; this part imports it instead of declaring a duplicate.
from scrapyard.scheduling.slot_manager import Slot

def apply_buffer(slot: Slot, buffer_minutes: int) -> Slot:
    """Apply a buffer to both ends of the slot."""
    if not isinstance(buffer_minutes, int) or buffer_minutes < 0:
        raise ValueError("Buffer minutes must be a non-negative integer.")
    
    new_start = slot.start_time - timedelta(minutes=buffer_minutes)
    new_end = slot.end_time + timedelta(minutes=buffer_minutes)
    
    return Slot(start_time=new_start, end_time=new_end)

def calculate_buffered_duration(slot: Slot) -> int:
    """Calculate the total buffered duration of a slot in minutes."""
    duration = slot.end_time - slot.start_time
    return int(duration.total_seconds() // 60)

def _selftest():
    try:
        from scrapyard.utils.time_utils import to_timezone
    except ImportError:
        def to_timezone(slot: Slot, tz: timezone) -> Slot:
            return Slot(
                start_time=slot.start_time.astimezone(tz),
                end_time=slot.end_time.astimezone(tz)
            )
    
    start_time = datetime.now(timezone.utc)
    end_time = start_time + timedelta(minutes=30)
    slot = Slot(start_time=start_time, end_time=end_time)
    
    original_start = slot.start_time
    original_end = slot.end_time
    
    buffer_minutes = 15
    buffered_slot = apply_buffer(slot, buffer_minutes)
    
    assert slot.start_time == original_start, "Original slot was modified"
    assert slot.end_time == original_end, "Original slot was modified"
    assert (buffered_slot.start_time - slot.start_time) == timedelta(minutes=-buffer_minutes), "Start time buffer is incorrect"
    assert (buffered_slot.end_time - slot.end_time) == timedelta(minutes=buffer_minutes), "End time buffer is incorrect"
    
    buffered_duration = calculate_buffered_duration(buffered_slot)
    expected_minutes = 60
    assert buffered_duration == expected_minutes, f"Buffered duration calculation is incorrect: got {buffered_duration}, expected {expected_minutes}"
    
    try:
        apply_buffer(slot, -10)
        raise AssertionError("ValueError should have been raised for negative buffer minutes")
    except ValueError as e:
        assert str(e) == "Buffer minutes must be a non-negative integer.", "Incorrect error message for negative buffer minutes"
    
    try:
        apply_buffer(slot, 10.5)
        raise AssertionError("ValueError should have been raised for non-integer buffer minutes")
    except ValueError:
        pass
    
    target_tz = timezone(timedelta(hours=2))
    slot_tz = to_timezone(slot, target_tz)
    buffered_slot_tz = apply_buffer(slot_tz, 15)
    
    assert (slot_tz.start_time - buffered_slot_tz.start_time) == timedelta(minutes=15), "Time zone-aware start time buffer is incorrect"
    assert (buffered_slot_tz.end_time - slot_tz.end_time) == timedelta(minutes=15), "Time zone-aware end time buffer is incorrect"
    assert buffered_slot_tz.start_time.tzinfo == target_tz, "Timezone not preserved"
    
    print("All tests passed!")

if __name__ == "__main__":
    _selftest()
