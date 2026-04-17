
import time
import pandas as pd
import streamlit as st

st.set_page_config(page_title="K9SF Running Order", layout="wide")

DEFAULT_COLORS = {
    "LEFT": "#1E3A8A",   # blue
    "RIGHT": "#B91C1C",  # red
}
DEFAULT_TEXT_COLOR = "#FFFFFF"


def init_ro_state():
    defaults = {
        "left_index": 0,
        "right_index": 0,
        "left_hold": False,
        "right_hold": False,
        "left_color": DEFAULT_COLORS["LEFT"],
        "right_color": DEFAULT_COLORS["RIGHT"],
        "text_color": DEFAULT_TEXT_COLOR,
        "left_flash": False,
        "right_flash": False,
        "left_status_text": "HOLD",
        "right_status_text": "HOLD",
        "left_search_name": "Search 1",
        "right_search_name": "Search 2",
        "left_search_description": "",
        "right_search_description": "",        "master_df": None,

        "source_filename": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_ro_state()


# ----------------------------
# HELPERS
# ----------------------------
def safe_str(val):
    if pd.isna(val):
        return ""
    return str(val).strip()


def ensure_required_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    required_defaults = {
        "RO": "",
        "Handler": "",
        "Dog": "",
        "Breed": "",
        "Status": "ACTIVE",
    }
    for col, default in required_defaults.items():
        if col not in df.columns:
            df[col] = default

    df["RO"] = df["RO"].fillna("").astype(str).str.strip()
    df["Handler"] = df["Handler"].fillna("").astype(str).str.strip()
    df["Dog"] = df["Dog"].fillna("").astype(str).str.strip()
    df["Breed"] = df["Breed"].fillna("").astype(str).str.strip()
    df["Status"] = df["Status"].fillna("ACTIVE").astype(str).str.upper().str.strip()
    df.loc[df["Status"] == "", "Status"] = "ACTIVE"
    return df


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename common spreadsheet headers to the fields the app uses."""
    df = df.copy()
    rename_map = {}
    for col in df.columns:
        key = safe_str(col).lower()
        if key in {"ro", "running order", "order", "#"}:
            rename_map[col] = "RO"
        elif key in {"handler", "handler name", "name", "team"}:
            rename_map[col] = "Handler"
        elif key in {"dog", "dog name"}:
            rename_map[col] = "Dog"
        elif key in {"breed", "dog breed"}:
            rename_map[col] = "Breed"
        elif key in {"status"}:
            rename_map[col] = "Status"
    return df.rename(columns=rename_map)


def load_uploaded_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Load one master running order shared by both searches.
    Both Search 1 and Search 2 use the SAME team list.
    Each search has its own current index/pointer.
    """
    df = standardize_columns(df)
    return ensure_required_columns(df.reset_index(drop=True))

    # fallback: split in half
    midpoint = (len(original) + 1) // 2
    left_df = original.iloc[:midpoint].reset_index(drop=True)
    right_df = original.iloc[midpoint:].reset_index(drop=True)
    return ensure_required_columns(left_df), ensure_required_columns(right_df)


def is_active_row(row) -> bool:
    if row is None:
        return False
    status = safe_str(row.get("Status", "ACTIVE")).upper()
    return status != "SCRATCH"


def get_next_active_index(df: pd.DataFrame, start_idx: int) -> int:
    if df is None or df.empty:
        return 0
    idx = max(0, start_idx)
    while idx < len(df):
        if is_active_row(df.iloc[idx]):
            return idx
        idx += 1
    return len(df) - 1


def get_prev_active_index(df: pd.DataFrame, start_idx: int) -> int:
    if df is None or df.empty:
        return 0
    idx = min(start_idx, len(df) - 1)
    while idx >= 0:
        if is_active_row(df.iloc[idx]):
            return idx
        idx -= 1
    return 0


def first_active_index(df: pd.DataFrame) -> int:
    return get_next_active_index(df, 0)


def get_display_row(df: pd.DataFrame, idx: int):
    if df is None or df.empty:
        return None
    if idx < 0 or idx >= len(df):
        return None
    row = df.iloc[idx]
    if is_active_row(row):
        return row
    new_idx = get_next_active_index(df, idx)
    if new_idx < 0 or new_idx >= len(df):
        return None
    row = df.iloc[new_idx]
    return row if is_active_row(row) else None


def get_team_display(row):
    handler_name = safe_str(row.get("Handler", "")) or "Handler"
    dog_name = safe_str(row.get("Dog", ""))
    breed = safe_str(row.get("Breed", ""))
    return handler_name, dog_name, breed


def get_ro_display(row):
    ro = safe_str(row.get("RO", ""))
    return ro or "--"


def render_mobile_card(
    row,
    bg_color,
    text_color,
    search_name="Search 1 - Theater",
    hold=False,
    hold_text="HOLD",
    flash=False,
):
    flash_border = "8px solid #FDE047" if flash else "0px solid transparent"
    flash_shadow = "0 0 0 6px rgba(253,224,71,.30)" if flash else "0 6px 16px rgba(0,0,0,.16)"
    card_height = 360

    if hold:
        st.markdown(
            f"""
            <div style="
                background:{bg_color};
                color:{text_color};
                border-radius:18px;
                border:{flash_border};
                padding:18px 12px;
                min-height:{card_height}px;
                display:flex;
                flex-direction:column;
                justify-content:center;
                align-items:center;
                text-align:center;
                box-shadow:{flash_shadow};
            ">
                <div style="font-size:2rem; font-weight:900; margin-top:6px;">{hold_text}</div>
                <div style="font-size:1rem; margin-top:14px; opacity:.92;">{search_name}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    if row is None:
        st.markdown(
            f"""
            <div style="
                background:{bg_color};
                color:{text_color};
                border-radius:18px;
                border:{flash_border};
                padding:18px 12px;
                min-height:{card_height}px;
                display:flex;
                flex-direction:column;
                justify-content:center;
                align-items:center;
                text-align:center;
                box-shadow:{flash_shadow};
            ">
                <div style="font-size:1rem; font-weight:800;">{search_name}</div>
                <div style="font-size:1rem; margin-top:14px;">No team loaded</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    handler_name, dog_name, breed = get_team_display(row)
    ro_number = get_ro_display(row)

    dog_html = ""
    if dog_name:
        dog_html += f"""
        <div style="
            font-size:1.1rem;
            margin-top:10px;
            font-weight:700;
            line-height:1.15;
        ">{dog_name}</div>
        """

    if breed:
        dog_html += f"""
        <div style="
            font-size:0.88rem;
            margin-top:4px;
            opacity:.88;
            font-weight:500;
            line-height:1.1;
        ">{breed}</div>
        """

    st.markdown(
        f"""
        <div style="
            background:{bg_color};
            color:{text_color};
            border-radius:18px;
            border:{flash_border};
            padding:16px 12px 18px 12px;
            min-height:{card_height}px;
            display:flex;
            flex-direction:column;
            justify-content:flex-start;
            text-align:center;
            box-shadow:{flash_shadow};
        ">
            <div style="
                font-size:4.1rem;
                line-height:1;
                font-weight:900;
                margin-top:4px;
                margin-bottom:8px;
            ">
                {ro_number}
            </div>

            <div style="
                font-size:0.95rem;
                font-weight:800;
                letter-spacing:.03em;
                opacity:.96;
                margin-bottom:16px;
                word-break:break-word;
            ">
                {search_name}
            </div>

            <div style="
                font-size:1.25rem;
                line-height:1.15;
                font-weight:900;
                word-break:break-word;
            ">
                {handler_name}
            </div>

            {dog_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def load_uploaded_file(uploaded_file):
    filename = uploaded_file.name.lower()
    if filename.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
    return load_uploaded_dataframe(df)


def build_display_label(row):
    return f"RO {safe_str(row.get('RO', ''))} | {safe_str(row.get('Handler', ''))} | {safe_str(row.get('Dog', ''))} | {safe_str(row.get('Status', 'ACTIVE'))}"


def add_team(df: pd.DataFrame, ro_value: str, handler: str, dog: str, breed: str) -> pd.DataFrame:
    df = df.copy()
    ro_value = safe_str(ro_value)
    if not ro_value:
        existing_ros = pd.to_numeric(df["RO"], errors="coerce")
        max_ro = int(existing_ros.max()) if existing_ros.notna().any() else 0
        ro_value = str(max_ro + 1)

    new_row = pd.DataFrame([
        {
            "RO": ro_value,
            "Handler": safe_str(handler),
            "Dog": safe_str(dog),
            "Breed": safe_str(breed),
            "Status": "ACTIVE",
        }
    ])
    df = pd.concat([df, new_row], ignore_index=True)
    return ensure_required_columns(df)


# ----------------------------
# HEADER / FILE LOAD
# ----------------------------
st.title("K9SF Running Order")
st.caption("Manual, editable, live event board for day-of-trial changes.")

mode = st.sidebar.radio(
    "View",
    ["Public Display", "Admin"],
    index=0,
    help="Use Public Display on the phone-facing screen. Use Admin on the control device.",
)

if mode == "Public Display":
    st.sidebar.success("Public Display mode")
else:
    st.sidebar.warning("Admin mode")

uploaded_file = st.file_uploader(
    "Upload running order (.xlsx, .xls, or .csv)",
    type=["xlsx", "xls", "csv"],
)

if uploaded_file is not None:
    incoming_name = uploaded_file.name
    if st.session_state.source_filename != incoming_name or st.session_state.master_df is None:
        try:
            master_df = load_uploaded_file(uploaded_file)
            st.session_state.master_df = master_df
            st.session_state.left_index = first_active_index(master_df)
            st.session_state.right_index = first_active_index(master_df)
            st.session_state.source_filename = incoming_name
        except Exception as e:
            st.error(f"Could not read file: {e}")
            st.stop()

master_df = st.session_state.master_df

if master_df is None:
    st.info("Upload your running order file to begin.")
    st.stop()


# ----------------------------
# PUBLIC / MOBILE VIEWER
# ----------------------------
left_row = get_display_row(master_df, st.session_state.left_index)
right_row = get_display_row(master_df, st.session_state.right_index)

if mode == "Public Display":
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] {display: none !important;}
        div[data-testid="stHorizontalBlock"] > div {
            align-items: stretch !important;
        }
        .block-container {
            padding-top: 1rem;
            padding-bottom: 1rem;
            padding-left: 1rem;
            padding-right: 1rem;
            max-width: 100%;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2, gap="small")

    with col1:
        render_mobile_card(
            row=left_row,
            bg_color=st.session_state.left_color,
            text_color=st.session_state.text_color,
            search_name=st.session_state.left_search_name,
            hold=st.session_state.left_hold,
            hold_text=st.session_state.left_status_text,
            flash=st.session_state.left_flash,
        )

    with col2:
        render_mobile_card(
            row=right_row,
            bg_color=st.session_state.right_color,
            text_color=st.session_state.text_color,
            search_name=st.session_state.right_search_name,
            hold=st.session_state.right_hold,
            hold_text=st.session_state.right_status_text,
            flash=st.session_state.right_flash,
        )

    if st.session_state.left_flash or st.session_state.right_flash:
        time.sleep(0.35)

    st.session_state.left_flash = False
    st.session_state.right_flash = False
    st.stop()

# ----------------------------
# ADMIN CONTROLS
# ----------------------------
st.markdown("---")
st.subheader("Admin Controls")
admin_left, admin_right = st.columns(2, gap="large")

# LEFT / SEARCH 1
with admin_left:
    st.markdown("### Search 1")
    st.session_state.left_search_name = st.text_input(
        "Search Label (editable anytime)",
        value=st.session_state.left_search_name,
        key="left_search_name_input",
        help="Example: Search 1 - Theater",
    )
    st.session_state.left_search_description = st.text_input(
        "Search Description",
        value=st.session_state.left_search_description,
        key="left_search_description_input",
    )
    st.session_state.left_color = st.color_picker(
        "Search 1 Screen Color",
        value=st.session_state.left_color,
        key="left_color_picker",
    )
    st.session_state.left_status_text = st.selectbox(
        "Search 1 Hold Text",
        ["HOLD", "PAUSED"],
        index=0 if st.session_state.left_status_text == "HOLD" else 1,
        key="left_hold_text_select",
    )

    lnav1, lnav2, lnav3 = st.columns(3)
    with lnav1:
        if st.button("◀ Search 1 Back", use_container_width=True):
            if master_df is not None and not master_df.empty:
                new_idx = get_prev_active_index(master_df, st.session_state.left_index - 1)
                st.session_state.left_index = max(0, new_idx)
                st.session_state.left_flash = True
                st.rerun()
    with lnav2:
        if st.button("Search 1 Next ▶", use_container_width=True):
            if master_df is not None and not master_df.empty:
                next_start = st.session_state.left_index + 1
                if next_start < len(master_df):
                    st.session_state.left_index = get_next_active_index(master_df, next_start)
                    st.session_state.left_flash = True
                    st.rerun()
    with lnav3:
        if st.button("Search 1 Reset", use_container_width=True):
            st.session_state.left_index = first_active_index(master_df)
            st.session_state.left_hold = False
            st.session_state.left_flash = True
            st.rerun()

    st.session_state.left_hold = st.toggle(
        "Search 1 HOLD / PAUSE",
        value=st.session_state.left_hold,
        key="left_hold_toggle",
    )
    st.caption(f"Current Search 1 index: {st.session_state.left_index}")

    st.markdown("#### Edit Search 1 Running Order")
    left_editor_df = master_df.copy()
    left_editor_df["Display"] = left_editor_df.apply(build_display_label, axis=1)
    left_options = left_editor_df["Display"].tolist()

    if left_options:
        selected_left_display = st.selectbox(
            "Select Search 1 Entry",
            options=left_options,
            key="left_entry_select",
        )
        left_selected_idx = left_editor_df.index[left_editor_df["Display"] == selected_left_display][0]

        le1, le2, le3 = st.columns(3)
        with le1:
            if st.button("Scratch Entry", key="scratch_left", use_container_width=True):
                master_df.at[left_selected_idx, "Status"] = "SCRATCH"
                st.session_state.master_df = ensure_required_columns(master_df)
                if left_selected_idx == st.session_state.left_index:
                    next_idx = get_next_active_index(st.session_state.master_df, left_selected_idx + 1)
                    st.session_state.left_index = max(0, next_idx)
                st.rerun()
        with le2:
            if st.button("Restore Entry", key="restore_left", use_container_width=True):
                master_df.at[left_selected_idx, "Status"] = "ACTIVE"
                st.session_state.master_df = ensure_required_columns(master_df)
                st.rerun()
        with le3:
            if st.button("Delete Entry", key="delete_left", use_container_width=True):
                master_df = master_df.drop(index=left_selected_idx).reset_index(drop=True)
                master_df = ensure_required_columns(master_df)
                st.session_state.master_df = master_df
                if len(master_df) == 0:
                    st.session_state.left_index = 0
                    st.session_state.right_index = 0
                else:
                    if st.session_state.left_index >= len(master_df):
                        st.session_state.left_index = len(master_df) - 1
                    if st.session_state.right_index >= len(master_df):
                        st.session_state.right_index = len(master_df) - 1
                st.rerun()

    st.markdown("#### Add Search 1 Team")
    new_left_ro = st.text_input("New Search 1 RO", key="new_left_ro")
    new_left_handler = st.text_input("New Search 1 Handler", key="new_left_handler")
    new_left_dog = st.text_input("New Search 1 Dog", key="new_left_dog")
    new_left_breed = st.text_input("New Search 1 Breed", key="new_left_breed")

    if st.button("Add Search 1 Team", key="add_left_team", use_container_width=True):
        st.session_state.master_df = add_team(
            master_df,
            new_left_ro,
            new_left_handler,
            new_left_dog,
            new_left_breed,
        )
        st.rerun()


# RIGHT / SEARCH 2
with admin_right:
    st.markdown("### Search 2")
    st.session_state.right_search_name = st.text_input(
        "Search Label (editable anytime)",
        value=st.session_state.right_search_name,
        key="right_search_name_input",
        help="Example: Search 2 - Vehicles",
    )
    st.session_state.right_search_description = st.text_input(
        "Search Description",
        value=st.session_state.right_search_description,
        key="right_search_description_input",
    )
    st.session_state.right_color = st.color_picker(
        "Search 2 Screen Color",
        value=st.session_state.right_color,
        key="right_color_picker",
    )
    st.session_state.right_status_text = st.selectbox(
        "Search 2 Hold Text",
        ["HOLD", "PAUSED"],
        index=0 if st.session_state.right_status_text == "HOLD" else 1,
        key="right_hold_text_select",
    )

    rnav1, rnav2, rnav3 = st.columns(3)
    with rnav1:
        if st.button("◀ Search 2 Back", use_container_width=True):
            if master_df is not None and not master_df.empty:
                new_idx = get_prev_active_index(master_df, st.session_state.right_index - 1)
                st.session_state.right_index = max(0, new_idx)
                st.session_state.right_flash = True
                st.rerun()
    with rnav2:
        if st.button("Search 2 Next ▶", use_container_width=True):
            if master_df is not None and not master_df.empty:
                next_start = st.session_state.right_index + 1
                if next_start < len(master_df):
                    st.session_state.right_index = get_next_active_index(master_df, next_start)
                    st.session_state.right_flash = True
                    st.rerun()
    with rnav3:
        if st.button("Search 2 Reset", use_container_width=True):
            st.session_state.right_index = first_active_index(master_df)
            st.session_state.right_hold = False
            st.session_state.right_flash = True
            st.rerun()

    st.session_state.right_hold = st.toggle(
        "Search 2 HOLD / PAUSE",
        value=st.session_state.right_hold,
        key="right_hold_toggle",
    )
    st.caption(f"Current Search 2 index: {st.session_state.right_index}")

    st.markdown("#### Edit Search 2 Running Order")
    right_editor_df = master_df.copy()
    right_editor_df["Display"] = right_editor_df.apply(build_display_label, axis=1)
    right_options = right_editor_df["Display"].tolist()

    if right_options:
        selected_right_display = st.selectbox(
            "Select Search 2 Entry",
            options=right_options,
            key="right_entry_select",
        )
        right_selected_idx = right_editor_df.index[right_editor_df["Display"] == selected_right_display][0]

        re1, re2, re3 = st.columns(3)
        with re1:
            if st.button("Scratch Entry", key="scratch_right", use_container_width=True):
                master_df.at[right_selected_idx, "Status"] = "SCRATCH"
                st.session_state.master_df = ensure_required_columns(master_df)
                if right_selected_idx == st.session_state.right_index:
                    next_idx = get_next_active_index(st.session_state.master_df, right_selected_idx + 1)
                    st.session_state.right_index = max(0, next_idx)
                st.rerun()
        with re2:
            if st.button("Restore Entry", key="restore_right", use_container_width=True):
                master_df.at[right_selected_idx, "Status"] = "ACTIVE"
                st.session_state.master_df = ensure_required_columns(master_df)
                st.rerun()
        with re3:
            if st.button("Delete Entry", key="delete_right", use_container_width=True):
                master_df = master_df.drop(index=right_selected_idx).reset_index(drop=True)
                master_df = ensure_required_columns(master_df)
                st.session_state.master_df = master_df
                if len(master_df) == 0:
                    st.session_state.left_index = 0
                    st.session_state.right_index = 0
                else:
                    if st.session_state.left_index >= len(master_df):
                        st.session_state.left_index = len(master_df) - 1
                    if st.session_state.right_index >= len(master_df):
                        st.session_state.right_index = len(master_df) - 1
                st.rerun()

    st.markdown("#### Add Search 2 Team")
    new_right_ro = st.text_input("New Search 2 RO", key="new_right_ro")
    new_right_handler = st.text_input("New Search 2 Handler", key="new_right_handler")
    new_right_dog = st.text_input("New Search 2 Dog", key="new_right_dog")
    new_right_breed = st.text_input("New Search 2 Breed", key="new_right_breed")

    if st.button("Add Search 2 Team", key="add_right_team", use_container_width=True):
        st.session_state.master_df = add_team(
            master_df,
            new_right_ro,
            new_right_handler,
            new_right_dog,
            new_right_breed,
        )
        st.rerun()


# ----------------------------
# OPTIONAL ADMIN DATA PREVIEW
# ----------------------------
with st.expander("Show working running order table"):
    st.markdown("**Master Running Order Table**")
    st.dataframe(st.session_state.master_df, use_container_width=True, hide_index=True)
