import argparse
import pretty_midi
import sys

def extract_skyline(input_midi_path: str, output_midi_path: str):
    """
    Extracts the highest pitch active at any given time from a MIDI file 
    using the Skyline algorithm.
    """
    try:
        pm = pretty_midi.PrettyMIDI(input_midi_path)
    except Exception as e:
        print(f"Error loading MIDI file: {e}")
        sys.exit(1)

    # 1. Collect all non-drum notes from all instruments
    all_notes = []
    for inst in pm.instruments:
        if not inst.is_drum:
            for note in inst.notes:
                all_notes.append(note)

    if not all_notes:
        print("No tonal notes found in the MIDI file.")
        sys.exit(0)

    # 2. Create sweep-line events (start and end points for every note)
    events = []
    for i, note in enumerate(all_notes):
        # (time, event_type, pitch, velocity, unique_note_id)
        # event_type: 1 for start, -1 for end
        events.append((note.start, 1, note.pitch, note.velocity, i))
        events.append((note.end, -1, note.pitch, note.velocity, i))

    # Group events by exact time to avoid zero-length notes when chords strike
    events_by_time = {}
    for time, ev_type, pitch, vel, nid in events:
        if time not in events_by_time:
            events_by_time[time] = []
        events_by_time[time].append((ev_type, pitch, vel, nid))

    sorted_times = sorted(events_by_time.keys())

    # 3. Sweep line to find the maximum pitch at any given time
    skyline_notes = []
    active_notes = {}  # note_id -> (pitch, velocity)
    
    current_segment_start = 0
    current_velocity = 100

    for time in sorted_times:
        # What is the highest pitch BEFORE we process events at this exact millisecond?
        prev_max = max((p for p, v in active_notes.values()), default=-1)

        # Process all events occurring exactly at 'time'
        for ev_type, pitch, vel, nid in events_by_time[time]:
            if ev_type == 1: # Note starts
                active_notes[nid] = (pitch, vel)
            else:            # Note ends
                if nid in active_notes:
                    del active_notes[nid]

        # What is the highest pitch AFTER we processed the events?
        curr_max = max((p for p, v in active_notes.values()), default=-1)

        # If the skyline (highest pitch) has changed, close the old note and start a new one
        if curr_max != prev_max:
            # If there was an active top note, close it and save it to our melody list
            if prev_max != -1 and time > current_segment_start:
                skyline_notes.append(pretty_midi.Note(
                    velocity=int(current_velocity),
                    pitch=int(prev_max),
                    start=current_segment_start,
                    end=time
                ))

            # If a new top note is taking over, mark its starting time and velocity
            if curr_max != -1:
                current_segment_start = time
                # Grab the velocity of whichever note is currently providing the top pitch
                max_pitch_velocities = [v for p, v in active_notes.values() if p == curr_max]
                current_velocity = max_pitch_velocities[0] if max_pitch_velocities else 100

    # 4. Write the resulting melody out to a new MIDI file
    out_pm = pretty_midi.PrettyMIDI()
    out_inst = pretty_midi.Instrument(program=0)  # 0 = Acoustic Grand Piano
    out_inst.notes = skyline_notes
    out_pm.instruments.append(out_inst)
    
    out_pm.write(output_midi_path)
    print(f"Success! Skyline extracted to: {output_midi_path}")
    print(f"Original note count: {len(all_notes)} | Skyline note count: {len(skyline_notes)}")


def separate_hands_dynamic_gap(input_midi_path: str, output_midi_path: str, default_split=60):
    """
    Separates a piano MIDI into Left and Right hands using a Dynamic Gap approach.
    It tracks the largest pitch gap between active notes to dynamically shift the split point.
    """
    try:
        pm = pretty_midi.PrettyMIDI(input_midi_path)
    except Exception as e:
        print(f"Error loading MIDI file: {e}")
        sys.exit(1)

    # 1. Collect and sort all non-drum notes
    all_notes = []
    for inst in pm.instruments:
        if not inst.is_drum:
            all_notes.extend(inst.notes)
            
    if not all_notes:
        print("No tonal notes found in the MIDI file.")
        sys.exit(0)

    all_notes.sort(key=lambda n: n.start)
    
    rh_notes = []
    lh_notes = []
    
    # Maintain a dynamic split point (starts at MIDI 60 / Middle C)
    current_split = default_split
    
    # 2. Iterate through notes and calculate the dynamic gap
    for note in all_notes:
        # Find all notes currently playing at the exact moment this note starts
        active_at_time = [n for n in all_notes if n.start <= note.start and n.end > note.start]
        
        if len(active_at_time) >= 2:
            # Sort active pitches to find the gaps between them
            active_pitches = sorted([n.pitch for n in active_at_time])
            
            max_gap = 0
            best_split = current_split
            
            # Find the largest gap between adjacent pitches
            for j in range(len(active_pitches) - 1):
                gap = active_pitches[j+1] - active_pitches[j]
                if gap > max_gap:
                    max_gap = gap
                    # Place the target split point exactly in the middle of the largest gap
                    best_split = active_pitches[j] + (gap / 2.0)
            
            # Smooth the split point transition so it doesn't jump wildly (alpha filter)
            current_split = (current_split * 0.7) + (best_split * 0.3)
            
        # 3. Assign the note to the Left or Right hand
        if note.pitch >= current_split:
            rh_notes.append(note)
        else:
            lh_notes.append(note)

    # 4. Write out to a new 2-track MIDI file
    out_pm = pretty_midi.PrettyMIDI()
    
    # Track 1: Right Hand
    rh_inst = pretty_midi.Instrument(program=0, name="Right Hand")
    rh_inst.notes = rh_notes
    out_pm.instruments.append(rh_inst)
    
    # Track 2: Left Hand
    lh_inst = pretty_midi.Instrument(program=0, name="Left Hand")
    lh_inst.notes = lh_notes
    out_pm.instruments.append(lh_inst)
    
    out_pm.write(output_midi_path)
    print(f"Success! Dynamic gap separation saved to: {output_midi_path}")
    print(f"Right Hand notes: {len(rh_notes)} | Left Hand notes: {len(lh_notes)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MIDI tools for melody extraction and hand separation."
    )
    
    parser.add_argument(
        "input", 
        type=str, 
        help="Path to the input MIDI file"
    )
    
    parser.add_argument(
        "-o", "--output", 
        type=str, 
        default="output.mid", 
        help="Path to save the output MIDI file (default: output.mid)"
    )

    # Add an argument to choose the algorithm
    parser.add_argument(
        "--algo", 
        type=str, 
        choices=["skyline", "gap"], 
        default="gap", 
        help="Algorithm to run: 'skyline' (melody extraction) or 'gap' (left/right hand separation)"
    )

    args = parser.parse_args()
    
    # Route to the correct algorithm
    if args.algo == "skyline":
        extract_skyline(args.input, args.output)
    elif args.algo == "gap":
        separate_hands_dynamic_gap(args.input, args.output)
