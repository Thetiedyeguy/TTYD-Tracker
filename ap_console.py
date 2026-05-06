import argparse
import asyncio
import http.server
import json
import os
import sys
import threading
import uuid
import webbrowser
from datetime import datetime

import websockets

_BASE_DIR = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))

ITEMS_HANDLING_ALL = 0b111
BROWSER_WS_PORT = 8765
HTML_HTTP_PORT = 8766

def _start_html_server() -> None:
    base = _BASE_DIR

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                with open(os.path.join(base, "tracker.html"), "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *_):
            pass

    http.server.HTTPServer(("localhost", HTML_HTTP_PORT), _Handler).serve_forever()


# --- Shared graph state (built up as loading zones are visited) ---
_graph_nodes: list[str] = []          # ordered list of region names
_graph_edges: list[dict] = []         # [{"from": str, "to": str, "zone": str}, ...]
_node_set: set[str] = set()
_edge_set: set[tuple] = set()         # (min(a,b), max(a,b)) for dedup
_prev_region: str | None = None
_node_sidebar: dict = {}          # region_name → {zones, locs} from last visit
_browser_clients: set = set()
_recommendations: list[dict] = []


async def _broadcast(msg: dict) -> None:
    if not _browser_clients:
        return
    payload = json.dumps(msg)
    dead = set()
    for client in _browser_clients:
        try:
            await client.send(payload)
        except Exception:
            dead.add(client)
    _browser_clients.difference_update(dead)


async def _browser_handler(websocket) -> None:
    _browser_clients.add(websocket)
    try:
        await websocket.send(json.dumps({
            "type": "graph_state",
            "nodes": _graph_nodes,
            "edges": _graph_edges,
            "current": _prev_region,
            "sidebar": _node_sidebar.get(_prev_region, {"zones": [], "locs": []}),
            "node_sidebars": _node_sidebar,
        }))
        async for raw in websocket:
            try:
                msg = json.loads(raw)
                if msg.get("type") == "report":
                    _recommendations.append(msg)
                    itype = "Zone" if msg.get("item_type") == "zone" else "Location"
                    print(f"[{ts()}] Report recorded: {itype} '{msg.get('name', '?')}'")
            except Exception:
                pass
    except Exception:
        pass
    finally:
        _browser_clients.discard(websocket)


def ts():
    return datetime.now().strftime("%H:%M:%S")


def build_lookups(data_pkg, game):
    game_data = data_pkg.get("games", {}).get(game, {})
    item_id_to_name = {v: k for k, v in game_data.get("item_name_to_id", {}).items()}
    loc_id_to_name = {v: k for k, v in game_data.get("location_name_to_id", {}).items()}
    return item_id_to_name, loc_id_to_name



def format_item(item, item_id_to_name, loc_id_to_name, slot_info):
    item_name = item_id_to_name.get(item["item"], f"#{item['item']}")
    loc_name = loc_id_to_name.get(item["location"], f"loc#{item['location']}")
    player_slot = item.get("player", 0)
    player_info = slot_info.get(str(player_slot), {})
    player_name = player_info.get("name", f"slot{player_slot}")
    flags = item.get("flags", 0)
    flag_str = ""
    if flags & 0b001:
        flag_str += " [progression]"
    if flags & 0b010:
        flag_str += " [useful]"
    if flags & 0b100:
        flag_str += " [trap]"
    return f"{item_name}{flag_str}  (from {player_name} @ {loc_name})"


def render_print_json(pkt):
    parts = pkt.get("data", [])
    return "".join(p.get("text", "") for p in parts)


async def _handle_loading_zone(
    region: str, zone_id: str,
    zones: list | None = None,
    locs: list | None = None,
    dst_zone: str | None = None,
    src_zone: str | None = None,
) -> None:
    global _prev_region
    if region == "Unknown":
        return

    sidebar = {"zones": zones or [], "locs": locs or []}
    _node_sidebar[region] = sidebar

    update: dict = {
        "type": "visit",
        "region": region,
        "new_node": False,
        "edge": None,
        "sidebar": sidebar,
        "node_sidebar_update": {region: sidebar},
    }

    if region not in _node_set:
        _node_set.add(region)
        _graph_nodes.append(region)
        update["new_node"] = True

    if _prev_region and _prev_region != region:
        edge_key = (min(_prev_region, region), max(_prev_region, region))
        if edge_key not in _edge_set:
            _edge_set.add(edge_key)
            edge = {
                "from": _prev_region, "to": region, "zone": zone_id,
                "src_zone": src_zone, "dst_zone": dst_zone,
            }
            _graph_edges.append(edge)
            update["edge"] = edge

    # Mark the exit zone as visited in the departing region's sidebar
    if _prev_region and src_zone and _prev_region in _node_sidebar:
        for z in _node_sidebar[_prev_region].get("zones", []):
            if z["name"] == src_zone and not z.get("visited"):
                z["visited"] = True
                update["node_sidebar_update"][_prev_region] = _node_sidebar[_prev_region]
                break

    _prev_region = region
    await _broadcast(update)


async def _main_async(args) -> None:
    threading.Thread(target=_start_html_server, daemon=True).start()
    await asyncio.sleep(0.1)  # let HTTP server bind before browser opens
    print(f"[{ts()}] Opening tracker in browser...")
    webbrowser.open(f"http://localhost:{HTML_HTTP_PORT}/")
    print(f"[{ts()}] Browser WS on ws://localhost:{BROWSER_WS_PORT}")
    async with websockets.serve(_browser_handler, "localhost", BROWSER_WS_PORT):
        await run(args.host, args.port, args.slot, args.game, args.password)


async def run(host, port, slot, game, password):
    uri = f"ws://{host}:{port}"
    print(f"[{ts()}] Connecting to {uri} ...")

    item_id_to_name = {}
    loc_id_to_name = {}
    slot_info = {}
    received_index = 0
    server_version = {"major": 0, "minor": 6, "build": 0, "class": "Version"}

    async with websockets.connect(uri, max_size=None) as ws:
        # --- RoomInfo ---
        raw = await ws.recv()
        pkts = json.loads(raw)
        for pkt in pkts:
            if pkt["cmd"] == "RoomInfo":
                sv = pkt.get("version", {})
                server_version = {
                    "major": sv.get("major", 0),
                    "minor": sv.get("minor", 6),
                    "build": sv.get("build", 0),
                    "class": "Version",
                }
                break

        # --- GetDataPackage ---
        await ws.send(json.dumps([{"cmd": "GetDataPackage", "games": [game]}]))
        raw = await ws.recv()
        pkts = json.loads(raw)
        for pkt in pkts:
            if pkt["cmd"] == "DataPackage":
                item_id_to_name, loc_id_to_name = build_lookups(pkt["data"], game)
                break

        # --- Connect ---
        connect_pkt = {
            "cmd": "Connect",
            "password": password,
            "game": game,
            "name": slot,
            "uuid": str(uuid.uuid4()),
            "version": server_version,
            "items_handling": ITEMS_HANDLING_ALL,
            "tags": ["Tracker"],
            "slot_data": True,
        }
        await ws.send(json.dumps([connect_pkt]))

        raw = await ws.recv()
        pkts = json.loads(raw)
        connected = False
        for pkt in pkts:
            if pkt["cmd"] == "Connected":
                slot_info = pkt.get("slot_info", {})
                print(f"[{ts()}] Connected as '{slot}' — {len(pkt.get('checked_locations', []))} checked, {len(pkt.get('missing_locations', []))} remaining")
                connected = True
            elif pkt["cmd"] == "ConnectionRefused":
                print(f"[{ts()}] Connection refused: {pkt.get('errors')}")
                return
            elif pkt["cmd"] == "ReceivedItems":
                idx = pkt.get("index", 0)
                received_index = idx + len(pkt.get("items", []))

        if not connected:
            print(f"[{ts()}] Did not receive Connected packet.")
            return
        async for raw in ws:
            pkts = json.loads(raw)
            for pkt in pkts:
                cmd = pkt.get("cmd")

                if cmd == "ReceivedItems":
                    items = pkt.get("items", [])
                    idx = pkt.get("index", 0)
                    if idx != received_index:
                        print(f"[{ts()}] WARNING: ReceivedItems index jump ({received_index} -> {idx})")
                    received_index = idx + len(items)
                    print(f"[{ts()}] ReceivedItems ({len(items)}):")
                    for item in items:
                        print(f"  {format_item(item, item_id_to_name, loc_id_to_name, slot_info)}")

                elif cmd == "PrintJSON":
                    text = render_print_json(pkt)
                    print(f"[{ts()}] {text}")

                elif cmd == "RoomUpdate":
                    newly_checked = pkt.get("checked_locations", [])
                    if newly_checked:
                        updated_regions: dict = {}
                        for loc_id in newly_checked:
                            loc_name = loc_id_to_name.get(loc_id)
                            if loc_name:
                                for rname, sb in _node_sidebar.items():
                                    for loc in sb.get("locs", []):
                                        if loc["name"] == loc_name and not loc["checked"]:
                                            loc["checked"] = True
                                            updated_regions[rname] = sb
                        if updated_regions:
                            await _broadcast({"type": "sidebar_updates", "updates": updated_regions})
                    updated_players = pkt.get("players")
                    if updated_players:
                        print(f"[{ts()}] RoomUpdate — players updated: {updated_players}")

                elif cmd == "Bounced":
                    data = pkt.get("data", {})
                    if data.get("type") == "ttyd_loading_zone":
                        room = data.get("room", "?")
                        bero = data.get("bero", "?")
                        region = data.get("region", "Unknown")
                        print(f"[{ts()}] Loading zone: {room}:{bero}  ->  {region}")
                        await _handle_loading_zone(
                            region, f"{room}:{bero}",
                            data.get("zones"), data.get("locs"),
                            data.get("dst_zone"), data.get("src_zone"),
                        )
                    elif data.get("type") == "ttyd_sidebar_update":
                        updates = data.get("updates", {})
                        if updates:
                            for region, sb in updates.items():
                                _node_sidebar[region] = sb
                            await _broadcast({"type": "sidebar_updates", "updates": updates})

                else:
                    print(f"[{ts()}] [{cmd}] {json.dumps(pkt)}")


def _write_recommendations() -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ttyd_recommendations_{timestamp}.txt"
    if getattr(sys, "frozen", False):
        out_dir = os.path.dirname(sys.executable)
    else:
        out_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write("=== TTYD Playtester Rule Recommendations ===\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        for i, rec in enumerate(_recommendations, 1):
            itype = "Zone" if rec.get("item_type") == "zone" else "Location"
            current = rec.get("current_rule", "").strip() or "(always accessible)"
            f.write(f"{i}. {itype}: {rec.get('name', '?')}\n")
            f.write(f"   Current rule: {current}\n")
            f.write(f"   Suggestion:   {rec.get('suggestion', '').strip()}\n\n")
    print(f"[{ts()}] Saved {len(_recommendations)} recommendation(s) to: {path}")


def main():
    parser = argparse.ArgumentParser(description="Archipelago TTYD Tracker")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--slot", default=None, help="Your player slot name")
    parser.add_argument("--game", default=None, help="Game name as registered in Archipelago")
    parser.add_argument("--password", default=None, help="Room password if required")
    args = parser.parse_args()

    frozen = getattr(sys, "frozen", False)

    if args.host is None:
        val = input("Archipelago host [localhost]: ").strip()
        args.host = val if val else "localhost"
    if args.port is None:
        val = input("Archipelago port [38281]: ").strip()
        args.port = int(val) if val else 38281
    if args.slot is None:
        while not args.slot:
            args.slot = input("Your slot name: ").strip()
    if args.game is None:
        val = input("Game name [Paper Mario: The Thousand-Year Door]: ").strip()
        args.game = val if val else "Paper Mario: The Thousand-Year Door"
    if args.password is None:
        args.password = input("Room password (leave blank if none): ").strip()

    try:
        asyncio.run(_main_async(args))
    except KeyboardInterrupt:
        print(f"\n[{ts()}] Disconnected.")

    if _recommendations:
        _write_recommendations()

    if frozen:
        input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
