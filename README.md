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

# (Legacy) Command Line Notes

This is a Command Line Tournament Manager. You can add players, place them in matches against each other, select winners, and much more

I recently used this to help run a Smash Ultimate Tournament of 14 people. This program made everything easier, and it was a ton of fun!

You can read about my experience creating this program on my website [here](https://www.mowinpeople.com/swiss-tournament-manager/)

# How to Use

To run this program, all you need is the main.py file and to have python installed. Open a terminal in the location of main.py and type `python main.py` and the program should run!

You will see the main menu which has several options. I’ll go through what each option can do one at a time in the sections below

## Adding Players (1, 2)

In order to have a tournament, you need players! To add players, you simply type `1` on the main menu and hit enter. Type the number of players you’d like to add (an integer at least 1). Then, type their name and hit enter!

If you’d like to change a player’s name after adding them or delete a player, you can do so in the **Secret Area**.

Once you’ve added some players, you can view a list of them from the main menu by typing `2`. This list will display the players in the order you added them.

*Note: Each player you add will be associated with an index (int 0 or greater). This will be what you use to ‘select’ them for things such as adding a player to a match or selecting which player won a match.*

## Generating Matches (3)

Now that you have some players, you’ll want to find the best matchups possible for the Swiss Tournament. That is, you will need to know which 2 players have played the least and are closest in skill level based on their results in the tournament so far. 

To get a recommendation of the best matchups, you can type `3`. This will lead you to a submenu. Here, you can display the players in ‘Primed order’ by typing `1`. This will display the list of players in order of fewest to most matches played, and fewest to most lives. For a good Swiss Tournament, you’d ideally have players near the top play each other next.

You can also type `2` to get the matchup recommendation from the program. This will be the two players at the top of the previous list who have not faced each other and are not currently in an ongoing match. If you like this matchup, you can type `3` to automatically add it to the list of ongoing matches. If you want to replace one of the players in the suggested match, you can press `1` or `2`. You may want to do this is one of the players is too busy to play for example.

There are some additional complexities to this. If you want more details, read the code at `best_matchup_menu()` and `find_primed_player_index()`!

## Ongoing Matches (4, 5)

In addition to generating matchups, you can add matches manually by typing `4` on the main menu. You will then need to type the index of the first player and then the second player you want in the match. 

To view all the ongoing matches, you can type `5` on the main menu.

If you’d like to alter or delete an ongoing match, you can do so in the **Secret Area**

## Match Results (6, 7)

Now that you have ongoing matches, you need to be able to input the results! You can do so by typing `6` on the main menu. You first type the index of the ongoing match you’d like to resolve, then the index of the player who won!

To view match results, you can type `7` on the main menu which takes you to a submenu. To view all results in the order they were added to the program, type `1`. To filter this list by only matches a specific player was involved in, type `2` and then type the index of the player you’d like to view the matches of

If you’d like to change the results of matches, you can do so in the **Secret Area**

## Save Tournament (8)

To keep from losing data, this program has the option to save everything that has occurred to a text file. Just type `8` in the main menu and this will save `tourney0.txt` in the same folder as main.py. On multiple saves, it will increase the number in the name of the file. 

*Note: If you close the program and open it again, it will reset to saving to `tourney0.txt` and overwrite any file by that name in this location, so move your files after generating them to keep them safe!*

## Exit Program (0)

To exit the program, type `0` on the main menu and follow the instructions. You can also just close the terminal window.

## Secret Area (91)

This program has the secret capability to directly change data such as match results, player lives and more. This functionality is hidden to keep any bold players from taking advantage of it while your back is turned.

When you type `91` on the main menu, you are taken to the **Secret Area** which has several options.

1. Here you can select a player. At which point, you will be prompted to fill in their name, matches played, and lives one by one
2. You can select a player to remove from the tournament which will reorder the indexes of the remaining players.
Note: Any matches involving the deleted player will now store the invalid index -1, so make sure to delete or alter these matches in addition to the player.
3. Here you can select an ongoing match and change the players which are involved.
4. Here you can delete an ongoing match
5. Here you can select a completed match and change the players who were involved.
Note: This will not automatically change the number of played matches or lives of the players you add
6. Here you can delete a completed match
7. With this option, you can ‘undo’ a completed match. This removes the match from completed matches, places it back into ongoing matches, subtracts 1 match from both players’ totals, and adds one life to the loser’s number of lives. This is intended for if you input a match result and accidentally select the wrong winner

Use this power wisely!

# Miscellaneous

It is hard coded that players will start the tournament with 2 lives. If you’d like to change this, you’ll have to alter the value of the variable `start_lives` at the top of main.py
