# Swiss Tournament Manager (Streamlit App)

A simple Streamlit app to run a Swiss-style Pokemon TCG tournament with:
- Start/Reset tournament
- Add/remove players before starting
- Configure total rounds
- Generate Swiss pairings each round (performance-based)
- Handle odd players with automatic BYE (BYEs can repeat if needed)
- Enter results (win/loss/draw) per match
- Rankings with tie-breaker using Opponents' Win Rate (OWR)
- Round history and final standings

## Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the app:
   ```bash
   streamlit run main.py
   ```
3. In the sidebar:
   - Enter a tournament name and number of rounds
   - Add players
   - Click “Start Tournament”

4. In the main area:
   - Click “Generate pairings for this round”
   - Enter match results (Player1 wins / Draw / Player2 wins); BYEs are automatic
   - Save results to advance rounds
   - View live standings and round history

Notes:
- Scoring uses 3 points for a win, 1 for a draw, 0 for a loss. BYE awards 3 points and does not affect W/L/D or OWR.
- Pairings are based on current points and OWR. The algorithm guarantees no rematches whenever a valid solution exists (using backtracking search); rematches are only permitted as a last resort if all possible pairings would result in one.
- OWR is computed as the average match win ratio of all opponents a player has faced (BYEs excluded).

---
