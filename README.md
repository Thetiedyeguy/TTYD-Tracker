# TTYD Archipelago Tracker

A live entrance-randomization tracker for Paper Mario: The Thousand-Year Door in Archipelago multiworlds. It connects to the Archipelago server and opens a browser window showing a graph of discovered regions, accessible loading zones, and location check status.

---

## Requirements

- The Archipelago server must be running and you must be connected to it with the TTYD client before launching the tracker.

---

## Launching

Double-click **TTYD_Tracker.exe**. A console window will open and ask five questions before the browser launches.

---

## Setup Questions

### Archipelago host
The IP address or hostname of the machine running the Archipelago server.

- Playing locally on your own machine → press **Enter** to accept the default `localhost`
- Playing with others → enter the address provided by the room host (e.g. `archipelago.gg`)

### Archipelago port
The port the Archipelago server is listening on.

- Press **Enter** to accept the default `38281` unless the host told you a different port.

### Your slot name
Your player name in the multiworld — the name that was entered when the room was generated. This is case-sensitive.

- In the Archipelago launcher or room page, this appears as your "Player Name" or "Slot Name".
- If you are unsure, ask whoever generated the room or check the room's player list.

### Game name
The game as it is registered in Archipelago.

- Press **Enter** to accept the default `Paper Mario: The Thousand-Year Door`.
- Only change this if the room was generated with a different game name (uncommon).

### Room password
The password for the room, if one was set.

- If the room has no password, press **Enter** to leave it blank.

---

## Using the Tracker

Once all questions are answered, a browser tab opens automatically showing the tracker. The console window must stay open while you play — closing it disconnects the tracker. All of the following is explained within the trackers help button denoted with a question mark in the bottom right.

### Graph
- **Scroll** — zoom in / out
- **Drag background** — pan
- **Drag a node** — reposition a region
- **Hover a connection** — shows the loading zone names on each end
- **Checkbox (top-left)** — color-codes nodes by accessibility: green = has reachable unchecked items, red = all items blocked, gray = all items done

### Sidebar
The sidebar appears when you enter a loading zone and shows all zones and locations in your current region.

- **Left-click an item** — expand or collapse the access rule explanation
- **Right-click any item** — opens a context menu:
  - **Toggle Done** (locations only) — manually marks a location as done, or un-marks it. Looks identical to a server-confirmed pickup and works in both directions.
  - **Suggest Rule Change** — see Reporting below

### Search
Type in the search box (top-right) to find any location or zone by name. Selecting a result highlights the shortest path to it on the graph in purple.

---

## Reporting Rule Issues

If you believe a location or loading zone has incorrect logic, right-click it in the sidebar and choose **Suggest Rule Change**. A popup will show the current rule and a text field for your suggestion.

**To save your reports:** press **Ctrl+C** in the console window when you are done playing. The tracker will write a file named `ttyd_recommendations_YYYYMMDD_HHMMSS.txt` in the same folder as the exe, with one entry per report listing the item name, its current rule, and your suggestion.

> Do not close the console window by clicking the X — use Ctrl+C so the file has a chance to write.
