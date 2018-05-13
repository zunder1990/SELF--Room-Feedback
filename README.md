# SELF--Room-Feedback

### Using config.json file 

The script uses a config.json file to provide some ability to tune the script without
having to hard-code values. 

The config.json file options are:
* room_id: Which room id to look up in google sheets
* schedule_sheet: The name of the "tab" in the Google Sheet containing the scheduled events.
* session_length_min: (minutes) Planned length of sessions. Used to compute the window of time the votes for a particular session are collected.
* session_start_offset_min: (minutes) How long the scheduled session start time to begin accepting votes / feedback.
* session_end_offset_min: (minutes) How long past the scheduled sessio end time to stop accepting votes / feedback.
* simulate_voting: (boolean) Simulate voting as simple test of Google Sheet connection and local vote log.