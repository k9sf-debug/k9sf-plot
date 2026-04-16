
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import qrcode
import streamlit as st
from PIL import Image

APP_TITLE = "Running Order — Two Simultaneous Searches"
DEFAULT_ADMIN_PIN = os.environ.get("RUNORDER_ADMIN_PIN", "2468")
STATE_FILE = Path(os.environ.get("RUNORDER_STATE_FILE", "shared_state.json"))
LOCK_FILE = Path(str(STATE_FILE) + ".lock")

SEARCH1_COLOR = "#1f77b4"
SEARCH2_COLOR = "#d62728"


def acquire_lock(timeout_s: float = 5.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.05)
    return False


def release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def load_app_ro_excel(uploaded_file) -> pd.DataFrame:
    raw = pd.read_excel(uploaded_file, header=None)

    header_idx = None
    for i in range(min(len(raw), 120)):
        row = [str(cell).strip().lower() for cell in raw.iloc[i].tolist()]
        if "run number" in row:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("Couldn't find a header row containing 'Run Number'.")

    cols = [str(c).strip() for c in raw.iloc[header_idx].tolist()]
    df = raw.iloc[header_idx + 1 :].copy()
    df.columns = cols

    if "Run Number" not in df.columns:
        raise ValueError("Parsed header but 'Run Number' column missing.")

    df = df.dropna(subset=["Run Number"]).copy()
    df["Run Number"] = pd.to_numeric(df["Run Number"], errors="coerce")
    df = df.dropna(subset=["Run Number"]).copy()
    df["Run Number"] = df["Run Number"].astype(int)

    if "Status" not in df.columns:
        df["Status"] = "Active"
    else:
        df["Status"] = df["Status"].fillna("Active").astype(str)

    return df.sort_values("Run Number").reset_index(drop=True)


def team_string(row: pd.Series) -> str:
    rn = int(row["Run Number"])
    last_ = str(row.get("Handler Last Name", "")).strip()
    first_ = str(row.get("Handler First Name", "")).strip()
    dog_ = str(row.get("Dog Call Name", "")).strip()
    breed_ = str(row.get("Breed", "")).strip()
    base = f"{rn}: {first_} {last_} — {dog_}".strip()
    if breed_ and breed_ != "nan":
        base += f" ({breed_})"
    return base


def clamp_to_existing(runs_sorted: List[int], desired: int) -> int:
    if not runs_sorted:
        return desired
    if desired <= runs_sorted[0]:
        return runs_sorted[0]
    if desired > runs_sorted[-1]:
        return runs_sorted[0]
    for r in runs_sorted:
        if r >= desired:
            return r
    return runs_sorted[0]


def next_run_wrap(runs_sorted: List[int], current: int) -> int:
    if not runs_sorted:
        return current
    try:
        idx = runs_sorted.index(current)
    except ValueError:
        return clamp_to_existing(runs_sorted, current)
    return runs_sorted[(idx + 1) % len(runs_sorted)]


@dataclass
class SharedState:
    started: bool = False
    s1_now: Optional[int] = None
    s2_now: Optional[int] = None
    s1_start: int = 1
    s2_start: int = 15
    scratched: List[int] = None
    roster_rows: List[Dict[str, Any]] = None
    log: List[Dict[str, Any]] = None
    updated_at: float = 0.0
    s1_start_time: str = ""
    s2_start_time: str = ""
    breaks_info: str = ""
    end_of_search_info: str = ""
    message_board: str = ""

    def __post_init__(self):
        if self.scratched is None:
            self.scratched = []
        if self.roster_rows is None:
            self.roster_rows = []
        if self.log is None:
            self.log = []


def read_state() -> SharedState:
    if not STATE_FILE.exists():
        return SharedState()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return SharedState(**data)
    except Exception:
        return SharedState()


def write_state(state: SharedState) -> None:
    state.updated_at = time.time()
    if not acquire_lock():
        st.warning("Busy (someone else is updating). Try again.")
        return
    try:
        STATE_FILE.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    finally:
        release_lock()


def add_log(state: SharedState, action: str, search: str, run_number: Optional[int], note: str = ""):
    state.log.append(
        {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "search": search,
            "run_number": run_number,
            "note": note,
        }
    )


def get_df_from_state(state: SharedState) -> pd.DataFrame:
    if not state.roster_rows:
        return pd.DataFrame()
    df = pd.DataFrame(state.roster_rows)
    if "Status" not in df.columns:
        df["Status"] = "Active"
    df["Status"] = df["Status"].fillna("Active").astype(str)
    if "Run Number" in df.columns:
        df["Run Number"] = pd.to_numeric(df["Run Number"], errors="coerce")
        df = df.dropna(subset=["Run Number"]).copy()
        df["Run Number"] = df["Run Number"].astype(int)
    return df.sort_values("Run Number").reset_index(drop=True)


def get_row(df: pd.DataFrame, run_number: int) -> Optional[pd.Series]:
    m = df[df["Run Number"] == run_number]
    if m.empty:
        return None
    return m.iloc[0]


def build_inactive_set(df: pd.DataFrame, scratched: List[int]) -> set:
    inactive = set(int(x) for x in (scratched or []))
    if not df.empty and "Status" in df.columns:
        cancelled = df.loc[df["Status"].fillna("Active") != "Active", "Run Number"].astype(int).tolist()
        inactive.update(cancelled)
    return inactive


def next_non_inactive(runs: List[int], inactive_set: set, start_from: int) -> Optional[int]:
    if not runs:
        return None
    candidate = start_from
    for _ in range(len(runs)):
        if candidate not in inactive_set:
            return candidate
        candidate = next_run_wrap(runs, candidate)
    return None


def compute_now_on_next(runs: List[int], inactive_set: set, now_ptr: Optional[int]):
    if now_ptr is None:
        return (None, None, None)
    now_ptr = next_non_inactive(runs, inactive_set, now_ptr)
    if now_ptr is None:
        return (None, None, None)
    on_deck = next_non_inactive(runs, inactive_set, next_run_wrap(runs, now_ptr))
    nxt = None
    if on_deck is not None:
        nxt = next_non_inactive(runs, inactive_set, next_run_wrap(runs, on_deck))
    return (now_ptr, on_deck, nxt)


def normalize_pointers(state: SharedState, df: pd.DataFrame) -> None:
    if df.empty or "Run Number" not in df.columns:
        state.s1_now = None
        state.s2_now = None
        return
    runs = sorted(df["Run Number"].astype(int).tolist())
    inactive_set = build_inactive_set(df, state.scratched)

    def fix(ptr: Optional[int]) -> Optional[int]:
        if ptr is None:
            return None
        ptr = clamp_to_existing(runs, int(ptr))
        return next_non_inactive(runs, inactive_set, int(ptr))

    state.s1_now = fix(state.s1_now)
    state.s2_now = fix(state.s2_now)


def mode_from_url() -> str:
    qp = st.query_params
    m = qp.get("mode", "viewer")
    if isinstance(m, list):
        m = m[0]
    return "admin" if str(m).lower().strip() == "admin" else "viewer"


def big_text_colored(label: str, value: str, color: str):
    st.markdown(
        f'''
<div style="border-left: 12px solid {color};
            padding: 12px 16px;
            margin-bottom: 14px;
            border-radius: 14px;
            background: rgba(0,0,0,0.02);">
  <div style="font-size: 13px; font-weight: 800; color: {color};
              margin-bottom: 6px; letter-spacing: 0.4px;">{label}</div>
  <div style="font-size: 30px; font-weight: 900; line-height: 1.15;">{value}</div>
</div>
''',
        unsafe_allow_html=True,
    )


def viewer_banner(state: SharedState):
    items = []
    if state.s1_start_time.strip():
        items.append(f"**Search 1 start:** {state.s1_start_time.strip()}")
    if state.s2_start_time.strip():
        items.append(f"**Search 2 start:** {state.s2_start_time.strip()}")
    if state.breaks_info.strip():
        items.append(f"**Breaks:** {state.breaks_info.strip()}")
    if state.end_of_search_info.strip():
        items.append(f"**End of search:** {state.end_of_search_info.strip()}")
    if state.message_board.strip():
        items.append(f"**Message:** {state.message_board.strip()}")
    if items:
        st.info(" • ".join(items))


def make_qr(data: str, box_size: int = 10, border: int = 2) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    if hasattr(img, "get_image"):
        img = img.get_image()
    return img


def show_qr_panel(title: str, url: str):
    st.markdown(f"**{title}**")
    st.code(url)
    st.image(make_qr(url), use_container_width=False)


st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)

mode = mode_from_url()
state = read_state()
df = get_df_from_state(state)

if mode == "viewer":
    refresh_seconds = 2
    st.caption(
        f"Viewer mode • Auto-refresh ~{refresh_seconds}s • Updated: "
        f"{time.strftime('%H:%M:%S', time.localtime(state.updated_at)) if state.updated_at else '—'}"
    )

with st.sidebar:
    st.subheader("Mode")
    if mode == "viewer":
        st.write("✅ Viewer (read-only)")
        st.write("Admin mode: add ?mode=admin to the URL.")
    else:
        st.write("🔒 Admin")
        pin = st.text_input("Admin PIN", type="password")
        unlocked = pin == DEFAULT_ADMIN_PIN
        if not unlocked:
            st.warning("Enter PIN to unlock controls.")
        else:
            st.success("Admin unlocked.")

        st.divider()
        st.subheader("Roster")
        uploaded = st.file_uploader("Upload running order (.xlsx)", type=["xlsx"])
        if unlocked and uploaded:
            try:
                roster_df = load_app_ro_excel(uploaded)
                state.roster_rows = roster_df.to_dict(orient="records")
                add_log(state, "UPLOAD", "BOTH", None, "Roster uploaded")
                normalize_pointers(state, roster_df)
                write_state(state)
                st.success("Roster loaded.")
                df = roster_df
            except Exception as e:
                st.error(str(e))

        st.subheader("Start Numbers")
        s1_start = st.number_input("Search 1 start Run #", min_value=1, value=int(state.s1_start), step=1, disabled=not unlocked)
        s2_start = st.number_input("Search 2 start Run #", min_value=1, value=int(state.s2_start), step=1, disabled=not unlocked)

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Reset", disabled=not unlocked):
                state.started = False
                state.s1_now = None
                state.s2_now = None
                state.scratched = []
                state.log = []
                state.s1_start = int(s1_start)
                state.s2_start = int(s2_start)
                add_log(state, "RESET", "BOTH", None)
                write_state(state)
                st.success("Reset done.")
        with c2:
            if st.button("Start", disabled=not unlocked):
                if df.empty:
                    st.error("Upload a roster first.")
                else:
                    runs = sorted(df["Run Number"].astype(int).tolist())
                    state.s1_start = int(s1_start)
                    state.s2_start = int(s2_start)
                    state.s1_now = clamp_to_existing(runs, state.s1_start)
                    state.s2_now = clamp_to_existing(runs, state.s2_start)
                    state.started = True
                    add_log(state, "START", "BOTH", None, f"S1={state.s1_now}, S2={state.s2_now}")
                    normalize_pointers(state, df)
                    write_state(state)
                    st.success("Started.")

        st.divider()
        st.subheader("Event Info (shows to viewers)")
        s1_time = st.text_input("Search 1 start time", value=state.s1_start_time, disabled=not unlocked, placeholder="e.g., 8:00 AM")
        s2_time = st.text_input("Search 2 start time", value=state.s2_start_time, disabled=not unlocked, placeholder="e.g., 8:15 AM")
        breaks = st.text_area("Breaks / schedule notes", value=state.breaks_info, disabled=not unlocked, height=90)
        end_info = st.text_input("End of search info", value=state.end_of_search_info, disabled=not unlocked, placeholder="e.g., Search ends ~3:30 PM")
        msg = st.text_area("Message board (announcements)", value=state.message_board, disabled=not unlocked, height=110)
        if st.button("Save Event Info", disabled=not unlocked):
            state.s1_start_time = s1_time
            state.s2_start_time = s2_time
            state.breaks_info = breaks
            state.end_of_search_info = end_info
            state.message_board = msg
            add_log(state, "EVENT_INFO_UPDATE", "BOTH", None, "Updated banner")
            write_state(state)
            st.success("Saved.")

        st.divider()
        st.subheader("QR Codes")
        public_base = st.text_input("Hosted app base URL", placeholder="https://your-app-url")
        if unlocked:
            with st.expander("Show QR Codes", expanded=False):
                if public_base:
                    viewer_url = public_base.rstrip("/") + "/"
                    admin_url = viewer_url + "?mode=admin"
                    show_qr_panel("Viewer", viewer_url)
                    show_qr_panel("Admin", admin_url)
                else:
                    st.info("Enter your hosted app URL to generate QR codes.")

if df.empty:
    st.info("Admin: upload the Excel roster in admin mode. Viewers: wait for admin to load roster.")
    st.stop()

runs = sorted(df["Run Number"].astype(int).tolist())
inactive_set = build_inactive_set(df, state.scratched)
viewer_banner(state)


def do_advance(search: str, complete: bool, hold: bool = False):
    now_ptr = state.s1_now if search == "S1" else state.s2_now
    if now_ptr is None:
        return
    if hold:
        add_log(state, "HOLD", search, now_ptr)
    elif complete:
        add_log(state, "COMPLETE", search, now_ptr)
    else:
        add_log(state, "SKIP", search, now_ptr)
    nxt = next_run_wrap(runs, int(now_ptr))
    nxt = next_non_inactive(runs, inactive_set, int(nxt))
    if search == "S1":
        state.s1_now = nxt
    else:
        state.s2_now = nxt
    write_state(state)


def do_jump(search: str, desired: int):
    j = clamp_to_existing(runs, desired)
    j = next_non_inactive(runs, inactive_set, int(j))
    if search == "S1":
        state.s1_now = j
    else:
        state.s2_now = j
    add_log(state, "JUMP", search, j, f"Requested {desired}")
    write_state(state)


def do_scratch(run_num: int):
    rn = int(run_num)
    if rn not in set(state.scratched or []):
        state.scratched = sorted(list(set(state.scratched or []) | {rn}))
        add_log(state, "SCRATCH", "BOTH", rn)
        normalize_pointers(state, df)
        write_state(state)


left, right = st.columns(2)

def render_search(col, label, ptr, search_key):
    with col:
        color = SEARCH1_COLOR if search_key == "s1" else SEARCH2_COLOR
        label_prefix = "SEARCH 1" if search_key == "s1" else "SEARCH 2"
        st.subheader(label)
        now_ptr, on_deck, nxt = compute_now_on_next(runs, inactive_set, ptr)
        if now_ptr is None:
            st.warning("No runs available (all cancelled/scratched?).")
            return
        now_row = get_row(df, int(now_ptr))
        on_row = get_row(df, int(on_deck)) if on_deck is not None else None
        nxt_row = get_row(df, int(nxt)) if nxt is not None else None

        big_text_colored(f"{label_prefix} • NOW UP", team_string(now_row) if now_row is not None else str(now_ptr), color)
        big_text_colored("ON DECK", team_string(on_row) if on_row is not None else "—", color)
        big_text_colored("NEXT", team_string(nxt_row) if nxt_row is not None else "—", color)

        if mode == "admin":
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button(f"Advance {label}", key=f"{search_key}_adv"):
                    do_advance("S1" if search_key == "s1" else "S2", complete=True)
            with b2:
                if st.button(f"Skip {label}", key=f"{search_key}_skip"):
                    do_advance("S1" if search_key == "s1" else "S2", complete=False)
            with b3:
                if st.button(f"Hold {label}", key=f"{search_key}_hold"):
                    do_advance("S1" if search_key == "s1" else "S2", complete=False, hold=True)

            j1, j2 = st.columns([2, 1])
            with j1:
                desired = st.number_input(f"Jump {label} to Run #", min_value=1, value=int(now_ptr), step=1, key=f"{search_key}_jumpnum")
            with j2:
                if st.button("Jump", key=f"{search_key}_jumpbtn"):
                    do_jump("S1" if search_key == "s1" else "S2", int(desired))

render_search(left, "Search 1", state.s1_now, "s1")
render_search(right, "Search 2", state.s2_now, "s2")

st.divider()

if mode == "admin":
    st.subheader("Edit Running Order (Admin)")
    st.caption("Use Cancel for withdrawals/cancellations. Use Insert to add a team and shift run numbers down.")
    tab1, tab2, tab3 = st.tabs(["Quick Edit Table", "Cancel / Delete", "Insert Team"])

    with tab1:
        edit_df = df.copy().sort_values("Run Number").reset_index(drop=True)
        edited = st.data_editor(
            edit_df,
            use_container_width=True,
            num_rows="dynamic",
            disabled=["Run Number"],
            column_config={"Status": st.column_config.SelectboxColumn("Status", options=["Active", "Cancelled"], required=True)},
        )
        if st.button("Save table changes"):
            state.roster_rows = edited.to_dict(orient="records")
            add_log(state, "ROSTER_EDIT_TABLE", "BOTH", None, "Saved edits")
            df2 = get_df_from_state(state)
            normalize_pointers(state, df2)
            write_state(state)
            st.success("Saved.")

    with tab2:
        c1, c2 = st.columns(2)
        with c1:
            rn_cancel = st.number_input("Run # to CANCEL", min_value=1, value=1, step=1, key="rn_cancel")
            if st.button("Cancel run #"):
                df2 = df.copy()
                if (df2["Run Number"] == int(rn_cancel)).any():
                    df2.loc[df2["Run Number"] == int(rn_cancel), "Status"] = "Cancelled"
                    state.roster_rows = df2.to_dict(orient="records")
                    add_log(state, "CANCEL_RUN", "BOTH", int(rn_cancel))
                    normalize_pointers(state, df2)
                    write_state(state)
                    st.success(f"Cancelled Run #{int(rn_cancel)}")
                else:
                    st.error("Run number not found.")
        with c2:
            rn_delete = st.number_input("Run # to DELETE (hard)", min_value=1, value=1, step=1, key="rn_delete")
            if st.button("Delete run # (hard)"):
                df2 = df[df["Run Number"] != int(rn_delete)].copy()
                if len(df2) == len(df):
                    st.error("Run number not found.")
                else:
                    state.roster_rows = df2.to_dict(orient="records")
                    add_log(state, "DELETE_RUN", "BOTH", int(rn_delete))
                    normalize_pointers(state, df2)
                    write_state(state)
                    st.success(f"Deleted Run #{int(rn_delete)}")
        st.markdown("**Scratch quick tool:**")
        scr = st.number_input("Scratch Run #", min_value=1, value=1, step=1, key="scratch_num")
        if st.button("Scratch"):
            do_scratch(int(scr))
            st.success(f"Scratched Run #{int(scr)}")

    with tab3:
        st.markdown("Insert a new team at a run number (shifts existing run numbers down by 1).")
        ins_rn = st.number_input("Insert at Run #", min_value=1, value=1, step=1, key="ins_rn")
        c1, c2 = st.columns(2)
        with c1:
            ins_last = st.text_input("Handler Last Name", key="ins_last")
            ins_first = st.text_input("Handler First Name", key="ins_first")
            ins_dog = st.text_input("Dog Call Name", key="ins_dog")
        with c2:
            ins_breed = st.text_input("Breed", key="ins_breed")
            ins_notes = st.text_input("Notes (optional)", key="ins_notes")
        if st.button("Insert team now"):
            df2 = df.copy()
            for col in ["Handler Last Name", "Handler First Name", "Dog Call Name", "Breed", "Status"]:
                if col not in df2.columns:
                    df2[col] = "" if col != "Status" else "Active"
            df2.loc[df2["Run Number"] >= int(ins_rn), "Run Number"] = df2.loc[df2["Run Number"] >= int(ins_rn), "Run Number"] + 1
            new_row = {
                "Run Number": int(ins_rn),
                "Handler Last Name": ins_last,
                "Handler First Name": ins_first,
                "Dog Call Name": ins_dog,
                "Breed": ins_breed,
                "Status": "Active",
            }
            if "Notes" in df2.columns or ins_notes.strip():
                if "Notes" not in df2.columns:
                    df2["Notes"] = ""
                new_row["Notes"] = ins_notes.strip()
            df2 = pd.concat([df2, pd.DataFrame([new_row])], ignore_index=True)
            df2 = df2.sort_values("Run Number").reset_index(drop=True)
            state.roster_rows = df2.to_dict(orient="records")
            add_log(state, "INSERT_TEAM", "BOTH", int(ins_rn), f"{ins_first} {ins_last} / {ins_dog}")
            normalize_pointers(state, df2)
            write_state(state)
            st.success(f"Inserted team at Run #{int(ins_rn)}")

    st.divider()
    st.subheader("Action Log / Export")
    log_df = pd.DataFrame(state.log or [])
    st.dataframe(log_df, use_container_width=True)
    csv = log_df.to_csv(index=False).encode("utf-8")
    st.download_button("Download log CSV", csv, file_name="running_order_log.csv", mime="text/csv")
else:
    st.caption("Viewer mode is read-only. Ask the admin if something needs to change.")


