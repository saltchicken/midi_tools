import argparse
import pretty_midi
import sys
import math

def detect_melody_tracks(pm: pretty_midi.PrettyMIDI, score_margin: float = 15.0) -> list[pretty_midi.Instrument]:
    """
    Scores each instrument track and returns all tracks that score within 
    a certain margin of the best-scoring track.
    """
    track_scores = []

    for inst in pm.instruments:
        if inst.is_drum or not inst.notes:
            continue
            
        num_notes = len(inst.notes)
        
        # 1. Average Pitch
        avg_pitch = sum(n.pitch for n in inst.notes) / num_notes
        
        # 2. Polyphony (Notes per unique start time)
        unique_starts = len(set(round(n.start, 3) for n in inst.notes))
        polyphony = num_notes / unique_starts if unique_starts > 0 else 1.0
        
        # Penalize tracks with high polyphony (chords)
        polyphony_penalty = (polyphony - 1.0) * 40 
        
        # 3. Note Activity
        activity_bonus = math.log10(num_notes + 1) * 5
        
        score = avg_pitch - polyphony_penalty + activity_bonus
        track_scores.append((score, inst))
        
    if not track_scores:
        return []
        
    best_score = max(score for score, inst in track_scores)
    
    return [inst for score, inst in track_scores if best_score - score <= score_margin]


def extract_skyline(pm: pretty_midi.PrettyMIDI, auto_detect: bool = False) -> pretty_midi.PrettyMIDI:
    """
    Extracts the highest pitch active at any given time from a MIDI file 
    using the Skyline algorithm. Returns a new PrettyMIDI object.
    """
    all_notes = []
    
    if auto_detect:
        melody_insts = detect_melody_tracks(pm)
        if not melody_insts:
            raise ValueError("No suitable tonal track found for melody detection.")
            
        print(f"Auto-detected {len(melody_insts)} melody track(s).")
        for inst in melody_insts:
            all_notes.extend(inst.notes)
    else:
        for inst in pm.instruments:
            if not inst.is_drum:
                all_notes.extend(inst.notes)

    if not all_notes:
        raise ValueError("No tonal notes found to process.")

    # Create sweep-line events
    events = []
    for i, note in enumerate(all_notes):
        events.append((note.start, 1, note.pitch, note.velocity, i))
        events.append((note.end, -1, note.pitch, note.velocity, i))

    events_by_time = {}
    for time, ev_type, pitch, vel, nid in events:
        events_by_time.setdefault(time, []).append((ev_type, pitch, vel, nid))

    sorted_times = sorted(events_by_time.keys())

    skyline_notes = []
    active_notes = {}  
    
    current_segment_start = 0
    current_velocity = 100

    for time in sorted_times:
        prev_max = max((p for p, v in active_notes.values()), default=-1)

        for ev_type, pitch, vel, nid in events_by_time[time]:
            if ev_type == 1:
                active_notes[nid] = (pitch, vel)
            else:
                active_notes.pop(nid, None)

        curr_max = max((p for p, v in active_notes.values()), default=-1)

        if curr_max != prev_max:
            if prev_max != -1 and time > current_segment_start:
                skyline_notes.append(pretty_midi.Note(
                    velocity=int(current_velocity),
                    pitch=int(prev_max),
                    start=current_segment_start,
                    end=time
                ))

            if curr_max != -1:
                current_segment_start = time
                max_pitch_velocities = [v for p, v in active_notes.values() if p == curr_max]
                current_velocity = max_pitch_velocities[0] if max_pitch_velocities else 100

    out_pm = pretty_midi.PrettyMIDI()
    out_inst = pretty_midi.Instrument(program=0)  
    out_inst.notes = skyline_notes
    out_pm.instruments.append(out_inst)
    
    print(f"Original note count: {len(all_notes)} | Skyline note count: {len(skyline_notes)}")
    return out_pm


def separate_hands_dynamic_gap(pm: pretty_midi.PrettyMIDI, default_split: float = 60.0) -> pretty_midi.PrettyMIDI:
    """
    Separates a piano MIDI into Left and Right hands using a Dynamic Gap approach.
    Returns a new PrettyMIDI object.
    """
    all_notes = []
    for inst in pm.instruments:
        if not inst.is_drum:
            all_notes.extend(inst.notes)
            
    if not all_notes:
        raise ValueError("No tonal notes found in the MIDI file.")

    all_notes.sort(key=lambda n: n.start)
    
    rh_notes = []
    lh_notes = []
    
    current_split = default_split
    active_at_time = []
    
    # O(N) active-note tracking instead of O(N^2) full scans
    for note in all_notes:
        # Clear out notes that have finished playing before this note starts
        active_at_time = [n for n in active_at_time if n.end > note.start]
        active_at_time.append(note)
        
        if len(active_at_time) >= 2:
            active_pitches = sorted([n.pitch for n in active_at_time])
            
            max_gap = 0
            best_split = current_split
            
            for j in range(len(active_pitches) - 1):
                gap = active_pitches[j+1] - active_pitches[j]
                if gap > max_gap:
                    max_gap = gap
                    best_split = active_pitches[j] + (gap / 2.0)
            
            # Alpha filter smoothing
            current_split = (current_split * 0.7) + (best_split * 0.3)
            
        if note.pitch >= current_split:
            rh_notes.append(note)
        else:
            lh_notes.append(note)

    out_pm = pretty_midi.PrettyMIDI()
    
    rh_inst = pretty_midi.Instrument(program=0, name="Right Hand")
    rh_inst.notes = rh_notes
    out_pm.instruments.append(rh_inst)
    
    lh_inst = pretty_midi.Instrument(program=0, name="Left Hand")
    lh_inst.notes = lh_notes
    out_pm.instruments.append(lh_inst)
    
    print(f"Right Hand notes: {len(rh_notes)} | Left Hand notes: {len(lh_notes)}")
    return out_pm


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MIDI tools for melody extraction and hand separation."
    )
    parser.add_argument("input", type=str, help="Path to the input MIDI file")
    parser.add_argument("-o", "--output", type=str, default="output.mid", help="Path to save output")
    parser.add_argument("--algo", type=str, choices=["skyline", "gap"], default="gap")
    parser.add_argument("--detect-track", action="store_true", help="Auto-detect melody track(s) for Skyline")
    
    args = parser.parse_args()
    
    # Isolate File I/O to the main execution block
    try:
        pm = pretty_midi.PrettyMIDI(args.input)
    except Exception as e:
        print(f"Error loading MIDI file: {e}")
        sys.exit(1)
        
    try:
        if args.algo == "skyline":
            out_pm = extract_skyline(pm, auto_detect=args.detect_track)
        elif args.algo == "gap":
            out_pm = separate_hands_dynamic_gap(pm)
            
        out_pm.write(args.output)
        print(f"Success! Output saved to: {args.output}")
        
    except Exception as e:
        print(f"Processing failed: {e}")
        sys.exit(1)
