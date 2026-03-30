from __future__ import annotations

import math
import uuid
import time
import threading
from dataclasses import dataclass, field
from typing import Literal, Optional

import streamlit as st
try:
    # Optional, for live UI updates without blocking
    from streamlit_autorefresh import st_autorefresh  # type: ignore
except Exception:
    st_autorefresh = None  # fallback if package not installed


# ----- Domain Models -----

ResultType = Literal["P1", "P2", "DRAW", "BYE"]


@dataclass
class Player:
    id: str
    name: str
    wins: int = 0
    losses: int = 0
    draws: int = 0
    points: int = 0
    opponents: set[str] = field(default_factory=set)
    bye_rounds: list[int] = field(default_factory=list)

    @property
    def matches_played(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def match_win_ratio(self) -> float:
        total = self.matches_played
        if total == 0:
            return 0.0
        return (self.wins + 0.5 * self.draws) / total


@dataclass
class Match:
    id: str
    round_index: int  # 1-based round number for UX
    player1_id: str
    player2_id: Optional[str]  # None indicates a BYE match
    result: Optional[ResultType] = None
    table: int = 0


@dataclass
class TimerState:
    start_ts: Optional[float] = None
    duration_secs: int = 30 * 60  # 30 minutes default


@dataclass
class TournamentState:
    name: str = "Pokemon TCG Night"
    total_rounds: int = 3
    current_round: int = 0  # 0 means not started; otherwise 1..total_rounds
    started: bool = False
    completed: bool = False
    players_by_id: dict[str, Player] = field(default_factory=dict)
    pairings_by_round: dict[int, list[Match]] = field(default_factory=dict)  # round -> matches
    timers_by_match_id: dict[str, TimerState] = field(default_factory=dict)
    _timer_thread_running: bool = False
    avoid_repeat_byes: bool = True


# ----- Constants -----

POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0
BYE_POINTS = 3  # Bye counts for points only; does not affect W/L/D or OWR


# ----- Helpers -----

def get_state() -> TournamentState:
    # Initialize or migrate session state to latest schema
    if "tournament" not in st.session_state:
        st.session_state.tournament = TournamentState()
    state = st.session_state.tournament
    # Backward compatibility: older sessions may miss new attributes
    if not hasattr(state, "timers_by_match_id"):
        state.timers_by_match_id = {}
    if not hasattr(state, "pairings_by_round"):
        state.pairings_by_round = {}
    if not hasattr(state, "_timer_thread_running"):
        state._timer_thread_running = False
    if not hasattr(state, "avoid_repeat_byes"):
        state.avoid_repeat_byes = True
    return state


def reset_tournament() -> None:
    st.session_state.tournament = TournamentState()


def add_player(name: str) -> None:
    name = name.strip()
    if not name:
        return
    state = get_state()
    player_id = str(uuid.uuid4())
    state.players_by_id[player_id] = Player(id=player_id, name=name)


def remove_player(player_id: str) -> None:
    state = get_state()
    if player_id in state.players_by_id:
        del state.players_by_id[player_id]


def start_tournament(total_rounds: int, name: str) -> None:
    state = get_state()
    if len(state.players_by_id) < 2:
        st.warning("Need at least 2 players to start.")
        return
    state.name = name.strip() or "Pokemon TCG Night"
    state.total_rounds = int(total_rounds)
    state.started = True
    state.current_round = 1
    state.completed = False
    state.pairings_by_round = {}


def _player_record_excluding(
    state: TournamentState, player_id: str, exclude_opponent_id: Optional[str]
) -> tuple[int, int, int]:
    """Return (wins, draws, losses) for player, excluding matches vs exclude_opponent_id."""
    wins = 0
    draws = 0
    losses = 0
    for matches in state.pairings_by_round.values():
        for m in matches:
            if m.result is None or m.result == "BYE":
                continue
            if m.player1_id != player_id and m.player2_id != player_id:
                continue
            other_id = m.player2_id if m.player1_id == player_id else m.player1_id
            if exclude_opponent_id and other_id == exclude_opponent_id:
                continue
            if m.result == "DRAW":
                draws += 1
            elif (m.result == "P1" and m.player1_id == player_id) or (m.result == "P2" and m.player2_id == player_id):
                wins += 1
            else:
                losses += 1
    return wins, draws, losses


def compute_owr_for_player(state: TournamentState, player: Player, floor: float = 0.25) -> float:
    """Opponents' Win Rate: average of opponents' match win ratios, each computed
    excluding their matches vs this player, and floored per opponent.
    Draw = 0.5 win, BYEs excluded."""
    if not player.opponents:
        return 0.0
    opponent_mwrs: list[float] = []
    for opp_id in player.opponents:
        # Opponent may have been removed; skip if not present
        if opp_id not in state.players_by_id:
            continue
        w, d, l = _player_record_excluding(state, opp_id, exclude_opponent_id=player.id)
        total = w + d + l
        if total == 0:
            mw = 0.0
        else:
            mw = (w + 0.5 * d) / total
        if mw < floor:
            mw = floor
        opponent_mwrs.append(mw)
    if not opponent_mwrs:
        return 0.0
    return sum(opponent_mwrs) / len(opponent_mwrs)


def compute_standings(state: TournamentState) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for player in state.players_by_id.values():
        rows.append(
            {
                "Player": player.name,
                "Points": player.points,
                "W": player.wins,
                "D": player.draws,
                "L": player.losses,
                "Matches": player.matches_played,
                "OWR": round(compute_owr_for_player(state, player), 3),
            }
        )
    rows.sort(key=lambda r: (r["Points"], r["OWR"], r["W"]), reverse=True)
    return rows


def _find_rematch_free_pairings(
    unpaired: list[str],
    players_by_id: dict[str, Player],
) -> list[tuple[str, str]] | None:
    """Backtracking search for a fully rematch-free pairing.

    Fixes the highest-ranked unpaired player and tries each remaining candidate
    in ranking order. Returns a list of (p1_id, p2_id) pairs preserving Swiss
    ordering, or None if no rematch-free solution exists.
    """
    if not unpaired:
        return []

    p1_id = unpaired[0]
    player1 = players_by_id[p1_id]
    remaining = unpaired[1:]

    for idx, candidate_id in enumerate(remaining):
        if candidate_id not in player1.opponents:
            new_remaining = remaining[:idx] + remaining[idx + 1:]
            result = _find_rematch_free_pairings(new_remaining, players_by_id)
            if result is not None:
                return [(p1_id, candidate_id)] + result

    return None


def _greedy_pairings_with_rematch(
    unpaired: list[str],
    players_by_id: dict[str, Player],
) -> list[tuple[str, str]]:
    """Greedy fallback used only when a rematch-free solution is provably impossible.

    Prefers non-rematches but will accept a rematch rather than leaving players
    unpaired.
    """
    remaining = list(unpaired)
    pairs: list[tuple[str, str]] = []
    while len(remaining) >= 2:
        p1 = remaining.pop(0)
        player1 = players_by_id[p1]
        opponent_index = 0
        for idx, candidate_id in enumerate(remaining):
            if candidate_id not in player1.opponents:
                opponent_index = idx
                break
        p2 = remaining.pop(opponent_index)
        pairs.append((p1, p2))
    return pairs


def generate_pairings_for_round(state: TournamentState, round_index: int) -> list[Match]:
    # Sort players by performance: Points desc, OWR desc, then name for stable display
    players_sorted: list[Player] = sorted(
        state.players_by_id.values(),
        key=lambda p: (p.points, compute_owr_for_player(state, p), p.name.lower()),
        reverse=True,
    )
    unpaired_ids: list[str] = [p.id for p in players_sorted]
    matches: list[Match] = []
    table_no = 1
    bye_candidate_id: Optional[str] = None

    # If odd number of players, choose a BYE candidate first (prefer players without previous BYE)
    if len(unpaired_ids) % 2 == 1:
        # Iterate from worst-performing to best (reverse of players_sorted)
        reversed_players = list(reversed(players_sorted))
        if state.avoid_repeat_byes:
            # First try: someone with no previous BYE
            for pl in reversed_players:
                if len(pl.bye_rounds) == 0:
                    bye_candidate_id = pl.id
                    break
        # Fallback: choose player(s) with minimum number of BYEs
        if bye_candidate_id is None:
            min_byes = min(len(pl.bye_rounds) for pl in reversed_players)
            for pl in reversed_players:
                if len(pl.bye_rounds) == min_byes:
                    bye_candidate_id = pl.id
                    break
        # Remove BYE candidate from pool; append BYE match after pairing others
        if bye_candidate_id in unpaired_ids:
            unpaired_ids.remove(bye_candidate_id)

    # Use backtracking to guarantee no rematches whenever a valid solution exists.
    # Only fall back to greedy (which may allow rematches) if provably impossible.
    paired = _find_rematch_free_pairings(unpaired_ids, state.players_by_id)
    if paired is None:
        paired = _greedy_pairings_with_rematch(unpaired_ids, state.players_by_id)

    for p1_id, p2_id in paired:
        matches.append(
            Match(
                id=str(uuid.uuid4()),
                round_index=round_index,
                player1_id=p1_id,
                player2_id=p2_id,
                result=None,
                table=table_no,
            )
        )
        table_no += 1

    # Handle odd number: create BYE for chosen candidate
    if bye_candidate_id is not None:
        matches.append(
            Match(
                id=str(uuid.uuid4()),
                round_index=round_index,
                player1_id=bye_candidate_id,
                player2_id=None,
                result="BYE",
                table=table_no,
            )
        )
    # Initialize timers for new matches (non-BYE)
    for m in matches:
        if m.player2_id is None:
            continue
        if m.id not in state.timers_by_match_id:
            state.timers_by_match_id[m.id] = TimerState()
    return matches


def apply_match_result(state: TournamentState, match: Match, result: ResultType) -> None:
    p1 = state.players_by_id.get(match.player1_id)
    p2 = state.players_by_id.get(match.player2_id) if match.player2_id else None

    if result == "BYE":
        if p1:
            p1.points += BYE_POINTS
            p1.bye_rounds.append(match.round_index)
        match.result = "BYE"
        return

    if p1 and p2:
        # Track opponents for OWR
        p1.opponents.add(p2.id)
        p2.opponents.add(p1.id)

        if result == "P1":
            p1.wins += 1
            p2.losses += 1
            p1.points += POINTS_WIN
        elif result == "P2":
            p2.wins += 1
            p1.losses += 1
            p2.points += POINTS_WIN
        elif result == "DRAW":
            p1.draws += 1
            p2.draws += 1
            p1.points += POINTS_DRAW
            p2.points += POINTS_DRAW
        match.result = result


def all_results_entered(matches: list[Match]) -> bool:
    for m in matches:
        if m.player2_id is None:
            # BYE auto-filled
            continue
        if m.result not in ("P1", "P2", "DRAW"):
            return False
    return True


def _format_seconds(secs: int) -> str:
    mins = secs // 60
    rem = secs % 60
    return f"{mins:02d}:{rem:02d}"


def _remaining_seconds(timer: TimerState) -> int:
    if timer.start_ts is None:
        return timer.duration_secs
    elapsed = int(time.time() - timer.start_ts)
    remaining = timer.duration_secs - elapsed
    return max(0, remaining)


def _ensure_timer_thread(state: TournamentState) -> None:
    if state._timer_thread_running:
        return

    def _tick():
        # Background heartbeat to support live timers
        while True:
            try:
                # Touch a heartbeat in session to indicate progress
                st.session_state["__timer_heartbeat"] = time.time()
            except Exception:
                # Session may be closing; exit quietly
                break
            time.sleep(1)

    t = threading.Thread(target=_tick, daemon=True)
    t.start()
    state._timer_thread_running = True


def _render_round_timers(state: TournamentState, round_matches: list[Match]) -> None:
    st.markdown("**Timers (30:00 per match)**")
    # Start the background heartbeat thread
    _ensure_timer_thread(state)

    # Optional live auto-refresh (requires streamlit-autorefresh)
    live = st.sidebar.checkbox("Live timers (auto-refresh every second)", value=st.session_state.get("live_timers", True), key="live_timers_chk")
    st.session_state["live_timers"] = live
    if live and st_autorefresh is not None:
        st_autorefresh(interval=1000, key="__auto_refresh_key")

    for m in round_matches:
        if m.player2_id is None:
            # Skip BYE
            continue
        p1 = state.players_by_id[m.player1_id]
        p2 = state.players_by_id[m.player2_id]
        timer = state.timers_by_match_id.get(m.id, TimerState())
        remaining = _remaining_seconds(timer)

        cols = st.columns([4, 2, 1, 1])
        with cols[0]:
            st.write(f"Table {m.table}: {p1.name} vs {p2.name}")
        with cols[1]:
            color = "red" if remaining <= 5 * 60 else "white"
            st.markdown(f"<span style='font-size:1.1rem;color:{color};'>⏱️ {_format_seconds(remaining)}</span>", unsafe_allow_html=True)
        with cols[2]:
            if st.button("Start/Restart", key=f"timer_start_{m.id}"):
                # Start now; subtract 1s so UI shows immediate change
                timer.start_ts = time.time() - 1
                state.timers_by_match_id[m.id] = timer
        with cols[3]:
            if st.button("Reset", key=f"timer_reset_{m.id}"):
                state.timers_by_match_id[m.id] = TimerState()
                # A rerun happens automatically after button click


# ----- UI -----

st.set_page_config(page_title="Swiss Tournament (Pokemon TCG)", layout="wide")


def sidebar_controls() -> None:
    state = get_state()
    st.sidebar.header("Tournament Setup")
    tournament_name = st.sidebar.text_input("Tournament name", value=state.name, disabled=state.started)
    total_rounds = st.sidebar.number_input(
        "Total rounds", min_value=1, max_value=20, value=state.total_rounds, step=1, disabled=state.started
    )

    if not state.started:
        st.sidebar.subheader("Players")
        # Clear the text input safely before widget creation if flagged from previous run
        if st.session_state.get("clear_add_player_name", False):
            st.session_state["add_player_name"] = ""
            st.session_state["clear_add_player_name"] = False
        new_player_name = st.sidebar.text_input("Add player", value="", key="add_player_name")
        cols = st.sidebar.columns([1, 1])
        with cols[0]:
            if st.button("Add", type="primary", use_container_width=True):
                add_player(new_player_name)
                st.session_state["clear_add_player_name"] = True
                st.rerun()
        with cols[1]:
            if st.button("Reset", use_container_width=True):
                reset_tournament()
                st.stop()

        roster = list(state.players_by_id.values())
        if roster:
            st.sidebar.caption("Current players:")
            for pl in roster:
                c1, c2 = st.sidebar.columns([4, 1])
                with c1:
                    st.write(pl.name)
                with c2:
                    if st.button("✕", key=f"del_{pl.id}"):
                        remove_player(pl.id)
                        st.rerun()

        st.sidebar.divider()
        if st.sidebar.button("Start Tournament", type="primary", use_container_width=True):
            start_tournament(total_rounds=int(total_rounds), name=tournament_name)
            st.rerun()
    else:
        st.sidebar.write(f"Name: {state.name}")
        st.sidebar.write(f"Rounds: {state.total_rounds}")
        st.sidebar.write(f"Players: {len(state.players_by_id)}")
        # Allow toggling BYE policy live
        avoid = st.sidebar.checkbox(
            "Avoid repeat BYEs (until all have one)",
            value=state.avoid_repeat_byes,
            help="Prefer assigning BYEs to players who haven't had one yet.",
        )
        state.avoid_repeat_byes = bool(avoid)
        # Restart tournament keeping same roster/config
        if st.sidebar.button("Restart (keep players & rounds)", use_container_width=True):
            restart_same_tournament()
            st.rerun()
        # Seed snapshot to jump to Round 3 with mid-results
        if st.sidebar.button("Seed snapshot to Round 3 (use current roster)", use_container_width=True):
            seed_snapshot_round3()
            st.rerun()
        if st.sidebar.button("Reset Tournament", use_container_width=True):
            reset_tournament()
            st.rerun()


def render_pairings_and_results() -> None:
    state = get_state()
    if not state.started:
        return

    st.subheader(f"Round {state.current_round} of {state.total_rounds}")

    # Generate pairings if needed
    round_matches = state.pairings_by_round.get(state.current_round)
    if round_matches is None:
        if st.button("Generate pairings for this round", type="primary"):
            matches = generate_pairings_for_round(state, state.current_round)
            state.pairings_by_round[state.current_round] = matches
            st.rerun()
        return

    # Display pairings and results entry
    st.caption("Enter the result for each match and click 'Save results'.")
    # Timers for current round
    _render_round_timers(state, round_matches)

    form = st.form(f"results_form_round_{state.current_round}")
    selection_map: dict[str, ResultType] = {}

    for match in round_matches:
        p1 = state.players_by_id[match.player1_id]
        if match.player2_id is None:
            # BYE
            form.markdown(f"Table {match.table}: **{p1.name}** has a BYE (+{BYE_POINTS} pts)")
            selection_map[match.id] = "BYE"
            continue
        p2 = state.players_by_id[match.player2_id]

        # Use a unique key per match
        default_index = 0
        options = [f"{p1.name} wins", "Draw", f"{p2.name} wins"]
        if match.result == "P1":
            default_index = 0
        elif match.result == "DRAW":
            default_index = 1
        elif match.result == "P2":
            default_index = 2

        choice = form.radio(
            f"Table {match.table}: {p1.name} vs {p2.name}",
            options=options,
            index=default_index,
            key=f"radio_{match.id}",
            horizontal=True,
        )
        selection_map[match.id] = "P1" if choice.startswith(p1.name) else ("P2" if choice.endswith("wins") else "DRAW")

    submitted = form.form_submit_button("Save results", type="primary")
    if submitted:
        # Apply results
        for match in round_matches:
            result = selection_map.get(match.id)
            if result is None:
                continue
            apply_match_result(state, match, result)

        # Validate that all non-bye have results
        if not all_results_entered(round_matches):
            st.error("Please enter a result for every match.")
            return

        # Move to next round or complete
        if state.current_round < state.total_rounds:
            state.current_round += 1
        else:
            state.completed = True
        st.rerun()


def render_standings() -> None:
    state = get_state()
    st.subheader("Standings")
    rows = compute_standings(state)
    if not rows:
        st.info("Add players and start the tournament to view standings.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_history() -> None:
    state = get_state()
    if not state.pairings_by_round:
        return

    with st.expander("Rounds & Results History", expanded=False):
        for rnd in sorted(state.pairings_by_round.keys()):
            st.markdown(f"**Round {rnd}**")
            for m in state.pairings_by_round[rnd]:
                p1 = state.players_by_id[m.player1_id]
                if m.player2_id is None:
                    st.write(f"Table {m.table}: {p1.name} — BYE")
                    continue
                p2 = state.players_by_id[m.player2_id]
                if m.result == "P1":
                    st.write(f"Table {m.table}: {p1.name} def. {p2.name}")
                elif m.result == "P2":
                    st.write(f"Table {m.table}: {p2.name} def. {p1.name}")
                elif m.result == "DRAW":
                    st.write(f"Table {m.table}: {p1.name} drew with {p2.name}")
                else:
                    st.write(f"Table {m.table}: {p1.name} vs {p2.name} — pending")


def main() -> None:
    state = get_state()
    st.title("Swiss Tournament Manager — Pokemon TCG")
    sidebar_controls()

    if not state.started:
        st.info("Add players in the sidebar and click Start Tournament.")
        roster = list(state.players_by_id.values())
        if roster:
            st.subheader("Current Roster")
            st.dataframe(
                [{"Player": p.name} for p in roster],
                use_container_width=True,
                hide_index=True,
            )
        render_standings()
        return

    if state.completed:
        st.success("Tournament complete! Final standings below.")
        render_standings()
        render_history()
        return

    render_pairings_and_results()
    render_standings()
    render_history()


def restart_same_tournament() -> None:
    state = get_state()
    # Keep name, rounds, and roster; reset scores, pairings, timers
    for p in state.players_by_id.values():
        p.wins = 0
        p.losses = 0
        p.draws = 0
        p.points = 0
        p.opponents = set()
        p.bye_rounds = []
    state.pairings_by_round = {}
    state.timers_by_match_id = {}
    state.current_round = 1
    state.started = True
    state.completed = False


def seed_snapshot_round3() -> None:
    """Seed the tournament with two completed rounds based on the user's snapshot and jump to Round 3.
    Expects the following players (case-insensitive name match):
    oTeuPai, akito, Mandy Pata, rafa, kiorabits, Ingrid, xXfernandolaXx
    """
    state = get_state()
    # Build a name->id map (lowercased)
    name_to_id: dict[str, str] = {p.name.strip().lower(): p.id for p in state.players_by_id.values()}
    required = ["oteupai", "akito", "mandy pata", "rafa", "kiorabits", "ingrid", "xxfernandolaxx"]
    if not all(n in name_to_id for n in required):
        st.error("Snapshot seeding failed: roster must include oTeuPai, akito, Mandy Pata, rafa, kiorabits, Ingrid, xXfernandolaXx.")
        return

    pid = lambda n: name_to_id[n]
    # Reset results
    state.pairings_by_round = {}
    state.timers_by_match_id = {}
    for p in state.players_by_id.values():
        p.wins = p.losses = p.draws = p.points = 0
        p.opponents = set()
        p.bye_rounds = []
    state.started = True
    state.completed = False

    # Round 1
    r1: list[Match] = []
    r1.append(Match(id=str(uuid.uuid4()), round_index=1, player1_id=pid("oteupai"), player2_id=pid("xxfernandolaxx"), table=1))
    r1.append(Match(id=str(uuid.uuid4()), round_index=1, player1_id=pid("akito"), player2_id=pid("rafa"), table=2))
    r1.append(Match(id=str(uuid.uuid4()), round_index=1, player1_id=pid("kiorabits"), player2_id=pid("mandy pata"), table=3))
    r1.append(Match(id=str(uuid.uuid4()), round_index=1, player1_id=pid("ingrid"), player2_id=None, result="BYE", table=4))
    # Apply results
    apply_match_result(state, r1[0], "P1")  # oTeuPai def xXfernandolaXx
    apply_match_result(state, r1[1], "P1")  # akito def rafa
    apply_match_result(state, r1[2], "P1")  # kiorabits def Mandy Pata
    apply_match_result(state, r1[3], "BYE")  # Ingrid BYE
    state.pairings_by_round[1] = r1

    # Round 2
    r2: list[Match] = []
    r2.append(Match(id=str(uuid.uuid4()), round_index=2, player1_id=pid("oteupai"), player2_id=pid("kiorabits"), table=1))
    r2.append(Match(id=str(uuid.uuid4()), round_index=2, player1_id=pid("akito"), player2_id=pid("ingrid"), table=2))
    r2.append(Match(id=str(uuid.uuid4()), round_index=2, player1_id=pid("rafa"), player2_id=pid("xxfernandolaxx"), table=3))
    r2.append(Match(id=str(uuid.uuid4()), round_index=2, player1_id=pid("mandy pata"), player2_id=None, result="BYE", table=4))
    # Apply results
    apply_match_result(state, r2[0], "P1")  # oTeuPai def kiorabits
    apply_match_result(state, r2[1], "P1")  # akito def Ingrid
    apply_match_result(state, r2[2], "P1")  # rafa def xXfernandolaXx
    apply_match_result(state, r2[3], "BYE")  # Mandy Pata BYE
    state.pairings_by_round[2] = r2

    # Jump to Round 3
    state.current_round = 3
    state.avoid_repeat_byes = True


if __name__ == "__main__":
    main()


